"""The ask stage: a question to a `ManualAnswer`, written only from the retrieved Manual Chunks.

The rules are in docs/design-decisions.md, section "Answering". Retrieval and config errors raise;
LLM problems come back as a `ManualAnswer` with `error` set.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from navigate_helper.ask_log import AskLog
from navigate_helper.config import Config, load_config
from navigate_helper.embed import ChromaRetriever, load_embedder, open_store
from navigate_helper.llm import OpenAILLM
from navigate_helper.prompts import APOLOGY, CONTEXT_TEMPLATE, SYSTEM_PROMPT

CLOSEST_PAGES = 3


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
class ManualAnswer:
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


class Assistant:
    def __init__(self, retriever, llm, chunk_store, k: int, log_path: Path | None = None, model: str = ""):
        self._retriever = retriever
        self._llm = llm
        self._chunks = chunk_store
        self._k = k
        self._log = AskLog(log_path, model) if log_path is not None else None

    def ask(self, question: str) -> ManualAnswer:
        hits = self._retriever.retrieve(question, self._k)  # retrieval errors raise
        retrieved = [ScoredChunk.from_chunk(self._chunks.get(chunk_id), score) for chunk_id, score in hits]
        answer = self._answer(question, retrieved)
        if self._log is not None:
            self._log.write(asdict(answer))
        return answer

    def _answer(self, question: str, retrieved: list[ScoredChunk]) -> ManualAnswer:
        context = "\n\n".join(f"[{c.chunk_id}]\n{c.text}" for c in retrieved)
        prompt = [("system", SYSTEM_PROMPT), ("human", CONTEXT_TEMPLATE.format(context=context, question=question))]
        try:
            output = self._llm.invoke(prompt)
        except Exception as error:  # refusal, truncation, API errors: never raised to the caller
            return ManualAnswer(question, APOLOGY, covered=False, retrieved=retrieved, error=f"{type(error).__name__}: {error}")

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
        return ManualAnswer(
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


def format_answer(answer: ManualAnswer) -> str:
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


def run(config: Config, question: str) -> ManualAnswer:
    answer = build_assistant(config).ask(question)
    print(format_answer(answer))
    return answer
