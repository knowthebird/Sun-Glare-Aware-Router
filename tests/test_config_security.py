from __future__ import annotations

import pytest

from src.config import ConfigError, load_settings


def test_load_settings_rejects_external_plain_http_provider_urls(monkeypatch) -> None:
    monkeypatch.setenv("SUNROUTER_GEOCODER_BASE_URL", "http://example.com/search")

    with pytest.raises(ConfigError, match="SUNROUTER_GEOCODER_BASE_URL"):
        load_settings()


def test_load_settings_allows_local_plain_http_provider_urls(monkeypatch) -> None:
    monkeypatch.setenv(
        "SUNROUTER_ROUTER_BASE_URL",
        "http://localhost:5000/route/v1",
    )

    settings = load_settings()

    assert settings.router_base_url == "http://localhost:5000/route/v1"


def test_load_settings_rejects_provider_urls_with_credentials(monkeypatch) -> None:
    monkeypatch.setenv(
        "SUNROUTER_REVERSE_GEOCODER_BASE_URL",
        "https://user:password@example.com/reverse",
    )

    with pytest.raises(ConfigError, match="must not include credentials"):
        load_settings()


def test_load_settings_rejects_unsafe_routing_profile(monkeypatch) -> None:
    monkeypatch.setenv("SUNROUTER_ROUTING_PROFILE", "../driving")

    with pytest.raises(ConfigError, match="SUNROUTER_ROUTING_PROFILE"):
        load_settings()


def test_load_settings_rejects_unreasonable_numeric_values(monkeypatch) -> None:
    monkeypatch.setenv("SUNROUTER_HTTP_TIMEOUT_S", "0")

    with pytest.raises(ConfigError, match="SUNROUTER_HTTP_TIMEOUT_S"):
        load_settings()
