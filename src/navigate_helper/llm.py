"""The LLM adapters (OpenAI, Anthropic): structured output behind `invoke(messages)`, plus `provider` and `model`.

`Assistant` in `ask` takes any object with those, so it holds no provider code.
"""

from pydantic import BaseModel, Field

from navigate_helper.config import MAX_COMPLETION_TOKENS, Config


class LLMAnswer(BaseModel):
    """The fixed structured-output schema."""

    answer: str = Field(description="Het antwoord in het Nederlands (Markdown), zonder verwijzingen naar chunk_ids.")
    covered: bool = Field(description="False als de context de vraag niet beantwoordt.")
    cited_chunk_ids: list[str] = Field(description="De chunk_ids die voor het antwoord zijn gebruikt.")


class LLMError(RuntimeError):
    """The LLM refused, was cut off, or returned nothing usable."""


class OpenAILLM:
    """`ChatOpenAI` with strict structured output; `invoke(messages)` returns an `LLMAnswer` or raises."""

    provider = "openai"

    def __init__(self, config: Config):
        from langchain_openai import ChatOpenAI

        self.model = config.llm_model
        chat = ChatOpenAI(
            model=config.llm_model,
            api_key=config.require_api_key(),
            reasoning_effort=config.llm_reasoning_effort,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )
        self._chat = chat
        self._chain = chat.with_structured_output(LLMAnswer, method="json_schema", strict=True, include_raw=True)

    def invoke(self, messages) -> LLMAnswer:
        result = self._chain.invoke(messages)
        raw = result.get("raw")
        if raw is not None:
            if raw.additional_kwargs.get("refusal"):
                raise LLMError(f"the model refused: {raw.additional_kwargs['refusal']}")
            if (getattr(raw, "response_metadata", None) or {}).get("finish_reason") == "length":
                raise LLMError(f"the answer was cut off at {MAX_COMPLETION_TOKENS} completion tokens")
        if result.get("parsed") is None:
            raise LLMError(f"unparseable model output: {result.get('parsing_error')}")
        return result["parsed"]


class AnthropicLLM:
    """`ChatAnthropic` with JSON-schema structured output; same `invoke(messages)` as `OpenAILLM`."""

    provider = "anthropic"

    def __init__(self, config: Config):
        from langchain_anthropic import ChatAnthropic

        self.model = config.llm_model
        chat = ChatAnthropic(model=config.llm_model, api_key=config.require_api_key(), max_tokens=MAX_COMPLETION_TOKENS)
        self._chat = chat
        # json_schema, not the default forced tool call: newer Claude models do not support forced tool calls.
        self._chain = chat.with_structured_output(LLMAnswer, method="json_schema", include_raw=True)

    def invoke(self, messages) -> LLMAnswer:
        result = self._chain.invoke(messages)
        raw = result.get("raw")
        stop_reason = (getattr(raw, "response_metadata", None) or {}).get("stop_reason")
        if stop_reason == "refusal":
            raise LLMError("the model refused to answer")
        if stop_reason == "max_tokens":
            raise LLMError(f"the answer was cut off at {MAX_COMPLETION_TOKENS} completion tokens")
        if result.get("parsed") is None:
            raise LLMError(f"unparseable model output: {result.get('parsing_error')}")
        return result["parsed"]


def build_llm(config: Config):
    """The adapter for `config.llm_provider`. Raises `MissingConfigError` without that provider's API key."""
    return AnthropicLLM(config) if config.llm_provider == "anthropic" else OpenAILLM(config)
