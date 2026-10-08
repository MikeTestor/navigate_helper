import shutil
from html import unescape

import pytest

from navigate_helper import clean, page_view
from navigate_helper.config import load_config
from navigate_helper.page_view import page_viewer


@pytest.fixture
def raw(tmp_path, pages_dir):
    """A raw/ tree built from the fixture pages, with the Cleaned Pages already written."""
    htm = tmp_path / "knowledge-base" / "raw" / "htm_docs"
    shutil.copytree(pages_dir, htm)
    images = htm.parent / "images"
    images.mkdir()
    (images / "shot.gif").write_bytes(b"GIF89a")
    (images / "bare.jpg").write_bytes(b"x")
    return tmp_path


@pytest.fixture
def config(raw):
    config = load_config({"DATA_DIR": str(raw)})
    clean.run(config)
    return config


def iframe_doc(view):
    start = view.raw_html.index('srcdoc="') + len('srcdoc="')
    return unescape(view.raw_html[start : view.raw_html.index('" style=', start)])


def test_iframe_fills_the_window_height(config):
    view = page_viewer("with_files.htm", config)
    assert "height:calc(100vh - 216px)" in view.raw_html and "min-height:300px" in view.raw_html


def test_iframe_runs_only_our_link_script_not_the_pages_scripts(config):
    view = page_viewer("with_files.htm", config)
    assert 'sandbox="allow-same-origin allow-scripts"' in view.raw_html
    doc = iframe_doc(view)
    assert "RH_Document_Write" not in doc and "whver.js" not in doc
    assert doc.count("<script") == 1 and "navigateHelperPage" in doc


def test_image_forms_resolve_to_raw(config):
    doc = iframe_doc(page_viewer("with_files.htm", config))
    raw_dir = config.raw_dir.resolve().as_posix()
    assert f'src="/gradio_api/file={raw_dir}/htm_docs/with_files_files/pic.png"' in doc
    assert f'src="/gradio_api/file={raw_dir}/images/shot.gif"' in doc
    assert 'src="missing.jpg"' in doc  # unresolved: left alone


def test_bare_filename_resolves_into_raw_images(config):
    html = '<img src="bare.jpg"><img src="./bare.jpg">'
    out = page_view.rewrite_page(html, config.raw_dir)
    assert out.count("/images/bare.jpg") == 2


def test_images_cannot_escape_raw(config):
    assert page_view.resolve_image("../../outside.png", config.raw_dir) is None
    assert page_view.resolve_image("https://example.nl/a.png", config.raw_dir) is None


def test_script_hooks_are_removed(config):
    html = '<p onclick="x()"><a href="javascript:x()">a</a><iframe src="y"></iframe></p>'
    out = page_view.rewrite_page(html, config.raw_dir)
    assert "onclick" not in out and "javascript:" not in out and "<iframe" not in out


def test_links_to_other_manual_pages_become_plain_text(config):
    html = (
        '<p><a href="Budgetten.htm">een</a> <a href="Page.htm#deel">twee</a> <a href="Pagina_(x),.htm">drie</a> '
        '<a href="https://example.nl/a">vier</a> <a href="mailto:a@b.nl">vijf</a> <a href="#boven">zes</a></p>'
    )
    out = page_view.rewrite_page(html, config.raw_dir)
    assert ".htm" not in out and "<a>" not in out
    assert "een twee drie" in out
    assert 'href="https://example.nl/a"' in out and 'href="mailto:a@b.nl"' in out and 'href="#boven"' in out


def test_links_to_existing_manual_pages_carry_data_page_in_the_viewer_only(config):
    html = '<a href="tables.htm#a">een</a> <a href="no%5Fsections.htm">twee</a> <a href="missing.htm">drie</a> <a href="x/tables.htm">vier</a>'
    shown = page_view.rewrite_page(html, config.raw_dir, links="viewer")
    assert 'data-page="tables.htm"' in shown and 'data-page="no_sections.htm"' in shown
    assert shown.count("data-page") == 2 and "missing.htm" not in shown and "x/tables.htm" not in shown
    plain = page_view.rewrite_page(html, config.raw_dir)
    assert "data-page" not in plain and ".htm" not in plain


def test_viewer_iframe_links_pages_but_the_full_page_is_served_with_real_links(config):
    assert "no_sections.htm" in (config.htm_dir / "tables.htm").read_text(encoding="utf-8-sig")
    assert 'data-page="no_sections.htm"' in iframe_doc(page_viewer("tables.htm", config))
    served = page_view.served_page("tables.htm", config)
    assert 'href="no_sections.htm#a"' in served and "data-page" not in served and "<script" not in served


def test_served_page_keeps_links_to_existing_pages_quoted_and_drops_the_rest(config):
    html = '<a href="no%5Fsections.htm">een</a> <a href="missing.htm">twee</a> <a href="#deel">drie</a>'
    out = page_view.rewrite_page(html, config.raw_dir, links="served")
    assert 'href="no_sections.htm"' in out and "missing.htm" not in out and 'href="#deel"' in out
    assert "</a> twee <a" in out  # the missing page's link is plain text


def test_served_page_only_for_real_manual_pages(config):
    assert page_view.served_page("with_files.htm", config) is not None
    for name in ("missing.htm", "../with_files.htm", "sub/with_files.htm", "with_files.txt", ""):
        assert page_view.served_page(name, config) is None


def test_served_page_has_rewritten_image_urls(config):
    served = page_view.served_page("with_files.htm", config)
    assert f'src="/gradio_api/file={config.raw_dir.resolve().as_posix()}/images/shot.gif"' in served


def test_anchor_links_stay_inside_the_iframe_document(config):
    html = '<p><a href="#deel">naar deel</a></p><h2><a name="deel"></a>Deel</h2>'
    doc = iframe_doc(page_view.PageView("", page_view.raw_iframe(page_view.rewrite_page(html, config.raw_dir)), ""))
    assert 'href="about:srcdoc#deel"' in doc  # a bare #deel would load the app's own URL in the frame
    assert 'name="deel"' in doc


def test_heading_has_title_and_open_full_page_link_without_a_path(config):
    view = page_viewer("with_files.htm", config)
    assert "Pagina met afbeeldingen" in view.heading
    assert 'target="_blank"' in view.heading and ">open full page</a>" in view.heading
    visible = view.heading.split(">open full page<")[0].split("<a ")[0]
    assert str(config.data_dir) not in visible and "/gradio_api" not in visible


def test_open_full_page_points_at_the_served_page(config):
    view = page_viewer("with_files.htm", config)
    href = unescape(view.heading.split('href="')[1].split('"')[0])
    assert href == "/manual/with_files.htm"


def test_cleaned_page_renders_beside_without_front_matter_or_page_link_targets(config):
    md = page_viewer("tables.htm", config).cleaned_markdown
    assert md.startswith("# Tabellen voorbeeld")
    assert "| Veld | Uitleg |" in md
    assert "debiteur" in md and "<no_sections.htm>" not in md


def test_cleaned_screenshots_become_file_urls():
    md = page_view.rewrite_cleaned("---\nmenu_path:\n  - \"A\"\n---\n\n# T\n\n![](images/shot.gif)\n![](images/weg.gif)\n", _raw_with_shot())
    assert "menu_path" not in md and "![](/gradio_api/file=" in md and "weg.gif" not in md


def _raw_with_shot():
    import tempfile
    from pathlib import Path

    raw = Path(tempfile.mkdtemp()) / "raw"
    (raw / "images").mkdir(parents=True)
    (raw / "images" / "shot.gif").write_bytes(b"x")
    return raw


def test_missing_page_shows_a_message(config):
    for name in ("bestaat_niet.htm", "../secret.htm", "", None, "tables.txt"):
        view = page_viewer(name, config)
        assert view.raw_html == "" and view.cleaned_markdown == "" and "<em>" in view.heading


def test_markdown_source_is_the_cleaned_file_as_written(config):
    view = page_viewer("tables.htm", config)
    assert view.markdown_source == (config.cleaned_dir / "tables.md").read_text(encoding="utf-8")
    assert "(<no_sections.htm>)" in view.markdown_source  # the Page Link is kept: the file, not the rendered text
    assert "(<no_sections.htm>)" not in view.cleaned_markdown


def test_markdown_source_is_empty_without_a_cleaned_page(config):
    (config.cleaned_dir / "tables.md").unlink()
    assert page_viewer("tables.htm", config).markdown_source == ""


def test_missing_cleaned_page_shows_a_message_beside_the_raw_page(config):
    (config.cleaned_dir / "tables.md").unlink()
    view = page_viewer("tables.htm", config)
    assert "<iframe" in view.raw_html and "Geen Cleaned Page" in view.cleaned_markdown
