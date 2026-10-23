"""The OpenAI adapter: `ChatOpenAI` with strict structured output, behind `invoke(messages)`.

`Assistant` in `ask` takes any object with that method, so it holds no provider code.
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

    def __init__(self, config: Config):
        from langchain_openai import ChatOpenAI

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
