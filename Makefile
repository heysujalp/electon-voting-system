# ElectON v2 — Common Development Commands
.PHONY: help run migrate makemigrations test lint setup clean docker-build docker-up docker-down check-migrations cleanup-sessions dev dev-django solana-up anchor-build anchor-deploy

help:  ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:  ## First-time project setup
	python -m venv venv
	. venv/bin/activate && pip install -r requirements-dev.txt
	cp .env.example .env
	python manage.py createcachetable
	python manage.py migrate
	@echo "\n✅ Setup complete. Run 'make run' to start the server."

run:  ## Start development server
	python manage.py runserver

migrate:  ## Run database migrations
	python manage.py migrate

makemigrations:  ## Create new migrations
	python manage.py makemigrations

test:  ## Run tests with coverage
	pytest --cov=apps --cov-report=term-missing

lint:  ## Run linter
	ruff check .

lint-fix:  ## Auto-fix lint errors
	ruff check --fix .

shell:  ## Open Django shell
	python manage.py shell

createsuperuser:  ## Create admin superuser
	python manage.py createsuperuser

collectstatic:  ## Collect static files
	python manage.py collectstatic --noinput

clean:  ## Remove cache and compiled files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage

# ─── Docker ─────────────────────────────────────────────────────
docker-build:  ## Build Docker image
	docker build -t electon .

docker-up:  ## Start all services with Docker Compose
	docker compose up -d

docker-down:  ## Stop all Docker services
	docker compose down

docker-logs:  ## Tail Docker logs
	docker compose logs -f web

# ─── Utilities ──────────────────────────────────────────────────
check-migrations:  ## Verify no missing migrations
	python manage.py makemigrations --check --dry-run

cleanup-sessions:  ## Remove expired voter sessions
	python manage.py cleanup_sessions

check:  ## Run all checks (lint + migrations + tests)
	@echo "── Lint ──"
	ruff check .
	@echo "── Migration Check ──"
	python manage.py makemigrations --check --dry-run
	@echo "── Tests ──"
	pytest --cov=apps --cov-report=term-missing

# ─── Solana / Anchor ─────────────────────────────────────────────
dev:  ## Start full local stack (Solana test-validator + Anchor deploy + Django)
	./dev.sh

dev-django:  ## Start Django only (skip blockchain)
	./dev.sh --no-chain

solana-up:  ## Start Solana test-validator (blocks terminal)
	export PATH="$$HOME/.local/share/solana/install/active_release/bin:$$PATH" && \
	solana-test-validator --reset --ledger test-ledger --log

anchor-build:  ## Build Anchor program
	export PATH="$$HOME/.local/share/solana/install/active_release/bin:$$HOME/.cargo/bin:$$PATH" && \
	cd solana-program && anchor build

anchor-deploy:  ## Deploy Anchor program to localnet
	export PATH="$$HOME/.local/share/solana/install/active_release/bin:$$HOME/.cargo/bin:$$PATH" && \
	cd solana-program && anchor deploy --provider.cluster localnet
