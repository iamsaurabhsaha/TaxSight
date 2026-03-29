"""Application settings with BYOK LLM configuration."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path.home() / ".ai-tax-prep"

DEFAULT_MODELS = {
    "anthropic": "anthropic/claude-sonnet-4-20250514",
    "openai": "openai/gpt-4o",
    "gemini": "gemini/gemini-2.0-flash",
    "ollama": "ollama/llama3.1",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TAX_PREP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Provider
    llm_provider: str = Field(default="anthropic", description="LLM provider to use")
    model: Optional[str] = Field(default=None, description="Model override")

    # API Keys (read from standard env vars, no prefix)
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_BASE_URL"
    )

    # Database
    db_path: Path = Field(default=APP_DIR / "tax_prep.db")

    # PolicyEngine
    pe_mode: str = Field(default="api", description="'api' or 'local'")

    # Context management
    max_context_tokens: int = Field(default=100_000)
    context_summarize_threshold: float = Field(
        default=0.8, description="Summarize when context reaches this % of max"
    )

    @property
    def resolved_model(self) -> str:
        if self.model:
            return self.model
        return DEFAULT_MODELS.get(self.llm_provider, DEFAULT_MODELS["anthropic"])

    @property
    def api_key(self) -> Optional[str]:
        key_map = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }
        return key_map.get(self.llm_provider)

    def ensure_app_dir(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
