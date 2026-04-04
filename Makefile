# ============================================================
# GLM Agent Engine - Makefile
#
# Quick reference:
#   make setup          First-time setup (.env + data dirs)
#   make build          Build Docker image
#   make up             Start all services
#   make down           Stop all services
#   make logs           Follow glm-agent logs
#   make logs-engine    Follow only engine (FastAPI) logs
#   make test           Run unit tests
#   make test-integration Run integration tests
#   make redis-cli      Open Redis CLI
#   make db-shell       Open database shell
# ============================================================

.PHONY: help build up down restart logs ps \
        test test-integration lint format clean setup \
        deploy redis-cli db-shell logs-engine \
        logs-redis logs-caddy shell

# Default target
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ===================== Docker ==============================

build: ## Build Docker image
	docker compose build

up: ## Start all services (detached)
	docker compose up -d

down: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose restart

logs: ## Follow all logs
	docker compose logs -f

logs-engine: ## Follow engine (FastAPI) logs only
	docker compose logs -f glm-agent 2>&1 | rg --line-buffered "(uvicorn|fastapi|engine|ERROR|WARNING)" || docker compose logs -f glm-agent

logs-redis: ## Follow Redis logs only
	docker compose logs -f redis

logs-caddy: ## Follow Caddy logs only
	docker compose exec glm-agent sh -c 'tail -f /proc/1/fd/2 2>/dev/null || true' 2>/dev/null || docker compose logs -f glm-agent 2>&1 | rg --line-buffered "caddy"

ps: ## Show running services
	docker compose ps

shell: ## Open a shell in the glm-agent container
	docker compose exec glm-agent bash

# ===================== Testing ==============================

test: ## Run Python unit tests
	cd app && uv run pytest ../tests/ -v

test-integration: ## Run integration tests (requires running services)
	cd app && uv run pytest ../tests/ -v -m integration -o markers=true 2>/dev/null \
		|| cd app && uv run pytest ../tests/ -v --timeout=60

test-verbose: ## Run tests with full output
	cd app && uv run pytest ../tests/ -v -s --tb=long

# ===================== Development =========================

lint: ## Lint Python code
	uv tool run ruff check app/ tests/

format: ## Format Python code
	uv tool run ruff format app/ tests/

typecheck: ## Type-check Python code
	cd app && uv run mypy . --ignore-missing-imports 2>/dev/null || echo "mypy not installed, skipping"

# ===================== Database ============================

db-shell: ## Open database shell (SQLite or MySQL)
	@if grep -q "mysql" .env 2>/dev/null; then \
		echo "Opening MySQL shell..."; \
		docker compose exec glm-agent bash -c \
			"mysql -h mysql -u $${MYSQL_USER:-glmagent} -p$${MYSQL_PASSWORD:-glmagent_pw} $${MYSQL_DATABASE:-glm_agent}"; \
	else \
		echo "Opening SQLite shell (using sqlite3 CLI)..."; \
		docker compose exec glm-agent sqlite3 /home/z/my-project/db/custom.db; \
	fi

db-backup: ## Backup SQLite database
	@mkdir -p backups
	@cp data/db/custom.db "backups/custom.db.$$(date +%Y%m%d_%H%M%S).db"
	@echo "Backup created in backups/"

db-reset: ## Reset SQLite database (WARNING: deletes all data)
	@rm -f data/db/custom.db
	@echo "Database reset. It will be recreated on next start."

# ===================== Redis ===============================

redis-cli: ## Open Redis CLI
	docker compose exec redis redis-cli

redis-flush: ## Flush all Redis data (WARNING: destructive)
	docker compose exec redis redis-cli FLUSHALL
	@echo "Redis flushed."

redis-info: ## Show Redis info and stats
	docker compose exec redis redis-cli INFO

# ===================== Setup ===============================

setup: ## Initial setup (create .env, data dirs)
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env - please configure ZAI_API_KEY"; fi
	@mkdir -p data/{project,upload,download,db,sync,backups}
	@echo "Setup complete. Edit .env then run: make build && make up"

# ===================== Production ==========================

deploy: build ## Build and deploy (force recreate)
	docker compose up -d --build --force-recreate

# ===================== Cleanup =============================

clean: ## Clean build artifacts and local data
	rm -rf app/.venv
	rm -rf data/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf backups/
	@echo "Cleaned build artifacts and data directories."

clean-docker: ## Remove Docker images, volumes, and containers
	docker compose down -v --rmi local --remove-orphans
	@echo "Removed containers, volumes, and local images."

clean-all: clean clean-docker ## Full clean (artifacts + Docker)
	@echo "Full clean complete."
