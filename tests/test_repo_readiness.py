from __future__ import annotations

from pathlib import Path
import shutil

from src import config


def test_load_settings_reads_values_from_project_dotenv(monkeypatch) -> None:
    repo_root = Path.cwd().resolve()
    temp_dir = (repo_root / "tests/_tmp_repo_readiness").resolve()
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(temp_dir)
    monkeypatch.delenv("SUNROUTER_DEFAULT_TIMEZONE", raising=False)
    monkeypatch.delenv("SUNROUTER_ROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("SUNROUTER_MAX_ALTERNATIVES", raising=False)
    Path(".env").write_text(
        "\n".join(
            [
                "SUNROUTER_DEFAULT_TIMEZONE=UTC",
                "SUNROUTER_ROUTER_BASE_URL=https://example.test/route/v1",
                "SUNROUTER_MAX_ALTERNATIVES=5",
            ]
        ),
        encoding="utf-8",
    )

    settings = config.load_settings()

    assert settings.default_timezone == "UTC"
    assert settings.router_base_url == "https://example.test/route/v1"
    assert settings.max_alternatives == 5
    monkeypatch.chdir(repo_root)
    shutil.rmtree(temp_dir)


def test_repo_includes_streamlit_cloud_support_files() -> None:
    assert Path("requirements.txt").is_file()
    assert Path(".streamlit/config.toml").is_file()
    assert Path(".streamlit/secrets.toml.example").is_file()


def test_readme_mentions_streamlit_community_cloud_and_secrets() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Streamlit Community Cloud" in readme
    assert "requirements.txt" in readme
    assert "secrets.toml" in readme
