# Open questions for the walking skeleton (2026-09-28)

Decisions still open before building the walking skeleton (all five stages end to end in `src/`). Everything in [design-decisions.md](design-decisions.md) is settled and not repeated here. Terminology is defined in [CONTEXT.md](../CONTEXT.md).

Each item has a **recommendation**, not a decision. None of these have been confirmed yet.

## Facts found in the raw data and code

- **`src/` is the generic "ragger" template**, not built for this project: `ragger.ingest` does load, chunk and embed in one go; the chunker is a plain `RecursiveCharacterTextSplitter` (1,000 characters, 200 overlap); `EMBEDDING_MODEL` defaults to `all-MiniLM-L6-v2`; `llm.py` supports four providers with hard-coded models; the Chroma collection is named `ragger` and stored in `./database/chroma`; the UI is a plain `gr.ChatInterface`. The README refers to a `.env.example` that doesn't exist.
- **Headings are sparse**: 385 pages have `<h1>`, 406 `<h2>`, 235 `<h3>`, 35 `<h4>`. **175 pages have no `<h2>` or `<h3>` at all.**
- **The HTML is mostly Word output** (`MsoNormal` about 28k times, `PlainText`, `t1st`, `PdfParaStyle*`, `Table_Style_CN`). Some headings are probably styled paragraphs, not `<hN>` tags.
- **Links**:
  - about 2,150 in-page links (`href="#…"`)
  - about 1,361 links to another page plus an anchor (`Page.htm#anchor`)
  - about 1,727 plain `.htm` links
  - a few external links (rechtspraak.nl, betaalvereniging.nl, wiki.eurosystems.nl, and others) and one link to a `.pdf`
- **Images come in three forms**:
  - a bare filename (`src="image920.jpg"`): about 4,099 unique, **all present in `raw/images/`**
  - `images/…` (673 references)
  - `<Page>_files/…` subfolders inside `htm_docs/` (for example `Documentlogistiek_CN_voor_wiki_files/`, `verdeling_files/`). These are **not** in `raw/images/`.
- **Encoding**: all pages are UTF-8 **with a BOM** and CRLF line endings.
- **Stray files** in `htm_docs/`: `creditnavigator.log` and CSS.
- **Very large pages**: `Partner_vastleggen_en_wijziging_huwelijksgoederenrecht.htm` (1.1 MB), `dbrdeb902.htm` (1.0 MB), `dbrdeb901.htm` (0.8 MB). The cause hasn't been checked yet.

## A. Before building

1. **What happens to the template code?** Recommendation: keep the stage folders, rewrite their internals to match the design, and support OpenAI only (model set in `.env`). Drop the Anthropic, Google and Ollama paths.
2. **Package name and command-line interface.** Recommendation: rename the `ragger` package and README; add one entry point, `python -m <pkg> clean|chunk|embed|all`; set the raw, cleaned, chunked and Chroma paths in config; add `.env.example` (`OPENAI_API_KEY`, `LLM_MODEL`, `EMBEDDING_MODEL`, paths).
3. **Dependencies.** `pyproject.toml` carries template packages this project doesn't use (modal, wandb, speedtest-cli, feedparser, pydub, and others). Should they be pruned?
4. **Test strategy.** Recommendation: test first on pure functions (cleaner, chunker, citation parsing), plus answering with a fake retriever and a fake LLM. Use a few real Manual Pages as fixtures.

## B. Stage 1 – Clean

5. **What counts as a heading?** Recommendation: only real `<hN>` tags, with no guessing from bold or styled paragraphs. `<title>` becomes the `#` heading; an `<h1>` that repeats the title is dropped.
6. **Link handling.** Recommendation: drop in-page `#` links but keep their text; cut the `#anchor` off links to other pages; keep external links as normal Markdown links, but they are not Page Links.
7. **Screenshot paths.** Store each path relative to `raw/`, so all three forms resolve. This slightly changes the `![](image920.jpg)` format in the design. Confirm.
8. **Tables.** Recommendation: convert to simple Markdown pipe tables, unwrap one-cell layout tables, and flatten nested tables. Merged cells are lost.
9. **Tooling and a spike first.** Recommendation: `markdownify` with custom converters. First inspect the three largest pages and find how RoboHelp marks breadcrumbs, so the strip rules are known.
10. **Files to skip**: anything that isn't `.htm` in `htm_docs/`; read with `utf-8-sig`.

## C. Stage 2 – Chunk

11. **Pages with no `##` or `###`**: treat the whole page as one section, then split it at the 1,500-character cap. Does `####` start a new section? Recommendation: no.
12. **What text gets embedded?** Recommendation: strip image markup and link URLs from the Chunk text (keeping link text), and keep them in the `screenshots` and `page_links` metadata. The 1,500-character cap includes the context line.
13. **Token check.** 1,500 Dutch characters may come close to e5's 512-token limit. Recommendation: the chunk stage counts tokens with the e5 tokenizer and warns about any Chunk over 512.
14. **Version detection.** A precise regex for `NV1.4`, `NV 1.4`, `NV2.0` and similar variants.
15. **Merging short sections at the end of a page.** When the last section is under about 200 characters, merge it into the previous one.

## D. Stage 3 – Embed

16. **Chroma metadata only holds single values**, not lists. Recommendation: store scalar fields only in Chroma, use the Chroma ID as `chunk_id`, and look up the full Chunk in the chunked JSON when answering.
17. **e5 prefixes and similarity scores.** Recommendation: a small embeddings wrapper that adds `query: ` and `passage: `; normalise the vectors; use cosine distance, so the debug-panel score means something.
18. **Where the store lives.** Recommendation: `database/embedded/` (the folder already exists), deleted on every rebuild. The first run downloads the e5 model (about 1 GB).

## E. Answering (the boundary between RAG logic and UI)

19. **The interface the UI uses.** Recommendation: `ask(question) -> Answer`. `Answer` carries the text, a `covered` flag, the cited and retrieved Chunks with scores, the Screenshots, the Page Links and the source pages. The UI knows nothing else.
20. **Citation format.** Option 1 (recommended): structured JSON output `{answer, covered, cited_chunk_ids}`. Option 2: inline `[Budgetten#3]` markers parsed with a regex. Either way, cited IDs that weren't retrieved are dropped.
21. **"Not in the Manual" detection.** Recommendation: the LLM sets `covered=false`. The 2–3 closest pages are the top unique pages among the Retrieved Chunks, ranked by score. Alternative: a similarity threshold.
22. **Prompt language and context format.** The system prompt is in Dutch, and each Retrieved Chunk is labelled with its `chunk_id`.

## F. Gradio dev app

23. **Layout.** Recommendation: `gr.Blocks` instead of `ChatInterface`. The chat goes on the left; the right side has tabs for Debug and the Page viewer.
24. **How a Page Link opens the Page viewer.** A Markdown link in the chat would open a new browser page. Option 1 (recommended): show Page Links as a clickable list or dropdown under each Answer; choosing one loads the viewer. Option 2: inline links plus custom JavaScript.
25. **Showing the raw page.** Its CSS and scripts use relative paths, and its images are in three different places. Recommendation: strip scripts, point image `src` at Gradio file URLs (via `allowed_paths`), and show it in a sandboxed iframe (`srcdoc`) next to the rendered Cleaned Page.
26. **Where Screenshots appear.** Recommendation: a `gr.Gallery` under the Answer, with duplicates removed, rather than images inside the chat message.
27. **Debug panel content.** Recommendation: a table of Retrieved Chunks with `chunk_id`, page title, heading path, score, whether each was cited, and the Chunk text expandable.

## A possible ticket split (after the decisions above)

1. Scaffolding: config, `.env.example`, command-line interface, package rename, template cleanup
2. Clean stage
3. Chunk stage
4. Embed stage
5. `ask()` and the `Answer` model (retrieval, prompt, citations, not-covered handling)
6. Gradio chat with Screenshots, Page Links and the debug panel
7. Page viewer (raw page and Cleaned Page side by side)
