from pathlib import Path


def test_backend_dockerfile_configures_uvicorn_and_runtime_env_defaults():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"

    assert dockerfile.exists()

    text = dockerfile.read_text(encoding="utf-8")

    assert "pip install --no-cache-dir -r requirements.txt" in text
    assert "DATABASE_URL=sqlite+pysqlite:////data/kyrgame.db" in text
    assert "RUN mkdir -p /data" in text
    assert "KYRGAME_RESET_ON_BOOT=0" in text
    assert "KYRGAME_CORS_ORIGINS=" in text
    assert 'CMD ["sh", "-c", "uvicorn kyrgame.webapp:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]' in text
