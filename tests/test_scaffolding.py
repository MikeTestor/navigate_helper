import importlib

import pytest

from navigate_helper import cli
from navigate_helper.config import MissingConfigError, load_config
from tests.fakes import FakeChunkStore, FakeEmbedder, FakeLLM, FakeRetriever, FakeTokenizer


@pytest.mark.parametrize("module", ["clean", "chunk", "embed", "ask", "ui", "config", "cli"])
def test_stage_modules_import(module):
    importlib.import_module(f"navigate_helper.{module}")


def test_runtime_dependencies_import():
    for name in ("bs4", "markdownify", "chromadb", "gradio", "langchain_chroma",
                 "langchain_huggingface", "langchain_openai", "dotenv", "tqdm"):
        importlib.import_module(name)


def test_config_defaults():
    config = load_config({})
    assert config.llm_model == "gpt-5-mini"
    assert config.llm_reasoning_effort == "low"
    assert config.embedding_model == "intfloat/multilingual-e5-base"
    assert config.retrieval_k == 6
    assert config.chroma_dir.name == "chroma"
    assert config.openai_api_key is None


def test_config_reads_env_keys():
    config = load_config({"OPENAI_API_KEY": "k", "LLM_MODEL": "m", "RETRIEVAL_K": "3", "DATA_DIR": "x"})
    assert (config.openai_api_key, config.llm_model, config.retrieval_k) == ("k", "m", 3)
    assert config.cleaned_dir.parts[0] == "x"


def test_only_ask_and_ui_need_the_api_key(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: load_config({}))
    with pytest.raises(MissingConfigError):
        load_config({}).require_api_key()
    # embed runs without the key check (stubbed: the real stage would rebuild database/)
    ran = []
    monkeypatch.setattr(cli.embed, "run", lambda config: ran.append(config))
    assert cli.main(["embed"]) == 0
    assert len(ran) == 1
    for argv in (["ask", "vraag"], ["ui"]):
        assert cli.main(argv) == 1
        assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_page_filter_goes_to_clean_and_chunk_only():
    parser = cli.build_parser()
    assert parser.parse_args(["clean", "--page", "x"]).page == "x"
    assert parser.parse_args(["chunk", "--page", "x"]).page == "x"
    with pytest.raises(SystemExit):
        parser.parse_args(["embed", "--page", "x"])


def test_all_stops_on_first_failure_and_skips_the_ui(monkeypatch):
    calls = []

    def stage(name, fail=False):
        def run(config, **kwargs):
            calls.append(name)
            if fail:
                raise NotImplementedError(name)
        return run

    for name in ("clean", "chunk", "embed"):
        monkeypatch.setattr(cli.STAGES[name], "run", stage(name, fail=name == "chunk"))
    monkeypatch.setattr(cli.ui, "run", stage("ui"))
    monkeypatch.setattr(cli, "load_config", lambda: load_config({}))
    assert cli.main(["all"]) == 1
    assert calls == ["clean", "chunk"]


def test_fixture_pages_exist(pages_dir):
    names = {p.name for p in pages_dir.glob("*.htm")}
    assert names == {"tables.htm", "no_sections.htm", "with_files.htm", "Mengcodes_voorbeeld.htm"}
    assert (pages_dir / "with_files_files" / "pic.png").exists()
    assert (pages_dir / "tables.htm").read_bytes().startswith(b"\xef\xbb\xbf")


def test_fakes_behave():
    embedder = FakeEmbedder()
    assert embedder.embed_documents(["a", "a"])[0] == embedder.embed_documents(["a"])[0]
    assert FakeRetriever([("p#0", 0.9), ("p#1", 0.8)]).retrieve("q", 1) == [("p#0", 0.9)]
    assert FakeChunkStore({"p#0": {"chunk_id": "p#0"}}).get("p#0")["chunk_id"] == "p#0"
    assert FakeLLM(result="r").invoke("p") == "r"
    assert FakeTokenizer().count("een twee drie") == 3
