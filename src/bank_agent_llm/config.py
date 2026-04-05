"""Application configuration.

Loads config/config.yaml, expands ${ENV_VAR} tokens via os.path.expandvars
(pydantic-settings does not do this natively for YAML), and validates the
result with Pydantic models.

Usage:
    from bank_agent_llm.config import get_settings
    settings = get_settings()
    print(settings.database.url)
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator, model_validator

_UNEXPANDED_VAR = re.compile(r"\$\{[^}]+\}")
_DEFAULT_CONFIG_PATH = Path("config/config.yaml")


# ─── Sub-models ──────────────────────────────────────────────────────────────

class DatabaseConfig(BaseModel):
    url: str = "sqlite:///data/bank_agent.db"


class EmailAccountConfig(BaseModel):
    name: str
    imap_host: str
    imap_port: int = 993
    use_ssl: bool = True
    username: str
    password: str
    folders: list[str] = ["INBOX"]
    subject_keywords: list[str] = ["extracto", "estado de cuenta", "bank statement"]

    @model_validator(mode="after")
    def check_no_unexpanded_vars(self) -> "EmailAccountConfig":
        for field in ("username", "password"):
            value = getattr(self, field)
            if _UNEXPANDED_VAR.search(value):
                raise ValueError(
                    f"email_accounts[{self.name!r}].{field} still contains an unexpanded "
                    f"variable ({value!r}). Set the corresponding environment variable."
                )
        return self


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    categorization_model: str = "llama3.2"
    chat_model: str = "llama3.2"


class CategoryConfig(BaseModel):
    name: str
    subcategories: list[str] = []


class PipelineConfig(BaseModel):
    raw_data_dir: str = "data/raw"
    processed_data_dir: str = "data/processed"
    initial_lookback_days: int = 365
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.upper()


# ─── Root settings ────────────────────────────────────────────────────────────

class Settings(BaseModel):
    database: DatabaseConfig = DatabaseConfig()
    email_accounts: list[EmailAccountConfig] = []
    ollama: OllamaConfig = OllamaConfig()
    categories: list[CategoryConfig] = []
    pipeline: PipelineConfig = PipelineConfig()


# ─── Loader ───────────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file, expanding ${ENV_VAR} tokens before parsing."""
    raw = path.read_text(encoding="utf-8")
    expanded = os.path.expandvars(raw)
    return yaml.safe_load(expanded) or {}


@lru_cache(maxsize=1)
def _cached_settings(config_path: str) -> Settings:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Copy config/config.example.yaml to {path} and fill in your settings."
        )
    data = _load_yaml(path)
    return Settings.model_validate(data)


def get_settings(config_path: str | Path | None = None) -> Settings:
    """Return the application settings, cached after first load.

    Args:
        config_path: Override the default config location
                     (``config/config.yaml`` relative to cwd).
    """
    path = str(Path(config_path) if config_path else _DEFAULT_CONFIG_PATH)
    return _cached_settings(path)


def clear_settings_cache() -> None:
    """Clear the settings cache. Useful in tests."""
    _cached_settings.cache_clear()
