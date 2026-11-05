import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from navigate_helper.ask_log import AskLog
from navigate_helper.code_search import CodeSearch, CodeSearchError
from navigate_helper.code_tools import CodeTools
from navigate_helper.config import load_config
from navigate_helper.llm import LLMError
from tests.fakes import FakeToolLLM, scripted_turn

GREP = ("grep", {"pattern": "Invoice"})
READ = ("read", {"path": "src/order.p", "start": 1, "limit": 3})


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "code"
    (root / "src").mkdir(parents=True)
    (root / "src" / "order.p").write_text("DEF VAR x.\nRUN Invoice.\nMESSAGE Hello.\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "secret.p").write_text("Invoice secret\n", encoding="utf-8")
    return CodeTools(root)


def search(tools, turns, **options):
    llm = FakeToolLLM(turns=turns)
    return CodeSearch(llm, tools, **options), llm


def run(sut, **kwargs):
    kwargs.setdefault("manual_answer", "Zie de handleiding.")
    kwargs.setdefault("manual_pages", ["Facturen.htm"])
    return sut.run("Hoe werkt facturen?", **kwargs)


def tool_messages(llm, call=-1):
    return [m for m in llm.calls[call][0] if isinstance(m, ToolMessage)]


# --- a normal run ----------------------------------------------------------------------------


def test_a_normal_run_calls_tools_feeds_results_back_and_finishes(tools):
    sut, llm = search(tools, [scripted_turn(calls=(GREP,), tokens=100), scripted_turn(calls=(READ,), tokens=200),
                              scripted_turn("De code roept Invoice aan.", tokens=300)])
    result = run(sut)
    assert result.status == "finished" and result.conclusion == "De code roept Invoice aan." and result.error is None
    assert [(c.name, c.args, c.ok) for c in result.tool_calls] == [("grep", GREP[1], True), ("read", READ[1], True)]
    assert (result.input_tokens, result.output_tokens) == (600, 600)
    assert (result.provider, result.model) == ("fake", "fake-model")
    first, second = tool_messages(llm, 1), tool_messages(llm, 2)
    assert "src/order.p:2" in first[0].content and first[0].tool_call_id == "call-0"
    assert "RUN Invoice." in second[1].content and len(second) == 2


def test_the_model_gets_the_three_tools_and_a_prompt_with_the_manual_answer(tools):
    sut, llm = search(tools, [scripted_turn("Klaar.")])
    run(sut)
    messages, offered = llm.calls[0]
    assert [t["function"]["name"] for t in offered] == ["grep", "list", "read"]
    assert all(t["type"] == "function" and t["function"]["parameters"]["type"] == "object" for t in offered)
    system, human = messages
    assert isinstance(system, SystemMessage) and isinstance(human, HumanMessage)
    assert "onafhankelijk" in system.content and "grep" in system.content
    for text in ("Hoe werkt facturen?", "Zie de handleiding.", "Facturen.htm"):
        assert text in human.content


def test_a_tool_error_goes_back_to_the_model_and_counts_as_a_call(tools):
    escape = ("read", {"path": "../outside.p"})
    excluded = ("list", {"path": "data"})
    sut, llm = search(tools, [scripted_turn(calls=(escape, excluded)), scripted_turn("Niet gelezen.")])
    result = run(sut)
    assert result.status == "finished" and [c.ok for c in result.tool_calls] == [False, False]
    assert all(m.content.startswith("error:") for m in tool_messages(llm))


@pytest.mark.parametrize("call", [("delete", {"path": "x"}), ("read", {}), ("grep", {"pattern": "x", "bogus": 1})])
def test_unknown_tools_and_bad_arguments_are_errors_for_the_model_not_crashes(tools, call):
    sut, llm = search(tools, [scripted_turn(calls=(call,)), scripted_turn("Klaar.")])
    result = run(sut)
    assert result.status == "finished" and result.tool_calls[0].ok is False
    assert tool_messages(llm)[0].content.startswith("error:")


# --- limits ----------------------------------------------------------------------------------


def test_the_tool_call_limit_stops_before_the_call_that_would_exceed_it(tools):
    sut, llm = search(tools, [scripted_turn(calls=(GREP,)), scripted_turn(calls=(READ, GREP))], max_tool_calls=2)
    result = run(sut)
    assert result.status == "tool_call_limit" and result.conclusion is None
    assert len(result.tool_calls) == 2 and len(llm.calls) == 2  # no model call after the limit


def test_the_input_token_limit_stops_a_turn_that_wants_more_tools(tools):
    sut, llm = search(tools, [scripted_turn(calls=(GREP,), tokens=600), scripted_turn(calls=(READ,), tokens=600)],
                      max_input_tokens=1000)
    result = run(sut)
    assert result.status == "token_limit" and result.conclusion is None
    assert result.input_tokens == 1200 and len(result.tool_calls) == 1 and len(llm.calls) == 2


def test_a_final_answer_is_kept_even_if_it_crossed_the_token_limit(tools):
    sut, _ = search(tools, [scripted_turn("Klaar.", tokens=5000)], max_input_tokens=1000)
    result = run(sut)
    assert result.status == "finished" and result.conclusion == "Klaar."


def test_the_time_limit_stops_the_run_with_a_partial_result(tools):
    ticks = iter(range(0, 1000, 6))
    sut, llm = search(tools, [scripted_turn(calls=(GREP,)), scripted_turn(calls=(READ,)), scripted_turn("x")],
                      max_seconds=10, clock=lambda: next(ticks))
    result = run(sut)
    assert result.status == "timeout" and result.conclusion is None
    assert len(llm.calls) < 3 and result.elapsed_seconds >= 10


@pytest.mark.parametrize("stop_after", [0, 1])
def test_cancelling_stops_the_run_without_a_conclusion(tools, stop_after):
    sut, llm = search(tools, [scripted_turn(calls=(GREP,)), scripted_turn("x")])
    polls = []

    def cancelled():
        polls.append(1)
        return len(polls) > stop_after

    result = run(sut, cancelled=cancelled)
    assert result.status == "cancelled" and result.conclusion is None
    assert len(llm.calls) == stop_after


def test_an_llm_error_ends_the_run_with_the_evidence_so_far(tools):
    sut, _ = search(tools, [scripted_turn(calls=(GREP,)), LLMError("cut off")])
    result = run(sut)
    assert result.status == "error" and "cut off" in result.error and result.conclusion is None
    assert len(result.tool_calls) == 1


# --- OpenAI is blocked for code unless allowed ------------------------------------------------


def test_openai_is_refused_for_code_unless_explicitly_allowed(tools):
    llm = FakeToolLLM(provider="openai")
    with pytest.raises(CodeSearchError, match="ALLOW_CODE_TO_OPENAI"):
        CodeSearch(llm, tools)
    CodeSearch(llm, tools, allow_code_to_openai=True)
    CodeSearch(FakeToolLLM(provider="anthropic"), tools)


def test_the_flag_is_read_from_config():
    assert load_config({}).allow_code_to_openai is False
    assert load_config({"ALLOW_CODE_TO_OPENAI": "true"}).allow_code_to_openai is True
    assert load_config({"ALLOW_CODE_TO_OPENAI": "no"}).allow_code_to_openai is False


# --- logging ---------------------------------------------------------------------------------


def test_each_run_logs_tool_calls_tokens_provider_and_model_but_not_tool_results(tools, tmp_path):
    log = tmp_path / "log.jsonl"
    sut, _ = search(tools, [scripted_turn(calls=(GREP,), tokens=100), scripted_turn("Klaar.", tokens=50)],
                    log=AskLog(log))
    run(sut)
    (line,) = [json.loads(row) for row in log.read_text(encoding="utf-8").splitlines()]
    assert line["kind"] == "code_search" and line["question"] == "Hoe werkt facturen?" and line["status"] == "finished"
    assert (line["provider"], line["model"], line["input_tokens"], line["output_tokens"]) == ("fake", "fake-model", 150, 150)
    (call,) = line["tool_calls"]
    assert (call["name"], call["args"], call["ok"]) == ("grep", GREP[1], True) and call["result_chars"] > 0
    assert "RUN Invoice" not in log.read_text(encoding="utf-8")


def test_a_stopped_run_is_logged_too(tools, tmp_path):
    log = tmp_path / "log.jsonl"
    sut, _ = search(tools, [scripted_turn(calls=(GREP,)), scripted_turn(calls=(READ,))], max_tool_calls=1, log=AskLog(log))
    run(sut)
    assert json.loads(log.read_text(encoding="utf-8"))["status"] == "tool_call_limit"
