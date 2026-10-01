import json
import shutil

import pytest

from navigate_helper import chunk, cli, clean
from navigate_helper.config import CHUNK_TOKEN_CAP, StageError, load_config
from tests.fakes import FakeTokenizer

tok = FakeTokenizer()


def words(n, prefix="woord"):
    return " ".join(f"{prefix}{i}" for i in range(n))


def page(body, title="Pagina", menu_path=None):
    front = ""
    if menu_path:
        front = "---\nmenu_path:\n" + "".join(f'  - "{s}"\n' for s in menu_path) + "---\n\n"
    return f"{front}# {title}\n\n{body}\n"


def build(markdown, stem="P", cap=CHUNK_TOKEN_CAP):
    return chunk.chunk_page(markdown, stem, tok, cap=cap).chunks


def passage_tokens(c):
    return tok.count("passage: " + c["text"])


@pytest.fixture
def config(tmp_path, pages_dir):
    """A cleaned/ folder built from the fixture pages, with no raw/ of the real Manual."""
    htm = tmp_path / "knowledge-base" / "raw" / "htm_docs"
    shutil.copytree(pages_dir, htm)
    (htm.parent / "images").mkdir()
    (htm.parent / "images" / "shot.gif").write_bytes(b"GIF89a")
    cfg = load_config({"DATA_DIR": str(tmp_path)})
    clean.run(cfg)
    return cfg


# --- sections -------------------------------------------------------------------------------


def test_sections_start_at_h2_and_h3_and_h4_stays_inside():
    body = f"## A\n\n{words(40)}\n\n### B\n\n{words(40, 'b')}\n\n#### Diep\n\n{words(40, 'c')}"
    chunks = build(page(body))
    assert [c["heading_path"] for c in chunks] == [["Pagina", "A"], ["Pagina", "A", "B"]]
    assert "#### Diep" in chunks[1]["text"]


def test_page_without_h2_is_one_section_under_the_title():
    chunks = build(page(words(50)))
    assert len(chunks) == 1
    assert chunks[0]["heading_path"] == ["Pagina"]
    assert chunks[0]["text"].splitlines()[0] == "Pagina"


def test_context_line_joins_headings_and_strips_emphasis():
    chunks = build(page(f"## **Eerste**\n\n{words(40)}\n\n### Tweede\n\n{words(40, 'langewoord')}"))
    assert chunks[1]["text"].splitlines()[0] == "Pagina › Eerste › Tweede"
    assert chunks[1]["heading_path"] == ["Pagina", "Eerste", "Tweede"]


def test_h2_resets_the_h3_level():
    chunks = build(page(f"## A\n\n### A1\n\n{words(40, 'langewoord')}\n\n## B\n\n{words(40, 'langewoord')}"))
    assert chunks[-1]["heading_path"] == ["Pagina", "B"]


def test_headings_inside_code_fences_are_not_sections():
    chunks = build(page(f"## A\n\n```\n## niet een kop\n```\n\n{words(40)}"))
    assert len(chunks) == 1 and "## niet een kop" in chunks[0]["text"]


# --- size -----------------------------------------------------------------------------------


def test_cap_counts_passage_prefix_context_and_body():
    chunks = build(page("\n\n".join(words(30, f"p{i}x") for i in range(30))))
    assert len(chunks) > 1
    assert all(passage_tokens(c) <= CHUNK_TOKEN_CAP for c in chunks)
    assert all(c["token_count"] == passage_tokens(c) for c in chunks)


def test_blocks_are_not_cut_when_they_fit_in_a_chunk():
    paragraphs = [words(150, f"p{i}x") for i in range(4)]
    chunks = build(page("\n\n".join(paragraphs)))
    assert len(chunks) > 1
    for p in paragraphs:
        assert sum(p in c["text"] for c in chunks) == 1


def test_list_items_are_block_boundaries():
    items = "\n".join(f"- {words(60, f'i{n}x')}" for n in range(12))
    chunks = build(page(items))
    assert len(chunks) > 1
    for c in chunks:
        assert all(line.startswith("- ") for line in c["text"].splitlines()[1:])


def test_oversized_paragraph_splits_by_sentence_then_word():
    sentences = " ".join(f"{words(120, f's{n}x')}." for n in range(5))
    chunks = build(page(sentences))
    assert len(chunks) >= 2
    assert all(c["text"].rstrip().endswith(".") for c in chunks)  # cut at sentence ends
    assert all(passage_tokens(c) <= CHUNK_TOKEN_CAP for c in chunks)

    long_sentence = words(1000)  # no punctuation at all
    chunks = build(page(long_sentence))
    assert all(passage_tokens(c) <= CHUNK_TOKEN_CAP for c in chunks)
    assert " ".join(c["text"].split("\n", 1)[1] for c in chunks).split() == long_sentence.split()


def test_no_overlap_between_chunks():
    chunks = build(page(words(1000)))
    seen = [w for c in chunks for w in c["text"].split("\n", 1)[1].split()]
    assert seen == words(1000).split()


def test_chunk_over_ceiling_is_an_error_never_truncated():
    giant = "x" * 10
    class Heavy:
        def count(self, text):
            return 600 if giant in text else len(text.split())
    with pytest.raises(StageError, match="512"):
        chunk.chunk_page(page(giant), "P", Heavy())


# --- tables ---------------------------------------------------------------------------------


def table(rows, header="| Code | Uitleg |"):
    lines = [header, "| --- | --- |"] + [f"| {{${r}}} | {words(8, f'u{r}x')} |" for r in range(rows)]
    return "\n".join(lines)


def test_table_splits_in_row_groups_with_repeated_header():
    chunks = build(page("## T\n\n" + table(120)))
    assert len(chunks) > 1
    for c in chunks:
        lines = c["text"].splitlines()
        assert lines[1:3] == ["| Code | Uitleg |", "| --- | --- |"]
        assert all(l.startswith("|") and l.endswith("|") for l in lines[1:])
        assert passage_tokens(c) <= CHUNK_TOKEN_CAP
    rows = [l for c in chunks for l in c["text"].splitlines()[3:]]
    assert len(rows) == 120 and len(set(rows)) == 120


def test_small_table_stays_whole_with_its_text():
    chunks = build(page("## T\n\nIntro tekst " + words(40) + "\n\n" + table(3)))
    assert len(chunks) == 1 and chunks[0]["text"].count("| Code | Uitleg |") == 1


# --- embedded text --------------------------------------------------------------------------


def test_images_links_and_urls_are_reduced_to_text_and_collected_as_metadata():
    body = (
        "## A\n\n"
        f"Zie [de debiteur](<Debiteur,_Overzicht.htm>) en [Google](https://google.nl/x?a=1) {words(40)}\n\n"
        "![](images/shot.gif)\n\n![](htm_docs/P_files/b.png)"
    )
    (c,) = build(page(body))
    assert "Zie de debiteur en Google" in c["text"]
    assert "![" not in c["text"] and "](" not in c["text"] and "google.nl" not in c["text"]
    assert c["screenshots"] == ["images/shot.gif", "htm_docs/P_files/b.png"]
    assert c["page_links"] == [{"title": "de debiteur", "page_file": "Debiteur,_Overzicht.htm"}]


def test_screenshots_and_links_go_with_the_chunk_that_contains_them():
    first = words(300, "a")
    second = words(300, "b")
    body = f"## A\n\n{first}\n\n![](images/one.png)\n\n{second} [L](<Two.htm>)\n\n![](images/two.png)"
    c1, c2 = build(page(body))
    assert c1["screenshots"] == ["images/one.png"] and c1["page_links"] == []
    assert c2["screenshots"] == ["images/two.png"]
    assert c2["page_links"] == [{"title": "L", "page_file": "Two.htm"}]


def test_menu_path_is_metadata_not_text():
    (c,) = build(page(words(50), menu_path=["Basis", "Relaties"]))
    assert c["menu_path"] == ["Basis", "Relaties"]
    assert "Basis" not in c["text"]


# --- short sections -------------------------------------------------------------------------


def test_short_section_merges_into_next_and_keeps_its_own_heading_path():
    body = f"## Kort\n\nEven kort.\n\n## Lang\n\n{words(80)}"
    (c,) = build(page(body))
    assert c["heading_path"] == ["Pagina", "Kort"]
    assert "Even kort." in c["text"] and "## Lang" in c["text"]


def test_last_short_section_merges_into_the_previous_one():
    body = f"## Lang\n\n{words(80)}\n\n## Kort\n\nEven kort."
    (c,) = build(page(body))
    assert c["heading_path"] == ["Pagina", "Lang"]
    assert "Even kort." in c["text"]


def test_merge_never_exceeds_the_cap():
    body = f"## Kort\n\nEven kort.\n\n## Lang\n\n{words(395)}"
    chunks = build(page(body))
    assert len(chunks) == 2
    assert all(passage_tokens(c) <= CHUNK_TOKEN_CAP for c in chunks)


def test_a_single_short_section_is_still_indexed():
    (c,) = build(page("Kort."))
    assert c["text"].endswith("Kort.")


def test_empty_preamble_is_not_a_section():
    chunks = build(page(f"## A\n\n{words(80)}"))
    assert [c["heading_path"] for c in chunks] == [["Pagina", "A"]]


def test_page_with_only_a_title_yields_no_chunks():
    result = chunk.chunk_page("# Leeg\n", "P", tok)
    assert result.chunks == [] and result.empty


def test_hub_page_of_linked_headings_is_still_indexed():
    body = "\n\n".join(f"## [Onderwerp {i}](<Pagina{i}.htm>)" for i in range(3))
    (c,) = build(page(body))
    assert "Onderwerp 1" in c["text"] and "](" not in c["text"]
    assert {l["page_file"] for l in c["page_links"]} == {"Pagina0.htm", "Pagina1.htm", "Pagina2.htm"}


def test_section_with_only_a_screenshot_is_still_indexed():
    (c,) = build(page("## Alleen plaatje\n\n![](images/shot.gif)"))
    assert c["screenshots"] == ["images/shot.gif"] and c["heading_path"] == ["Pagina", "Alleen plaatje"]


# --- ids and metadata -----------------------------------------------------------------------


def test_chunk_ids_and_metadata_fields():
    chunks = build(page(f"## A\n\n{words(300)}\n\n## B\n\n{words(300, 'b')}", title="Mijn pagina"), stem="Mijn_pagina")
    assert [c["chunk_id"] for c in chunks] == [f"Mijn_pagina#{i}" for i in range(len(chunks))]
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert set(chunks[0]) == {
        "chunk_id", "page_file", "page_title", "heading_path", "chunk_index", "screenshots", "page_links",
        "versions", "char_count", "token_count", "menu_path", "text",
    }
    assert chunks[0]["page_file"] == "Mijn_pagina.htm" and chunks[0]["page_title"] == "Mijn pagina"
    assert chunks[0]["char_count"] == len(chunks[0]["text"])


# --- versions -------------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("Dit is NV1.4.", ["1.4"]),
    ("In nv 2.0 en NV 1.4 werkt dit.", ["1.4", "2.0"]),
    ("NV&nbsp;2.0 scherm", ["2.0"]),
    ("NV 2.0 scherm", ["2.0"]),
    ("geen versie, maar INVOICE2.0", []),
])
def test_version_regex(text, expected):
    (c,) = build(page(f"{text} {words(40)}"))
    assert c["versions"] == expected


@pytest.mark.parametrize("root,expected", [
    ("Programma uitleg via menustructuur NV 1.4/EuroDossier", ["1.4"]),
    ("Programma uitleg via menustructuur NV 2.0", ["2.0"]),
    ("Programma uitleg via menustructuur Configuratiecentrum", []),
    ("Basis", []),
])
def test_version_hint_from_menu_path_root(root, expected):
    (c,) = build(page(words(50), menu_path=[root, "Sub"]))
    assert c["versions"] == expected


def test_hint_and_regex_are_united_and_sorted():
    (c,) = build(page(f"NV 1.4 {words(40)}", menu_path=["Programma uitleg via menustructuur NV 2.0"]))
    assert c["versions"] == ["1.4", "2.0"]


def test_unmatched_nv_spellings_are_reported():
    result = chunk.chunk_page(page(f"NV2 en NV 3.1 en NV 1.4 en NV-2.0 {words(40)}"), "P", tok)
    assert result.unmatched_nv == {"NV2": 1, "NV 3.1": 1, "NV-2.0": 1}


# --- run ------------------------------------------------------------------------------------


def read(config, stem):
    return json.loads((config.chunked_dir / f"{stem}.json").read_text(encoding="utf-8"))


def test_run_writes_one_json_array_per_page(config):
    report = chunk.run(config, tokenizer=tok)
    names = {p.stem for p in config.chunked_dir.glob("*.json")}
    assert names == {"tables", "no_sections", "with_files", "Mengcodes_voorbeeld"}
    chunks = read(config, "tables")
    assert chunks[0]["chunk_id"] == "tables#0" and chunks[0]["page_title"] == "Tabellen voorbeeld"
    assert report.pages_chunked == 4 and report.chunks == sum(len(read(config, n)) for n in names)
    assert report.max_tokens == max(c["token_count"] for n in names for c in read(config, n))
    assert report.empty_pages == []
    assert set(report.token_stats) >= {"min", "median", "mean", "p90", "p99", "max"}


def test_run_rebuilds_the_output_folder(config):
    config.chunked_dir.mkdir(parents=True)
    (config.chunked_dir / "stale.json").write_text("[]", encoding="utf-8")
    chunk.run(config, tokenizer=tok)
    assert not (config.chunked_dir / "stale.json").exists()


def test_run_page_filter_only_touches_that_page(config):
    chunk.run(config, tokenizer=tok)
    (config.chunked_dir / "tables.json").unlink()
    chunk.run(config, page="tables", tokenizer=tok)
    assert (config.chunked_dir / "tables.json").exists() and (config.chunked_dir / "with_files.json").exists()


def test_run_reports_pages_empty_after_cleaning_and_writes_no_file(config):
    (config.cleaned_dir / "leeg.md").write_text("# Leeg\n", encoding="utf-8")
    report = chunk.run(config, tokenizer=tok)
    assert report.empty_pages == ["leeg"]
    assert not (config.chunked_dir / "leeg.json").exists()
    assert report.pages_chunked == 4


def test_run_errors_when_the_cleaned_folder_or_page_is_missing(config, tmp_path):
    with pytest.raises(StageError, match="clean"):
        chunk.run(load_config({"DATA_DIR": str(tmp_path / "nowhere")}), tokenizer=tok)
    with pytest.raises(StageError, match="nope"):
        chunk.run(config, page="nope", tokenizer=tok)


def test_run_raises_after_processing_when_a_chunk_exceeds_the_ceiling(config):
    class Heavy:
        def count(self, text):
            return 600 if "Veld" in text else len(text.split())
    with pytest.raises(StageError, match="tables"):
        chunk.run(config, tokenizer=Heavy())


def test_cli_chunk_uses_the_shared_model_name(config, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(chunk, "load_tokenizer", lambda name: seen.append(name) or tok)
    monkeypatch.setattr(cli, "load_config", lambda: config)
    assert cli.main(["chunk", "--page", "tables"]) == 0
    assert seen == [config.embedding_model]
    assert "Chunks" in capsys.readouterr().out


@pytest.mark.slow
def test_real_e5_tokenizer_counts_and_respects_the_cap():
    tokenizer = chunk.load_tokenizer(load_config({}).embedding_model)
    text = "passage: Dit is een Nederlandse zin over de debiteur."
    assert 5 < tokenizer.count(text) < 40
    result = chunk.chunk_page(page("\n\n".join(words(30, f"p{i}x") for i in range(40))), "P", tokenizer)
    assert result.chunks and all(c["token_count"] <= CHUNK_TOKEN_CAP for c in result.chunks)
