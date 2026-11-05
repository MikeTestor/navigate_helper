"""Configuration: env keys from the environment / .env, plus fixed constants."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Fixed constants (not env-configurable).
CHUNK_TOKEN_CAP = 400
CHUNK_TOKEN_CEILING = 512
SHORT_SECTION_CHARS = 200
COLLECTION_NAME = "navigate_manual"
MAX_COMPLETION_TOKENS = 4000
CODE_SEARCH_MAX_TOOL_CALLS = 40
CODE_SEARCH_MAX_INPUT_TOKENS = 300_000
CODE_SEARCH_MAX_SECONDS = 600

PROVIDERS = ("openai", "anthropic")
DEFAULT_LLM_PROVIDER = "openai"
# The models the GUI dropdown offers per provider: a fixed allowlist, never free text (ADR 0002). The first is the default.
PROVIDER_MODELS = {
    "openai": ("gpt-5.4-mini",),
    "anthropic": ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"),
}
DEFAULT_LLM_MODELS = {provider: models[0] for provider, models in PROVIDER_MODELS.items()}
API_KEY_NAMES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_RETRIEVAL_K = 6
DEFAULT_DATA_DIR = "database"


class MissingConfigError(RuntimeError):
    """A required configuration value is not set."""


class LLMChoiceError(ValueError):
    """A provider or model that is not on the allowlist."""


class StageError(RuntimeError):
    """A pipeline stage cannot run or finished with failures."""


@dataclass(frozen=True)
class Config:
    openai_api_key: str | None
    llm_model: str
    llm_reasoning_effort: str
    embedding_model: str
    retrieval_k: int
    data_dir: Path
    code_dir: Path | None = None
    llm_provider: str = DEFAULT_LLM_PROVIDER
    anthropic_api_key: str | None = None
    allow_code_to_openai: bool = False

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "knowledge-base" / "raw"

    @property
    def htm_dir(self) -> Path:
        return self.raw_dir / "htm_docs"

    @property
    def cleaned_dir(self) -> Path:
        return self.data_dir / "knowledge-base" / "cleaned"

    @property
    def chunked_dir(self) -> Path:
        return self.data_dir / "knowledge-base" / "chunked"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "embedded" / "chroma"

    @property
    def ask_log_path(self) -> Path:
        return self.data_dir / "ask_log.jsonl"

    def require_api_key(self) -> str:
        """The key of the configured provider. Only `ask` and `ui` need it."""
        key = self.anthropic_api_key if self.llm_provider == "anthropic" else self.openai_api_key
        if not key:
            raise MissingConfigError(f"{API_KEY_NAMES[self.llm_provider]} is not set (put it in .env).")
        return key


def allowed_models(config: Config, provider: str) -> tuple[str, ...]:
    """The allowlist for `provider`. The model set in `.env` for the default provider is trusted and listed first."""
    if provider not in PROVIDER_MODELS:
        raise LLMChoiceError(f"unknown provider {provider!r}; choose one of {', '.join(PROVIDERS)}")
    models = PROVIDER_MODELS[provider]
    if provider == config.llm_provider and config.llm_model not in models:
        return (config.llm_model, *models)
    return models


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from `env`, or from the process environment and `.env`."""
    if env is None:
        load_dotenv()
        env = dict(os.environ)
    provider = (env.get("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()
    if provider not in PROVIDERS:
        raise MissingConfigError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, not {provider!r}.")
    return Config(
        openai_api_key=env.get("OPENAI_API_KEY") or None,
        anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
        llm_provider=provider,
        llm_model=env.get("LLM_MODEL") or DEFAULT_LLM_MODELS[provider],
        llm_reasoning_effort=env.get("LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        embedding_model=env.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        retrieval_k=int(env.get("RETRIEVAL_K", DEFAULT_RETRIEVAL_K)),
        data_dir=Path(env.get("DATA_DIR", DEFAULT_DATA_DIR)),
        code_dir=Path(env["CODE_DIR"]) if env.get("CODE_DIR") else None,
        allow_code_to_openai=(env.get("ALLOW_CODE_TO_OPENAI") or "").strip().lower() == "true",
    )
