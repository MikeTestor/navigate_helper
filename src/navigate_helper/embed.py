"""Stage 3 – Embed: Chunks (`chunked/*.json`) to a Chroma store at `embedded/chroma/`.

The rules are in docs/design-decisions.md, section "Stage 3 – Embed".
"""

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from navigate_helper.chunk import CONTEXT_SEPARATOR
from navigate_helper.config import CHUNK_TOKEN_CEILING, COLLECTION_NAME, Config, StageError

BATCH_SIZE = 64
PASSAGE_PROMPT = "passage: "
QUERY_PROMPT = "query: "


def build_embedder(model_name: str):
    """The e5 model: the prefixes are added by the model call, so stored text stays prefix-free."""
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=model_name,
        encode_kwargs={"prompt": PASSAGE_PROMPT, "normalize_embeddings": True},
        query_encode_kwargs={"prompt": QUERY_PROMPT, "normalize_embeddings": True},
    )


def load_embedder(config: Config):
    return build_embedder(config.embedding_model)


def open_store(chroma_dir: Path, embedder):
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embedder,
        persist_directory=str(chroma_dir),
        collection_configuration={"hnsw": {"space": "cosine"}},
    )


def release_chroma_clients() -> None:
    from chromadb.api.shared_system_client import SharedSystemClient

    for system in list(SharedSystemClient._identifier_to_system.values()):
        system.stop()  # closes the sqlite handles, which Windows will not let us delete otherwise
    SharedSystemClient.clear_system_cache()


def _stored_count(store) -> int:
    return store._collection.count()


class ChromaRetriever:
    """Top k Chunks for a question as `(chunk_id, score)`, best first. The score is cosine
    similarity, shown raw; there is no threshold."""

    def __init__(self, store):
        self._store = store

    def retrieve(self, question: str, k: int) -> list[tuple[str, float]]:
        found = self._store.similarity_search_with_relevance_scores(question, k=k)
        return [(document.id, score) for document, score in found]


# --- the stage ------------------------------------------------------------------------------


@dataclass
class EmbedReport:
    chunks: int = 0
    pages: int = 0
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        return f"embedded {self.chunks} Chunks from {self.pages} pages in {self.elapsed_seconds:.1f}s"


def _metadata(chunk: dict) -> dict:
    return {
        "page_file": chunk["page_file"],
        "page_title": chunk["page_title"],
        "heading_path": CONTEXT_SEPARATOR.join(chunk["heading_path"]),
        "chunk_index": chunk["chunk_index"],
        "token_count": chunk["token_count"],
        "menu_path": CONTEXT_SEPARATOR.join(chunk["menu_path"]),
    }


def load_chunks(chunked_dir: Path) -> tuple[list[dict], int]:
    """All Chunks (in file order) and the number of pages they come from, checked by the guards."""
    files = sorted(chunked_dir.glob("*.json")) if chunked_dir.is_dir() else []
    if not files:
        raise StageError(f"no Chunks found in {chunked_dir}; run `chunk` first")
    chunks: list[dict] = []
    seen: dict[str, str] = {}
    for path in files:
        for chunk in json.loads(path.read_text(encoding="utf-8")):
            chunk_id = chunk["chunk_id"]
            if chunk_id in seen:
                raise StageError(f"duplicate chunk_id {chunk_id} (in {seen[chunk_id]} and {path.name})")
            if chunk["token_count"] > CHUNK_TOKEN_CEILING:
                raise StageError(
                    f"{chunk_id} has {chunk['token_count']} tokens, over the {CHUNK_TOKEN_CEILING}-token limit; "
                    "it is never truncated"
                )
            seen[chunk_id] = path.name
            chunks.append(chunk)
    if not chunks:
        raise StageError(f"the files in {chunked_dir} hold no Chunks; run `chunk` first")
    return chunks, len(files)


def run(config: Config, embedder=None) -> EmbedReport:
    chunks, pages = load_chunks(config.chunked_dir)  # all guards pass before the old store is touched
    started = time.perf_counter()
    if embedder is None:
        embedder = load_embedder(config)
    release_chroma_clients()  # an open client in this process would keep serving the deleted store
    try:
        shutil.rmtree(config.chroma_dir)  # not delete_collection: chroma-core/chroma#7594
    except FileNotFoundError:
        pass
    except OSError as error:
        raise StageError(f"cannot delete the old store at {config.chroma_dir}: {error}") from error
    config.chroma_dir.parent.mkdir(parents=True, exist_ok=True)
    store = open_store(config.chroma_dir, embedder)

    for start in tqdm(range(0, len(chunks), BATCH_SIZE), desc="embed", unit="batch", disable=len(chunks) <= BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        store.add_texts(
            texts=[c["text"] for c in batch],
            metadatas=[_metadata(c) for c in batch],
            ids=[c["chunk_id"] for c in batch],
        )

    stored = _stored_count(store)
    if stored != len(chunks):
        raise StageError(f"Chunk count mismatch: {len(chunks)} in the JSON but {stored} in Chroma")
    report = EmbedReport(len(chunks), pages, time.perf_counter() - started)
    print(report.summary())
    return report
