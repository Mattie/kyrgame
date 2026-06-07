import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_compose_dev_stack_wires_backend_frontend_postgres_and_tunnel_profile():
    compose_path = REPO_ROOT / "compose.yaml"

    stack = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = stack["services"]

    assert set(services) == {"backend", "cloudflared", "db", "frontend"}
    for service in services.values():
        assert service["restart"] == "unless-stopped"

    assert services["db"]["image"].startswith("postgres:16")
    assert services["backend"]["build"] == {
        "context": ".",
        "dockerfile": "backend/Dockerfile",
    }
    assert "--reload" not in services["backend"]["command"]
    assert "postgresql+psycopg://" in services["backend"]["environment"]["DATABASE_URL"]
    assert "@db:5432/" in services["backend"]["environment"]["DATABASE_URL"]
    assert services["backend"]["environment"]["KYRGAME_ADMIN_TOKEN"] == "${KYRGAME_ADMIN_TOKEN:-}"
    assert services["backend"]["environment"]["KYRGAME_ADMIN_ALLOWLIST_PATH"]
    assert services["backend"]["environment"]["KYRGAME_TELEMETRY_DIR"] == "${KYRGAME_TELEMETRY_DIR:-/data/telemetry}"
    assert services["backend"]["environment"]["KYRGAME_DB_CONNECT_ATTEMPTS"] == "${KYRGAME_DB_CONNECT_ATTEMPTS:-30}"
    assert services["backend"]["environment"]["KYRGAME_DB_CONNECT_RETRY_SECONDS"] == "${KYRGAME_DB_CONNECT_RETRY_SECONDS:-1}"
    assert "http://127.0.0.1:5173" in services["backend"]["environment"]["KYRGAME_CORS_ORIGINS"]

    assert services["frontend"]["image"].startswith("node:20")
    assert "npm ci && npm run dev" in services["frontend"]["command"]
    assert "--host ::" in services["frontend"]["command"]
    assert services["frontend"]["environment"]["VITE_API_BASE_URL"] == "${VITE_API_BASE_URL:-}"
    assert services["frontend"]["environment"]["VITE_WS_URL"] == "${VITE_WS_URL:-}"
    assert services["frontend"]["environment"]["KYRGAME_BACKEND_PROXY_TARGET"] == (
        "${KYRGAME_BACKEND_PROXY_TARGET:-http://backend:8000}"
    )
    assert services["frontend"]["environment"]["KYRGAME_VITE_ALLOWED_HOSTS"] == (
        "${KYRGAME_VITE_ALLOWED_HOSTS:-willow.eventscripts.com}"
    )
    assert services["frontend"]["environment"]["KYRGAME_VITE_USE_POLLING"] == "${KYRGAME_VITE_USE_POLLING:-1}"

    assert services["cloudflared"]["profiles"] == ["tunnel"]
    assert services["cloudflared"]["network_mode"] == "service:frontend"
    assert "--token" not in services["cloudflared"]["command"]
    assert "--config /etc/cloudflared/config.yml" in services["cloudflared"]["command"]
    assert services["cloudflared"]["environment"]["TUNNEL_TOKEN"] == "${CLOUDFLARE_TUNNEL_TOKEN:-}"
    assert "./cloudflared:/etc/cloudflared:ro" in services["cloudflared"]["volumes"]


def test_cloudflared_ingress_routes_to_frontend_loopback_for_dashboard_parity():
    config_path = REPO_ROOT / "cloudflared" / "config.yml"

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config["ingress"] == [{"service": "http://127.0.0.1:5173"}]


def test_vite_tunnel_mode_proxies_backend_http_and_websocket_paths():
    text = (REPO_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    source_proxy_pattern = (
        "^/(auth|admin|public|i18n|world|locations|objects|spells|commands|players|sessions|ws)(/|\\\\?|$)"
    )
    runtime_proxy_pattern = re.compile(
        r"^/(auth|admin|public|i18n|world|locations|objects|spells|commands|players|sessions|ws)(/|\?|$)"
    )

    assert "KYRGAME_BACKEND_PROXY_TARGET" in text
    assert "http://backend:8000" in text
    assert source_proxy_pattern in text
    assert runtime_proxy_pattern.match("/auth/register")
    assert runtime_proxy_pattern.match("/world/locations")
    assert runtime_proxy_pattern.match("/ws?token=game-session")
    assert runtime_proxy_pattern.match("/ws/admin/scry?player=Hero")
    assert not runtime_proxy_pattern.match("/assets/ws?token=game-session")
    assert "ws: true" in text
    assert "KYRGAME_VITE_ALLOWED_HOSTS" in text
    assert "allowedHosts: tunnelAllowedHosts" in text
    assert "allowedHosts: true" not in text


def test_root_docker_env_example_includes_local_only_admin_and_tunnel_controls():
    text = (REPO_ROOT / ".env.docker.example").read_text(encoding="utf-8")

    assert "KYRGAME_ADMIN_ALLOWLIST_PATH=/config/admin-allowlist.yaml" in text
    assert "KYRGAME_TELEMETRY_DIR=/data/telemetry" in text
    assert "KYRGAME_DB_CONNECT_ATTEMPTS=30" in text
    assert "KYRGAME_DB_CONNECT_RETRY_SECONDS=1" in text
    assert "KYRGAME_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173" in text
    assert "KYRGAME_ADMIN_TOKEN=\n" in text
    assert "dev-admin-token" not in text
    assert "CLOUDFLARE_TUNNEL_TOKEN=" in text
    assert "KYRGAME_BACKEND_PROXY_TARGET=http://backend:8000" in text
    assert "KYRGAME_VITE_ALLOWED_HOSTS=willow.eventscripts.com" in text
    assert "KYRGAME_VITE_USE_POLLING=1" in text
    assert "VITE_API_BASE_URL=\n" in text
    assert "VITE_WS_URL=\n" in text


def test_makefile_exposes_documented_ops_targets():
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    for target in ["up", "test", "seed", "package-content", "config", "tunnel-up", "tunnel-logs", "tunnel-config"]:
        assert f"{target}:" in text

    assert "$(COMPOSE) --env-file $(ENV_FILE) up -d --build" in text
    assert "$(COMPOSE) --env-file $(ENV_FILE) --profile tunnel up -d cloudflared" in text
    assert "-m kyrgame.scripts.seed_db" in text
    assert "-m kyrgame.scripts.package_content" in text


def test_backend_development_package_content_command_runs_from_repo_root():
    text = (REPO_ROOT / "backend" / "DEVELOPMENT.md").read_text(encoding="utf-8")
    command = (
        "cd backend && python -m kyrgame.scripts.package_content --output "
        "../legacy/Dist/offline-content.json"
    )

    assert text.count(command) == 1


def test_alpha_runbook_uses_portable_paths_and_distinct_tunnel_steps():
    text = (REPO_ROOT / "docs" / "ALPHA_TESTING_RUNBOOK.md").read_text(encoding="utf-8")

    assert "C:\\Users\\matti" not in text
    assert ".agents\\skills\\local-dev-servers" not in text
    assert "Set-Location -LiteralPath '<path-to-kyrgame>'" in text
    assert "make ENV_FILE=.env.docker.local up" in text
    assert "make ENV_FILE=.env.docker.local tunnel-up" in text
    assert "docker compose --env-file .env.docker.local -p kyrgame-local ps" in text


def test_root_dockerignore_keeps_local_credentials_and_build_outputs_out_of_context():
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    for pattern in [
        ".env",
        ".env.*",
        "backend/.env",
        "frontend/node_modules",
        "frontend/dist",
        "local-docker",
    ]:
        assert pattern in text
