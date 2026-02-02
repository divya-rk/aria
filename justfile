# Aria - Audio Recognition and Ingestion Architecture
# Run `just` to see available commands

set dotenv-load

# Default recipe - show help
default:
    @just --list

# ============================================================================
# Installation
# ============================================================================

# Install dependencies with uv
install:
    uv pip install -e .

# Install with dev dependencies
install-dev:
    uv pip install -e ".[dev]"
    pre-commit install

# Sync dependencies (faster than install)
sync:
    uv pip sync pyproject.toml

# ============================================================================
# Linting & Formatting
# ============================================================================

# Run all linting checks
lint:
    ruff check src tests
    ruff format --check src tests
    mypy src/aria

# Fix linting issues automatically
fix:
    ruff check --fix src tests
    ruff format src tests

# Format code with ruff
format:
    ruff format src tests

# Type check with mypy
typecheck:
    mypy src/aria

# ============================================================================
# Testing
# ============================================================================

# Run unit tests
test:
    pytest tests/unit -v

# Run integration tests
test-integration:
    pytest tests/integration -v

# Run all tests with coverage
test-all:
    pytest tests -v --cov=aria --cov-report=term-missing

# Run tests in watch mode
test-watch:
    pytest-watch tests/unit

# ============================================================================
# Development
# ============================================================================

# Start API server with reload
serve:
    aria serve --reload

# Start Dagster dev server
dagster:
    dagster dev -m aria.orchestration

# Start local services (DynamoDB, LocalStack)
docker-up:
    docker-compose up -d

# Stop local services
docker-down:
    docker-compose down

# Build docker image
docker-build:
    docker build -t aria:latest .

# ============================================================================
# CLI Shortcuts
# ============================================================================

# Search vector database
search query:
    aria search "{{query}}"

# Show statistics
stats:
    aria stats

# Validate data quality
validate:
    aria validate --check all

# Generate quality report
report:
    aria report

# ============================================================================
# Utilities
# ============================================================================

# Clean build artifacts
clean:
    rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Setup local LanceDB
setup-db:
    python scripts/setup_lancedb.py

# Run backfill job
backfill:
    python scripts/backfill.py

# Create new virtual environment with uv
venv:
    uv venv
    @echo "Run 'source .venv/bin/activate' to activate"

# Update dependencies
update:
    uv pip compile pyproject.toml -o requirements.lock
    uv pip sync requirements.lock
