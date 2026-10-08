# Navigate Helper

An assistant that answers Dutch questions about Aryza Navigate, grounded in its Dutch online Manual, using retrieval-augmented generation (RAG). It is built for Helpdesk Employees first.

## Status

Walking skeleton under construction. The package, CLI, configuration, test tooling and the `clean` stage are in place; the other stages (`chunk`, `embed`, `ask`, `ui`) are stubs that fail with "not implemented" until their build issues land.

## Where to look

- [CONTEXT.md](CONTEXT.md): the domain vocabulary (Manual Page, Chunk, Answer and so on).
- [docs/design-decisions.md](docs/design-decisions.md): the build-ready spec.
- [Wayfinder map](https://github.com/MikeTestor/navigate_helper/issues/1): how the decisions were reached.

## Setup

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

This creates `.venv` with the runtime dependencies and the `dev` group (pytest, Jupyter, nbstripout) and installs the package in editable mode. `pyproject.toml` and `uv.lock` are the only dependency sources.

Put the Manual in `database/knowledge-base/raw/` (`htm_docs/` and `images/`).

## Commands

```bash
uv run python -m navigate_helper clean            # raw/ -> cleaned/*.md
uv run python -m navigate_helper chunk            # cleaned/ -> chunked/*.json
uv run python -m navigate_helper embed            # chunked/ -> Chroma store
uv run python -m navigate_helper all              # clean, chunk, embed; stops on the first failure
uv run python -m navigate_helper ask "<vraag>"    # one question, printed
uv run python -m navigate_helper ui               # Gradio dev app
```

`clean` and `chunk` take `--page <stem>` (the Manual Page filename without `.htm`) to process one page. Each stage rebuilds its output from scratch. `all` does not start the UI.

`clean` prints a summary and writes `cleaned/_clean_report.json` (pages cleaned, dropped Page Links and images, and the short or link-only pages it flagged, with the reason).

## Configuration

Set these in a `.env` file in the project root (there is no `.env.example`; this table is the reference). Only `ask` and `ui` need `OPENAI_API_KEY`.

| Key | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | none | OpenAI key |
| `LLM_MODEL` | `gpt-5-mini` | Chat model |
| `LLM_REASONING_EFFORT` | `low` | Reasoning effort for the chat model |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | Local embedding model |
| `RETRIEVAL_K` | `6` | Chunks retrieved per question |
| `DATA_DIR` | `database` | Root of all data folders |

The `ui` command also reads two optional settings: `GRADIO_SERVER_PORT` (default `7860`) and `GRADIO_SERVER_NAME` (default `127.0.0.1`). See *Sharing the app with colleagues* below.

The chunk token cap, the short-Section merge threshold and the Chroma collection name (`navigate_manual`) are constants in `src/navigate_helper/config.py`.

## Sharing the app with colleagues

By default the app only accepts connections from the machine it runs on (`http://127.0.0.1:7860`). To let colleagues on the company network use it, start it listening on all network interfaces:

```powershell
$env:GRADIO_SERVER_NAME = "0.0.0.0"
uv run python -m navigate_helper ui
```

or put `GRADIO_SERVER_NAME=0.0.0.0` in `.env`. Colleagues then open `http://<PC name or IP address>:7860`.

- Windows Firewall needs an inbound rule for the port (7860 unless `GRADIO_SERVER_PORT` is set). That is a manual step on the machine, not part of the code.
- The app works only while that PC is on and the command is running.
- There is no login: the app is read-only and meant for use inside the company network. Do not expose it to the internet; every question costs money on the OpenAI key.

**First run:** `embed` and `ask` download the e5 embedding model (about 1 GB) into the Hugging Face cache once.

**Model deadline:** OpenAI removes `gpt-5-mini` and `gpt-5` from its API on **2026-12-11**. The follow-up [Pick the successor to gpt-5-mini](https://github.com/MikeTestor/navigate_helper/issues/25) must land before then.

## Code layout

```
src/navigate_helper/
  __main__.py, cli.py   command line
  config.py             env keys and constants
  clean.py              stage 1: Manual Pages -> Cleaned Pages
  chunk.py              stage 2: Cleaned Pages -> Chunks (JSON)
  embed.py              stage 3: Chunks -> Chroma store
  ask.py                ask() and Answer
  ui.py                 Gradio dev app
tests/                  pytest; fixtures/pages holds four small Manual Pages
database/               data, not committed (knowledge-base/, embedded/, ask_log.jsonl)
docs/                   design-decisions.md and agent docs
```

## Tests

```bash
uv run pytest             # fast tests with fakes; never reads raw/
uv run pytest -m slow     # also runs the tests that load the real e5 model
```
