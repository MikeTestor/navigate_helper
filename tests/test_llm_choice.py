"""The provider and model choice: the fixed allowlist in config and the `LLMSwitch` that builds one adapter per choice."""

import pytest

from navigate_helper.config import PROVIDER_MODELS, MissingConfigError, allowed_models, load_config
from navigate_helper.llm import LLMChoiceError, LLMSwitch
from tests.fakes import FakeLLM

OPENAI = {"OPENAI_API_KEY": "sk-test"}


# --- the allowlist ---------------------------------------------------------------------------------


def test_the_allowlist_is_fixed_per_provider_and_starts_with_the_default_model():
    assert PROVIDER_MODELS == {
        "openai": ("gpt-5.4-mini", "gpt-5.6-terra"),
        "anthropic": ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"),
    }
    config = load_config({})
    assert allowed_models(config, "openai") == ("gpt-5.4-mini", "gpt-5.6-terra")
    assert allowed_models(config, "anthropic")[0] == "claude-sonnet-5-5"


def test_a_model_set_in_env_for_the_default_provider_is_allowed_and_listed_first():
    config = load_config({"LLM_MODEL": "gpt-next"})
    assert allowed_models(config, "openai") == ("gpt-next", "gpt-5.4-mini", "gpt-5.6-terra")
    assert allowed_models(config, "anthropic") == PROVIDER_MODELS["anthropic"]  # only the default provider gains it


def test_an_unknown_provider_has_no_models():
    with pytest.raises(LLMChoiceError, match="provider"):
        allowed_models(load_config({}), "mistral")


# --- the switch ------------------------------------------------------------------------------------


class Factory:
    """Stands in for `build_llm`: records the Config it was given and returns a fresh fake of that provider/model."""

    def __init__(self, error=None):
        self.configs, self.error = [], error

    def __call__(self, config):
        self.configs.append(config)
        if self.error:
            raise self.error
        return FakeLLM(provider=config.llm_provider, model=config.llm_model)


def test_the_default_choice_is_the_llm_the_app_was_started_with():
    seed, factory = FakeLLM(provider="openai", model="gpt-5.4-mini"), Factory()
    switch = LLMSwitch(load_config(OPENAI), factory, seed=seed)
    assert switch.get("openai", "gpt-5.4-mini") is seed and factory.configs == []


def test_another_choice_builds_an_adapter_for_that_provider_and_model_once():
    factory = Factory()
    config = load_config({**OPENAI, "ANTHROPIC_API_KEY": "sk-ant-test", "LLM_REASONING_EFFORT": "high"})
    switch = LLMSwitch(config, factory)
    llm = switch.get("anthropic", "claude-haiku-5-5")
    assert (llm.provider, llm.model) == ("anthropic", "claude-haiku-5-5")
    assert switch.get("anthropic", "claude-haiku-5-5") is llm and len(factory.configs) == 1
    built = factory.configs[0]
    assert (built.llm_provider, built.llm_model) == ("anthropic", "claude-haiku-5-5")
    assert built.anthropic_api_key == "sk-ant-test" and built.llm_reasoning_effort == "high"  # the rest is kept


@pytest.mark.parametrize("provider, model", [
    ("anthropic", "gpt-5.4-mini"),     # a real model of the other provider
    ("openai", "gpt-4-free-text"),   # not on the allowlist
    ("mistral", "large"),            # unknown provider
    ("openai", ""),
])
def test_a_choice_outside_the_allowlist_is_refused_before_anything_is_built(provider, model):
    factory = Factory()
    with pytest.raises(LLMChoiceError):
        LLMSwitch(load_config(OPENAI), factory).get(provider, model)
    assert factory.configs == []


def test_a_provider_without_an_api_key_fails_with_the_config_error_and_is_not_cached():
    factory = Factory(error=MissingConfigError("ANTHROPIC_API_KEY is not set (put it in .env)."))
    switch = LLMSwitch(load_config(OPENAI), factory)
    for _ in range(2):
        with pytest.raises(MissingConfigError, match="ANTHROPIC_API_KEY"):
            switch.get("anthropic", "claude-sonnet-5-5")
    assert len(factory.configs) == 2  # a failure is never cached
