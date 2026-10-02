## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for MikeTestor/navigate_helper, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default triage labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.

## Working rules

- Start each issue on a new branch from an up-to-date `main`. Check `git branch --show-current` before committing.
- Use TDD with the fakes in `tests/fakes.py`. Tests must never read `raw/`, call OpenAI, load the real e5 model, or run the real clean/chunk/embed stages; use `tmp_path` and fakes.
- Never delete, rebuild or let a test touch `database/embedded/chroma/` (the full store takes about 47 minutes to build).
- Ask before any real OpenAI call, and before pushing or opening a PR. Commit freely.
- Run the tests with `uv run pytest -q`. CI runs the same on every PR.
