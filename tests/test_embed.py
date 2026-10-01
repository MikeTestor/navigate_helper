import json

import pytest

from navigate_helper import embed
from navigate_helper.config import COLLECTION_NAME, CHUNK_TOKEN_CEILING, StageError, load_config
from tests.fakes import FakeEmbedder


def make_chunk(stem, index, text=None, tokens=50, **extra):
    chunk = {
        "heading_path": [stem, f"Kop {index}"],
        "screenshots": [],
        "page_links": [],
        "chunk_id": f"{stem}#{index}",
        "page_file": f"{stem}.htm",
        "page_title": stem,
        "chunk_index": index,
        "versions": [],
        "char_count": 10,
        "token_count": tokens,
        "menu_path": ["Menu", "Sub"],
        "text": text or f"{stem} › Kop {index}\nInhoud {stem} {index}",
    }
    chunk.update(extra)
    return chunk


def write_page(config, stem, chunks):
    config.chunked_dir.mkdir(parents=True, exist_ok=True)
    (config.chunked_dir / f"{stem}.json").write_text(json.dumps(chunks), encoding="utf-8")


@pytest.fixture
def config(tmp_path):
    cfg = load_config({"DATA_DIR": str(tmp_path)})
    write_page(cfg, "A", [make_chunk("A", 0), make_chunk("A", 1)])
    write_page(cfg, "B", [make_chunk("B", 0)])
    return cfg


def store_of(config, embedder):
    return embed.open_store(config.chroma_dir, embedder)


# --- the embedder and its e5 prefixes -------------------------------------------------------


class FakeSentenceTransformer:
    instances = []

    def __init__(self, model_name, **kwargs):
        self.model_name = model_name
        self.calls = []
        FakeSentenceTransformer.instances.append(self)

    def encode(self, texts, **kwargs):
        import numpy as np

        self.calls.append((list(texts), kwargs))
        return np.ones((len(texts), 4))


def test_both_e5_prefixes_reach_the_model(monkeypatch):
    import sentence_transformers

    FakeSentenceTransformer.instances.clear()
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeSentenceTransformer)
    embedder = embed.build_embedder("some/e5-model")
    embedder.embed_documents(["tekst"])
    embedder.embed_query("vraag")

    model = FakeSentenceTransformer.instances[0]
    assert model.model_name == "some/e5-model"
    (doc_texts, doc_kwargs), (query_texts, query_kwargs) = model.calls
    assert doc_texts == ["tekst"]
    assert (doc_kwargs["prompt"], doc_kwargs["normalize_embeddings"]) == ("passage: ", True)
    assert query_texts == ["vraag"]
    assert (query_kwargs["prompt"], query_kwargs["normalize_embeddings"]) == ("query: ", True)


def test_embedder_uses_the_configured_model_name(monkeypatch):
    seen = []
    monkeypatch.setattr(embed, "build_embedder", lambda name: seen.append(name) or FakeEmbedder())
    cfg = load_config({"EMBEDDING_MODEL": "x/y", "DATA_DIR": "unused"})
    assert embed.load_embedder(cfg) is not None
    assert seen == ["x/y"]


# --- the stage ------------------------------------------------------------------------------


def test_embeds_every_chunk_into_the_cosine_collection(config):
    report = embed.run(config, embedder=FakeEmbedder())
    assert (report.chunks, report.pages) == (3, 2)

    collection = store_of(config, FakeEmbedder())._collection
    assert collection.name == COLLECTION_NAME == "navigate_manual"
    assert collection.count() == 3
    assert collection.configuration["hnsw"]["space"] == "cosine"


def test_id_document_and_scalar_metadata(config):
    chunk = make_chunk("C", 0, text="C › Kop\nde tekst", **{"heading_path": ["C", "Kop", "Diep"]})
    write_page(config, "C", [chunk])
    embed.run(config, embedder=FakeEmbedder())

    got = store_of(config, FakeEmbedder())._collection.get(ids=["C#0"])
    assert got["ids"] == ["C#0"]
    assert got["documents"] == ["C › Kop\nde tekst"]  # the exact text, without the `passage: ` prefix
    assert got["metadatas"][0] == {
        "page_file": "C.htm",
        "page_title": "C",
        "heading_path": "C › Kop › Diep",
        "chunk_index": 0,
        "token_count": 50,
        "menu_path": "Menu › Sub",
    }


def test_the_embedder_receives_the_chunk_texts(config):
    embedder = FakeEmbedder()
    embed.run(config, embedder=embedder)
    sent = [t for batch in embedder.documents for t in batch]
    assert sorted(sent) == sorted(
        [make_chunk("A", 0)["text"], make_chunk("A", 1)["text"], make_chunk("B", 0)["text"]]
    )


def test_embeds_in_batches(config, monkeypatch):
    monkeypatch.setattr(embed, "BATCH_SIZE", 2)
    embedder = FakeEmbedder()
    embed.run(config, embedder=embedder)
    assert [len(b) for b in embedder.documents] == [2, 1]


def test_each_run_rebuilds_from_scratch(config):
    embed.run(config, embedder=FakeEmbedder())
    (config.chunked_dir / "B.json").unlink()
    (config.chroma_dir / "stale.txt").write_text("old")
    report = embed.run(config, embedder=FakeEmbedder())
    assert report.chunks == 2
    assert not (config.chroma_dir / "stale.txt").exists()
    assert store_of(config, FakeEmbedder())._collection.count() == 2


def test_keeps_the_gitkeep_next_to_chroma(config):
    keep = config.chroma_dir.parent / ".gitkeep"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("")
    embed.run(config, embedder=FakeEmbedder())
    assert keep.exists()


def test_report_summary_has_chunks_pages_and_elapsed_time(config, capsys):
    report = embed.run(config, embedder=FakeEmbedder())
    assert report.elapsed_seconds >= 0
    out = capsys.readouterr().out
    assert "3 Chunks" in out and "2 pages" in out and "s" in out


# --- failing clearly ------------------------------------------------------------------------


def test_missing_chunked_folder_fails_clearly(tmp_path):
    cfg = load_config({"DATA_DIR": str(tmp_path)})
    with pytest.raises(StageError, match="chunk"):
        embed.run(cfg, embedder=FakeEmbedder())


def test_empty_chunked_folder_fails_clearly(tmp_path):
    cfg = load_config({"DATA_DIR": str(tmp_path)})
    cfg.chunked_dir.mkdir(parents=True)
    (cfg.chunked_dir / ".gitkeep").write_text("")
    with pytest.raises(StageError, match="chunk"):
        embed.run(cfg, embedder=FakeEmbedder())


def test_failure_does_not_destroy_the_existing_store(config):
    embed.run(config, embedder=FakeEmbedder())
    for path in config.chunked_dir.glob("*.json"):
        path.unlink()
    with pytest.raises(StageError):
        embed.run(config, embedder=FakeEmbedder())
    assert store_of(config, FakeEmbedder())._collection.count() == 3


# --- guards ---------------------------------------------------------------------------------


def test_duplicate_chunk_ids_across_pages_raise(config):
    write_page(config, "C", [make_chunk("A", 0)])  # claims A#0 again
    with pytest.raises(StageError, match="A#0"):
        embed.run(config, embedder=FakeEmbedder())


def test_token_count_over_512_raises_and_is_never_truncated(config):
    write_page(config, "C", [make_chunk("C", 0, tokens=CHUNK_TOKEN_CEILING + 1)])
    with pytest.raises(StageError, match="C#0"):
        embed.run(config, embedder=FakeEmbedder())


def test_token_count_of_exactly_512_is_allowed(config):
    write_page(config, "C", [make_chunk("C", 0, tokens=CHUNK_TOKEN_CEILING)])
    assert embed.run(config, embedder=FakeEmbedder()).chunks == 4


def test_count_mismatch_between_json_and_chroma_raises(config, monkeypatch):
    monkeypatch.setattr(embed, "_stored_count", lambda store: 2)
    with pytest.raises(StageError, match="3.*2|mismatch"):
        embed.run(config, embedder=FakeEmbedder())


# --- the retriever --------------------------------------------------------------------------


def test_retriever_returns_chunk_id_and_cosine_similarity_best_first(config):
    embedder = FakeEmbedder()
    embed.run(config, embedder=embedder)
    retriever = embed.ChromaRetriever(store_of(config, embedder))

    # the query is embedded as the exact text of A#1, so A#1 must be the perfect match
    results = retriever.retrieve(make_chunk("A", 1)["text"], k=3)
    assert [chunk_id for chunk_id, _ in results][0] == "A#1"
    assert results[0][1] == pytest.approx(1.0, abs=1e-4)
    assert len(results) == 3
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)


def test_retriever_is_top_k_with_no_threshold(config):
    embedder = FakeEmbedder()
    embed.run(config, embedder=embedder)
    retriever = embed.ChromaRetriever(store_of(config, embedder))
    assert len(retriever.retrieve("iets heel anders", k=2)) == 2
    assert len(retriever.retrieve("iets heel anders", k=10)) == 3  # fewer Chunks than k


def test_retriever_embeds_the_question_as_a_query(config):
    embedder = FakeEmbedder()
    embed.run(config, embedder=embedder)
    embed.ChromaRetriever(store_of(config, embedder)).retrieve("hoe werkt dit?", k=1)
    assert embedder.queries == ["hoe werkt dit?"]


# --- the real model -------------------------------------------------------------------------


@pytest.mark.slow
def test_real_e5_model_ranks_the_relevant_chunk_first(tmp_path):
    cfg = load_config({"DATA_DIR": str(tmp_path)})
    write_page(
        cfg,
        "Fx",
        [
            make_chunk("Fx", 0, text="Kosten\nHet kostenstempel moderen: kies Acties, dan Kostenmoderatie."),
            make_chunk("Fx", 1, text="Dossier\nEen nieuw dossier aanmaken doe je via het menu Dossier."),
            make_chunk("Fx", 2, text="Betalingen\nBetalingen worden ingelezen via het bankbestand."),
        ],
    )
    embed.run(cfg)  # real model from Config.embedding_model
    retriever = embed.ChromaRetriever(embed.open_store(cfg.chroma_dir, embed.load_embedder(cfg)))
    results = retriever.retrieve("Hoe maak ik een nieuw dossier aan?", k=3)
    assert results[0][0] == "Fx#1"
    assert all(0.0 < score <= 1.0 for _, score in results)
