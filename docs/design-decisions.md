# Design decisions (grilling session, 2026-09-23)

Outcome of a `/grill-with-docs` session on [instructions.md](../instructions.md). Terminology is defined in [CONTEXT.md](../CONTEXT.md).

## Facts about the source data

- 622 `.htm` Manual Pages exported from Adobe RoboHelp 9, in `database/knowledge-base/raw/htm_docs/`; 4,686 images in `database/knowledge-base/raw/images/`.
- The Manual is in **Dutch** and uses the old product name "Credit Navigator" / "NV" (the same product as Aryza Navigate).
- About 270 pages mention NV1.4 and about 250 mention NV2.0, sometimes both on one page.
- Every page has a unique `<title>`; 234 pages have no `<h1>`; 278 pages contain tables.
- Raw pages reference images by bare filename (`src="image920.jpg"`), but the images live in `raw/images/`.
- Page Links point at other `.htm` files by filename (for example `href="CreditNavigatorConstanten_mappen.htm"`).

## Scope and users

1. **Asker**: Helpdesk Employees first; End Users possibly later.
2. **Language**: Dutch questions, Dutch Answers.
3. **Versions**: ignore NV1.4 vs NV2.0 for now. Record version mentions as metadata, but don't filter on them.
4. **LLM data policy**: OpenAI is acceptable during development (no client data). **Re-evaluate before go-live.**
5. **Prototype = walking skeleton**: all five stages end to end in `src/`, crude but real, improved in place (not a throwaway).
6. **Scope**: all 622 Manual Pages from the start.

## Stage 1 – Clean (`raw/` → `database/knowledge-base/cleaned/<page>.md`)

- Output is a **Markdown** Cleaned Page per Manual Page.
- Page title from `<title>`.
- Keep headings, lists and tables.
- Screenshot → `![](image920.jpg)`; Page Link → `[title](Page.htm)`.
- Strip RoboHelp scripts, styles and breadcrumbs.

## Stage 2 – Chunk (`cleaned/` → `database/knowledge-base/chunked/<page>.json`)

- Folder renamed from `chuncked` to `chunked`.
- **One JSON file per Manual Page**, holding an array of Chunks.
- **Split by heading section** (`##` / `###`):
  - cap **1,500 characters**, **150 overlap**, used only when a section is too long
  - merge sections under about 200 characters into the next one
  - each Chunk's text starts with a context line: `Pagina › Heading › Subheading`
- **Chunk ID** is deterministic: `<page-file-stem>#<chunk_index>` (for example `Budgetten#3`).
- **Metadata**: `chunk_id`, `page_file`, `page_title`, `heading_path`, `chunk_index`, `screenshots` (list), `page_links` (list of `{title, page_file}`), `versions` (list), `char_count`.

## Stage 3 – Embed

- Chroma + Langchain.
- Embedding model: **`intfloat/multilingual-e5-base`**, run locally. It replaces `all-MiniLM-L6-v2`, which is English-only.
- This model reads at most **512 tokens**, which is why the Chunk cap is 1,500 characters.
- e5 models expect `query: ` / `passage: ` prefixes on their input.

## Answering

- Retrieve **k = 6** Chunks.
- LLM: **`gpt-5-mini`** as the development default, configurable in `.env`. Compare against `gpt-5` later.
- The LLM must **cite the chunk IDs** it used. Only Cited Chunks contribute Screenshots and Page Links, plus a link to each cited Chunk's own Manual Page.
- If the Manual doesn't cover the question, the Answer says so plainly (in Dutch) and lists the 2–3 closest Manual Pages. No answers from general knowledge.
- **Single-turn**: each question is retrieved on its own. Multi-turn (rewriting a follow-up into a standalone question) comes later.

## Stages 4 and 5 – Gradio dev app

- Gradio for development; no deployment needed. Keep the RAG logic separate from the UI so the front end can be swapped later.
- Chat shows each Answer with the Screenshots and Page Links of its Cited Chunks.
- **Debug panel**: Retrieved Chunks with source page, heading and similarity score.
- **Page viewer**: clicking a Page Link shows the **raw page** (image paths rewritten to `raw/images/`) **side by side** with its **Cleaned Page**. This doubles as a check on the cleaning step.

## Operations

- Separate commands `clean`, `chunk` and `embed`, plus `all`.
- Each stage rebuilds its output from scratch; no incremental updates.

## Later (not in the prototype)

- **Evaluation Set**: 30–50 real helpdesk questions, each paired with the Manual Page(s) that answer it. Build it before tuning chunk size, k and the model.
- Version filtering (NV1.4 / NV2.0).
- OCR or vision descriptions of Screenshots.
- Multi-turn follow-up questions.
- Production UI choice, and the data-policy review before go-live.
