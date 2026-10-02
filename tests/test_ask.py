import json
import warnings

import pytest

from navigate_helper import ask, cli
from navigate_helper.ask import Assistant, JsonChunkStore, LLMAnswer
from navigate_helper.config import load_config
from navigate_helper.prompts import APOLOGY, SYSTEM_PROMPT
from tests.fakes import FakeChunkStore, FakeLLM, FakeRetriever
from tests.test_embed import make_chunk, write_page


def chunks():
    return {
        "A#0": make_chunk("A", 0, screenshots=["images/a.jpg", "images/shared.jpg"],
                          page_links=[{"title": "Pagina B", "page_file": "B.htm"}]),
        "A#1": make_chunk("A", 1, screenshots=["images/shared.jpg"],
                          page_links=[{"title": "Pagina B", "page_file": "B.htm"}]),
        "B#0": make_chunk("B", 0, screenshots=["images/b.jpg"]),
        "C#0": make_chunk("C", 0),
        "D#0": make_chunk("D", 0),
    }


HITS = [("A#0", 0.9), ("A#1", 0.8), ("B#0", 0.7), ("C#0", 0.6), ("D#0", 0.5)]


def assistant(result=None, error=None, k=5, log_path=None, hits=HITS):
    llm = FakeLLM(result=result, error=error)
    retriever = FakeRetriever(hits)
    return Assistant(retriever, llm, FakeChunkStore(chunks()), k, log_path=log_path, model="fake"), llm, retriever


def reply(cited, covered=True, text="Antwoord."):
    return LLMAnswer(answer=text, covered=covered, cited_chunk_ids=cited)


def test_covered_answer_collects_cited_chunks_screenshots_and_links_deduplicated():
    sut, _, retriever = assistant(reply(["A#0", "A#1", "B#0"]))
    answer = sut.ask("vraag")
    assert retriever.calls == [("vraag", 5)]
    assert answer.question == "vraag" and answer.text == "Antwoord." and answer.covered and answer.error is None
    assert [c.chunk_id for c in answer.cited] == ["A#0", "A#1", "B#0"]
    assert answer.screenshots == ["images/a.jpg", "images/shared.jpg", "images/b.jpg"]
    assert answer.page_links == [{"title": "Pagina B", "page_file": "B.htm"}]
    assert answer.source_pages == [{"page_file": "A.htm", "page_title": "A"}, {"page_file": "B.htm", "page_title": "B"}]
    assert not answer.uncited


def test_retrieved_holds_all_k_with_scores_and_cited_flag():
    answer = assistant(reply(["B#0"]))[0].ask("vraag")
    assert [(c.chunk_id, c.score, c.cited) for c in answer.retrieved] == [
        ("A#0", 0.9, False), ("A#1", 0.8, False), ("B#0", 0.7, True), ("C#0", 0.6, False), ("D#0", 0.5, False)]
    assert answer.retrieved[0].screenshots == ["images/a.jpg", "images/shared.jpg"]


def test_invalid_and_repeated_citations_are_dropped_or_merged():
    answer = assistant(reply(["A#0", "X#9", "A#0", "X#9"]))[0].ask("vraag")
    assert [c.chunk_id for c in answer.cited] == ["A#0"]
    assert answer.dropped_citation_ids == ["X#9"]


def test_covered_without_valid_citation_is_flagged_not_changed():
    answer = assistant(reply(["X#9"]))[0].ask("vraag")
    assert answer.covered and answer.text == "Antwoord." and answer.uncited
    assert answer.screenshots == [] and answer.source_pages == []


def test_not_covered_lists_the_three_closest_unique_pages():
    answer = assistant(reply([], covered=False, text="Staat niet in de handleiding."))[0].ask("vraag")
    assert not answer.covered and answer.error is None
    assert answer.text == "Staat niet in de handleiding."
    assert [p["page_file"] for p in answer.source_pages] == ["A.htm", "B.htm", "C.htm"]


def test_closest_pages_rank_by_best_score_not_input_order():
    hits = [("C#0", 0.2), ("B#0", 0.5), ("A#1", 0.3), ("A#0", 0.9)]
    answer = assistant(reply([], covered=False), hits=hits)[0].ask("vraag")
    assert [p["page_file"] for p in answer.source_pages] == ["A.htm", "B.htm", "C.htm"]


def test_prompt_has_dutch_system_message_and_chunk_id_plus_text_blocks_without_scores():
    sut, llm, _ = assistant(reply(["A#0"]), k=2)
    sut.ask("Hoe boek ik?")
    (system, human) = llm.prompts[0]
    assert system == ("system", SYSTEM_PROMPT)
    for phrase in ("Nederlands", "Aryza Navigate", "Credit Navigator", "NV", "covered", "cited_chunk_ids"):
        assert phrase in SYSTEM_PROMPT
    body = human[1]
    assert f"[A#0]\n{chunks()['A#0']['text']}" in body and f"[A#1]\n{chunks()['A#1']['text']}" in body
    assert "B#0" not in body and "0.9" not in body
    assert body.endswith("Vraag: Hoe boek ik?")


@pytest.mark.parametrize("error", [RuntimeError("refused"), ask.LLMError("cut off"), TimeoutError("api")])
def test_llm_problems_return_an_answer_with_error_and_keep_retrieved(error):
    answer = assistant(error=error)[0].ask("vraag")
    assert answer.error and str(error) in answer.error
    assert answer.covered is False and answer.text == APOLOGY
    assert len(answer.retrieved) == 5 and answer.cited == []


def test_retrieval_and_chunk_store_errors_raise():
    class Broken:
        def retrieve(self, question, k):
            raise ConnectionError("chroma down")

    with pytest.raises(ConnectionError):
        Assistant(Broken(), FakeLLM(result=reply([])), FakeChunkStore({}), 5).ask("vraag")
    with pytest.raises(KeyError):
        Assistant(FakeRetriever([("Z#0", 0.5)]), FakeLLM(result=reply([])), FakeChunkStore({}), 5).ask("vraag")


def test_every_call_appends_a_json_line_even_after_llm_errors(tmp_path):
    log = tmp_path / "sub" / "ask_log.jsonl"
    assistant(reply(["A#0"]), log_path=log)[0].ask("een")
    assistant(error=RuntimeError("x"), log_path=log)[0].ask("twee")
    first, second = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert first["question"] == "een" and first["model"] == "fake" and first["timestamp"]
    assert first["cited"][0]["chunk_id"] == "A#0" and len(first["retrieved"]) == 5
    assert second["question"] == "twee" and second["error"]


def test_logging_failure_only_warns(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    sut = assistant(reply(["A#0"]), log_path=blocker / "ask_log.jsonl")[0]
    with pytest.warns(UserWarning, match="ask log"):
        answer = sut.ask("vraag")
    assert answer.text == "Antwoord."


def test_no_warning_when_logging_works(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assistant(reply(["A#0"]), log_path=tmp_path / "log.jsonl")[0].ask("vraag")


def test_json_chunk_store_finds_chunks_by_id_with_stem_before_the_hash(tmp_path):
    config = load_config({"DATA_DIR": str(tmp_path)})
    write_page(config, "Pagina,_x", [make_chunk("Pagina,_x", 0), make_chunk("Pagina,_x", 1)])
    store = JsonChunkStore(config.chunked_dir)
    assert store.get("Pagina,_x#1")["chunk_index"] == 1
    with pytest.raises(FileNotFoundError):
        store.get("Nope#0")


def test_run_prints_the_answer_and_its_sources(monkeypatch, capsys, tmp_path):
    sut = assistant(reply(["A#0"]))[0]
    monkeypatch.setattr(ask, "build_assistant", lambda config: sut)
    answer = ask.run(load_config({"DATA_DIR": str(tmp_path)}), question="vraag")
    out = capsys.readouterr().out
    assert answer.text in out and "A.htm" in out and "images/a.jpg" in out and "Pagina B" in out


def test_cli_ask_runs_the_stage_after_the_key_check(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: load_config({"OPENAI_API_KEY": "sk-test"}))
    seen = []
    monkeypatch.setattr(cli.ask, "run", lambda config, question: seen.append(question))
    assert cli.main(["ask", "Hoe?"]) == 0
    assert seen == ["Hoe?"]


# --- the OpenAI adapter, with a stubbed chain (no network) ----------------------------------


class StubChain:
    def __init__(self, result):
        self.result = result

    def invoke(self, messages):
        return self.result


def adapter(result):
    llm = ask.OpenAILLM(load_config({"OPENAI_API_KEY": "sk-test"}))  # builds the client, calls nothing
    llm._chain = StubChain(result)
    return llm


def raw_message(finish_reason="stop", refusal=None):
    from langchain_core.messages import AIMessage

    return AIMessage(content="", additional_kwargs={"refusal": refusal} if refusal else {},
                     response_metadata={"finish_reason": finish_reason})


def test_adapter_returns_the_parsed_answer():
    parsed = reply(["A#0"])
    assert adapter({"raw": raw_message(), "parsed": parsed, "parsing_error": None}).invoke([]) is parsed


@pytest.mark.parametrize("result, message", [
    ({"raw": raw_message(refusal="nee"), "parsed": None, "parsing_error": None}, "refused"),
    ({"raw": raw_message("length"), "parsed": None, "parsing_error": None}, "cut off"),
    ({"raw": raw_message(), "parsed": None, "parsing_error": ValueError("bad")}, "unparseable"),
])
def test_adapter_raises_llm_error_for_refusal_truncation_and_bad_output(result, message):
    with pytest.raises(ask.LLMError, match=message):
        adapter(result).invoke([])


def test_adapter_uses_the_configured_effort_and_token_cap_without_temperature():
    chat = ask.OpenAILLM(load_config({"OPENAI_API_KEY": "sk-test", "LLM_REASONING_EFFORT": "low"}))._chat
    assert chat.reasoning_effort == "low" and chat.max_tokens == 4000 and chat.temperature is None
