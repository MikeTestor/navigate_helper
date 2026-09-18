# Ragger

A small Retrieval-Augmented Generation (RAG) project: chunk documents into a
Chroma vector store, retrieve relevant context for a question, and generate
an answer with a pluggable LLM provider (Anthropic, OpenAI, Google, or
Ollama).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
copy .env.example .env
```

Fill in `.env` with the API key for whichever provider you set as
`LLM_PROVIDER`.

## Usage

Ingest documents (markdown files) into the vector store:

```bash
python -m ragger.ingest path/to/docs
```

Launch the chat UI:

```bash
python -m user_interface.app
```

## Layout

- `src/file_preparing/` — stage 1: load raw files and clean them (e.g. strip
  HTML boilerplate).
- `src/chunking/` — stage 2: split cleaned documents into chunks.
- `src/embedding/` — stage 3: embed chunks and store them in Chroma.
- `src/ragger/` — RAG glue: config-driven CLI (`ingest.py`), retrieval +
  generation (`rag.py`), and the LLM provider abstraction (`llm.py`).
- `src/user_interface/` — stage 5: the Gradio chat app.
- `src/core/` — shared foundation (env-based config) used by every stage.
- `notebooks/` — exploration notebooks.
- `database/` — local Chroma persistence directory (gitignored).

## Using this as a template

This repo is meant to be forked for each new RAG project. When you fork it:

1. Set `CHROMA_COLLECTION_NAME` in `.env` to something project-specific (avoids
   collisions if you ever point two forks at the same Chroma directory).
2. Update the `name` and `description` in `pyproject.toml`.
3. Update this README's title/description.
4. Drop your own documents somewhere and point `ragger.ingest` at them —
   `database/` starts empty per fork.
5. Rename the `ragger` package (`src/ragger/` and the `ragger.*` imports) if
   the new project deserves its own name rather than staying "ragger".
