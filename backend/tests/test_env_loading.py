from pathlib import Path

from kyrgame.webapp import create_app


def test_create_app_loads_env_file(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("KYRGAME_ADMIN_TOKEN=from-env-file\n", encoding="utf-8")

    monkeypatch.setenv("KYRGAME_ENV_FILE", str(env_file))
    monkeypatch.delenv("KYRGAME_ADMIN_TOKEN", raising=False)

    app = create_app()

    assert "from-env-file" in app.state.admin_grants
