import gradio as gr
import pytest

from navigate_helper import ui
from navigate_helper.ask import Answer, ScoredChunk
from navigate_helper.config import load_config


def chunk(chunk_id, page_file="Budgetten.htm", title="Budgetten", score=0.9, cited=False, screenshots=(), links=()):
    return ScoredChunk(
        chunk_id=chunk_id, page_file=page_file, page_title=title, heading_path=["Budgetten", "Vastleggen"],
        menu_path=[], text=f"tekst van {chunk_id}", screenshots=list(screenshots), page_links=list(links),
        score=score, cited=cited,
    )


@pytest.fixture
def config(tmp_path):
    images = tmp_path / "knowledge-base" / "raw" / "images"
    images.mkdir(parents=True)
    for name in ("a.png", "b.png"):
        (images / name).write_bytes(b"x")
    return load_config({"DATA_DIR": str(tmp_path)})


def make_answer(**overrides):
    link = {"title": "Partner", "page_file": "Partner.htm"}
    c1 = chunk("Budgetten#1", cited=True, screenshots=["images/a.png", "images/missing.png"], links=[link])
    c2 = chunk("Budgetten#2", cited=True, screenshots=["images/a.png", "images/b.png"])
    c3 = chunk("Acties#1", page_file="Acties.htm", title="Acties", score=0.5)
    fields = dict(
        question="vraag", text="Het antwoord.", covered=True, cited=[c1, c2], retrieved=[c1, c2, c3],
        screenshots=["images/a.png", "images/missing.png", "images/b.png"], page_links=[link],
        dropped_citation_ids=["Fout#9"],
    )
    return Answer(**{**fields, **overrides})


def test_gallery_is_deduplicated_captioned_and_skips_missing_files(config):
    view = ui.answer_view(make_answer(), config)
    assert [caption for _, caption in view.gallery] == ["Budgetten / a.png", "Budgetten / b.png"]
    assert all(path.endswith(("a.png", "b.png")) for path, _ in view.gallery)


def test_no_screenshots_means_an_empty_large_view(config):
    answer = make_answer(cited=[chunk("Budgetten#1", cited=True)])
    large = ui.respond(FakeAssistant(answer), config, "vraag", [])[4]
    assert large["value"] is None


def test_selecting_a_thumbnail_shows_it_large():
    event = type("Event", (), {"value": {"image": {"path": "x/b.png"}, "caption": "Budgetten / b.png"}})()
    large = ui.select_screenshot(event)
    assert large["value"] == "x/b.png" and large["label"] == "Budgetten / b.png"


def test_page_links_become_radio_choices(config):
    assert ui.answer_view(make_answer(), config).page_link_choices == [("Partner", "Partner.htm")]


def test_debug_rows_follow_the_spec_columns(config):
    view = ui.answer_view(make_answer(), config)
    assert ui.DEBUG_HEADERS == ["chunk_id", "page title", "heading path", "score", "cited", "text"]
    assert view.debug_rows[0] == ["Budgetten#1", "Budgetten", "Budgetten > Vastleggen", 0.9, "ja", "tekst van Budgetten#1"]
    assert view.debug_rows[2][4] == ""


def test_debug_table_has_a_width_for_every_column():
    assert len(ui.DEBUG_COLUMN_WIDTHS) == len(ui.DEBUG_HEADERS)
    assert sum(int(w.rstrip("%")) for w in ui.DEBUG_COLUMN_WIDTHS) == 100


def test_debug_notes_show_dropped_citations_error_and_uncited(config):
    assert "Fout#9" in ui.answer_view(make_answer(), config).debug_notes
    uncited = make_answer(cited=[], dropped_citation_ids=[])
    assert "geen geldige bronverwijzing" in ui.answer_view(uncited, config).debug_notes
    failed = make_answer(error="LLMError: boom", covered=False, cited=[], dropped_citation_ids=[])
    notes = ui.answer_view(failed, config).debug_notes
    assert "LLMError: boom" in notes and "geen geldige bronverwijzing" not in notes


def test_covered_answer_lists_its_source_pages_before_the_page_links(config):
    sources = [{"page_file": "Budgetten.htm", "page_title": "Budgetten"}, {"page_file": "Partner.htm", "page_title": "Partner"}]
    view = ui.answer_view(make_answer(source_pages=sources), config)
    assert view.page_link_choices == [("Budgetten", "Budgetten.htm"), ("Partner", "Partner.htm")]


def test_uncovered_answer_offers_the_closest_pages_as_links(config):
    answer = make_answer(covered=False, cited=[], page_links=[], source_pages=[{"page_file": "Acties.htm", "page_title": "Acties"}])
    assert ui.answer_view(answer, config).page_link_choices == [("Acties", "Acties.htm")]


class FakeAssistant:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.questions = answer, error, []

    def ask(self, question):
        self.questions.append(question)
        if self.error:
            raise self.error
        return self.answer


def test_respond_appends_the_answer_to_the_chat(config):
    assistant = FakeAssistant(make_answer())
    history, box, links, gallery, large, rows, notes, shown = ui.respond(assistant, config, "vraag", [])
    assert assistant.questions == ["vraag"] and box == ""
    assert history == [{"role": "user", "content": "vraag"}, {"role": "assistant", "content": "Het antwoord."}]
    assert large["value"] == gallery[0][0] and large["label"] == "Budgetten / a.png"  # starts on the first screenshot
    assert len(gallery) == 2 and len(rows) == 3 and "Fout#9" in notes
    assert links["choices"] == [("Partner", "Partner.htm")] and shown == [("Partner", "Partner.htm")]


def test_new_pages_go_on_top_and_old_ones_are_kept():
    shown = ui.merge_page_links([("A", "a.htm"), ("B", "b.htm")], [("C", "c.htm"), ("B", "b.htm")])
    assert shown == [("C", "c.htm"), ("B", "b.htm"), ("A", "a.htm")]


def test_a_later_answer_keeps_earlier_links(config):
    sources = [{"page_file": "Budgetten.htm", "page_title": "Budgetten"}]
    history = [{"role": "user", "content": "eerder"}, {"role": "assistant", "content": "antwoord"}]
    earlier = [("Acties", "Acties.htm")]
    links = ui.respond(FakeAssistant(make_answer(source_pages=sources)), config, "vraag", history, earlier)[2]
    assert links["choices"] == [
        ("Budgetten", "Budgetten.htm"), ("Partner", "Partner.htm"), ("Acties", "Acties.htm")
    ]


def test_clear_empties_the_active_conversations_list():
    chats = [ui.Conversation(shown=[("A", "a.htm")]), ui.Conversation(shown=[("B", "b.htm")])]
    radio, chats = ui.clear_page_links(chats, 1)
    assert radio["choices"] == [] and radio["visible"] is False
    assert chats[0].shown == [("A", "a.htm")] and chats[1].shown == []


def make_chats(*titles):
    return [ui.Conversation(title=t, history=[{"role": "user", "content": t}]) for t in titles]


def test_a_new_chat_is_added_and_selected_with_empty_views():
    chats, active, history, links, gallery, large, rows, notes = ui.new_chat(make_chats("eerste vraag"))
    assert len(chats) == 2 and active == 1 and ui.tab_labels(chats) == ["eerste vraag", "Chat 2"]
    assert history == [] and links["visible"] is False and gallery == [] and large["value"] is None and rows == []


def test_closing_the_active_chat_lets_the_next_one_take_its_place():
    chats, active, history, *_ = ui.close_chat(make_chats("a", "b", "c"), 1, 1)
    assert [c.title for c in chats] == ["a", "c"] and active == 1
    assert history == [{"role": "user", "content": "c"}]


def test_closing_the_last_tab_selects_the_one_before():
    chats, active, history, *_ = ui.close_chat(make_chats("a", "b"), 1, 1)
    assert [c.title for c in chats] == ["a"] and active == 0 and history == [{"role": "user", "content": "a"}]


def test_closing_another_tab_keeps_the_active_chat():
    chats, active, history, *_ = ui.close_chat(make_chats("a", "b", "c"), 2, 0)  # c is active, a is closed
    assert [c.title for c in chats] == ["b", "c"] and active == 1
    assert history == [{"role": "user", "content": "c"}]
    chats, active, *_ = ui.close_chat(make_chats("a", "b", "c"), 0, 2)  # a is active, c is closed
    assert [c.title for c in chats] == ["a", "b"] and active == 0


def test_closing_the_only_chat_leaves_one_empty_chat():
    chats, active, history, links, *_ = ui.close_chat(make_chats("a"), 0, 0)
    assert len(chats) == 1 and chats[0].title == "" and active == 0 and history == []
    assert ui.tab_labels(chats) == ["Chat 1"] and links["visible"] is False


def test_switching_returns_the_index_and_that_chats_views():
    active, history, *_ = ui.switch_chat(make_chats("a", "b"), 1)
    assert active == 1 and history == [{"role": "user", "content": "b"}]


def test_the_first_question_names_the_tab_and_long_names_are_cut(config):
    chats = [ui.Conversation()]
    *_, chats, revision = ui.submit(FakeAssistant(make_answer()), config, "kort", chats, 0, 0)
    assert ui.tab_labels(chats) == ["kort"] and revision == 1  # the tab strip must redraw
    *_, chats, revision = ui.submit(FakeAssistant(make_answer()), config, "tweede", chats, 0, revision)
    assert ui.tab_labels(chats) == ["kort"] and revision == 1  # only the first question names it
    long = [ui.Conversation()]
    *_, long, _ = ui.submit(FakeAssistant(make_answer()), config, "een heel erg lange eerste vraag over iets", long, 0, 0)
    label = ui.tab_labels(long)[0]
    assert len(label) == ui.TAB_TITLE_CHARS and label.endswith("…")


def test_conversations_keep_their_own_history_links_and_views(config):
    chats = [ui.Conversation()]
    ui.submit(FakeAssistant(make_answer()), config, "vraag in chat 1", chats, 0, 0)
    chats, *_ = ui.new_chat(chats)
    ui.submit(FakeAssistant(make_answer(text="Tweede antwoord.")), config, "vraag in chat 2", chats, 1, 0)
    _, history, links, gallery, large, rows, notes = ui.switch_chat(chats, 0)
    assert [m["content"] for m in history] == ["vraag in chat 1", "Het antwoord."]
    assert links["choices"] == [("Partner", "Partner.htm")] and len(gallery) == 2 and len(rows) == 3
    assert "Fout#9" in notes
    _, history, *_ = ui.switch_chat(chats, 1)
    assert [m["content"] for m in history] == ["vraag in chat 2", "Tweede antwoord."]


def test_a_blank_question_changes_nothing_in_the_conversation(config):
    chats = [ui.Conversation()]
    ui.submit(FakeAssistant(make_answer()), config, "  ", chats, 0, 0)
    assert chats[0].history == [] and chats[0].title == ""


def test_a_failed_question_keeps_the_list(config):
    earlier = [("Acties", "Acties.htm")]
    *_, shown = ui.respond(FakeAssistant(error=RuntimeError("x")), config, "vraag", [], earlier)
    assert shown == earlier


def test_later_answers_do_not_preselect_a_page(config):
    sources = [{"page_file": "Budgetten.htm", "page_title": "Budgetten"}]
    history = [{"role": "user", "content": "eerder"}, {"role": "assistant", "content": "antwoord"}]
    links = ui.respond(FakeAssistant(make_answer(source_pages=sources)), config, "vraag", history)[2]
    assert "value" not in links and links["visible"] is True
    assert links["choices"][0] == ("Budgetten", "Budgetten.htm")


def test_clearing_the_radio_leaves_the_viewer_unchanged():
    shown = []
    wrapped = ui.keep_viewer_when_unselected(lambda page: shown.append(page) or ("h", "r", "c", "s"))
    assert wrapped("Budgetten.htm") == ("h", "r", "c", "s")
    assert len(wrapped(None)) == ui.VIEWER_OUTPUT_COUNT and shown == ["Budgetten.htm"]


def test_respond_preselects_the_first_page_so_the_viewer_loads(config):
    sources = [{"page_file": "Budgetten.htm", "page_title": "Budgetten"}]
    links = ui.respond(FakeAssistant(make_answer(source_pages=sources)), config, "vraag", [])[2]
    assert links["value"] == "Budgetten.htm"
    none = ui.respond(FakeAssistant(make_answer(page_links=[])), config, "vraag", [])[2]
    assert "value" not in none and none["visible"] is False


def test_respond_reports_retrieval_errors_in_the_chat(config):
    history, *_ = ui.respond(FakeAssistant(error=RuntimeError("chroma kapot")), config, "vraag", [])
    assert "chroma kapot" in history[-1]["content"]


def test_respond_ignores_an_empty_question(config):
    assistant = FakeAssistant(make_answer())
    ui.respond(assistant, config, "  ", [])
    assert assistant.questions == []


def test_chat_blocks_build_with_a_fake_assistant(config):
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config)
    assert isinstance(blocks, gr.Blocks)
    tabs = [b.label for b in blocks.blocks.values() if isinstance(b, gr.Tab)]
    assert tabs == ["Manual page", "Markdown page", "Debug", "Screenshots"]
    assert len({b.parent for b in blocks.blocks.values() if isinstance(b, gr.Tab)}) == 1  # one row of tabs


def test_chat_scrolls_to_the_latest_question_after_an_answer(config):
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config)
    chat = next(b for b in blocks.blocks.values() if isinstance(b, gr.Chatbot))
    assert chat.autoscroll is False  # Gradio's own scroll-to-bottom would fight the script
    assert any(fn.js == ui.SCROLL_TO_QUESTION_JS for fn in blocks.fns.values())


def test_markdown_tab_has_a_copy_button_that_copies_the_source(config):
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config)
    assert any(isinstance(b, gr.Button) and b.value == "Kopieer markdown" for b in blocks.blocks.values())
    assert any(fn.js == ui.COPY_MARKDOWN_JS for fn in blocks.fns.values())
    assert "clipboard.writeText" in ui.COPY_MARKDOWN_JS


def test_chat_blocks_draw_the_tab_strip_at_load_and_when_the_revision_changes(config):
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config)
    assert len(blocks.renderables) == 1  # draw_tabs: a title and × per chat, and a +


def test_question_box_is_focused_on_open(config):
    blocks = ui.chat_blocks(FakeAssistant(make_answer()), config)
    box = next(b for b in blocks.blocks.values() if getattr(b, "elem_id", None) == ui.QUESTION_ID)
    assert box.autofocus is True


def test_run_builds_the_assistant_once_and_serves_raw(monkeypatch, config):
    built, launched = [], {}

    class FakeBlocks:
        def launch(self, **kwargs):
            launched.update(kwargs)

    monkeypatch.setattr(ui, "build_assistant", lambda c: built.append(c) or FakeAssistant())
    monkeypatch.setattr(ui, "chat_blocks", lambda assistant, c: FakeBlocks())
    ui.run(config)
    assert built == [config]
    assert str(config.raw_dir.resolve()) in launched["allowed_paths"]
    assert f"#{ui.CHAT_ID} .message-wrap > .message-buttons" in launched["css"]  # copy button beside the message text
    assert f"#{ui.CHAT_ID} .message-buttons .icon-button-wrapper {{ margin: 0; }}" in launched["css"]  # equal sizes
    assert f"#{ui.LEFT_ID} {{ height: calc(100vh" in launched["css"]  # question box pinned to the bottom left
    assert f"#{ui.TABS_ID} .chat-tab.selected" in launched["css"]  # the active tab is marked
    assert f"#{ui.LEFT_ID} > .column {{ flex: 0 0 auto !important; }}" in launched["css"]
    assert f"#{ui.LINKS_ID} > .wrap:not(.default) {{ max-height: calc(3 * 35px" in launched["css"]  # three rows, then scroll  # the tab strip leaves the chat its height
    # refocuses the question box when the browser tab is selected again
    assert ui.QUESTION_ID in launched["js"] and "addEventListener('focus'" in launched["js"]


def test_page_viewer_has_a_hidden_jump_box_whose_input_loads_the_page(config):
    with gr.Blocks() as blocks:
        outputs, show, _ = ui.build_page_viewer(config)
    box = next(c for c in blocks.config["components"] if c["props"].get("elem_id") == ui.JUMP_ID)
    assert box["props"]["visible"] == "hidden"
    deps = [d for d in blocks.config["dependencies"] if (box["id"], "change") in [tuple(t) for t in d["targets"]]]
    assert len(deps) == 1 and len(deps[0]["outputs"]) == ui.VIEWER_OUTPUT_COUNT + 1
    assert f"#{ui.JUMP_ID} textarea" in ui.PAGE_JUMP_JS and "navigateHelperPage" in ui.PAGE_JUMP_JS
