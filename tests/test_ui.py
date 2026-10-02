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


def test_page_links_become_radio_choices(config):
    assert ui.answer_view(make_answer(), config).page_link_choices == [("Partner", "Partner.htm")]


def test_debug_rows_follow_the_spec_columns(config):
    view = ui.answer_view(make_answer(), config)
    assert ui.DEBUG_HEADERS == ["chunk_id", "page title", "heading path", "score", "cited", "text"]
    assert view.debug_rows[0] == ["Budgetten#1", "Budgetten", "Budgetten > Vastleggen", 0.9, "ja", "tekst van Budgetten#1"]
    assert view.debug_rows[2][4] == ""


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
    history, box, links, gallery, rows, notes = ui.respond(assistant, config, "vraag", [])
    assert assistant.questions == ["vraag"] and box == ""
    assert history == [{"role": "user", "content": "vraag"}, {"role": "assistant", "content": "Het antwoord."}]
    assert len(gallery) == 2 and len(rows) == 3 and "Fout#9" in notes
    assert links["choices"] == [("Partner", "Partner.htm")]


def test_respond_preselects_the_first_page_so_the_viewer_loads(config):
    sources = [{"page_file": "Budgetten.htm", "page_title": "Budgetten"}]
    links = ui.respond(FakeAssistant(make_answer(source_pages=sources)), config, "vraag", [])[2]
    assert links["value"] == "Budgetten.htm"
    none = ui.respond(FakeAssistant(make_answer(page_links=[])), config, "vraag", [])[2]
    assert none["value"] is None and none["visible"] is False


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
    labels = {getattr(b, "label", None) for b in blocks.blocks.values()}
    assert {"Page viewer", "Debug"} <= labels


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
