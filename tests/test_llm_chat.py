"""`chat(messages, tools)` on both adapters, with a stubbed chat model (no network)."""

import pytest
from langchain_core.messages import AIMessage

from navigate_helper.config import load_config
from navigate_helper.llm import AnthropicLLM, ChatTurn, LLMError, OpenAILLM, ToolCall

TOOLS = [{"type": "function", "function": {"name": "grep", "description": "d", "parameters": {"type": "object"}}}]


class StubChat:
    def __init__(self, message):
        self.message = message
        self.bound = []
        self.invoked = []

    def bind_tools(self, tools):
        self.bound.append(tools)
        return self

    def invoke(self, messages):
        self.invoked.append(messages)
        return self.message


def openai_llm(message):
    llm = OpenAILLM(load_config({"OPENAI_API_KEY": "sk-test"}))
    llm._chat = StubChat(message)
    return llm


def anthropic_llm(message):
    llm = AnthropicLLM(load_config({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-test"}))
    llm._chat = StubChat(message)
    return llm


def reply(text="", tool_calls=(), usage=None, **metadata):
    return AIMessage(content=text, tool_calls=list(tool_calls), usage_metadata=usage, response_metadata=metadata)


CALL = {"id": "t1", "name": "grep", "args": {"pattern": "Invoice"}}
USAGE = {"input_tokens": 1200, "output_tokens": 80, "total_tokens": 1280}


@pytest.mark.parametrize("build, metadata", [(openai_llm, {"finish_reason": "tool_calls"}),
                                             (anthropic_llm, {"stop_reason": "tool_use"})])
def test_chat_returns_tool_calls_text_and_token_counts(build, metadata):
    message = reply("Ik zoek.", [CALL], USAGE, **metadata)
    llm = build(message)
    turn = llm.chat(["vraag"], TOOLS)
    assert turn == ChatTurn(message=message, text="Ik zoek.", tool_calls=(ToolCall("t1", "grep", {"pattern": "Invoice"}),),
                            input_tokens=1200, output_tokens=80)
    assert llm._chat.bound == [TOOLS] and llm._chat.invoked == [["vraag"]]


@pytest.mark.parametrize("build, metadata", [(openai_llm, {"finish_reason": "stop"}),
                                             (anthropic_llm, {"stop_reason": "end_turn"})])
def test_chat_without_tool_calls_is_a_final_turn_and_missing_usage_counts_zero(build, metadata):
    turn = build(reply("Klaar.", **metadata)).chat([], TOOLS)
    assert turn.text == "Klaar." and turn.tool_calls == () and (turn.input_tokens, turn.output_tokens) == (0, 0)


@pytest.mark.parametrize("build, metadata, message", [
    (openai_llm, {"finish_reason": "length"}, "cut off"),
    (anthropic_llm, {"stop_reason": "max_tokens"}, "cut off"),
    (anthropic_llm, {"stop_reason": "refusal"}, "refused"),
])
def test_chat_raises_llm_error_when_cut_off_or_refused(build, metadata, message):
    with pytest.raises(LLMError, match=message):
        build(reply("", **metadata)).chat([], TOOLS)


def test_chat_raises_llm_error_when_openai_refuses():
    message = AIMessage(content="", additional_kwargs={"refusal": "nee"}, response_metadata={"finish_reason": "stop"})
    with pytest.raises(LLMError, match="refused"):
        openai_llm(message).chat([], TOOLS)
