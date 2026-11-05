# Two LLM providers with a GUI switch

Status: accepted (issue #44). Supersedes "OpenAI is the only provider" in `docs/design-decisions.md`.

Both Anthropic and OpenAI are supported for both Manual Answers and Code Answers. The Asker chooses provider and model in the app from a fixed allowlist per provider; defaults come from `LLM_PROVIDER` and `LLM_MODEL`. API keys stay in `.env`. The Anthropic key is what Aryza is approving for code; OpenAI has only been approved for development data without client data.

## Consequences

- The Code Search refuses OpenAI unless `ALLOW_CODE_TO_OPENAI=true` is set. That flag is the explicit decision point if OpenAI is ever approved for code.
- An `LLM` interface with one implementation per provider supports structured output (Manual path) and tool calling (Code path). Each Answer and log line records provider and model.
- Embeddings stay local (`multilingual-e5-base`); only the answering model changes.
- The `gpt-5-mini` removal deadline of 2026-12-11 is handled in the issue that adds the Anthropic provider.
- The data policy from `docs/design-decisions.md` still applies: re-evaluate before go-live. Questions may contain client data, so `database/ask_log.jsonl` stays gitignored.
- Working rule: ask before any real call to either provider.

## Amendment: a local provider for development

A third provider, `local`, is an OpenAI-compatible server on the same machine (Ollama). It exists so the whole Code path, including real tool calling, can be tried without a cloud key and without code leaving the PC. It is offered only when `LOCAL_LLM_URL` is set, its models come from `LOCAL_LLM_MODELS`, and the URL must be loopback (`localhost`, `127.0.0.1`, `::1`), which `load_config` enforces. Because that is what makes it safe, the `ALLOW_CODE_TO_OPENAI` gate does not apply to it, and it must never be pointed at another host. Small local models answer poorly; it is for checking the plumbing, not for production Answers.
