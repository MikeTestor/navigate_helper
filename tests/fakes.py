"""Fakes shared by the stage tests. They need no model, network or `raw/`."""

import hashlib
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage

from navigate_helper.llm import ChatTurn, ToolCall


class FakeEmbedder:
    """Deterministic embedder that records every call, so prefix tests can inspect it."""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.documents: list[list[str]] = []
        self.queries: list[str] = []

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255 for b in digest[: self.dim]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.append(list(texts))
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self._vector(text)


class FakeRetriever:
    """Returns canned (chunk_id, score) pairs, best first."""

    def __init__(self, results: list[tuple[str, float]]):
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, question: str, k: int) -> list[tuple[str, float]]:
        self.calls.append((question, k))
        return self.results[:k]


class FakeChunkStore:
    """Maps chunk_id to the full Chunk dict, as the chunked JSON would."""

    def __init__(self, chunks: dict[str, dict]):
        self.chunks = chunks

    def get(self, chunk_id: str) -> dict:
        return self.chunks[chunk_id]


@dataclass
class FakeLLM:
    """Returns a canned structured result, or raises a canned error."""

    result: object = None
    error: Exception | None = None
    prompts: list[object] = field(default_factory=list)
    provider: str = "fake"
    model: str = "fake-model"

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


def scripted_turn(text: str = "", calls: tuple[tuple[str, dict], ...] = (), tokens: int = 100) -> ChatTurn:
    """One model turn: final `text` and/or tool `calls` as (name, args); `tokens` counted as input and output."""
    tool_calls = tuple(ToolCall(id=f"call-{i}", name=name, args=args) for i, (name, args) in enumerate(calls))
    message = AIMessage(
        content=text, tool_calls=[{"id": c.id, "name": c.name, "args": c.args} for c in tool_calls]
    )
    return ChatTurn(message=message, text=text, tool_calls=tool_calls, input_tokens=tokens, output_tokens=tokens)


@dataclass
class FakeToolLLM:
    """Plays scripted `ChatTurn`s (or raises a scripted Exception) for `chat`, and records every call."""

    turns: list[object] = field(default_factory=list)
    provider: str = "fake"
    model: str = "fake-model"
    calls: list[tuple[list, list]] = field(default_factory=list)

    def chat(self, messages, tools):
        self.calls.append((list(messages), tools))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


class FakeTokenizer:
    """One token per whitespace-separated word; enough for cap and split tests."""

    def count(self, text: str) -> int:
        return len(text.split())
