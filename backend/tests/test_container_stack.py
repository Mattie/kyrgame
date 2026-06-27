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
    assert services["backend"]["environment"]["KYRGAME_FORCE_HONOR_MODE"] == "${KYRGAME_FORCE_HONOR_MODE:-0}"
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
        "^/(auth|public|i18n|world|locations|objects|spells|commands|players|sessions|ws)(/|\\\\?|$)|^/admin/(?!($|\\\\?))"
    )
    runtime_proxy_pattern = re.compile(
        r"^/(auth|public|i18n|world|locations|objects|spells|commands|players|sessions|ws)(/|\?|$)|^/admin/(?!($|\?))"
    )

    assert "KYRGAME_BACKEND_PROXY_TARGET" in text
    assert "http://backend:8000" in text
    assert source_proxy_pattern in text
    assert runtime_proxy_pattern.match("/auth/register")
    assert not runtime_proxy_pattern.match("/admin")
    assert not runtime_proxy_pattern.match("/admin?panel=players")
    assert not runtime_proxy_pattern.match("/admin/")
    assert not runtime_proxy_pattern.match("/admin/?panel=players")
    assert runtime_proxy_pattern.match("/admin/fixtures")
    assert runtime_proxy_pattern.match("/admin/fixtures?reload=1")
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
    assert "KYRGAME_FORCE_HONOR_MODE=0" in text
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
    assert "selfhost-" not in text


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
    assert "willow.eventscripts.com" not in text
    assert "kyrgame-local" not in text
    assert ".agents\\skills\\local-dev-servers" not in text
    assert "docs/DEV_HOSTING.md" in text


def test_root_dockerignore_keeps_local_credentials_and_build_outputs_out_of_context():
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    for pattern in [
        ".env",
        ".env.*",
        "backend/.env",
        "frontend/node_modules",
        "frontend/dist",
        "local-docker",
        "selfhost",
    ]:
        assert pattern in text
    assert "deploy/self-host" not in text


def test_readme_links_to_general_hosting_guides():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/DEV_HOSTING.md" in text
    assert "docs/SELF_HOSTING.md" in text
    assert "willow.eventscripts.com" not in text
    assert "kyrgame-local" not in text


def test_public_hosting_docs_do_not_include_private_environment_references():
    private_patterns = [
        (r"C:\\Users\\matti", "C:\\Users\\matti"),
        (r"\bmatti\b", "matti"),
        (r"willow\.eventscripts\.com", "willow.eventscripts.com"),
        (r"kyrgame-local", "kyrgame-local"),
    ]
    docs_to_scan = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "SELF_HOSTING.md",
        REPO_ROOT / "docs" / "DEV_HOSTING.md",
        REPO_ROOT / "docs" / "ALPHA_TESTING_RUNBOOK.md",
    ]

    for path in docs_to_scan:
        text = path.read_text(encoding="utf-8")
        for pattern, label in private_patterns:
            assert not re.search(pattern, text), f"{label!r} leaked into {path.relative_to(REPO_ROOT)}"


def test_self_hosting_guide_covers_operator_lifecycle():
    text = (REPO_ROOT / "docs" / "SELF_HOSTING.md").read_text(encoding="utf-8")

    for required in [
        "This repository does not ship a production reverse-proxy stack",
        "Caddy, nginx, Traefik",
        "same-origin",
        "private Postgres",
        "<your-domain>",
        "selfhost/config/admin-allowlist.yaml",
        "pg_dump -Fc",
        "pg_restore -l",
        "KYRGAME_RESET_ON_BOOT=0",
        "KYRGAME_SEED_IF_EMPTY=1",
        "KYRGAME_TRUST_PROXY_HEADERS=1",
        "kyrgame.webapp:create_app --factory",
        "LICENSE.txt",
    ]:
        assert required in text
    assert "deploy/self-host" not in text


def test_self_hosting_guide_does_not_ship_production_deploy_stack():
    for path in [
        REPO_ROOT / "deploy" / "self-host" / ".env.selfhost.example",
        REPO_ROOT / "deploy" / "self-host" / "Caddyfile",
        REPO_ROOT / "deploy" / "self-host" / "compose.yaml",
        REPO_ROOT / "deploy" / "self-host" / "web.Dockerfile",
    ]:
        assert not path.exists(), f"{path.relative_to(REPO_ROOT)} should stay out of the docs-only self-host guide"


def test_dev_hosting_guide_covers_local_stack_without_private_hostnames():
    text = (REPO_ROOT / "docs" / "DEV_HOSTING.md").read_text(encoding="utf-8")

    for required in [
        "compose.yaml",
        ".env.docker.example",
        "local-docker/admin-allowlist.yaml",
        "make ENV_FILE=.env.docker.example up",
        "docker compose --env-file .env.docker.example up -d --build",
        "KYRGAME_VITE_ALLOWED_HOSTS=<your-tunnel-host>",
        "127.0.0.1:5173",
        "127.0.0.1:8000",
    ]:
        assert required in text
