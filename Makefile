SHELL := /bin/bash
.DEFAULT_GOAL := help
.NOTPARALLEL:

COMPOSE_FILE := deployment/compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

LOCAL_DATABASE_URL ?= postgresql+asyncpg://bothesis:bothesis@127.0.0.1:5432/bothesis
LOCAL_QDRANT_URL ?= http://127.0.0.1:6333
LOCAL_S3_ENDPOINT ?= http://127.0.0.1:9000
LOCAL_S3_BUCKET ?= bothesis
QDRANT_COLLECTION ?= bothesis
QDRANT_VECTOR_SIZE ?= 1536

DEV_TENANT_ID ?= 00000000-0000-0000-0000-000000000001
DEV_USER_ID ?= 00000000-0000-0000-0000-000000000002
DEV_ROLE_ID ?= 00000000-0000-0000-0000-000000000003
DEV_TENANT_CODE ?= local
DEV_USER_EMAIL ?= local-admin@bothesis.dev

.PHONY: help init config services db-init db-seed db-reset qdrant-init status

help: ## Show available local-development commands.
	@echo "BoThesis local development"
	@echo
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: db-reset qdrant-init status ## Initialize the complete local BoThesis environment.
	@echo
	@echo "BoThesis local environment is ready."
	@echo "  API:       http://127.0.0.1:8000"
	@echo "  Qdrant:    $(LOCAL_QDRANT_URL)/dashboard"
	@echo "  MinIO:     http://127.0.0.1:9001"
	@echo "  Tenant ID: $$(sed -n 's/^NEXT_PUBLIC_BOTHESIS_TENANT_ID=//p' web/.env.local | tail -n 1)"
	@echo "  User ID:   $$(sed -n 's/^NEXT_PUBLIC_BOTHESIS_USER_ID=//p' web/.env.local | tail -n 1)"
	@echo
	@echo "Start the API with: cd backend && uv run python main.py"

config: ## Create missing local environment files and enforce local dependency endpoints.
	@set -euo pipefail
	@if [[ ! -f backend/.env ]]; then cp backend/.env.example backend/.env; fi
	@if [[ ! -f web/.env.local ]]; then cp web/.env.example web/.env.local; fi
	@update_env() { \
		local file="$$1" key="$$2" value="$$3" temp_file; \
		temp_file="$$(mktemp)"; \
		awk -v key="$$key" -v value="$$value" 'BEGIN { found = 0 } $$0 ~ "^" key "=" { print key "=" value; found = 1; next } { print } END { if (!found) print key "=" value }' "$$file" > "$$temp_file"; \
		mv "$$temp_file" "$$file"; \
	}; \
	remove_env() { \
		local file="$$1" key="$$2" temp_file; \
		temp_file="$$(mktemp)"; \
		awk -v key="$$key" '$$0 !~ "^" key "=" { print }' "$$file" > "$$temp_file"; \
		mv "$$temp_file" "$$file"; \
	}; \
	update_env backend/.env DATABASE_URL "$(LOCAL_DATABASE_URL)"; \
	update_env backend/.env QDRANT_URL "$(LOCAL_QDRANT_URL)"; \
	update_env backend/.env QDRANT_COLLECTION "$(QDRANT_COLLECTION)"; \
	update_env backend/.env BOTHESIS_OBJECT_STORAGE_PROVIDER aws_s3; \
	update_env backend/.env BOTHESIS_OBJECT_STORAGE_BUCKET "$(LOCAL_S3_BUCKET)"; \
	update_env backend/.env BOTHESIS_S3_ENDPOINT_URL "$(LOCAL_S3_ENDPOINT)"; \
	update_env backend/.env BOTHESIS_S3_ADDRESSING_STYLE path; \
	update_env backend/.env AWS_ACCESS_KEY_ID bothesis; \
	update_env backend/.env AWS_SECRET_ACCESS_KEY bothesis; \
	plugin_key="$$(sed -n 's/^BOTHESIS_PLUGIN_ENCRYPTION_KEY=//p' backend/.env | tail -n 1)"; \
	legacy_key="$$(sed -n 's/^BOTHESIS_CONNECTOR_ENCRYPTION_KEY=//p' backend/.env | tail -n 1)"; \
	if [[ ! "$$plugin_key" =~ ^[A-Za-z0-9_-]{43}=?$$ ]]; then \
		if [[ "$$legacy_key" =~ ^[A-Za-z0-9_-]{43}=?$$ ]]; then \
			plugin_key="$$legacy_key"; \
		else \
			plugin_key="$$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"; \
		fi; \
		update_env backend/.env BOTHESIS_PLUGIN_ENCRYPTION_KEY "$$plugin_key"; \
	fi; \
	remove_env backend/.env BOTHESIS_CONNECTOR_ENCRYPTION_KEY; \
	update_env backend/.env BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY true; \
	update_env web/.env.local NEXT_PUBLIC_BOTHESIS_API_URL http://127.0.0.1:8000
	@echo "Configured local backend and WebUI environment files."

services: config ## Start PostgreSQL, Qdrant, and S3-compatible object storage.
	@set -euo pipefail
	@$(COMPOSE) up -d postgres qdrant minio
	@for attempt in {1..30}; do \
		if $(COMPOSE) exec -T postgres sh -c 'pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' >/dev/null 2>&1; then break; fi; \
		if [[ $$attempt -eq 30 ]]; then echo "PostgreSQL did not become ready." >&2; exit 1; fi; \
		sleep 1; \
	done
	@for attempt in {1..30}; do \
		if curl --fail --silent --max-time 2 "$(LOCAL_QDRANT_URL)/readyz" >/dev/null; then break; fi; \
		if [[ $$attempt -eq 30 ]]; then echo "Qdrant did not become ready." >&2; exit 1; fi; \
		sleep 1; \
	done
	@for attempt in {1..30}; do \
		if curl --fail --silent --max-time 2 "$(LOCAL_S3_ENDPOINT)/minio/health/ready" >/dev/null; then break; fi; \
		if [[ $$attempt -eq 30 ]]; then echo "Object storage did not become ready." >&2; exit 1; fi; \
		sleep 1; \
	done
	@$(COMPOSE) run --rm minio-init >/dev/null
	@echo "PostgreSQL, Qdrant, and object storage are accepting connections."

db-init: services ## Rebuild the initial PostgreSQL schema from the ORM model.
	@set -euo pipefail
	@$(COMPOSE) exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"' >/dev/null
	@cd backend && DATABASE_URL="$(LOCAL_DATABASE_URL)" uv run python -c 'import asyncio; from bothesis.db.engine import get_engine; from bothesis.db.models import Base; exec("async def initialize():\n    engine = get_engine()\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    await engine.dispose()") ; asyncio.run(initialize())'
	@echo "PostgreSQL schema is initialized."

db-seed: services ## Create or refresh the deterministic local admin identity.
	@set -euo pipefail
	@tenant_id="$$( $(COMPOSE) exec -T postgres sh -c 'psql -Atq -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "$$1"' _ "INSERT INTO tenants (id, code, name, status, settings) VALUES ('$(DEV_TENANT_ID)', '$(DEV_TENANT_CODE)', 'BoThesis Local', 'active', '{}'::jsonb) ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, status = 'active', updated_at = now() RETURNING id" )"; \
	user_id="$$( $(COMPOSE) exec -T postgres sh -c 'psql -Atq -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "$$1"' _ "INSERT INTO users (id, email, display_name, status, preferences) VALUES ('$(DEV_USER_ID)', '$(DEV_USER_EMAIL)', 'Local Administrator', 'active', '{}'::jsonb) ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name, status = 'active', updated_at = now() RETURNING id" )"; \
	role_id="$$( $(COMPOSE) exec -T postgres sh -c 'psql -Atq -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "$$1"' _ "INSERT INTO roles (id, tenant_id, code, display_name, permission_codes, status) VALUES ('$(DEV_ROLE_ID)', '$$tenant_id', 'admin', 'Administrator', ARRAY['admin'], 'active') ON CONFLICT (tenant_id, code) DO UPDATE SET display_name = EXCLUDED.display_name, permission_codes = EXCLUDED.permission_codes, status = 'active', updated_at = now() RETURNING id" )"; \
	$(COMPOSE) exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "$$1"' _ "INSERT INTO tenant_memberships (user_id, tenant_id, role_id, status, joined_at, deleted_at) VALUES ('$$user_id', '$$tenant_id', '$$role_id', 'active', now(), NULL) ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id, status = 'active', deleted_at = NULL" >/dev/null; \
	update_env() { \
		local file="$$1" key="$$2" value="$$3" temp_file; \
		temp_file="$$(mktemp)"; \
		awk -v key="$$key" -v value="$$value" 'BEGIN { found = 0 } $$0 ~ "^" key "=" { print key "=" value; found = 1; next } { print } END { if (!found) print key "=" value }' "$$file" > "$$temp_file"; \
		mv "$$temp_file" "$$file"; \
	}; \
	update_env web/.env.local NEXT_PUBLIC_BOTHESIS_TENANT_ID "$$tenant_id"; \
	update_env web/.env.local NEXT_PUBLIC_BOTHESIS_USER_ID "$$user_id"; \
	echo "Local admin identity is ready: $$user_id"

db-reset: db-init db-seed ## Rebuild PostgreSQL from the current ORM and reseed local identity.
	@echo "PostgreSQL reset is complete."

qdrant-init: services ## Rebuild the derived contextual-hybrid Qdrant collection.
	@set -euo pipefail
	@status_code="$$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "$(LOCAL_QDRANT_URL)/collections/$(QDRANT_COLLECTION)")"; \
	if [[ "$$status_code" == "200" ]]; then \
		curl --fail --silent --show-error --max-time 10 \
			-X DELETE "$(LOCAL_QDRANT_URL)/collections/$(QDRANT_COLLECTION)" >/dev/null; \
	elif [[ "$$status_code" != "404" ]]; then \
		echo "Unexpected Qdrant response: HTTP $$status_code" >&2; \
		exit 1; \
	fi; \
	curl --fail --silent --show-error --max-time 10 \
		-X PUT "$(LOCAL_QDRANT_URL)/collections/$(QDRANT_COLLECTION)" \
		-H 'Content-Type: application/json' \
		-d '{"vectors":{"content":{"size":$(QDRANT_VECTOR_SIZE),"distance":"Cosine"}},"sparse_vectors":{"content_bm25":{"modifier":"idf"}}}' >/dev/null; \
	echo "Rebuilt Qdrant collection $(QDRANT_COLLECTION) with content + content_bm25."

status: ## Show the current local dependency and application health.
	@$(COMPOSE) ps
	@echo
	@curl --silent --show-error --max-time 10 http://127.0.0.1:8000/health || echo "API is not running yet."
	@echo
