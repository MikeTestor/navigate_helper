# Design decisions for the walking skeleton (final, 2026-10-01)

The build-ready spec for the walking skeleton. It folds the grilling session of 2026-09-23 and every resolution on the Wayfinder map ([build-ready spec for the walking skeleton](https://github.com/MikeTestor/navigate_helper/issues/1)). Terminology is defined in [CONTEXT.md](../CONTEXT.md). Each section names the map ticket that holds the full reasoning.

## Facts about the source data

- 619 `.htm` Manual Pages exported from Adobe RoboHelp 9 (622 files in the original grilling count included stray files), in `database/knowledge-base/raw/htm_docs/`; images in `raw/images/` and, for two pages, in `raw/htm_docs/<Page>_files/`. All pages are UTF-8 with a BOM and CRLF.
- The Manual is in **Dutch** and uses the old product name "Credit Navigator" / "NV" (the same product as Aryza Navigate).
- About 270 pages mention NV1.4 and about 250 mention NV2.0.
- Headings are real `<hN>` tags. 234 pages have no `<h1>` and 15 have no heading at all. 147 pages use bold paragraphs as pseudo-headings.
- Boilerplate is a breadcrumb `<script>` at the top of `<body>`. 129 pages carry a menu path in it.
- 1,668 tables on 278 pages, mostly key/value; 16 have over 100 rows.
- About 20% of pages (121) are merge-code reference pages (`Mengcodes_*`, `{$…}` placeholders). They tokenise at about 0.36 tokens per character, against about 0.24 for prose.
- Raw size is about 95% Word-export style bloat; the biggest pages still hold 40–50k characters after cleaning.

Sources: [Spike: inspect the raw Manual HTML](https://github.com/MikeTestor/navigate_helper/issues/3), [Measure e5 tokens per character](https://github.com/MikeTestor/navigate_helper/issues/4).

## Scope and users

1. **Asker**: Helpdesk Employees first; End Users possibly later.
2. **Language**: Dutch questions, Dutch Answers. Specs and code in English.
3. **Versions**: ignore NV1.4 vs NV2.0 for now. Record version mentions as metadata, don't filter on them.
4. **LLM data policy**: OpenAI is acceptable during development (no client data). **Re-evaluate before go-live.**
5. **Prototype = walking skeleton**: all five stages end to end, crude but real, improved in place (not a throwaway).
6. **Scope**: all Manual Pages from the start. The Kennispagina is not a source.

## Layout, CLI, config and tests

Source: [Scaffolding](https://github.com/MikeTestor/navigate_helper/issues/2).

- **Package**: one package `navigate_helper` in `src/` with a submodule per stage: `clean`, `chunk`, `embed`, `ask`, `ui`, `config`. The `ragger` name, `ragger/llm.py` and `ragger/ingest.py` go away. OpenAI is the only provider.
- **CLI**: `python -m navigate_helper clean|chunk|embed|all|ask|ui` (`argparse`). `clean` and `chunk` take an optional `--page <stem>` filter. `all` runs clean → chunk → embed, stops on the first failure and does not start the UI. Each stage rebuilds its output from scratch.
- **Dependencies**: only what the skeleton uses (`beautifulsoup4`, `markdownify`, `chromadb`, `gradio`, the langchain pieces, `sentence-transformers`, `torch`, `transformers`, `python-dotenv`, `tqdm`). A `dev` group holds `pytest`, Jupyter and `nbstripout`. `pyproject.toml` + `uv.lock` are the single source; `requirements.txt` and the `protobuf==3.20.2` pin are deleted. Verified with an import check.
- **Config**: env keys `OPENAI_API_KEY`, `LLM_MODEL`, `LLM_REASONING_EFFORT` (default `low`), `EMBEDDING_MODEL`, `RETRIEVAL_K` (6) and `DATA_DIR`. The chunk token cap, merge threshold and collection name (`navigate_manual`) are constants in code. Only `ask` and `ui` need the API key. No `.env.example`.
- **Tests**: `pytest` under `tests/`. Four small committed fixture pages (tables; no `##`/`###`; a `_files` folder; merge codes). Tests never read `raw/`. Property assertions, not snapshots. Fake embedder, retriever, chunk store and LLM by default, plus one `@pytest.mark.slow` test with the real e5 model, skipped by default. Each build issue writes its own tests.
- **Notebooks**: delete `02_test_llms.ipynb` and `sample_docs`; keep `01_explore.ipynb` only if it is about the Manual.
- **README**: owned by the scaffolding build issue: package name, `uv`/venv setup, commands, `.env` keys, code layout, the first-run e5 download (about 1 GB) and the model deadline below.
- **Default model**: `gpt-5-mini`. OpenAI removes it (and `gpt-5`) from the API on **2026-12-11**; a follow-up issue picks the successor (`gpt-5.6-terra` or `gpt-5.4-mini`) and verifies structured output and citations before then.

## Stage 1 – Clean (`raw/` → `database/knowledge-base/cleaned/<stem>.md`)

Source: [Clean rules](https://github.com/MikeTestor/navigate_helper/issues/8). Output is LF, no BOM; `<stem>` is the Manual Page filename without `.htm`.

- **Title and headings**: `<title>` (whitespace collapsed) is the single `#` line. Heading levels are shifted per page: the shallowest `<hN>` becomes `##`, others keep their relative depth, skipped levels closed up. An `<hN>` whose text equals the title is dropped. Chapter numbers stay as text. Bold-only paragraphs are **not** promoted (see [parked test](https://github.com/MikeTestor/navigate_helper/issues/16)).
- **Links**: `#anchor` links are dropped and their text kept. `Page.htm#anchor` becomes `Page.htm`. A Page Link is a relative `.htm` href, URL-decoded, written `[text](<Page.htm>)`, and becomes plain text when the target is missing from `htm_docs/` (counted in the report). `http(s)`, `mailto:` and `.pdf` links stay as ordinary Markdown links and are not Page Links. Links with empty text are dropped.
- **Screenshots**: `![](images/<name>)` for bare and `images/…` sources, `![](htm_docs/<Page>_files/<name>)` for `_files` sources; all relative to `raw/`; alt text empty. Images that don't resolve (including the one external image) are dropped and counted.
- **Tables**: every table becomes a pipe table with the first row as header; newlines in cells become spaces, `|` escaped. Single-cell and image-wrapper tables (1–2 cells) are unwrapped, the one nested table is flattened, merged cells are repeated into each spanned position. Tables are never truncated.
- **Strip**: `<head>`, all `<script>` and `<style>`, empty anchors, `iframe`/`object`/`embed`, and `MsoToc*` / `Toc1/2/3` classes. Never strip by `Footer` or other `Mso*` class (they hold Mengcodes content). `style` attributes are ignored.
- **Menu path**: the breadcrumb in the first `<script>` (129 pages) is parsed into `menu_path` and written as a YAML front-matter block. It is metadata, not text.
- **Files**: read `*.htm` with `utf-8-sig`; skip only `index.htm` and `rhair_fbody.htm`. No hub-page filter and no `Copy_*` rule. Pages under 200 characters of text, or mostly links, are cleaned but flagged in the clean report.
- **Tooling**: BeautifulSoup (`html.parser`) pre-clean, then `markdownify` with custom converters. Blank lines collapsed.

## Stage 2 – Chunk (`cleaned/` → `database/knowledge-base/chunked/<stem>.json`)

Source: [Chunk rules](https://github.com/MikeTestor/navigate_helper/issues/9). One JSON file per Manual Page, holding an array of Chunks.

- **Sections**: `##` and `###` start Sections. `####` and deeper stay inside their parent and in the Chunk text. `heading_path` is page title › `##` › `###` (never a fourth level). A page with no `##` is one Section under the `#` title.
- **Size**: a **token cap of 400** (hard ceiling 512, exceeding it is an error, never silent truncation), counted with the e5 tokenizer on the final string `passage: ` + context line + body. Split at block boundaries (paragraph, list item, table row group). Only when one block alone exceeds the cap, split by sentence, then by word. **No overlap.** The 400 and the zero overlap are starting values for tuning with the Evaluation Set.
- **Tables**: split by row groups within the cap, never inside a row, repeating the header row in each group. Merge-code pages get no special case; they simply yield more, smaller Chunks (see [compact rows, parked](https://github.com/MikeTestor/navigate_helper/issues/17)).
- **Embedded text**: context line `Pagina › Heading › Subheading` + body. Image markup removed. A Page Link is reduced to its text; external links keep text and lose the URL. `menu_path` is not embedded.
- **Short Sections**: under 200 characters of body (excluding the context line) merge into the next Section, keeping the first Section's heading in `heading_path`; the last Section merges into the previous one. A merge never exceeds the token cap. Flagged short and hub pages are still indexed; only pages empty after cleaning yield no Chunks (counted in the report).
- **Chunk ID**: `<stem>#<chunk_index>`, index from 0 per page, in page order.
- **Metadata** (JSON): `chunk_id`, `page_file`, `page_title`, `heading_path`, `chunk_index`, `screenshots` (list), `page_links` (list of `{title, page_file}`), `versions` (list), `char_count`, `token_count`, `menu_path`. `screenshots` and `page_links` go with the Chunk that contains them.
- **Versions**: one case-insensitive regex on each Chunk's body, `\bNV\s*(?:&nbsp;| |\s)?(1\.4|2\.0)\b`, normalised to `"1.4"` / `"2.0"`, plus a hint from the `menu_path` root (`NV 1.4` or `EuroDossier 64` → `"1.4"`, `NV 2.0` → `"2.0"`). `versions` is the sorted union and may be empty. The stage reports `NV…` spellings the regex misses, so it can be widened without a new decision.

## Stage 3 – Embed

Sources: [Embed stage](https://github.com/MikeTestor/navigate_helper/issues/10), [Chroma and Langchain research](https://github.com/MikeTestor/navigate_helper/issues/5).

- **Model**: `intfloat/multilingual-e5-base`, local, reads at most 512 tokens. One shared constant is used by the chunk tokenizer and the embedder.
- **Prefixes**: `HuggingFaceEmbeddings` with `encode_kwargs={"prompt": "passage: ", "normalize_embeddings": True}` and `query_encode_kwargs={"prompt": "query: ", "normalize_embeddings": True}`. No wrapper class, no `multi_process`. A unit test with a fake model checks both prefixes arrive.
- **Chroma holds**: ID = `chunk_id`; document = the exact embedded text; scalar metadata only (`page_file`, `page_title`, `heading_path` joined with ` › `, `chunk_index`, `token_count`, `menu_path`). The **chunked JSON is the source of truth**: `ask()` loads the full Chunk from it by `chunk_id`.
- **Distance and score**: collection created with `collection_configuration={"hnsw": {"space": "cosine"}}`. Score is cosine similarity (`1 - distance`) via `similarity_search_with_relevance_scores`, typically 0.7–1.0, shown raw. Always top k (default 6), no threshold.
- **Store**: `database/embedded/chroma/`, collection `navigate_manual`. Every `embed` deletes the `chroma/` folder (not `delete_collection`, because of chroma-core/chroma#7594) and rebuilds from all `chunked/*.json`. It fails clearly if `chunked/` is missing or empty.
- **Guards**: `chunk_id`s unique across pages; every `token_count` at most 512 (raise, never truncate); a Chunk count mismatch between JSON and Chroma is an error. Batched embedding with a progress line; report: Chunks embedded, pages covered, elapsed time. No smoke-test query in the stage.

## Answering

Sources: [ask() and Answer contract](https://github.com/MikeTestor/navigate_helper/issues/11), [structured output research](https://github.com/MikeTestor/navigate_helper/issues/6).

- **Interface**: `Assistant(retriever, llm, chunk_store, k).ask(question: str) -> Answer`; `build_assistant()` reads config and wires real Chroma, `ChatOpenAI` and the chunked JSON. The CLI `ask` command and the UI both use it; the UI builds it once at startup. Single-turn.
- **LLM output**: `with_structured_output(Pydantic)` (strict json_schema), fixed schema: `answer`, `covered`, and one flat `cited_chunk_ids: list[str]` for the whole Answer. Cited IDs that weren't retrieved are dropped after the call and kept in `dropped_citation_ids`. `covered=true` with zero valid citations is shown as-is and flagged in debug.
- **Not in the Manual**: the LLM decides via `covered`; no similarity threshold. On `covered=false` the LLM writes only a short Dutch "not covered" line, and `ask()` adds the 2–3 closest pages (top unique pages among the Retrieved Chunks by best score). No answers from general knowledge.
- **Prompt** (`prompts.py`, Dutch, hand-tuned): answer only from the context, always in Dutch, concise step by step, cite each `chunk_id` actually used, `covered=false` if the context doesn't answer, and Aryza Navigate = Credit Navigator = NV. Answers say "Aryza Navigate"; old names stay only inside quoted UI labels, menu paths and Mengcodes. No query rewriting. Each context block is `[chunk_id]` + the embedded text; no scores in the prompt. Screenshots and Page Links are attached by `ask()` from the Cited Chunks' JSON, never parsed from the text.
- **`Answer`** (plain fields filled by `ask()`): `question`, `text` (Dutch Markdown, no citation markers), `covered`, `cited: list[ScoredChunk]`, `retrieved: list[ScoredChunk]` (all k, each with `score` and a `cited` flag; a `ScoredChunk` is the full Chunk plus its score), `screenshots` (deduplicated, from Cited Chunks), `page_links` (deduplicated `{title, page_file}` from Cited Chunks), `source_pages` (`{page_file, page_title}`: Cited Chunks' pages, or the closest pages when not covered), `dropped_citation_ids`, `error: str | None`.
- **LLM settings**: reasoning effort `low` (env-configurable), max completion tokens 4,000 (constant), no temperature. LLM problems (refusal, truncation, API error) never raise: `ask()` returns an Answer with `error` set, `covered=False`, a short Dutch apology and `retrieved` still filled. Retrieval and config errors do raise. No retries beyond the openai client's own.
- **Dev log**: each `ask()` appends one JSON line to `database/ask_log.jsonl` (the Answer plus `timestamp` and `model`). Gitignored, because questions may hold client data. A logging failure is swallowed with a warning.

## Stages 4 and 5 – Gradio dev app

Sources: [Gradio dev app](https://github.com/MikeTestor/navigate_helper/issues/12), [Gradio research](https://github.com/MikeTestor/navigate_helper/issues/7). RAG logic stays in `ask`; `ui` knows only `Answer`.

- **Layout**: `gr.Blocks`; chat on the left; tabs on the right: **Page viewer** and **Debug**.
- **Page Links**: a radio list under each Answer; choosing one loads the Page viewer. No inline links and no custom JavaScript.
- **Page viewer**: the raw Manual Page (scripts stripped, image `src` rewritten to `/gradio_api/file=` URLs, relative links unwrapped to plain text because they cannot resolve inside the iframe, except links to another Manual Page, which stay links: a small script of our own (the only script that runs; `sandbox` adds `allow-scripts`) posts the clicked page to the app, which loads it in the viewer through a hidden box, `#anchor` links written as `about:srcdoc#anchor` in the iframe (a bare `#anchor` loads the app's own URL in the frame), `srcdoc` iframe with `sandbox="allow-same-origin"` and no `allow-scripts`) next to the rendered Cleaned Page. A heading shows the page title and an **open full page** link.
- **Image resolution**: pages and images are read from the project's `raw/` (`allowed_paths` covers it), not the shared drive. Bare filename → `raw/images/`, `images/x` → `raw/`, `<Page>_files/x` → `raw/htm_docs/`. **Open full page** opens `/manual/<Page>.htm` in a new tab: the app serves the rewritten page (scripts stripped, image URLs rewritten, no scripts allowed by a Content-Security-Policy) on the same port as the chat, so its links to other Manual Pages and `#anchor` links work as ordinary links. No file-system path is shown.
- **Screenshots**: a `gr.Gallery` under the Answer, deduplicated, captioned with page and file name.
- **Debug tab**: a table of Retrieved Chunks: `chunk_id`, page title, heading path, score, cited (yes/blank), the Chunk text; plus dropped citations and the `error` / uncited flags.
- The throwaway prototype lives on branch `prototype/gradio-dev-app` (commits 35a8148, 574d32b).

## Operations

- Separate commands `clean`, `chunk`, `embed`, plus `all`; each stage rebuilds from scratch. `ask` and `ui` read only what the earlier stages wrote.
- `database/ask_log.jsonl`, `database/embedded/` and the stage outputs are gitignored.

## Out of scope for this effort

- **Evaluation Set** (30–50 real helpdesk questions, each paired with the Manual Page(s) that answer it). The obvious next effort; build it before tuning chunk size, k and the model.
- Version filtering (NV1.4 / NV2.0).
- OCR or vision descriptions of Screenshots.
- Multi-turn follow-up questions.
- Production UI, hosting, and the data-policy review before go-live.
- The Kennispagina as a source.
- Parked as their own issues: [keyword search next to embeddings](https://github.com/MikeTestor/navigate_helper/issues/14), [Navigate source code as a retrieval source](https://github.com/MikeTestor/navigate_helper/issues/15), [bold pseudo-headings as headings](https://github.com/MikeTestor/navigate_helper/issues/16), [compact row rendering for merge-code pages](https://github.com/MikeTestor/navigate_helper/issues/17).

## Changed since the grilling session of 2026-09-23

| Earlier decision | Now | Why |
|---|---|---|
| Chunk cap 1,500 characters, 150 overlap | 400-token cap, no overlap | 1,500 characters overflows 512 tokens on merge-code pages (60% of their Chunks) |
| Context line only | Context line plus `menu_path` as metadata | The breadcrumb is free structure |
| Screenshot as `![](image920.jpg)` | `![](images/<name>)` relative to `raw/` | Images live in three places |
| Chunk metadata in Chroma | Scalar-only metadata in Chroma, full Chunk from the JSON | Chroma can't store `{title, page_file}` objects |
| Folder `chuncked` | `chunked` | Typo |
| 622 pages | 619 `.htm` files, 617 cleaned | `index.htm` and `rhair_fbody.htm` are skipped |
| `gpt-5-mini` as default | Still the default, with a successor follow-up | Removed from the API on 2026-12-11 |
| Debug panel and Page viewer sketched | Layout A, with radio list, gallery, open full page | Prototype reviewed |
