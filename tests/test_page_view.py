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
    assert "height:calc(100vh - 320px)" in view.raw_html and "min-height:300px" in view.raw_html


def test_iframe_is_sandboxed_without_scripts(config):
    view = page_viewer("with_files.htm", config)
    assert 'sandbox="allow-same-origin"' in view.raw_html and "allow-scripts" not in view.raw_html
    doc = iframe_doc(view)
    assert "<script" not in doc and "RH_Document_Write" not in doc


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


def test_heading_has_title_and_open_full_page_link_without_a_path(config):
    view = page_viewer("with_files.htm", config)
    assert "Pagina met afbeeldingen" in view.heading
    assert 'target="_blank"' in view.heading and ">open full page</a>" in view.heading
    visible = view.heading.split(">open full page<")[0].split("<a ")[0]
    assert str(config.data_dir) not in visible and "/gradio_api" not in visible


def test_full_page_copy_is_rewritten_and_written_under_view_dir(config):
    view = page_viewer("with_files.htm", config)
    href = unescape(view.heading.split('href="')[1].split('"')[0])
    assert href.startswith(page_view.FILE_URL_PREFIX)
    copies = list(page_view.view_dir().glob("*.html"))
    assert any("/gradio_api/file=" in c.read_text(encoding="utf-8") and "<script" not in c.read_text(encoding="utf-8") for c in copies)


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


def test_missing_cleaned_page_shows_a_message_beside_the_raw_page(config):
    (config.cleaned_dir / "tables.md").unlink()
    view = page_viewer("tables.htm", config)
    assert "<iframe" in view.raw_html and "Geen Cleaned Page" in view.cleaned_markdown
