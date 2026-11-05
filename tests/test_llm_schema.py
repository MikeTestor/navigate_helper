"""`invoke(messages, schema)` on both adapters: another structured-output schema, with a stubbed chat model (no network)."""

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from navigate_helper.config import load_config
from navigate_helper.llm import AnthropicLLM, LLMAnswer, LLMError, OpenAILLM


class Other(BaseModel):
    value: str


class StubChain:
    def __init__(self, result):
        self.result = result
        self.invoked = []

    def invoke(self, messages):
        self.invoked.append(messages)
        return self.result


class StubChat:
    """Records `with_structured_output` calls and hands back one prepared chain."""

    def __init__(self, chain):
        self.chain = chain
        self.structured = []

    def with_structured_output(self, schema, **kwargs):
        self.structured.append((schema, kwargs))
        return self.chain


def openai_llm():
    return OpenAILLM(load_config({"OPENAI_API_KEY": "sk-test"}))


def anthropic_llm():
    return AnthropicLLM(load_config({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-test"}))


def parsed(**metadata):
    return {"raw": AIMessage(content="", response_metadata=metadata), "parsed": Other(value="x"), "parsing_error": None}


@pytest.mark.parametrize("build, metadata, kwargs", [
    (openai_llm, {"finish_reason": "stop"}, {"method": "json_schema", "strict": True, "include_raw": True}),
    (anthropic_llm, {"stop_reason": "end_turn"}, {"method": "json_schema", "include_raw": True}),
])
def test_invoke_with_another_schema_builds_that_chain_once_and_returns_the_parsed_value(build, metadata, kwargs):
    llm = build()
    chain = StubChain(parsed(**metadata))
    llm._chat = StubChat(chain)
    assert llm.invoke(["a"], Other) == Other(value="x")
    assert llm.invoke(["b"], Other) == Other(value="x")
    assert llm._chat.structured == [(Other, kwargs)]  # built on the first call, cached for the second
    assert chain.invoked == [["a"], ["b"]]


@pytest.mark.parametrize("build, metadata", [
    (openai_llm, {"finish_reason": "stop"}),
    (anthropic_llm, {"stop_reason": "end_turn"}),
])
def test_invoke_without_a_schema_still_uses_the_default_llm_answer_chain(build, metadata):
    llm = build()
    default = StubChain({**parsed(**metadata), "parsed": LLMAnswer(answer="a", covered=True, cited_chunk_ids=[])})
    llm._chain = default
    llm._chat = StubChat(StubChain(None))
    assert llm.invoke(["q"]).answer == "a"
    assert default.invoked == [["q"]] and llm._chat.structured == []


@pytest.mark.parametrize("build, raw", [
    (openai_llm, {"finish_reason": "length"}),
    (anthropic_llm, {"stop_reason": "max_tokens"}),
])
def test_another_schema_is_checked_for_truncation_like_the_default(build, raw):
    llm = build()
    result = {"raw": AIMessage(content="", response_metadata=raw), "parsed": None, "parsing_error": None}
    llm._chat = StubChat(StubChain(result))
    with pytest.raises(LLMError, match="cut off"):
        llm.invoke([], Other)
