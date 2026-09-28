# Structured output from gpt-5-mini through Langchain (research, 2026-09-28)

Answers issue #6 and feeds open question E20 in [open-questions.md](../open-questions.md). The question is how to get `{answer: str, covered: bool, cited_chunk_ids: list[str]}` reliably from `gpt-5-mini` through Langchain. This note gives facts and options only; it makes no decisions.

**Versions checked:** `langchain-openai` 1.6.6 (released 2026-09-24; the project pins `>=1.6.2`), `openai` Python SDK 3.19.2 (the project pins `>=3.14.1`). The OpenAI docs now live at `developers.openai.com/api/docs/...` (old `platform.openai.com/docs` links redirect there). All docs were read on 2026-09-28.

## 1. gpt-5-mini will be shut down soon

- `gpt-5-mini` has one snapshot, `gpt-5-mini-2025-08-07`. [Model page](https://developers.openai.com/api/docs/models/gpt-5-mini)
- On 2026-06-11 OpenAI announced that **`gpt-5-mini-2025-08-07` and `gpt-5-2025-08-07` will be removed from the API on 2026-12-11**. The recommended replacements are `gpt-5.6-terra` (for mini) and `gpt-5.6-sol` (for gpt-5). [Deprecations](https://developers.openai.com/api/docs/deprecations)
- This means the design choice "gpt-5-mini now, compare against gpt-5 later" has less than 2.5 months left. Because the model is set in `.env`, switching is only a config change, but costs are different (see section 5).

## 2. How Langchain produces structured output (`langchain-openai` 1.6.6 source)

`ChatOpenAI.with_structured_output(schema, *, method="json_schema", include_raw=False, strict=None, tools=None, ...)`. The source is in `langchain_openai/chat_models/base.py`.

- **Default method on `ChatOpenAI` is `"json_schema"`**, which uses OpenAI Structured Outputs (`response_format` / `text.format`). The base class `BaseChatOpenAI` still defaults to `"function_calling"`. The other options are `"function_calling"` and `"json_mode"`.
- **Pydantic v2 class plus `json_schema`**: Langchain passes the class directly to the OpenAI SDK's `.parse()`. The SDK turns it into a strict schema with `to_strict_json_schema` and always sets `"strict": True` (`openai/lib/_parsing/_completions.py`, `type_to_response_format_param`). The parsed result is an instance of the Pydantic class.
- **TypedDict or dict schema**: strict is **off** unless you pass `strict=True`. The docstring says: "If schema is specified via `TypedDict` or JSON schema, `strict` is not enabled by default."
- **Pydantic v1 models** are silently switched to `function_calling`, with a warning.
- **`function_calling`** with `strict=True` also enforces the schema, but through a tool call. OpenAI's guidance is to use `text.format` / `response_format` when you are shaping the model's reply to the user, and function calling when you connect the model to your own tools. [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
- **`include_raw=True`** returns `{"raw": AIMessage, "parsed": ..., "parsing_error": ...}` and catches parsing errors instead of raising them. The raw message keeps the token usage, and the debug panel could use it too.
- **Refusals**: the parser raises `OpenAIRefusalError` when the message has a `refusal` field. With `include_raw=True`, that error ends up in `parsing_error`.
- **Truncation**: on the Chat Completions `.parse()` path, the SDK raises `LengthFinishReasonError` when `finish_reason == "length"` and `ContentFilterFinishReasonError` on a content filter. On the Responses API, look for `status == "incomplete"` with `incomplete_details.reason` equal to `max_output_tokens` or `content_filter`. [Guide, "Handle edge cases"](https://developers.openai.com/api/docs/guides/structured-outputs)

## 3. Reasoning-model caveats (GPT-5 family)

- **Temperature**: `ChatOpenAI.validate_temperature` **silently drops** any `temperature` other than 1 for `gpt-5*` models (except `-chat` models and `reasoning_effort="none"`). There is no error, so a `temperature=0` in config simply does nothing. OpenAI says: "When reasoning effort is not `none`, remove `temperature`, `top_p`, and `top_logprobs`" (plus `logprobs` on Chat Completions). [Model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- **Reasoning effort**: for `gpt-5` the docs list `minimal, low, medium, high`, so there is **no `none`** and therefore no temperature at all. [gpt-5 page](https://developers.openai.com/api/docs/models/gpt-5) The gpt-5-mini page doesn't repeat the list; it is the same August 2025 family. For comparison, `gpt-5.6-terra` supports `none, low, medium (default), high, xhigh, max`, and `gpt-5.4-mini` supports `none (default), low, medium, high, xhigh`.
  - Chat Completions uses `reasoning_effort`; Responses uses `reasoning.effort`. [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
  - In Langchain: `ChatOpenAI(reasoning_effort="low")` stays on Chat Completions; `ChatOpenAI(reasoning={"effort": "low"})` switches to the Responses API automatically.
- **Max tokens**: in Langchain, `max_tokens` is an alias of `max_completion_tokens` and is rewritten to `max_completion_tokens` in the Chat Completions payload ("max_tokens was deprecated ... in September 2024"). Reasoning tokens count against this limit. OpenAI recommends "reserving at least 25,000 tokens for reasoning and outputs when you start experimenting". A limit that is too low gives an incomplete response, sometimes before any visible output. [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
- **`use_responses_api`**: the default is `None`, which means automatic. Langchain uses the Responses API when `reasoning`, `include`, `truncation`, `context_management`, `use_previous_response_id` or `output_version="responses/v1"` is set, when built-in tools are used, or for Responses-only models (`gpt-5-pro`, `gpt-5.6-sol`, `*codex*`, and `gpt-6*` with tools). Otherwise `gpt-5-mini` goes to **Chat Completions**. gpt-5-mini supports both endpoints. [Model page](https://developers.openai.com/api/docs/models/gpt-5-mini) OpenAI says "you'll get improved model intelligence and performance by using Responses". [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) Structured Outputs works on both.
- **Verbosity**: Langchain can pass a `verbosity` setting (Responses `text.verbosity`).

## 4. Can `cited_chunk_ids` be limited to the retrieved IDs?

Yes, with strict Structured Outputs. [Guide, "Supported schemas"](https://developers.openai.com/api/docs/guides/structured-outputs)

- `enum` is supported, and arrays support `minItems` and `maxItems`. Strings support `pattern` and `format`. Numbers support `minimum` and `maximum`.
- Limits: up to 1,000 enum values per schema, up to 5,000 object properties, up to 10 levels of nesting, and at most 120,000 characters across all property names, enum values and similar. Six chunk IDs are far below these limits.
- Strict mode rules: every field must be `required`, `additionalProperties: false` is mandatory, and the root must be an object (not `anyOf`). Composition keywords such as `allOf`, `not` and `if/then/else` are not supported.
- **Latency catch**: "the first request you make with any schema will have additional latency as our API processes the schema, but subsequent requests with the same schema will not." A **per-question enum of the 6 retrieved IDs makes every request a new schema**, so every question pays that first-request cost. The size of the cost isn't published.
- There are three ways to build this:
  - (a) a dynamic schema per request, `items: {type: string, enum: [<retrieved ids>]}`, for example a Pydantic `create_model` with a `Literal[...]` built at runtime;
  - (b) a **fixed** schema that cites by position, for example `items: {type: integer, minimum: 1, maximum: 6}`, or a fixed enum such as `["C1".."C6"]`, which the code maps back to `chunk_id`s. The schema stays the same, so it is cached;
  - (c) a plain `list[str]` plus the post-filter already planned in E20 ("cited IDs that weren't retrieved are dropped").

  Options (a) and (b) make invalid IDs impossible at decoding time. Option (c) catches them afterwards.

## 5. Price and latency

Standard prices per 1M tokens, from the model pages (2026-09-28):

| Model | Input | Cached input | Output | Context | Status |
| --- | ---: | ---: | ---: | --- | --- |
| `gpt-5-mini` | $0.25 | $0.025 | $2 | 400k (272k input) | shutdown 2026-12-11 |
| `gpt-5` | $1.25 | $0.125 | $10 | 400k | shutdown 2026-12-11 |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 | 400k | current |
| `gpt-5.6-terra` (replaces mini) | $2 | $0.20 | $12 | 1.05M | current |

- gpt-5 costs **5×** gpt-5-mini for both input and output.
- **Latency**: the docs describe it only in words. gpt-5-mini is "a faster, more cost-efficient version of GPT-5" for "low latency, high volume workloads", and the gpt-5 page gives no latency figure. No published numbers; measure it. Reasoning effort is the main lever: "Lower effort favors speed and lower token usage." [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
- Rough estimate, not measured: one question is about 6 Chunks × ~400 tokens plus the prompt, so ~3–4k input tokens, and ~0.5–2k output tokens including reasoning. That is about $0.002–0.005 per question on gpt-5-mini and about 5× that on gpt-5.
- Rate limits for gpt-5-mini at Tier 1: 500 RPM, 500k TPM.

## Implications for the ask()/Answer contract

- Recommendation E20 option 1 (structured JSON) works with what the project already depends on. A Pydantic v2 `LlmAnswer(answer: str, covered: bool, cited_chunk_ids: list[str])` passed to `with_structured_output(LlmAnswer)` is strict by default on `ChatOpenAI`. This model is internal and separate from the richer `Answer` that `ask()` returns (E19).
- Ways to guarantee valid IDs: a dynamic enum (sure, but it pays the new-schema latency on every call), positional citation with a fixed schema (sure and cached, but needs a mapping step), or the post-filter (simplest, and needed anyway as a backstop).
- `ask()` needs defined behaviour for three non-happy outcomes: a refusal (`OpenAIRefusalError`), truncation (`LengthFinishReasonError`, or an `incomplete` status), and a parsing error. `include_raw=True` puts all three in one place and keeps the token usage for the debug panel.
- Config (`.env`) probably needs `LLM_MODEL` and `LLM_REASONING_EFFORT`, plus a generous max-tokens value. Don't expose `temperature`, because Langchain silently ignores it for gpt-5.
- The model choice has a deadline. `gpt-5-mini` and `gpt-5` stop working on 2026-12-11. The listed successor `gpt-5.6-terra` is ~8× the input price and 6× the output price of gpt-5-mini; `gpt-5.4-mini` is a cheaper current option at 3×/2.25×. Newer models accept `reasoning_effort="none"`, which makes `temperature` available again.
- `use_responses_api` can be left on auto (Chat Completions for gpt-5-mini), or set to `True` explicitly for OpenAI's recommended endpoint. The `Answer` contract is the same either way.
