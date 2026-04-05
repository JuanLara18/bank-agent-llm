"""Unit tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bank_agent_llm.config import clear_settings_cache, get_settings


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _write_config(path: Path, data: dict) -> Path:
    config = path / "config.yaml"
    config.write_text(yaml.dump(data), encoding="utf-8")
    return config


# ─── Loading ─────────────────────────────────────────────────────────────────

def test_raises_when_config_file_missing() -> None:
    with pytest.raises(FileNotFoundError, match="config.yaml"):
        get_settings("/nonexistent/path/config.yaml")


def test_loads_minimal_config_with_defaults(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {})
    settings = get_settings(config)
    assert settings.database.url == "sqlite:///data/bank_agent.db"
    assert settings.email_accounts == []
    assert settings.pipeline.log_level == "INFO"


def test_loads_custom_database_url(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {"database": {"url": "sqlite:///custom.db"}})
    assert get_settings(config).database.url == "sqlite:///custom.db"


# ─── Env var expansion ───────────────────────────────────────────────────────

def test_expands_env_vars_in_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DB_URL", "sqlite:///env_expanded.db")
    config = _write_config(tmp_path, {"database": {"url": "${TEST_DB_URL}"}})
    assert get_settings(config).database.url == "sqlite:///env_expanded.db"


def test_raises_on_unexpanded_email_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EMAIL_PASS", raising=False)
    data = {
        "email_accounts": [{
            "name": "personal",
            "imap_host": "imap.gmail.com",
            "username": "user@example.com",
            "password": "${EMAIL_PASS}",
        }]
    }
    with pytest.raises(Exception, match="unexpanded variable"):
        get_settings(_write_config(tmp_path, data))


def test_email_account_with_expanded_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_USER", "user@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret")
    data = {
        "email_accounts": [{
            "name": "personal",
            "imap_host": "imap.gmail.com",
            "username": "${EMAIL_USER}",
            "password": "${EMAIL_PASS}",
        }]
    }
    settings = get_settings(_write_config(tmp_path, data))
    assert settings.email_accounts[0].username == "user@example.com"
    assert settings.email_accounts[0].password == "secret"


# ─── Validation ──────────────────────────────────────────────────────────────

def test_invalid_log_level_raises(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {"pipeline": {"log_level": "VERBOSE"}})
    with pytest.raises(Exception, match="log_level"):
        get_settings(config)


def test_log_level_is_uppercased(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {"pipeline": {"log_level": "debug"}})
    assert get_settings(config).pipeline.log_level == "DEBUG"


def test_categories_parsed(tmp_path: Path) -> None:
    data = {
        "categories": [
            {"name": "Food", "subcategories": ["Groceries", "Restaurants"]},
            {"name": "Transport"},
        ]
    }
    settings = get_settings(_write_config(tmp_path, data))
    assert len(settings.categories) == 2
    assert settings.categories[0].name == "Food"
    assert settings.categories[1].subcategories == []


# ─── Caching ─────────────────────────────────────────────────────────────────

def test_settings_are_cached(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {})
    assert get_settings(config) is get_settings(config)


def test_clear_cache_forces_reload(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {})
    s1 = get_settings(config)
    clear_settings_cache()
    s2 = get_settings(config)
    assert s1 is not s2
