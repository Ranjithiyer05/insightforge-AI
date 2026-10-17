"""Application settings, read from environment variables only.

Secrets (API keys) stay on the server: they are read here and never
returned by any API endpoint (see `public_settings`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("INSIGHTFORGE_DATA_DIR", BASE_DIR / "data")))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 50))
    max_rows: int = field(default_factory=lambda: _int("MAX_ROWS", 1_000_000))
    sandbox_timeout_s: int = field(default_factory=lambda: _int("SANDBOX_TIMEOUT_S", 60))
    sandbox_memory_mb: int = field(default_factory=lambda: _int("SANDBOX_MEMORY_MB", 2048))
    sandbox_require_netns: bool = field(default_factory=lambda: _bool("SANDBOX_REQUIRE_NETNS", False))
    retry_budget: int = field(default_factory=lambda: _int("RETRY_BUDGET", 2))
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "none").lower())
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    db_blob_max_mb: int = field(default_factory=lambda: _int("DB_BLOB_MAX_MB", 25))
    retention_days: int = field(default_factory=lambda: _int("DATASET_RETENTION_DAYS", 30))
    allow_external_llm_sample_rows: bool = field(default_factory=lambda: _bool("ALLOW_LLM_SAMPLE_ROWS", False))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    )

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).resolve()
        if self.database_url.startswith("postgres://"):
            self.database_url = "postgresql+psycopg://" + self.database_url[len("postgres://"):]
        elif self.database_url.startswith("postgresql://"):
            self.database_url = "postgresql+psycopg://" + self.database_url[len("postgresql://"):]
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'insightforge.db'}"

    @property
    def persistent_db(self) -> bool:
        """False when the database is SQLite under the data directory, which free hosts wipe on restart."""
        return not self.database_url.startswith("sqlite") or _bool("STORAGE_PERSISTENT", False)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.runs_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()


def llm_api_key() -> str | None:
    """Server-side only. Never serialise this value."""
    if settings.llm_provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY") or None
    if settings.llm_provider == "openai":
        return os.environ.get("OPENAI_API_KEY") or None
    if settings.llm_provider in ("ollama", "openai_compatible"):
        return os.environ.get("LLM_API_KEY") or None  # often not needed (e.g. local Ollama)
    return None


def llm_base_url() -> str:
    if settings.llm_provider == "ollama":
        return os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    if settings.llm_provider == "openai_compatible":
        return os.environ.get("LLM_BASE_URL", "").rstrip("/")
    return "https://api.openai.com/v1"
