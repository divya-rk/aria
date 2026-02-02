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
# Kubernetes
# ============================================================================

# Render k8s manifests for dev
k8s-dev:
    kubectl kustomize k8s/overlays/dev

# Render k8s manifests for prod
k8s-prod:
    kubectl kustomize k8s/overlays/prod

# Apply k8s manifests to dev cluster
k8s-apply-dev:
    kubectl apply -k k8s/overlays/dev

# Apply k8s manifests to prod cluster
k8s-apply-prod:
    kubectl apply -k k8s/overlays/prod

# Delete k8s resources from dev cluster
k8s-delete-dev:
    kubectl delete -k k8s/overlays/dev

# View worker logs
k8s-logs worker:
    kubectl logs -n aria -l app.kubernetes.io/component={{worker}} -f

# View all worker pods
k8s-pods:
    kubectl get pods -n aria -o wide

# Scale a worker manually (for testing)
k8s-scale worker replicas:
    kubectl scale deployment/{{worker}}-worker -n aria --replicas={{replicas}}

# ============================================================================
# Docker Build
# ============================================================================

# AWS account ID (set via env or override)
aws_account := env_var_or_default("AWS_ACCOUNT_ID", "ACCOUNT_ID")
aws_region := env_var_or_default("AWS_REGION", "us-east-1")
ecr_registry := aws_account + ".dkr.ecr." + aws_region + ".amazonaws.com"

# Build all worker images
docker-build-all: docker-build-hydration docker-build-curation docker-build-embedding docker-build-tokenization

# Build hydration worker image
docker-build-hydration:
    docker build -t {{ecr_registry}}/aria-hydration:latest -f docker/Dockerfile.hydration .

# Build curation worker image
docker-build-curation:
    docker build -t {{ecr_registry}}/aria-curation:latest -f docker/Dockerfile.curation .

# Build embedding worker image
docker-build-embedding:
    docker build -t {{ecr_registry}}/aria-embedding:latest -f docker/Dockerfile.embedding .

# Build tokenization worker image
docker-build-tokenization:
    docker build -t {{ecr_registry}}/aria-tokenization:latest -f docker/Dockerfile.tokenization .

# Push all images to ECR
docker-push-all: docker-push-hydration docker-push-curation docker-push-embedding docker-push-tokenization

# Push hydration image
docker-push-hydration:
    docker push {{ecr_registry}}/aria-hydration:latest

# Push curation image
docker-push-curation:
    docker push {{ecr_registry}}/aria-curation:latest

# Push embedding image
docker-push-embedding:
    docker push {{ecr_registry}}/aria-embedding:latest

# Push tokenization image
docker-push-tokenization:
    docker push {{ecr_registry}}/aria-tokenization:latest

# ECR login
ecr-login:
    aws ecr get-login-password --region {{aws_region}} | docker login --username AWS --password-stdin {{ecr_registry}}

# ============================================================================
# CDK Infrastructure
# ============================================================================

# Synthesize CDK stacks
cdk-synth env="dev":
    cd iac && cdk synth -c environment={{env}} -c project=aria

# Deploy all CDK stacks
cdk-deploy env="dev":
    cd iac && cdk deploy --all -c environment={{env}} -c project=aria

# Diff CDK changes
cdk-diff env="dev":
    cd iac && cdk diff -c environment={{env}} -c project=aria

# Destroy CDK stacks (careful!)
cdk-destroy env="dev":
    cd iac && cdk destroy --all -c environment={{env}} -c project=aria

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
