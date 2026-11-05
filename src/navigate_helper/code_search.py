"""The Code Search: an agent loop over the read-only Code Checkout tools (ADR 0001).

The model gets `grep`, `list` and `read` through provider tool calling. The loop enforces the limits (tool calls,
input tokens, time, cancellation) and never turns a stopped run into a conclusion: a run that hit a limit has
`conclusion=None` and only the evidence it gathered. OpenAI is refused unless explicitly allowed (ADR 0002).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from navigate_helper.ask_log import AskLog
from navigate_helper.code_tools import CodeTools, CodeToolError
from navigate_helper.config import (
    CODE_SEARCH_MAX_INPUT_TOKENS,
    CODE_SEARCH_MAX_SECONDS,
    CODE_SEARCH_MAX_TOOL_CALLS,
)
from navigate_helper.prompts import (
    CODE_SEARCH_PROMPT,
    CODE_SEARCH_TEMPLATE,
    NO_MANUAL_ANSWER,
    NO_MANUAL_PAGES,
)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search the Code Checkout for lines matching a regular expression. "
            "Returns path:line: text, at most 100 matches. Case-insensitive by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression."},
                    "path": {"type": "string", "description": "File or folder to search, relative to the root. Default: all."},
                    "ignore_case": {"type": "boolean", "description": "Default true."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list",
            "description": "List the files and folders directly under a folder; folders end in a slash.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Folder, relative to the root. Default: the root."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read lines of a file (1-based `start`, at most 400 lines per call).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File, relative to the root."},
                    "start": {"type": "integer", "description": "First line. Default 1."},
                    "limit": {"type": "integer", "description": "Number of lines. Default 400."},
                },
                "required": ["path"],
            },
        },
    },
]


class CodeSearchError(RuntimeError):
    """The Code Search is not allowed to run in this configuration."""


def require_code_allowed(llm, allow_code_to_openai: bool) -> None:
    """Refuse to send code-derived text to OpenAI unless that was explicitly approved (ADR 0002)."""
    if llm.provider == "openai" and not allow_code_to_openai:
        raise CodeSearchError(
            "the Code Search does not send code to OpenAI; set ALLOW_CODE_TO_OPENAI=true only if that is approved"
        )


@dataclass
class ToolCallRecord:
    """One tool call of a run. The result text is not kept (it is code); only its size."""

    name: str
    args: dict
    ok: bool
    result_chars: int

    def describe(self) -> str:
        """One plain line: the tool name and its argument values, as in `grep Invoice src`."""
        return " ".join([self.name, *(str(value) for value in self.args.values())])


@dataclass(frozen=True)
class ProgressEvent:
    """One line of a run's progress. `kind` is started, tool_call or writing; `text` is for a human (Dutch)."""

    kind: str
    text: str


@dataclass
class CodeSearchResult:
    """`status` is finished, tool_call_limit, token_limit, timeout, cancelled or error.

    `conclusion` is the model's last word and is only set when `status == "finished"`.
    """

    question: str
    status: str
    conclusion: str | None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    provider: str = ""
    model: str = ""
    error: str | None = None


def _emitter(on_event):
    """`on_event` made safe: a callback that raises must not stop the search."""

    def emit(event: ProgressEvent) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:
            pass

    return emit


class CodeSearch:
    def __init__(
        self,
        llm,
        tools: CodeTools,
        *,
        allow_code_to_openai: bool = False,
        max_tool_calls: int = CODE_SEARCH_MAX_TOOL_CALLS,
        max_input_tokens: int = CODE_SEARCH_MAX_INPUT_TOKENS,
        max_seconds: float = CODE_SEARCH_MAX_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        log: AskLog | None = None,
    ):
        require_code_allowed(llm, allow_code_to_openai)
        self._llm = llm
        self._tools = tools
        self._max_tool_calls = max_tool_calls
        self._max_input_tokens = max_input_tokens
        self._max_seconds = max_seconds
        self._clock = clock
        self._log = log

    def run(
        self,
        question: str,
        manual_answer: str | None = None,
        manual_pages: list[str] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
        on_event: Callable[[ProgressEvent], None] | None = None,
    ) -> CodeSearchResult:
        """Run the search. `on_event` is called with a `ProgressEvent` as the run proceeds; its problems are ignored."""
        started = self._clock()
        result = CodeSearchResult(question, "finished", None, provider=self._llm.provider, model=self._llm.model)
        try:
            self._loop(result, started, question, manual_answer, manual_pages or [], cancelled, _emitter(on_event))
        except Exception as error:  # LLM refusal, truncation, API errors: a partial result, not a crash
            result.status, result.conclusion, result.error = "error", None, f"{type(error).__name__}: {error}"
        result.elapsed_seconds = self._clock() - started
        if self._log is not None:
            self._log.write({"kind": "code_search", **asdict(result)})
        return result

    def _loop(self, result, started, question, manual_answer, manual_pages, cancelled, emit) -> None:
        human = CODE_SEARCH_TEMPLATE.format(
            question=question,
            manual_answer=manual_answer or NO_MANUAL_ANSWER,
            manual_pages=", ".join(manual_pages) or NO_MANUAL_PAGES,
        )
        messages = [SystemMessage(CODE_SEARCH_PROMPT), HumanMessage(human)]
        emit(ProgressEvent("started", "Onderzoek gestart"))
        while True:
            stop = self._stop_reason(started, cancelled)
            if stop:
                result.status = stop
                return
            turn = self._llm.chat(messages, TOOL_DEFINITIONS)
            result.input_tokens += turn.input_tokens
            result.output_tokens += turn.output_tokens
            if not turn.tool_calls:  # a final answer is kept even when it crossed a limit
                result.status, result.conclusion = "finished", turn.text
                return
            if result.input_tokens > self._max_input_tokens:
                result.status = "token_limit"
                return
            messages.append(turn.message)
            for call in turn.tool_calls:
                if len(result.tool_calls) >= self._max_tool_calls:
                    result.status = "tool_call_limit"
                    return
                stop = self._stop_reason(started, cancelled)
                if stop:
                    result.status = stop
                    return
                ok, text = self._call_tool(call.name, call.args)
                record = ToolCallRecord(call.name, call.args, ok, len(text))
                result.tool_calls.append(record)
                emit(ProgressEvent("tool_call", record.describe() + ("" if ok else " (mislukt)")))
                messages.append(ToolMessage(content=text, tool_call_id=call.id))

    def _stop_reason(self, started: float, cancelled: Callable[[], bool]) -> str | None:
        if cancelled():
            return "cancelled"
        if self._clock() - started >= self._max_seconds:
            return "timeout"
        return None

    def _call_tool(self, name: str, args: dict) -> tuple[bool, str]:
        """Run one tool call. Problems come back as text for the model, never as exceptions."""
        try:
            if name == "grep":
                matches = self._tools.grep(**args)
                return True, "\n".join(f"{m.path}:{m.line}: {m.text}" for m in matches) or "(no matches)"
            if name == "list":
                return True, "\n".join(self._tools.list(**args)) or "(empty)"
            if name == "read":
                read = self._tools.read(**args)
                header = f"{read.path} lines {read.start}-{read.end} of {read.total_lines}"
                numbered = "\n".join(f"{n}: {line}" for n, line in enumerate(read.text.splitlines(), read.start))
                return True, f"{header}{' (more follows)' if read.truncated else ''}\n{numbered}"
            return False, f"error: unknown tool {name!r}; use grep, list or read"
        except CodeToolError as error:
            return False, f"error: {error}"
        except TypeError as error:  # missing or unexpected arguments
            return False, f"error: bad arguments for {name}: {error}"
