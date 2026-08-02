"""Config: loopback enforcement, path resolution, and key masking."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gaugix.config import Settings, mask_key, provider_key_status, read_api_key


def test_host_defaults_to_loopback():
    assert Settings().host == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::"])
def test_non_loopback_host_is_rejected(host):
    with pytest.raises(ValidationError, match="loopback"):
        Settings(host=host)


def test_relative_data_dir_resolves_against_repo_root():
    settings = Settings(data_dir=Path("./data"))
    assert settings.resolved_data_dir.is_absolute()
    assert settings.resolved_data_dir.name == "data"


def test_db_path_defaults_inside_data_dir(tmp_path):
    settings = Settings(data_dir=tmp_path, db_path=None)
    assert settings.resolved_db_path == tmp_path / "gaugix.db"
    assert settings.database_url.startswith("sqlite:///")


def test_ensure_dirs_creates_the_tree(tmp_path):
    settings = Settings(data_dir=tmp_path / "fresh")
    settings.ensure_dirs()
    assert settings.artifacts_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.exports_dir.is_dir()


def test_mask_key_never_leaks_the_secret():
    secret = "test-key-not-a-real-secret-1234"
    masked = mask_key(secret)
    assert masked == "…1234"
    assert secret not in masked


def test_mask_key_on_short_values_reveals_nothing():
    assert mask_key("abc") == "…"


def test_provider_key_status_reports_absent_keys(monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    status = provider_key_status()
    assert set(status) == {"anthropic", "openai", "gemini", "openrouter"}
    assert all(not s["present"] for s in status.values())
    assert all(s["masked"] is None for s in status.values())


def test_provider_key_status_masks_present_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secretvalue9876")
    status = provider_key_status()
    assert status["openai"]["present"] is True
    assert status["openai"]["masked"] == "…9876"
    assert "secretvalue" not in str(status)


def test_read_api_key_returns_none_for_missing_or_blank(monkeypatch):
    monkeypatch.setenv("BLANK_KEY", "   ")
    assert read_api_key(None) is None
    assert read_api_key("NOT_SET_ANYWHERE") is None
    assert read_api_key("BLANK_KEY") is None


def test_read_api_key_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "  value  ")
    assert read_api_key("SOME_KEY") == "value"
