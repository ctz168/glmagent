# ============================================================
# GLM Agent Engine - Makefile
# ============================================================

.PHONY: help build up down logs test lint clean

# Default target
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ===================== Docker ==============================

build: ## Build Docker image
	docker compose build

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose restart

logs: ## Follow logs
	docker compose logs -f glm-agent

ps: ## Show running services
	docker compose ps

# ===================== Development =========================

test: ## Run Python tests
	cd app && uv run pytest ../tests/ -v

lint: ## Lint Python code
	uv tool run ruff check app/ tests/

format: ## Format Python code
	uv tool run ruff format app/ tests/

clean: ## Clean build artifacts
	rm -rf app/.venv
	rm -rf data/
	rm -rf __pycache__/
	rm -rf .pytest_cache/

# ===================== Setup ===============================

setup: ## Initial setup (create .env, data dirs)
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env - please configure ZAI_API_KEY"; fi
	@mkdir -p data/{project,upload,download,db,sync}

# ===================== Production ==========================

deploy: build ## Build and deploy
	docker compose up -d --build --force-recreate
