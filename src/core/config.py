"""Central configuration loaded from environment variables / .env."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    llm_provider: str
    anthropic_api_key: str | None
    openai_api_key: str | None
    google_api_key: str | None
    hf_token: str | None
    ollama_host: str
    embedding_model: str
    chroma_persist_dir: str
    chroma_collection_name: str


def load_config() -> Config:
    return Config(
        llm_provider=os.environ.get("LLM_PROVIDER", "openai"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        hf_token=os.environ.get("HF_TOKEN"),
        ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        chroma_persist_dir=os.environ.get("CHROMA_PERSIST_DIR", "./database/chroma"),
        chroma_collection_name=os.environ.get("CHROMA_COLLECTION_NAME", "ragger"),
    )
