import json
import shutil

import pytest

from navigate_helper import cli, clean
from navigate_helper.config import Config, StageError, load_config


@pytest.fixture
def raw(tmp_path, pages_dir):
    """A raw/ tree built from the fixture pages."""
    htm = tmp_path / "knowledge-base" / "raw" / "htm_docs"
    shutil.copytree(pages_dir, htm)
    images = htm.parent / "images"
    images.mkdir()
    (images / "shot.gif").write_bytes(b"GIF89a")
    for skipped in ("index.htm", "rhair_fbody.htm"):
        (htm / skipped).write_text("<html><body>x</body></html>", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(raw) -> Config:
    return load_config({"DATA_DIR": str(raw)})


@pytest.fixture
def raw_dir(raw):
    return raw / "knowledge-base" / "raw"


def clean_page(config, stem):
    clean.run(config, page=stem)
    return (config.cleaned_dir / f"{stem}.md").read_text(encoding="utf-8")


def html_page(body, title="T"):
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


def test_title_headings_and_lists(config):
    md = clean_page(config, "tables")
    assert md.splitlines()[0] == "# Tabellen voorbeeld"
    # the h1 equals the title and is dropped; h2 -> ##, h3 -> ###
    assert md.count("# Tabellen voorbeeld") == 1
    assert "## Velden" in md and "### Lijst" in md
    assert "- Eerste punt" in md and "- Tweede punt" in md
    assert "\r" not in md and not md.startswith("﻿")


def test_headings_shift_when_the_page_starts_at_h2(config):
    md = clean_page(config, "with_files")
    assert "## Schermen" in md and "### Schermen" not in md


def test_skipped_heading_levels_are_closed_up(raw_dir):
    md = clean.clean_html(html_page("<h1>A</h1><h3>B</h3><h5>C</h5>"), "t", {}, raw_dir).markdown
    assert "## A" in md and "### B" in md and "#### C" in md


def test_pipe_table_with_header_row_and_escaped_pipe(config):
    md = clean_page(config, "tables")
    assert "| Veld | Uitleg |\n| --- | --- |" in md
    assert "| Bedrag | Het bedrag \\| in euro |" in md


def test_page_link_and_anchor_handling(config):
    md = clean_page(config, "tables")
    assert "[debiteur](<no_sections.htm>)" in md
    assert "#a" not in md
    md = clean_page(config, "no_sections")
    assert "[Tabellen voorbeeld](<tables.htm>)" in md


def test_external_and_in_page_links(raw_dir):
    body = '<p><a href="https://example.nl/x">extern</a> <a href="#top">naar boven</a> <a href="doc.pdf">pdf</a></p>'
    md = clean.clean_html(html_page(body), "t", {}, raw_dir).markdown
    assert "[extern](https://example.nl/x)" in md
    assert "naar boven" in md and "(#top)" not in md
    assert "[pdf](doc.pdf)" in md and "<doc.pdf>" not in md


def test_missing_page_link_becomes_text_and_is_counted(config, raw):
    page = raw / "knowledge-base" / "raw" / "htm_docs" / "tables.htm"
    page.write_text(page.read_text(encoding="utf-8-sig").replace("no_sections.htm", "bestaat_niet.htm"), encoding="utf-8")
    report = clean.run(config)
    md = (config.cleaned_dir / "tables.md").read_text(encoding="utf-8")
    assert "De naam van de debiteur" in md and "bestaat_niet" not in md
    assert report.page_links_dropped == 1


def test_screenshots_are_relative_to_raw_and_unresolved_ones_dropped(config):
    report = clean.run(config)
    md = (config.cleaned_dir / "with_files.md").read_text(encoding="utf-8")
    assert "![](htm_docs/with_files_files/pic.png)" in md
    assert "![](images/shot.gif)" in md
    assert "missing.jpg" not in md and "alt" not in md
    assert report.images_dropped == 1


def test_bare_image_name_resolves_into_raw_images(raw_dir):
    (raw_dir / "images" / "image920.jpg").write_bytes(b"x")
    md = clean.clean_html(html_page('<p><img src="image920.jpg" alt="images/image920.jpg"></p>'), "t", {}, raw_dir).markdown
    assert "![](images/image920.jpg)" in md and "alt" not in md


def test_scripts_and_breadcrumb_script_are_stripped(config):
    for stem in ("tables", "no_sections", "with_files", "Mengcodes_voorbeeld"):
        md = clean_page(config, stem)
        assert "RH_" not in md and "whver" not in md and "<script" not in md


def test_bold_paragraph_is_not_promoted_to_a_heading(config):
    md = clean_page(config, "no_sections")
    assert "**Let op**" in md
    assert not any(line.startswith("#") for line in md.splitlines()[1:])


def test_merge_codes_survive(config):
    md = clean_page(config, "Mengcodes_voorbeeld")
    assert "{$agiro[1].adresregel2}" in md
    assert "| Omschrijving | Mengobject | Mengveld | Mengcode |" in md


def test_menu_path_goes_into_front_matter(config, raw):
    page = raw / "knowledge-base" / "raw" / "htm_docs" / "no_sections.htm"
    write = ('RH_Document_Write("<a href=\\"x.htm#bc-1\\">Programma NV 2.0<\\/a> / '
             '<a href=\\"y.htm\\">Archivering<\\/a> / Menu 2.0<\\/p>");')
    anchor = 'RH_AddMasterBreadcrumbs("index.htm","","Home","");'
    page.write_text(page.read_text(encoding="utf-8-sig").replace(anchor, anchor + write), encoding="utf-8")
    md = clean_page(config, "no_sections")
    assert md.startswith('---\nmenu_path:\n  - "Programma NV 2.0"\n  - "Archivering"\n  - "Menu 2.0"\n---\n\n# Pagina zonder')
    assert "Programma NV 2.0" not in md.split("---", 2)[2]


def test_pages_without_a_breadcrumb_path_have_no_front_matter(config):
    assert clean_page(config, "tables").startswith("# ")


def test_colspan_and_rowspan_are_repeated(raw_dir):
    body = ("<table><tr><td>A</td><td colspan='2'>B</td></tr>"
            "<tr><td rowspan='2'>C</td><td>D</td><td>E</td></tr>"
            "<tr><td>F</td><td>G</td></tr></table>")
    md = clean.clean_html(html_page(body), "t", {}, raw_dir).markdown
    assert "| A | B | B |" in md
    assert "| C | D | E |" in md and "| C | F | G |" in md


def test_single_cell_and_image_wrapper_tables_are_unwrapped(raw_dir):
    body = ("<table><tr><td><p>Alleen tekst in een kader.</p></td></tr></table>"
            "<table><tr><td>links</td><td><img src='images/shot.gif'></td></tr></table>")
    md = clean.clean_html(html_page(body), "t", {}, raw_dir).markdown
    assert "|" not in md
    assert "Alleen tekst in een kader." in md and "![](images/shot.gif)" in md


def test_nested_table_is_flattened(raw_dir):
    body = ("<table><tr><td>Buiten</td><td><table><tr><td>x</td><td>y</td></tr></table></td></tr>"
            "<tr><td>a</td><td>b</td></tr></table>")
    md = clean.clean_html(html_page(body), "t", {}, raw_dir).markdown
    assert "| Buiten | x y |" in md


def test_toc_classes_are_removed_but_footer_class_is_kept(raw_dir):
    body = "<p class='MsoToc1'><a href='#a'>Inhoud</a></p><p class='MsoFooter'>fiatmap[1]</p>"
    md = clean.clean_html(html_page(body), "t", {}, raw_dir).markdown
    assert "Inhoud" not in md and "fiatmap[1]" in md


def test_skipped_pages_and_rebuild(config):
    config.cleaned_dir.mkdir(parents=True)
    (config.cleaned_dir / "oud.md").write_text("stale", encoding="utf-8")
    report = clean.run(config)
    names = {p.name for p in config.cleaned_dir.glob("*.md")}
    assert names == {"tables.md", "no_sections.md", "with_files.md", "Mengcodes_voorbeeld.md"}
    assert report.cleaned == 4


def test_page_filter_writes_one_page_and_keeps_the_others(config):
    clean.run(config)
    (config.cleaned_dir / "tables.md").unlink()
    clean.run(config, page="tables.htm")
    assert (config.cleaned_dir / "tables.md").exists() and (config.cleaned_dir / "no_sections.md").exists()


def test_unknown_page_and_missing_raw_dir_are_stage_errors(config, tmp_path):
    with pytest.raises(StageError):
        clean.run(config, page="bestaat_niet")
    with pytest.raises(StageError):
        clean.run(load_config({"DATA_DIR": str(tmp_path / "leeg")}))


def test_report_is_saved_with_flags(config):
    clean.run(config)
    saved = json.loads((config.cleaned_dir / "_clean_report.json").read_text(encoding="utf-8"))
    assert saved["cleaned"] == 4
    assert saved["flagged"]["no_sections.htm"] == ["short"]


def test_hub_page_is_flagged_mostly_links(raw_dir):
    body = "".join(f"<h3><a href='p{i}.htm'>Een linktekst nummer {i} voor de lijst</a></h3>" for i in range(3))
    pages = {f"p{i}.htm": f"p{i}.htm" for i in range(3)}
    page = clean.clean_html(html_page(body, "Hub"), "hub", pages, raw_dir)
    assert "mostly links" in page.flags and "short" in page.flags


def test_empty_page_is_flagged_empty(raw_dir):
    page = clean.clean_html(html_page(""), "leeg", {}, raw_dir)
    assert page.flags == ["empty"] and page.markdown.strip() == "# T"


def test_cli_clean_reports_stage_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: load_config({"DATA_DIR": str(tmp_path)}))
    assert cli.main(["clean"]) == 1
    assert "no Manual Pages found" in capsys.readouterr().err
