"""Minimal chat-completion wrapper over whichever provider is configured.

Uses each provider's native SDK directly (rather than langchain chat
models) since only langchain-openai is in requirements.txt.
"""

from collections.abc import Callable

from core.config import Config

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5",
    "google": "gemini-2.5-flash",
    "ollama": "llama3.2",
}


def get_chat_fn(config: Config) -> Callable[[str, str], str]:
    """Return a `chat(system, user) -> str` function for the configured provider."""
    provider = config.llm_provider
    if provider == "anthropic":
        return _anthropic_chat(config)
    if provider == "openai":
        return _openai_chat(config)
    if provider == "google":
        return _google_chat(config)
    if provider == "ollama":
        return _ollama_chat(config)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")


def _anthropic_chat(config: Config) -> Callable[[str, str], str]:
    import anthropic

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def chat(system: str, user: str) -> str:
        response = client.messages.create(
            model=DEFAULT_MODELS["anthropic"],
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    return chat


def _openai_chat(config: Config) -> Callable[[str, str], str]:
    from openai import OpenAI

    client = OpenAI(api_key=config.openai_api_key)

    def chat(system: str, user: str) -> str:
        response = client.chat.completions.create(
            model=DEFAULT_MODELS["openai"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    return chat


def _google_chat(config: Config) -> Callable[[str, str], str]:
    import google.generativeai as genai

    genai.configure(api_key=config.google_api_key)
    model = genai.GenerativeModel(
        DEFAULT_MODELS["google"], system_instruction=None
    )

    def chat(system: str, user: str) -> str:
        model_with_system = genai.GenerativeModel(
            DEFAULT_MODELS["google"], system_instruction=system
        )
        response = model_with_system.generate_content(user)
        return response.text

    return chat


def _ollama_chat(config: Config) -> Callable[[str, str], str]:
    import ollama

    client = ollama.Client(host=config.ollama_host)

    def chat(system: str, user: str) -> str:
        response = client.chat(
            model=DEFAULT_MODELS["ollama"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response["message"]["content"]

    return chat
