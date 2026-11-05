"""The LLM adapters (OpenAI, Anthropic): structured output behind `invoke(messages)`, plus `provider` and `model`.

`Assistant` in `ask` takes any object with those, so it holds no provider code.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from navigate_helper.config import MAX_COMPLETION_TOKENS, Config


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
    return AnthropicLLM(config) if config.llm_provider == "anthropic" else OpenAILLM(config)
