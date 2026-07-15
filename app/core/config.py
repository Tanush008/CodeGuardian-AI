"""Centralized application settings, loaded from environment variables.

Nothing else in the codebase should call os.environ directly — import
`settings` from here instead, so config is validated in one place and
tests can override it cleanly with dependency overrides / monkeypatch.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    
    # GitHub App
    github_app_id: str
    github_private_key_path: str
    github_webhook_secret: str

    # RAG
    chroma_persist_dir: str = "./data/chroma"
    coding_standards_path: str = "./docs/coding-standards.md"

    # Limits (guard against huge PRs blowing up token budgets / runtime)
    max_diff_files: int = 25
    max_file_bytes: int = 200_000

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Settings are cached so we parse env vars once per process."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
