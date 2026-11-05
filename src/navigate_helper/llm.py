"""The LLM adapters (OpenAI, Anthropic): structured output behind `invoke(messages, schema)`, plus `provider` and `model`.

`Assistant` in `ask` takes any object with those, so it holds no provider code. `schema` defaults to `LLMAnswer`
(the Manual path); the Code Answer path passes its own.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, Field

from navigate_helper.config import MAX_COMPLETION_TOKENS, Config, LLMChoiceError, allowed_models


class LLMAnswer(BaseModel):
    """The fixed structured-output schema."""

    answer: str = Field(description="Het antwoord in het Nederlands (Markdown), zonder verwijzingen naar chunk_ids.")
    covered: bool = Field(description="False als de context de vraag niet beantwoordt.")
    cited_chunk_ids: list[str] = Field(description="De chunk_ids die voor het antwoord zijn gebruikt.")


class LLMError(RuntimeError):
    """The LLM refused, was cut off, or returned nothing usable."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ChatTurn:
    """One model turn of a tool-calling conversation.

    `message` is the provider message, appended back to the conversation as is. No `tool_calls` means the
    turn is final and `text` is the model's last word.
    """

    message: Any
    text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: int
    output_tokens: int


def _chat_turn(message) -> ChatTurn:
    usage = message.usage_metadata or {}
    return ChatTurn(
        message=message,
        text=str(message.text),
        tool_calls=tuple(ToolCall(call["id"], call["name"], call["args"]) for call in message.tool_calls),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )


def _chain_for(llm, schema):
    """The structured-output chain for `schema`; `LLMAnswer` is built up front, any other schema once on first use."""
    if schema is LLMAnswer:
        return llm._chain
    if schema not in llm._other_chains:
        llm._other_chains[schema] = llm._structured(schema)
    return llm._other_chains[schema]


class OpenAILLM:
    """`ChatOpenAI` with strict structured output; `invoke(messages)` returns an `LLMAnswer` or raises."""

    provider = "openai"

    def __init__(self, config: Config):
        self.model = config.llm_model
        self._chat = self._client(config)
        self._chain = self._structured(LLMAnswer)
        self._other_chains: dict[type[BaseModel], Any] = {}

    @staticmethod
    def _client(config: Config):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.llm_model,
            api_key=config.require_api_key(),
            reasoning_effort=config.llm_reasoning_effort,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )

    def _structured(self, schema):
        return self._chat.with_structured_output(schema, method="json_schema", strict=True, include_raw=True)

    def invoke(self, messages, schema: type[BaseModel] = LLMAnswer):
        """The model's reply parsed into `schema` (default `LLMAnswer`), or an `LLMError`."""
        result = _chain_for(self, schema).invoke(messages)
        raw = result.get("raw")
        if raw is not None:
            self._check(raw)
        if result.get("parsed") is None:
            raise LLMError(f"unparseable model output: {result.get('parsing_error')}")
        return result["parsed"]

    def chat(self, messages, tools) -> ChatTurn:
        """One turn of a tool-calling conversation; `tools` are OpenAI-style function definitions."""
        message = self._chat.bind_tools(tools).invoke(messages)
        self._check(message)
        return _chat_turn(message)

    @staticmethod
    def _check(raw) -> None:
        if raw.additional_kwargs.get("refusal"):
            raise LLMError(f"the model refused: {raw.additional_kwargs['refusal']}")
        if (getattr(raw, "response_metadata", None) or {}).get("finish_reason") == "length":
            raise LLMError(f"the answer was cut off at {MAX_COMPLETION_TOKENS} completion tokens")


class LocalLLM(OpenAILLM):
    """An OpenAI-compatible server on this machine (Ollama), for development without a cloud key.

    The same client as `OpenAILLM`, pointed at `config.local_llm_url` (always loopback, see `load_config`). Nothing
    OpenAI-specific is sent: no reasoning effort, and JSON-schema output that is not `strict`. Code sent here never
    leaves the PC, so the code gate does not apply to this provider.
    """

    provider = "local"

    @staticmethod
    def _client(config: Config):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.llm_model,
            base_url=config.local_llm_url,
            api_key=config.require_api_key(),
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )

    def _structured(self, schema):
        return self._chat.with_structured_output(schema, method="json_schema", include_raw=True)


class AnthropicLLM:
    """`ChatAnthropic` with JSON-schema structured output; same `invoke(messages)` as `OpenAILLM`."""

    provider = "anthropic"

    def __init__(self, config: Config):
        from langchain_anthropic import ChatAnthropic

        self.model = config.llm_model
        chat = ChatAnthropic(model=config.llm_model, api_key=config.require_api_key(), max_tokens=MAX_COMPLETION_TOKENS)
        self._chat = chat
        self._chain = self._structured(LLMAnswer)
        self._other_chains: dict[type[BaseModel], Any] = {}

    def _structured(self, schema):
        # json_schema, not the default forced tool call: newer Claude models do not support forced tool calls.
        return self._chat.with_structured_output(schema, method="json_schema", include_raw=True)

    def invoke(self, messages, schema: type[BaseModel] = LLMAnswer):
        """The model's reply parsed into `schema` (default `LLMAnswer`), or an `LLMError`."""
        result = _chain_for(self, schema).invoke(messages)
        self._check(result.get("raw"))
        if result.get("parsed") is None:
            raise LLMError(f"unparseable model output: {result.get('parsing_error')}")
        return result["parsed"]

    def chat(self, messages, tools) -> ChatTurn:
        """One turn of a tool-calling conversation; `tools` are OpenAI-style function definitions."""
        message = self._chat.bind_tools(tools).invoke(messages)
        self._check(message)
        return _chat_turn(message)

    @staticmethod
    def _check(raw) -> None:
        stop_reason = (getattr(raw, "response_metadata", None) or {}).get("stop_reason")
        if stop_reason == "refusal":
            raise LLMError("the model refused to answer")
        if stop_reason == "max_tokens":
            raise LLMError(f"the answer was cut off at {MAX_COMPLETION_TOKENS} completion tokens")


def build_llm(config: Config):
    """The adapter for `config.llm_provider`. Raises `MissingConfigError` without that provider's API key."""
    adapters = {"anthropic": AnthropicLLM, "local": LocalLLM}
    return adapters.get(config.llm_provider, OpenAILLM)(config)


class LLMSwitch:
    """The adapter for a provider and model chosen in the GUI, built on first use and kept.

    Only choices on the allowlist (`allowed_models`) are built, so the dropdown values are never trusted. A choice that
    cannot be built (no API key for that provider) raises and is not kept. `seed` is the adapter the app started with.
    """

    def __init__(self, config: Config, factory: Callable[[Config], object] = build_llm, seed=None):
        self._config = config
        self._factory = factory
        self._llms = {} if seed is None else {(seed.provider, seed.model): seed}

    def get(self, provider: str, model: str):
        if model not in allowed_models(self._config, provider):
            raise LLMChoiceError(f"model {model!r} is not on the allowlist for {provider}")
        if (provider, model) not in self._llms:
            self._llms[(provider, model)] = self._factory(replace(self._config, llm_provider=provider, llm_model=model))
        return self._llms[(provider, model)]
