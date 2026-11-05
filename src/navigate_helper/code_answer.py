"""The Code Answer: a Code Search result as a structured, validated, always-unverified Answer.

A finished run ends in free text. One extra structured-output call turns that conclusion (not the transcript) into
a `CodeAnswer`. The model only names `path` and a line range; the CODE validates each range against the Code Checkout
and fills the snippet from the file, so a snippet can never be invented. A run that stopped (limit, cancelled, error)
stays a partial result: a fixed notice and the tool-call evidence, never a conclusion (ADR 0001).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from navigate_helper.ask_log import AskLog
from navigate_helper.code_search import CodeSearchResult, ToolCallRecord, require_code_allowed
from navigate_helper.code_tools import CodeToolError, CodeTools
from navigate_helper.prompts import CODE_ANSWER_PROMPT, CODE_ANSWER_TEMPLATE, NO_MANUAL_ANSWER, NO_MANUAL_PAGES

MAX_SNIPPET_LINES = 20
ALWAYS_NOT_CHECKED = ("configuratie", "maatwerk", "data")
UNVERIFIED_LABEL = "Ongecontroleerd antwoord op basis van de broncode: laat het door een ontwikkelaar bevestigen."

AGREES, DIFFERS, UNKNOWN, NO_MANUAL = "agrees", "differs", "unknown", "no_manual_answer"

# Statuses of a CodeAnswer besides the stopped ones it takes over from CodeSearchResult.
ANSWERED, UNSTRUCTURED = "answered", "unstructured"

STOPPED_NOTICES = {
    "tool_call_limit": "Het onderzoek van de code is gestopt omdat het maximum aantal tool-aanroepen is bereikt.",
    "token_limit": "Het onderzoek van de code is gestopt omdat het maximum aantal tokens is bereikt.",
    "timeout": "Het onderzoek van de code is gestopt omdat de maximale tijd is verstreken.",
    "cancelled": "Het onderzoek van de code is gestopt op verzoek.",
    "error": "Het onderzoek van de code is gestopt door een fout.",
}
NO_CONCLUSION = " Er is geen conclusie; hieronder staat wat is onderzocht."


# --- what the model returns (kept simple: Anthropic's JSON schema mode is picky) ------------------


class LLMCodeCitation(BaseModel):
    path: str = Field(description="Pad van het bestand zoals de conclusie het noemt, relatief aan de root van de code.")
    start_line: int = Field(description="Eerste regel (1-based).")
    end_line: int = Field(description="Laatste regel, ten minste start_line.")


class LLMCodeAnswer(BaseModel):
    """The fixed structured-output schema of the Code Answer step. There is deliberately no snippet field."""

    answer: str = Field(description="Het antwoord in het Nederlands (Markdown); identifiers en code letterlijk.")
    citations: list[LLMCodeCitation] = Field(description="Plekken in de code die de conclusie zelf noemt.")
    manual_agreement: Literal["agrees", "differs", "unknown"] = Field(
        description="Bevestigt de code het antwoord uit de handleiding, spreekt hij het tegen, of is dat onbekend."
    )
    differing_manual_pages: list[str] = Field(description="Alleen bij `differs`: de pagina's die de code tegenspreekt.")
    not_checked: list[str] = Field(description="Wat de conclusie als niet gecontroleerd noemt.")


# --- the Answer ------------------------------------------------------------------------------------


@dataclass
class CodeCitation:
    """A validated reference: the range exists in the Code Checkout and `snippet` was read from it.

    The snippet holds at most `MAX_SNIPPET_LINES` lines from `start_line`; `snippet_truncated` says the range is longer.
    """

    path: str
    start_line: int
    end_line: int
    snippet: str
    snippet_truncated: bool = False


@dataclass
class CodeAnswer:
    """`status` is answered, unstructured (the conclusion as written, structuring failed), or a stopped status of
    the Code Search (tool_call_limit, token_limit, timeout, cancelled, error). Every Code Answer is unverified.

    `manual_agreement` is agrees, differs, unknown, or no_manual_answer (set by the code, not the model).
    `code_date` is the ISO date the Code Checkout was last modified ("code per <date>").
    """

    question: str
    status: str
    text: str
    citations: list[CodeCitation] = field(default_factory=list)
    dropped_citations: list[str] = field(default_factory=list)
    manual_agreement: str = UNKNOWN
    differing_manual_pages: list[str] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)
    code_date: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    error: str | None = None
    provider: str = ""
    model: str = ""

    @property
    def uncited(self) -> bool:
        """A structured answer without a single valid Code Citation: shown as-is, flagged."""
        return self.status == ANSWERED and not self.citations


class CodeAnswerWriter:
    """Turns a `CodeSearchResult` into a `CodeAnswer`. Needs the same provider approval as the Code Search itself."""

    def __init__(
        self,
        llm,
        tools: CodeTools,
        code_date: str | None,
        *,
        allow_code_to_openai: bool = False,
        log: AskLog | None = None,
    ):
        require_code_allowed(llm, allow_code_to_openai)
        self._llm = llm
        self._tools = tools
        self._code_date = code_date
        self._log = log

    def write(
        self, result: CodeSearchResult, manual_answer: str | None = None, manual_pages: list[str] | None = None
    ) -> CodeAnswer:
        manual_pages = manual_pages or []
        answer = self._answer(result, manual_answer, manual_pages)
        answer.provider, answer.model = self._llm.provider, self._llm.model
        if self._log is not None:
            self._log.write({"kind": "code_answer", **asdict(answer)})
        return answer

    def _answer(self, result: CodeSearchResult, manual_answer: str | None, manual_pages: list[str]) -> CodeAnswer:
        base = dict(
            question=result.question,
            not_checked=list(ALWAYS_NOT_CHECKED),
            code_date=self._code_date,
            tool_calls=list(result.tool_calls),
        )
        if result.status != "finished":  # a stopped run never gets a conclusion
            notice = STOPPED_NOTICES.get(result.status, STOPPED_NOTICES["error"])
            return CodeAnswer(status=result.status, text=notice + NO_CONCLUSION, error=result.error, **base)
        if not (result.conclusion or "").strip():
            return CodeAnswer(
                status="error",
                text=STOPPED_NOTICES["error"] + NO_CONCLUSION,
                error="the Code Search finished without a conclusion",
                **base,
            )
        prompt = [
            ("system", CODE_ANSWER_PROMPT),
            (
                "human",
                CODE_ANSWER_TEMPLATE.format(
                    question=result.question,
                    manual_answer=manual_answer or NO_MANUAL_ANSWER,
                    manual_pages=", ".join(manual_pages) or NO_MANUAL_PAGES,
                    conclusion=result.conclusion,
                ),
            ),
        ]
        try:
            output = self._llm.invoke(prompt, LLMCodeAnswer)
        except Exception as error:  # refusal, truncation, API errors: the conclusion is still shown, as it was written
            return CodeAnswer(status=UNSTRUCTURED, text=result.conclusion, error=f"{type(error).__name__}: {error}", **base)

        citations, dropped = self._validated(output.citations)
        agreement, differing = _verdict(output, manual_answer, manual_pages)
        base["not_checked"] = _merge_not_checked(output.not_checked)
        return CodeAnswer(
            status=ANSWERED,
            text=output.answer,
            citations=citations,
            dropped_citations=dropped,
            manual_agreement=agreement,
            differing_manual_pages=differing,
            **base,
        )

    def _validated(self, cited: list[LLMCodeCitation]) -> tuple[list[CodeCitation], list[str]]:
        """Keep the ranges that exist in the Code Checkout, with the snippet read from the file; list the rest."""
        citations: list[CodeCitation] = []
        dropped: list[str] = []
        for item in cited:
            citation = self._citation(item)
            if citation is None:
                label = f"{item.path}:{item.start_line}-{item.end_line}"
                if label not in dropped:
                    dropped.append(label)
            elif citation not in citations:
                citations.append(citation)
        return citations, dropped

    def _citation(self, item: LLMCodeCitation) -> CodeCitation | None:
        start, end = item.start_line, item.end_line
        if start < 1 or end < start:
            return None
        path = item.path.strip().replace("\\", "/").removeprefix("./")
        try:
            read = self._tools.read(path, start, min(end - start + 1, MAX_SNIPPET_LINES))
        except CodeToolError:  # missing, outside the Code Checkout, excluded folder, extension not allowed
            return None
        if end > read.total_lines:  # the range does not fully exist
            return None
        return CodeCitation(read.path, start, end, read.text, snippet_truncated=end - start + 1 > MAX_SNIPPET_LINES)


def _verdict(output: LLMCodeAnswer, manual_answer: str | None, manual_pages: list[str]) -> tuple[str, list[str]]:
    if not manual_answer:
        return NO_MANUAL, []
    if output.manual_agreement != DIFFERS:
        return output.manual_agreement, []
    differing = [page for page in dict.fromkeys(p.strip() for p in output.differing_manual_pages) if page in manual_pages]
    return DIFFERS, differing


def _merge_not_checked(extra: list[str]) -> list[str]:
    merged = list(ALWAYS_NOT_CHECKED)
    for item in extra:
        item = item.strip()
        if item and item.lower() not in (m.lower() for m in merged):
            merged.append(item)
    return merged


# --- showing it --------------------------------------------------------------------------------------

AGREEMENT_LINES = {
    AGREES: "Handleiding: de code bevestigt het antwoord uit de handleiding.",
    DIFFERS: "Handleiding: de code wijkt af van het antwoord uit de handleiding.",
    UNKNOWN: "Handleiding: de code laat niet zien of het antwoord uit de handleiding klopt.",
    NO_MANUAL: "Handleiding: er was geen antwoord uit de handleiding om mee te vergelijken.",
}


def format_code_answer(answer: CodeAnswer) -> str:
    lines = [f"[{UNVERIFIED_LABEL}]"]
    if answer.code_date:
        lines.append(f"(code per {answer.code_date})")
    lines += ["", answer.text]
    if answer.error:
        lines += ["", f"[fout: {answer.error}]"]
    if answer.status == UNSTRUCTURED:
        lines += ["", "[let op: de bronverwijzingen in dit antwoord zijn niet gecontroleerd]"]
    if answer.status == ANSWERED:
        lines += ["", AGREEMENT_LINES.get(answer.manual_agreement, AGREEMENT_LINES[UNKNOWN])]
        if answer.differing_manual_pages:
            lines.append("Afwijkende pagina's: " + ", ".join(answer.differing_manual_pages))
    for citation in answer.citations:
        lines += ["", f"{citation.path}:{citation.start_line}-{citation.end_line}", citation.snippet]
        if citation.snippet_truncated:
            lines.append("[...]")
    if answer.dropped_citations:
        lines += ["", f"[{len(answer.dropped_citations)} verwijzing(en) weggelaten: de regels bestaan niet in de code]"]
    if answer.status not in (ANSWERED, UNSTRUCTURED) and answer.tool_calls:
        lines += ["", "Onderzocht:"] + [f"- {call.describe()}" for call in answer.tool_calls]
    lines += ["", "Niet gecontroleerd: " + ", ".join(answer.not_checked)]
    return "\n".join(lines)

