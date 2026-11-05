"""The Code path in the GUI: the check button, the automatic check, progress, Stop and the Code tab. Fakes only."""

import time

import gradio as gr
import pytest

from navigate_helper import ui
from navigate_helper.code_answer import CodeAnswer, LLMCodeAnswer, LLMCodeCitation
from navigate_helper.code_check import CodeChecker
from navigate_helper.code_search import ProgressEvent
from navigate_helper.code_tools import CodeTools
from navigate_helper.config import MissingConfigError
from navigate_helper.llm import LLMSwitch
from tests.fakes import FakeToolLLM, scripted_turn
from tests.test_ui import FakeAssistant, config, make_answer  # noqa: F401  (config is a fixture)


def code_checker(tmp_path):
    root = tmp_path / "code"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "order.p").write_text("DEF VAR x.\nRUN Invoice.\n", encoding="utf-8")
    result = LLMCodeAnswer(
        answer="De code roept Invoice aan.", citations=[LLMCodeCitation(path="src/order.p", start_line=2, end_line=2)],
        manual_agreement="agrees", differing_manual_pages=[], not_checked=[],
    )
    llm = FakeToolLLM(turns=[scripted_turn(calls=(("grep", {"pattern": "Invoice"}),)), scripted_turn("Conclusie.")], result=result)
    return CodeChecker(CodeTools(root), "2026-10-30"), llm


def chat_with_answer(answer=None, **fields):
    manual = answer or make_answer()
    history = [{"role": "user", "content": "vraag"}, {"role": "assistant", "content": manual.text, "options": ui.code_option()}]
    return ui.Conversation(title="vraag", history=history, last_manual=manual, **fields)


# --- offering the check -----------------------------------------------------------------------------


def test_a_manual_answer_offers_the_code_check_only_when_there_is_a_code_checkout(config):
    with_code = ui.respond(FakeAssistant(make_answer()), config, "vraag", [], offer_code=True)[0]
    assert with_code[-1]["options"] == [{"label": "Controleer in de code", "value": ui.CHECK_OPTION}]
    assert "options" not in ui.respond(FakeAssistant(make_answer()), config, "vraag", [])[0][-1]


def test_a_manual_answer_that_is_not_covered_starts_the_code_check_by_itself(config):
    chats = [ui.Conversation()]
    ui.submit(FakeAssistant(make_answer(covered=False)), config, "vraag", chats, 0, 0, offer_code=True)
    assert chats[0].auto_check is True and chats[0].last_manual.covered is False


@pytest.mark.parametrize("answer, offer", [
    (make_answer(covered=True), True),                    # the Manual answered
    (make_answer(covered=False, error="boom"), True),     # the Manual failed: not a "not in the Manual" answer
    (make_answer(covered=False), False),                  # there is no Code Checkout
])
def test_other_manual_answers_do_not_start_the_code_check(config, answer, offer):
    chats = [ui.Conversation()]
    ui.submit(FakeAssistant(answer), config, "vraag", chats, 0, 0, offer_code=offer)
    assert chats[0].auto_check is False


def test_the_latest_manual_answer_is_kept_for_the_button(config):
    chats = [ui.Conversation()]
    ui.submit(FakeAssistant(make_answer(text="Eerste.")), config, "een", chats, 0, 0, offer_code=True)
    ui.submit(FakeAssistant(make_answer(text="Tweede.")), config, "twee", chats, 0, 0, offer_code=True)
    assert chats[0].last_manual.text == "Tweede."


# --- a run ------------------------------------------------------------------------------------------


def test_checking_the_code_shows_progress_then_the_code_answer_below_the_manual_answer(tmp_path):
    checker, llm = code_checker(tmp_path)
    chat = chat_with_answer()
    states = []
    for _ in ui.check_code(chat, checker, lambda: llm):
        states.append((chat.checking, [dict(m) for m in chat.history]))
    assert states[0][0] is True and chat.checking is False and chat.stop is None
    assert any("grep Invoice" in m["content"] for _, h in states for m in h if m.get("metadata"))  # streamed
    manual, progress, code = chat.history[1:]
    assert manual["content"] == "Het antwoord." and "options" not in manual  # the button is gone once used
    assert progress["metadata"]["status"] == "done" and "1 stap" in progress["metadata"]["title"]
    assert "De code roept Invoice aan." in code["content"] and "Ongecontroleerd" in code["content"]
    assert "code per 2026-10-30" in code["content"] and "src/order.p:2-2" in code["content"]
    assert "RUN Invoice." not in code["content"]  # snippets live in the Code tab
    assert "RUN Invoice." in chat.code_view and "**src/order.p:2-2**" in chat.code_view


def test_stop_ends_the_run_with_a_partial_code_answer(tmp_path):
    class SlowChecker:
        def check(self, manual, llm, cancelled, on_event):
            on_event(ProgressEvent("started", "Onderzoek gestart"))
            deadline = time.monotonic() + 5
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.01)
            status = "cancelled" if cancelled() else "timeout"
            return CodeAnswer(manual.question, status, "Het onderzoek is gestopt op verzoek. Er is geen conclusie.")

    chat = chat_with_answer()
    for count, _ in enumerate(ui.check_code(chat, SlowChecker(), lambda: object())):
        if count == 1:  # the first progress line has arrived
            ui.stop_check([chat], 0)
    assert "geen conclusie" in chat.history[-1]["content"] and chat.checking is False and chat.code_view


def test_stop_without_a_run_does_nothing():
    chat = ui.Conversation()
    ui.stop_check([chat], 0)
    assert chat.stop is None


def test_a_refused_provider_is_reported_in_the_chat_and_the_button_comes_back(tmp_path):
    checker, _ = code_checker(tmp_path)
    chat = chat_with_answer()
    list(ui.check_code(chat, checker, lambda: FakeToolLLM(provider="openai")))
    last = chat.history[-1]
    assert "OpenAI" in last["content"] and last["options"] == ui.code_option()
    assert not any(m.get("metadata") for m in chat.history)  # no empty progress block left behind
    assert chat.checking is False and chat.stop is None


def test_an_unavailable_choice_is_reported_in_the_chat(tmp_path):
    def refuse():
        raise MissingConfigError("ANTHROPIC_API_KEY is not set (put it in .env).")

    checker, _ = code_checker(tmp_path)
    chat = chat_with_answer()
    list(ui.check_code(chat, checker, refuse))
    assert "ANTHROPIC_API_KEY" in chat.history[-1]["content"] and chat.history[-1]["options"] == ui.code_option()


def test_nothing_runs_without_a_manual_answer_a_checker_or_while_a_run_is_busy(tmp_path):
    checker, llm = code_checker(tmp_path)
    assert list(ui.check_code(ui.Conversation(), checker, lambda: llm)) == []
    assert list(ui.check_code(chat_with_answer(), None, lambda: llm)) == []
    assert list(ui.check_code(chat_with_answer(checking=True), checker, lambda: llm)) == []
    assert llm.calls == []


# --- the handlers behind the events ---------------------------------------------------------------


def test_the_check_handler_yields_the_chat_the_box_state_the_stop_button_the_code_view_and_the_chats(config, tmp_path):
    checker, llm = code_checker(tmp_path)
    switch = LLMSwitch(config, lambda c: llm)
    chats = [chat_with_answer()]
    outputs = list(ui.run_check(checker, switch, chats, 0, "openai", "gpt-5.4-mini"))
    first, last = outputs[0], outputs[-1]
    assert first[1]["interactive"] is False and first[2]["visible"] is True  # busy: no new question, Stop shown
    assert last[1]["interactive"] is True and last[2]["visible"] is False
    assert last[0] is chats[0].history and "RUN Invoice." in last[3] and last[4] is chats


def test_the_check_handler_yields_no_change_when_there_is_nothing_to_check(config, tmp_path):
    checker, llm = code_checker(tmp_path)
    (only,) = list(ui.run_check(checker, LLMSwitch(config, lambda c: llm), [ui.Conversation()], 0, "openai", "gpt-5.4-mini"))
    assert len(only) == 5 and llm.calls == []


def test_the_automatic_check_runs_only_when_the_conversation_asked_for_it(config, tmp_path):
    checker, llm = code_checker(tmp_path)
    switch = LLMSwitch(config, lambda c: llm)
    quiet = [chat_with_answer()]
    list(ui.auto_check(checker, switch, quiet, 0, "openai", "gpt-5.4-mini"))
    assert llm.calls == []
    asked = [chat_with_answer(make_answer(covered=False), auto_check=True)]
    list(ui.auto_check(checker, switch, asked, 0, "openai", "gpt-5.4-mini"))
    assert asked[0].auto_check is False and "De code roept Invoice aan." in asked[0].history[-1]["content"]


def test_the_code_view_belongs_to_its_conversation():
    chats = [ui.Conversation(code_view="eerste"), ui.Conversation(code_view="tweede")]
    assert ui.chat_view(chats[0])[-1] == "eerste" and ui.chat_view(chats[1])[-1] == "tweede"
    assert ui.new_chat(chats)[-1] == ""


def test_tabs_cannot_be_switched_while_a_code_check_runs():
    assert ui.busy([ui.Conversation(checking=True), ui.Conversation()]) and not ui.busy([ui.Conversation()])


# --- the app ----------------------------------------------------------------------------------------


def test_the_app_without_a_code_checkout_has_no_code_tab_and_no_stop_button(config):
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config)
    assert "Code" not in [b.label for b in blocks.blocks.values() if isinstance(b, gr.Tab)]
    assert not any(isinstance(b, gr.Button) and b.value == "Stop" for b in blocks.blocks.values())


def test_the_app_with_a_code_checkout_has_a_code_tab_a_hidden_stop_button_and_the_option_event(config, tmp_path):
    checker, _ = code_checker(tmp_path)
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config, checker=checker)
    assert [b.label for b in blocks.blocks.values() if isinstance(b, gr.Tab)][-1] == "Code"
    stop = next(b for b in blocks.blocks.values() if isinstance(b, gr.Button) and b.value == "Stop")
    assert stop.visible is False
    chat = next(b for b in blocks.blocks.values() if isinstance(b, gr.Chatbot))
    assert any(fn.targets[0][1] == "option_select" and fn.targets[0][0] == chat._id for fn in blocks.fns.values())


def test_a_question_through_the_app_gets_the_code_button(config, tmp_path):
    checker, _ = code_checker(tmp_path)
    blocks = ui.chat_blocks(FakeAssistant(make_answer(covered=False)), config, checker=checker)
    provider = next(b for b in blocks.blocks.values() if isinstance(b, gr.Dropdown) and b.label == "Provider")
    submit = next(fn for fn in blocks.fns.values() if provider in fn.inputs and len(fn.inputs) == 6)
    chats = [ui.Conversation()]
    submit.fn("vraag", "openai", "gpt-5.4-mini", chats, 0, 0)
    assert chats[0].history[-1]["options"] == ui.code_option() and chats[0].auto_check is True


def test_run_gives_the_chat_app_a_code_checker_built_from_the_config(monkeypatch, config):
    seen = {}
    monkeypatch.setattr(ui, "build_assistant", lambda c: FakeAssistant())
    monkeypatch.setattr(ui, "build_code_checker", lambda c: "checker")
    monkeypatch.setattr(ui, "chat_blocks", lambda assistant, c, switch=None, checker=None: seen.update(checker=checker) or "blocks")
    monkeypatch.setattr(ui, "serve", lambda *args, **kwargs: None)
    ui.run(config)
    assert seen["checker"] == "checker"
