COMPOSE ?= docker compose
ENV_FILE ?= .env.docker.example
PYTHON ?= python
NPM ?= npm

.PHONY: up down logs config test test-backend test-frontend build-frontend seed package-content tunnel-up tunnel-logs tunnel-config

up:
	$(COMPOSE) --env-file $(ENV_FILE) up --build

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
