# Good AI Enterprise Reference - Makefile
# Common commands for development and operations

.PHONY: help setup install lint format test coverage run docker-build docker-up docker-down clean

# Default target
help:
	@echo "Good AI Enterprise Reference"
	@echo ""
	@echo "Usage:"
	@echo "  make setup       - Install dependencies for development"
	@echo "  make install     - Install package"
	@echo "  make lint        - Run linting (ruff)"
	@echo "  make format      - Format code (ruff)"
	@echo "  make test        - Run tests"
	@echo "  make coverage    - Run tests with coverage"
	@echo "  make run         - Run API server locally"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-up   - Start services with Docker Compose"
	@echo "  make docker-down - Stop services"
	@echo "  make clean       - Clean build artifacts"

# Development setup
setup:
	python -m pip install --upgrade pip
	pip install -e ".[dev]"
	@echo "Setup complete. Copy .env.example to .env and configure."

# Install package only
install:
	pip install -e .

# Linting
lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

# Format code
format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

# Type checking
typecheck:
	mypy src/

# Run tests
test:
	pytest tests/ -v

# Run tests with coverage
coverage:
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term
	@echo "Coverage report: htmlcov/index.html"

# Run API server locally
run:
	uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000

# Docker operations
docker-build:
	docker build -t goodai-enterprise:latest -f infrastructure/Dockerfile .

docker-up:
	docker-compose -f infrastructure/docker-compose.yml up --build -d
	@echo "Services starting..."
	@echo "API: http://localhost:8000"
	@echo "Docs: http://localhost:8000/docs"

docker-down:
	docker-compose -f infrastructure/docker-compose.yml down

docker-logs:
	docker-compose -f infrastructure/docker-compose.yml logs -f

# Security audit
audit:
	pip-audit

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
