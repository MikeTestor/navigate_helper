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

DEFAULT_LLM_MODEL = "gpt-5-mini"
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_RETRIEVAL_K = 6
DEFAULT_DATA_DIR = "database"


class MissingConfigError(RuntimeError):
    """A required configuration value is not set."""


@dataclass(frozen=True)
class Config:
    openai_api_key: str | None
    llm_model: str
    llm_reasoning_effort: str
    embedding_model: str
    retrieval_k: int
    data_dir: Path

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
        """Only `ask` and `ui` need the key."""
        if not self.openai_api_key:
            raise MissingConfigError("OPENAI_API_KEY is not set (put it in .env).")
        return self.openai_api_key


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from `env`, or from the process environment and `.env`."""
    if env is None:
        load_dotenv()
        env = dict(os.environ)
    return Config(
        openai_api_key=env.get("OPENAI_API_KEY") or None,
        llm_model=env.get("LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_reasoning_effort=env.get("LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        embedding_model=env.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        retrieval_k=int(env.get("RETRIEVAL_K", DEFAULT_RETRIEVAL_K)),
        data_dir=Path(env.get("DATA_DIR", DEFAULT_DATA_DIR)),
    )
