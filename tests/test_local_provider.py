"""The `local` provider: an OpenAI-compatible server on this machine (Ollama), for development without a cloud key.

Code sent to it never leaves the PC, so the code gate (ADR 0002) does not apply; the URL must therefore be loopback.
Stubs only: nothing here contacts a server.
"""

import pytest
from langchain_core.messages import AIMessage

from navigate_helper.code_search import CodeSearchError, require_code_allowed
from navigate_helper.config import MissingConfigError, allowed_models, available_providers, load_config
from navigate_helper.llm import LLMAnswer, LLMChoiceError, LLMSwitch, LocalLLM, OpenAILLM, build_llm
from tests.fakes import FakeLLM

LOCAL = {"LOCAL_LLM_URL": "http://localhost:11434"}


# --- config -----------------------------------------------------------------------------------------


def test_the_local_provider_is_off_until_a_url_is_set():
    config = load_config({})
    assert config.local_llm_url is None and available_providers(config) == ("openai", "anthropic")
    with pytest.raises(LLMChoiceError, match="LOCAL_LLM_URL"):
        allowed_models(config, "local")


def test_with_a_url_it_is_offered_with_its_models_from_env():
    config = load_config(LOCAL)
    assert available_providers(config) == ("openai", "anthropic", "local")
    assert allowed_models(config, "local") == ("llama3.2",)
    many = load_config({**LOCAL, "LOCAL_LLM_MODELS": "llama3.2, gpt-oss ,"})
    assert allowed_models(many, "local") == ("llama3.2", "gpt-oss")


@pytest.mark.parametrize("url, expected", [
    ("http://localhost:11434", "http://localhost:11434/v1"),       # Ollama's OpenAI endpoint lives under /v1
    ("http://localhost:11434/", "http://localhost:11434/v1"),
    ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1"),
    ("http://[::1]:11434", "http://[::1]:11434/v1"),
])
def test_the_url_is_normalised_to_the_openai_endpoint(url, expected):
    assert load_config({"LOCAL_LLM_URL": url}).local_llm_url == expected


@pytest.mark.parametrize("url", ["http://192.168.1.5:11434", "https://api.example.com/v1", "http://ollama.internal:11434", "localhost:11434", "ftp://localhost"])
def test_a_url_that_is_not_on_this_machine_is_refused(url):
    with pytest.raises(MissingConfigError, match="LOCAL_LLM_URL"):
        load_config({"LOCAL_LLM_URL": url})


def test_local_can_be_the_default_provider_and_takes_its_default_model_from_the_local_list():
    config = load_config({**LOCAL, "LLM_PROVIDER": "local", "LOCAL_LLM_MODELS": "gpt-oss,llama3.2"})
    assert (config.llm_provider, config.llm_model) == ("local", "gpt-oss")
    assert load_config({**LOCAL, "LLM_PROVIDER": "local", "LLM_MODEL": "phi3"}).llm_model == "phi3"
    assert allowed_models(load_config({**LOCAL, "LLM_PROVIDER": "local", "LLM_MODEL": "phi3"}), "local")[0] == "phi3"


def test_local_as_the_default_provider_needs_the_url():
    with pytest.raises(MissingConfigError, match="LOCAL_LLM_URL"):
        load_config({"LLM_PROVIDER": "local"})


def test_the_local_provider_needs_no_api_key():
    config = load_config({**LOCAL, "LLM_PROVIDER": "local"})
    assert config.require_api_key()  # a placeholder: the client library insists on a non-empty key


# --- the adapter ------------------------------------------------------------------------------------


def local_config(**extra):
    return load_config({**LOCAL, "LLM_PROVIDER": "local", "LLM_REASONING_EFFORT": "high", **extra})


def test_build_llm_picks_the_local_adapter_for_the_local_provider():
    llm = build_llm(local_config())
    assert isinstance(llm, LocalLLM) and isinstance(llm, OpenAILLM)
    assert (llm.provider, llm.model) == ("local", "llama3.2")


def test_the_local_adapter_talks_to_the_local_url_without_openai_only_settings():
    chat = build_llm(local_config())._chat
    assert chat.openai_api_base == "http://localhost:11434/v1" and chat.model_name == "llama3.2"
    assert chat.reasoning_effort is None  # not sent: a local model may not know it
    assert chat.max_tokens == 4000


def test_structured_output_is_json_schema_but_not_strict(monkeypatch):
    from langchain_openai import ChatOpenAI

    seen = []
    monkeypatch.setattr(ChatOpenAI, "with_structured_output", lambda self, schema, **kwargs: seen.append((schema, kwargs)))
    build_llm(local_config())
    assert seen == [(LLMAnswer, {"method": "json_schema", "include_raw": True})]


def test_the_local_adapter_returns_the_parsed_answer_and_checks_truncation():
    from navigate_helper.llm import LLMError

    llm = build_llm(local_config())
    parsed = LLMAnswer(answer="a", covered=True, cited_chunk_ids=[])

    class Chain:
        def __init__(self, result):
            self.result = result

        def invoke(self, messages):
            return self.result

    ok = {"raw": AIMessage(content="", response_metadata={"finish_reason": "stop"}), "parsed": parsed, "parsing_error": None}
    llm._chain = Chain(ok)
    assert llm.invoke([]) is parsed
    llm._chain = Chain({**ok, "raw": AIMessage(content="", response_metadata={"finish_reason": "length"}), "parsed": None})
    with pytest.raises(LLMError, match="cut off"):
        llm.invoke([])


# --- the code gate ----------------------------------------------------------------------------------


def test_code_may_go_to_the_local_provider_without_approval_but_still_not_to_openai():
    require_code_allowed(FakeLLM(provider="local"), allow_code_to_openai=False)
    require_code_allowed(FakeLLM(provider="anthropic"), allow_code_to_openai=False)
    with pytest.raises(CodeSearchError, match="OpenAI"):
        require_code_allowed(FakeLLM(provider="openai"), allow_code_to_openai=False)


def test_the_switch_builds_a_local_adapter_only_when_it_is_configured():
    built = []
    switch = LLMSwitch(load_config(LOCAL), lambda c: built.append(c) or FakeLLM(provider=c.llm_provider, model=c.llm_model))
    assert switch.get("local", "llama3.2").provider == "local" and built[0].local_llm_url == "http://localhost:11434/v1"
    with pytest.raises(LLMChoiceError):
        LLMSwitch(load_config({}), lambda c: None).get("local", "llama3.2")
    with pytest.raises(LLMChoiceError):
        switch.get("local", "not-in-the-list")


# --- the dropdowns ----------------------------------------------------------------------------------


def test_the_provider_dropdown_offers_local_only_when_it_is_configured(tmp_path):
    import gradio as gr

    from navigate_helper import ui
    from tests.test_ui import FakeAssistant, make_answer

    def providers(env):
        blocks = ui.chat_blocks(FakeAssistant(make_answer()), load_config({"DATA_DIR": str(tmp_path), **env}))
        dropdown = next(b for b in blocks.blocks.values() if isinstance(b, gr.Dropdown) and b.label == "Provider")
        return [choice[0] for choice in dropdown.choices]

    assert providers({}) == ["openai", "anthropic"]
    assert providers(LOCAL) == ["openai", "anthropic", "local"]


def test_choosing_local_offers_its_models_and_selects_the_first():
    from navigate_helper import ui

    config = load_config({**LOCAL, "LOCAL_LLM_MODELS": "gpt-oss,llama3.2"})
    update = ui.models_for(config, "local")
    assert update["choices"] == ["gpt-oss", "llama3.2"] and update["value"] == "gpt-oss"
    assert ui.models_for(config, "anthropic")["value"] == "claude-sonnet-5-5"
