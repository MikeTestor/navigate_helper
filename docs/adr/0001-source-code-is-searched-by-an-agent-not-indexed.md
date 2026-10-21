# The Source Code is searched by an agent, not indexed

Status: accepted (issue #44)

Answers from the Source Code come from a Code Search: an agent with read-only `grep`, `list` and `read` tools over a Code Checkout, not from a vector index of code chunks. The Source Code is about 350 MB of text (mostly Progress 4GL and C#/WPF); an e5 index of it would take days to build, retrieve poorly across a call chain, and go stale. Letting a model read the code directly is what already gives good answers in the existing `bfx14` chat.

The Manual Answer stays the fast default. The Code Search runs when the Manual Answer is `covered=false` or when the Asker asks to check against the code, and it receives the Manual Answer so it can say whether the Manual agrees.

## Considered options

- Vector index of code chunks: rejected (build time, e5 is not trained on code, lost call chains, upkeep).
- Hybrid keyword/symbol index: not needed now. A small symbol index can be added later if the Code Search needs too many tool calls.
- LLM-written explanation pages through the Manual pipeline: rejected, because they are a second-hand opinion of the code and go stale silently.

## Consequences

- The Code Checkout is read in place through `CODE_DIR`, never copied into this repository. The tool layer, not the prompt, enforces read-only access, confinement to `CODE_DIR`, an extension allowlist (`.p .i .w .cls .v .cs .xaml .xml .df .md`) and the exclusion of `data/`, `projects/`, `.builder/`, `.claude/`, `.vs/`, `bin/` and `obj/`, which may hold customer data.
- Hard limits per run: 40 tool calls, about 300k input tokens, a 10 minute safety ceiling and a Stop button. A hit limit yields a partial Answer, never an invented conclusion. Tool calls and tokens are logged.
- A Code Answer shows the newest modification date in the Code Checkout ("code per <date>"). Currency is whatever is on disk.
- A Code Answer cites `path:line-range` with a snippet of at most about 20 lines, is labelled unverified, and states what it did not check (configuration, customisations, data).
- When the Manual and the Source Code disagree, both Answers are shown. The Manual is never flagged automatically.
