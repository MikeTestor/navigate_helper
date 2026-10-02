"""The ask stage: a question to an `Answer`, written only from the retrieved Manual Chunks.

The rules are in docs/design-decisions.md, section "Answering". Retrieval and config errors raise;
LLM problems come back as an `Answer` with `error` set.
"""

import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from navigate_helper.config import MAX_COMPLETION_TOKENS, Config, load_config
from navigate_helper.embed import ChromaRetriever, load_embedder, open_store
from navigate_helper.prompts import APOLOGY, CONTEXT_TEMPLATE, SYSTEM_PROMPT

CLOSEST_PAGES = 3


class LLMAnswer(BaseModel):
    """The fixed structured-output schema."""

    answer: str = Field(description="Het antwoord in het Nederlands (Markdown), zonder verwijzingen naar chunk_ids.")
    covered: bool = Field(description="False als de context de vraag niet beantwoordt.")
    cited_chunk_ids: list[str] = Field(description="De chunk_ids die voor het antwoord zijn gebruikt.")


class LLMError(RuntimeError):
    """The LLM refused, was cut off, or returned nothing usable."""


@dataclass
class ScoredChunk:
    """A full Chunk with its retrieval score and whether the Answer cited it."""

    chunk_id: str
    page_file: str
    page_title: str
    heading_path: list[str]
    menu_path: list[str]
    text: str
    screenshots: list[str]
    page_links: list[dict]
    score: float
    cited: bool = False

    @classmethod
    def from_chunk(cls, chunk: dict, score: float) -> "ScoredChunk":
        return cls(
            chunk_id=chunk["chunk_id"],
            page_file=chunk["page_file"],
            page_title=chunk["page_title"],
            heading_path=list(chunk.get("heading_path", [])),
            menu_path=list(chunk.get("menu_path", [])),
            text=chunk["text"],
            screenshots=list(chunk.get("screenshots", [])),
            page_links=list(chunk.get("page_links", [])),
            score=score,
        )


@dataclass
class Answer:
    question: str
    text: str
    covered: bool
    cited: list[ScoredChunk] = field(default_factory=list)
    retrieved: list[ScoredChunk] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    page_links: list[dict] = field(default_factory=list)
    source_pages: list[dict] = field(default_factory=list)
    dropped_citation_ids: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def uncited(self) -> bool:
        """A covered Answer without a single valid citation: shown as-is, flagged in debug."""
        return self.covered and not self.cited and self.error is None


class JsonChunkStore:
    """Full Chunks from `chunked/<stem>.json`, looked up by `chunk_id` (the stem is the part before `#`)."""

    def __init__(self, chunked_dir: Path):
        self._dir = chunked_dir
        self._pages: dict[str, dict[str, dict]] = {}

    def get(self, chunk_id: str) -> dict:
        stem = chunk_id.rsplit("#", 1)[0]
        if stem not in self._pages:
            path = self._dir / f"{stem}.json"
            chunks = json.loads(path.read_text(encoding="utf-8"))
            self._pages[stem] = {c["chunk_id"]: c for c in chunks}
        return self._pages[stem][chunk_id]


class OpenAILLM:
    """`ChatOpenAI` with strict structured output; `invoke(messages)` returns an `LLMAnswer` or raises."""

    def __init__(self, config: Config):
        from langchain_openai import ChatOpenAI

        chat = ChatOpenAI(
            model=config.llm_model,
            api_key=config.require_api_key(),
            reasoning_effort=config.llm_reasoning_effort,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )
        self._chat = chat
        self._chain = chat.with_structured_output(LLMAnswer, method="json_schema", strict=True, include_raw=True)

    def invoke(self, messages) -> LLMAnswer:
        result = self._chain.invoke(messages)
        raw = result.get("raw")
        if raw is not None:
            if raw.additional_kwargs.get("refusal"):
                raise LLMError(f"the model refused: {raw.additional_kwargs['refusal']}")
            if (getattr(raw, "response_metadata", None) or {}).get("finish_reason") == "length":
                raise LLMError(f"the answer was cut off at {MAX_COMPLETION_TOKENS} completion tokens")
        if result.get("parsed") is None:
            raise LLMError(f"unparseable model output: {result.get('parsing_error')}")
        return result["parsed"]


class Assistant:
    def __init__(self, retriever, llm, chunk_store, k: int, log_path: Path | None = None, model: str = ""):
        self._retriever = retriever
        self._llm = llm
        self._chunks = chunk_store
        self._k = k
        self._log_path = log_path
        self._model = model

    def ask(self, question: str) -> Answer:
        hits = self._retriever.retrieve(question, self._k)  # retrieval errors raise
        retrieved = [ScoredChunk.from_chunk(self._chunks.get(chunk_id), score) for chunk_id, score in hits]
        answer = self._answer(question, retrieved)
        self._log(answer)
        return answer

    def _answer(self, question: str, retrieved: list[ScoredChunk]) -> Answer:
        context = "\n\n".join(f"[{c.chunk_id}]\n{c.text}" for c in retrieved)
        prompt = [("system", SYSTEM_PROMPT), ("human", CONTEXT_TEMPLATE.format(context=context, question=question))]
        try:
            output = self._llm.invoke(prompt)
        except Exception as error:  # refusal, truncation, API errors: never raised to the caller
            return Answer(question, APOLOGY, covered=False, retrieved=retrieved, error=f"{type(error).__name__}: {error}")

        by_id = {c.chunk_id: c for c in retrieved}
        cited: list[ScoredChunk] = []
        dropped: list[str] = []
        for chunk_id in output.cited_chunk_ids:
            if chunk_id not in by_id:
                if chunk_id not in dropped:
                    dropped.append(chunk_id)
            elif by_id[chunk_id] not in cited:
                cited.append(by_id[chunk_id])
        for chunk in cited:
            chunk.cited = True

        pages = _pages(cited) if output.covered else closest_pages(retrieved)
        return Answer(
            question=question,
            text=output.answer,
            covered=output.covered,
            cited=cited,
            retrieved=retrieved,
            screenshots=_unique(s for c in cited for s in c.screenshots),
            page_links=_unique(
                (link for c in cited for link in c.page_links), key=lambda link: (link["title"], link["page_file"])
            ),
            source_pages=pages,
            dropped_citation_ids=dropped,
        )

    def _log(self, answer: Answer) -> None:
        if self._log_path is None:
            return
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "model": self._model, **asdict(answer)}
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as error:
            warnings.warn(f"could not write the ask log {self._log_path}: {error}")


def _unique(items, key=lambda item: item) -> list:
    seen, result = set(), []
    for item in items:
        if key(item) not in seen:
            seen.add(key(item))
            result.append(item)
    return result


def _pages(chunks: list[ScoredChunk]) -> list[dict]:
    pages = ({"page_file": c.page_file, "page_title": c.page_title} for c in chunks)
    return _unique(pages, key=lambda page: page["page_file"])


def closest_pages(retrieved: list[ScoredChunk]) -> list[dict]:
    """The top unique pages among the Retrieved Chunks by best score."""
    best_first = sorted(retrieved, key=lambda c: c.score, reverse=True)
    return _pages(best_first)[:CLOSEST_PAGES]


def build_assistant(config: Config | None = None) -> Assistant:
    """Wire the real Chroma store, `ChatOpenAI` and the chunked JSON. Loads the e5 model (slow)."""
    config = config or load_config()
    llm = OpenAILLM(config)  # raises MissingConfigError without the API key
    store = open_store(config.chroma_dir, load_embedder(config))
    return Assistant(
        ChromaRetriever(store),
        llm,
        JsonChunkStore(config.chunked_dir),
        config.retrieval_k,
        log_path=config.ask_log_path,
        model=config.llm_model,
    )


def format_answer(answer: Answer) -> str:
    lines = [answer.text]
    if answer.error:
        lines += ["", f"[fout: {answer.error}]"]
    if answer.source_pages:
        lines += ["", "Bronnen:" if answer.covered else "Dichtstbijzijnde pagina's:"]
        lines += [f"- {p['page_title']} ({p['page_file']})" for p in answer.source_pages]
    if answer.page_links:
        lines += ["", "Zie ook:"] + [f"- {link['title']} ({link['page_file']})" for link in answer.page_links]
    if answer.screenshots:
        lines += ["", "Screenshots:"] + [f"- {s}" for s in answer.screenshots]
    if answer.uncited:
        lines += ["", "[let op: geen geldige bronverwijzing]"]
    return "\n".join(lines)


def run(config: Config, question: str) -> Answer:
    answer = build_assistant(config).ask(question)
    print(format_answer(answer))
    return answer
