# The Claude Code CLI is a provider for the Code Search, switchable with the API providers

Status: accepted (design session 2026-11-06; build issues to follow). Builds on ADR 0001 and ADR 0002. Needs the Code Tool Server of ADR 0004 (designed in the branch `docs/mcp-code-tools-design`, not yet on `main`).

The operator has a Claude Code subscription through the company but no Anthropic API key, so the Code Search cannot run on the `anthropic` provider. Claude Code can be started headless (`claude -p`) under the operator's own login, which is what the Claude plugin for VS Code and Claudian (Obsidian) do. This ADR adds that as a provider, and keeps the API path one switch away.

## Decisions

- **A fourth provider, `claude-code`**, next to `openai`, `anthropic` and `local`. It is chosen in the same GUI dropdown as the others and goes through the same `LLMSwitch` and allowlist (ADR 0002). Its models are the Claude models the CLI accepts, listed in `PROVIDER_MODELS`.
- **Opt-in with `CLAUDE_CODE=true` in `.env`**, and only when the `claude` binary is found. Without the flag the provider is not offered, the same way `local` needs `LOCAL_LLM_URL`.
- **Switching is one setting, never a code change.** In the GUI: pick `anthropic` instead of `claude-code` in the Provider dropdown. At startup: `LLM_PROVIDER`. The `anthropic` provider is the way to run the app for colleagues.
- **The seam is the Code Search, not the LLM.** Claude Code runs its own agent loop, so it cannot be driven one `chat()` turn at a time. A Code Search is anything with `run(question, manual_answer, manual_pages, cancelled, on_event) -> CodeSearchResult`. `CodeSearch` (our loop, for the API providers and `local`) and a new `ClaudeCodeSearch` (one `claude -p` subprocess per question) both are one. `CodeChecker.check` picks the one that belongs to the chosen LLM. Everything after the search stays as it is: `CodeAnswerWriter`, citation validation against the Code Checkout, the unverified label, partial answers, the ask log, the GUI.
- **Structuring uses the same provider.** `ClaudeCodeLLM.invoke(messages, schema)` runs `claude -p --json-schema <schema> --tools ""`, so `CodeAnswerWriter` and the Manual path need no change. Whether the first run can return the structured answer itself, saving a second process start, is for the spike to find out.
- **Claude Code only gets our tools.** The subprocess is started with the built-in tools off (`--tools ""`), `--strict-mcp-config` with a generated `--mcp-config` that lists only the Code Tool Server (`navigate-code-mcp <root>`), only that server's tools allowed, no permission prompts possible, `--setting-sources ""` and `--no-session-persistence`, our `CODE_SEARCH_PROMPT` added with `--append-system-prompt`, and an empty temporary folder as working directory so no `CLAUDE.md` from the code is picked up. `--bare` is not used: it skips the keychain, which probably breaks the subscription login. The built-in `Read`/`Grep` are not an option: they ignore the excluded folders (`data`, `projects`, ...), the extension allowlist and the read and match caps of ADR 0004. The exact flags are confirmed in the spike.
- **The Code Answer contract is kept.** From the stream-json events the code builds the same `ToolCallRecord`s and `ProgressEvent`s. "No conclusion without a successful tool call" is checked on the tool results. The limits map to the same statuses: the tool-call cap and the timeout by killing the process, `cancelled` the same way, and the token limit from the usage the CLI reports (coarser than our own loop). A stopped run is still a partial result.
- **The code gate.** `claude-code` counts as an Anthropic route and may see code. The operator states that using their company Claude Code seat on the company code is approved (they already use the Claude plugin for VS Code on it); this extends the approval in ADR 0002, which named the API key. If Aryza policy asks for it in writing, that is the operator's to arrange.
- **For the operator's own use only.** The provider runs under the logged-in user's own subscription. It is not for a deployment shared with colleagues; for them `CLAUDE_CODE` stays unset and the `anthropic` provider with the API key is used.
- **Tests use a fake runner.** The subprocess call sits behind a small function that yields stream-json lines; tests give it recorded lines from `tmp_path` or in-memory fixtures. No test starts `claude`, and none calls Anthropic (working rules). Windows: `claude.exe` is started without a shell, the prompt goes in on stdin.
- **A spike comes first.** One real `claude -p` call, after asking, to record the true stream-json event shapes, the flags that work, and the startup time. If anything differs from this ADR, amend it.
- **Acceptance is a comparison, not a hope.** The same questions from `docs/code-eval-seed.md` go through the Claude plugin for VS Code and through this provider (and, where possible, the `anthropic` provider), and the answers and citations are compared by hand. If this provider is clearly worse, first loosen the caps for this provider; do not switch to the built-in tools.

## Considered options

- **An adapter with `chat()` like the others.** Not possible: the Claude Code loop cannot be driven per turn.
- **The Claude Agent SDK instead of the CLI.** It wraps the same binary and adds a dependency; a plain subprocess is enough to start with. The SDK can replace the subprocess code later without changing anything above the runner.
- **Built-in Claude Code tools with deny rules.** Weaker than the Code Tool Server: the model could reach folders and files we exclude today.

## Consequences

- Each question starts one (or two) `claude` processes and loads Claude Code's own system prompt: some seconds of overhead the API path does not have. Not yet measured.
- Quality may differ from the VS Code plugin because the model works with our `grep`/`list`/`read` and their caps instead of the built-in tools. The comparison above decides whether that matters.
- The Code Tool Server (ADR 0004) becomes a prerequisite for this provider.
- `config.py` gets a fourth provider and a rule for when it is available; `llm.py` gets `ClaudeCodeLLM`; `code_search.py` gets `ClaudeCodeSearch` and the shared `CodeSearch` protocol; `code_check.py` gets the choice between them. The GUI needs no new control.
