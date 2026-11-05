"""The Code path as one service: Manual Answer in, Code Answer out, with progress events. Fakes and `tmp_path` only."""

import json
import os
import threading
from datetime import datetime

import pytest

from navigate_helper.ask import ManualAnswer
from navigate_helper.ask_log import AskLog
from navigate_helper.code_answer import CodeAnswer, LLMCodeAnswer, LLMCodeCitation
from navigate_helper.code_check import CodeChecker, build_code_checker, stream_check
from navigate_helper.code_search import CodeSearchError, ProgressEvent
from navigate_helper.code_tools import CodeTools
from navigate_helper.config import load_config
from tests.fakes import FakeToolLLM, scripted_turn

GREP = ("grep", {"pattern": "Invoice"})


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "code"
    (root / "src").mkdir(parents=True)
    (root / "src" / "order.p").write_text("DEF VAR x.\nRUN Invoice.\nMESSAGE Hello.\n", encoding="utf-8")
    return CodeTools(root)


def manual(covered=True, error=None, text="Zie de handleiding."):
    return ManualAnswer(
        "Hoe werkt facturen?", text, covered=covered, error=error,
        source_pages=[{"page_file": "Facturen.htm", "page_title": "Facturen"}],
    )


def structured(**overrides):
    fields = dict(
        answer="De code roept Invoice aan.", citations=[LLMCodeCitation(path="src/order.p", start_line=2, end_line=2)],
        manual_agreement="agrees", differing_manual_pages=[], not_checked=[],
    )
    return LLMCodeAnswer(**{**fields, **overrides})


def scripted(*turns, **options):
    return FakeToolLLM(turns=list(turns) or [scripted_turn(calls=(GREP,)), scripted_turn("Conclusie.")], result=structured(), **options)


def checker(tools, **options):
    return CodeChecker(tools, "2026-10-30", **options)


# --- check ------------------------------------------------------------------------------------------


def test_a_manual_answer_is_checked_against_the_code_and_becomes_a_code_answer(tools):
    answer = checker(tools).check(manual(), scripted())
    assert isinstance(answer, CodeAnswer) and answer.status == "answered" and answer.code_date == "2026-10-30"
    assert answer.citations[0].snippet == "RUN Invoice." and answer.manual_agreement == "agrees"
    assert [c.name for c in answer.tool_calls] == ["grep"]


def test_a_covered_manual_answer_and_its_pages_go_to_the_search_and_the_structuring_step(tools):
    llm = scripted()
    checker(tools).check(manual(), llm)
    search_prompt = llm.calls[0][0][1].content
    assert "Zie de handleiding." in search_prompt and "Facturen.htm" in search_prompt
    assert "Facturen.htm" in str(llm.prompts[0])


@pytest.mark.parametrize("answer", [manual(covered=False, text="Dat staat niet in de handleiding."),
                                    manual(error="boom", text="Sorry")])
def test_a_manual_answer_that_did_not_answer_is_not_handed_over_as_one(tools, answer):
    llm = scripted()
    result = checker(tools).check(answer, llm)
    prompt = llm.calls[0][0][1].content
    assert "geen antwoord uit de handleiding" in prompt
    assert "Dat staat niet" not in prompt and "Sorry" not in prompt and "Facturen.htm" not in prompt
    assert result.manual_agreement == "no_manual_answer"


def test_progress_events_run_from_started_through_tool_calls_to_writing(tools):
    events = []
    checker(tools).check(manual(), scripted(), on_event=events.append)
    assert [e.kind for e in events] == ["started", "tool_call", "writing"]
    assert all(isinstance(e, ProgressEvent) for e in events)


def test_a_stopped_search_gives_a_partial_answer_and_no_writing_event(tools):
    events = []
    llm = scripted(scripted_turn(calls=(GREP,)))
    answer = checker(tools).check(manual(), llm, cancelled=lambda: True, on_event=events.append)
    assert answer.status == "cancelled" and answer.citations == [] and llm.prompts == []
    assert "writing" not in [e.kind for e in events]


def test_openai_is_refused_unless_code_to_openai_is_allowed(tools):
    with pytest.raises(CodeSearchError, match="OpenAI"):
        checker(tools).check(manual(), scripted(provider="openai"))
    assert checker(tools, allow_code_to_openai=True).check(manual(), scripted(provider="openai")).status == "answered"


def test_both_steps_are_logged(tools, tmp_path):
    path = tmp_path / "ask_log.jsonl"
    checker(tools, log=AskLog(path)).check(manual(), scripted())
    assert [json.loads(line)["kind"] for line in path.read_text(encoding="utf-8").splitlines()] == ["code_search", "code_answer"]


# --- build_code_checker -----------------------------------------------------------------------------


def test_there_is_no_checker_without_a_code_dir_or_with_a_missing_folder(tmp_path):
    assert build_code_checker(load_config({"DATA_DIR": str(tmp_path)})) is None
    assert build_code_checker(load_config({"DATA_DIR": str(tmp_path), "CODE_DIR": str(tmp_path / "nope")})) is None


def test_the_checker_takes_the_code_date_at_startup_and_the_openai_flag_from_config(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    (root / "a.p").write_text("x", encoding="utf-8")
    stamp = datetime(2026, 10, 30, 12).timestamp()
    os.utime(root / "a.p", (stamp, stamp))
    sut = build_code_checker(load_config({"DATA_DIR": str(tmp_path), "CODE_DIR": str(root)}))
    assert sut.check(manual(), scripted()).code_date == "2026-10-30"
    with pytest.raises(CodeSearchError):
        sut.check(manual(), scripted(provider="openai"))
    env = {"DATA_DIR": str(tmp_path), "CODE_DIR": str(root), "ALLOW_CODE_TO_OPENAI": "true"}
    assert build_code_checker(load_config(env)).check(manual(), scripted(provider="openai")).status == "answered"


def test_a_code_dir_without_readable_files_has_no_code_date(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    sut = build_code_checker(load_config({"DATA_DIR": str(tmp_path), "CODE_DIR": str(root)}))
    assert sut.check(manual(), scripted()).code_date is None


# --- the event stream -------------------------------------------------------------------------------


def test_stream_check_yields_each_event_then_the_code_answer_last(tools):
    items = list(stream_check(checker(tools), manual(), scripted()))
    assert [type(i).__name__ for i in items] == ["ProgressEvent", "ProgressEvent", "ProgressEvent", "CodeAnswer"]
    assert items[-1].status == "answered"


def test_stream_check_re_raises_a_refusal_in_the_caller(tools):
    with pytest.raises(CodeSearchError):
        list(stream_check(checker(tools), manual(), scripted(provider="openai")))


def test_stream_check_hands_the_cancel_flag_to_the_search(tools):
    stop = threading.Event()
    stop.set()
    *_, answer = stream_check(checker(tools), manual(), scripted(), cancelled=stop.is_set)
    assert answer.status == "cancelled"
