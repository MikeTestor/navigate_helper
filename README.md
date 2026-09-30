# Navigate Helper

An assistant that answers Dutch questions about Aryza Navigate, grounded in its Dutch online Manual, using retrieval-augmented generation (RAG). It is built for Helpdesk Employees first.

## Status

In planning. The design for a walking skeleton (clean → chunk → embed → answer → Gradio dev app) is being settled. `src/` still holds generic template code and will be rewritten to match the design, so don't rely on its commands or package names yet.

## Where to look

- [CONTEXT.md](CONTEXT.md): the domain vocabulary (Manual Page, Chunk, Answer and so on).
- [docs/design-decisions.md](docs/design-decisions.md): what has been decided.
- [Wayfinder map](https://github.com/MikeTestor/navigate_helper/issues/1): the open decisions and their tickets.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Commands, configuration and the code layout will be documented here once the scaffolding is decided.
