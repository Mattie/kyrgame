COMPOSE ?= docker compose
ENV_FILE ?= .env.docker.example
SELFHOST_ENV_FILE ?= deploy/self-host/.env.selfhost.local
SELFHOST_COMPOSE_FILE ?= deploy/self-host/compose.yaml
PYTHON ?= python
NPM ?= npm

.PHONY: up down logs config test test-backend test-frontend build-frontend seed package-content tunnel-up tunnel-logs tunnel-config selfhost-config selfhost-up selfhost-down selfhost-logs selfhost-backup

up:
	$(COMPOSE) --env-file $(ENV_FILE) up -d --build

down:
	$(COMPOSE) --env-file $(ENV_FILE) down

logs:
	$(COMPOSE) --env-file $(ENV_FILE) logs -f

config:
	$(COMPOSE) --env-file $(ENV_FILE) config

test: test-backend test-frontend

test-backend:
	$(PYTHON) -m pytest backend/tests

test-frontend:
	$(NPM) --prefix frontend test -- --run

build-frontend:
	$(NPM) --prefix frontend run build

seed:
	$(COMPOSE) --env-file $(ENV_FILE) run --rm backend python -m kyrgame.scripts.seed_db

package-content:
	$(PYTHON) -m pytest backend/tests/test_localization.py::test_offline_packager_writes_bundle
	cd backend && $(PYTHON) -m kyrgame.scripts.package_content --output ../legacy/Dist/offline-content.json

tunnel-config:
	$(COMPOSE) --env-file $(ENV_FILE) --profile tunnel config

tunnel-up:
	$(COMPOSE) --env-file $(ENV_FILE) --profile tunnel up -d cloudflared

tunnel-logs:
	$(COMPOSE) --env-file $(ENV_FILE) logs -f cloudflared

selfhost-config:
	$(COMPOSE) --env-file $(SELFHOST_ENV_FILE) -f $(SELFHOST_COMPOSE_FILE) config

selfhost-up:
	$(COMPOSE) --env-file $(SELFHOST_ENV_FILE) -f $(SELFHOST_COMPOSE_FILE) up -d --build

selfhost-down:
	$(COMPOSE) --env-file $(SELFHOST_ENV_FILE) -f $(SELFHOST_COMPOSE_FILE) down

selfhost-logs:
	$(COMPOSE) --env-file $(SELFHOST_ENV_FILE) -f $(SELFHOST_COMPOSE_FILE) logs -f

selfhost-backup:
	mkdir -p selfhost/backups
	$(COMPOSE) --env-file $(SELFHOST_ENV_FILE) -f $(SELFHOST_COMPOSE_FILE) exec -T db sh -lc 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -Fc' > selfhost/backups/kyrgame-$$(date +%Y%m%d-%H%M%S).dump
