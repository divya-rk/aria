# aria

**A**udio **R**ecognition and **I**ngestion **A**rchitecture

Scalable data pipeline for processing millions of audio files into LLM-ready training data.

## Features

- **Speech-to-text** using Whisper (GPU-accelerated)
- **Speaker diarization** and segmentation
- **Quality scoring** and deduplication (MinHash LSH)
- **PII detection** and redaction (Presidio)
- **Vector embeddings** stored in LanceDB
- **Tokenization and sharding** for LLM training
- **Scales to millions** of files using Ray on Kubernetes
- **Dagster orchestration** with full lineage tracking

## Architecture

```
Collection → Hydration → Curation → Embedding → Tokenization
     ↓           ↓           ↓          ↓           ↓
  S3/SQS    Ray+GPU      Quality    LanceDB     Shards
            Whisper      Filtering              for LLM
```

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer
- [just](https://github.com/casey/just) - Command runner
- Docker (for local development)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install just
brew install just  # macOS
```

### Installation

```bash
# Create virtual environment
just venv
source .venv/bin/activate

# Install dependencies
just install-dev
```

### Local Development

```bash
# Start local services (DynamoDB, S3)
just docker-up

# Run the API server
just serve

# Run Dagster
just dagster

# Run linting
just lint

# Run tests
just test
```

### CLI Usage

```bash
# Search vector database
aria search "machine learning concepts" --top-k 10

# Validate data quality
aria validate --check all

# Show statistics
aria stats

# Generate quality report
aria report
```

### API Usage

```bash
# Start server
aria serve

# Search (POST)
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "top_k": 10}'

# Search (GET)
curl "http://localhost:8000/search?q=machine+learning&top_k=10"

# Validate embeddings
curl http://localhost:8000/validate/embeddings

# Get stats
curl http://localhost:8000/stats
```

## Project Structure

```
aria/
├── src/aria/
│   ├── collection/      # S3 events, SQS consumer
│   ├── hydration/       # Whisper transcription
│   ├── curation/        # Quality, dedup, PII
│   ├── embedding/       # Chunking, vectors
│   ├── tokenization/    # Sharding for LLM
│   ├── storage/         # DynamoDB, LanceDB, S3
│   ├── query/           # API and CLI
│   └── orchestration/   # Dagster assets
├── tests/
├── infra/aws/           # Terraform configs
└── configs/             # Environment configs
```

## Pipeline Stages

### 1. Collection
Ingest audio files from S3 via event notifications or inventory reports.

### 2. Hydration
Transcribe audio using Whisper with Ray for distributed GPU processing.

### 3. Curation
- Quality scoring (confidence, language, length)
- Deduplication (MinHash LSH)
- PII detection and redaction

### 4. Embedding
- Text chunking with overlap
- Vector embeddings (sentence-transformers)
- Store in LanceDB

### 5. Tokenization
- Tokenize with tiktoken
- Create fixed-size shards
- Package for LLM training

## Configuration

Environment variables:

```bash
# AWS
AWS_REGION=us-east-1

# S3
S3_RAW_BUCKET=aria-raw
S3_OUTPUT_BUCKET=aria-output

# SQS
SQS_INGESTION_QUEUE_URL=https://sqs...

# DynamoDB
DYNAMODB_TABLE_NAME=aria-jobs

# LanceDB
LANCEDB_URI=s3://aria-lancedb/

# Whisper
WHISPER_MODEL_SIZE=large-v3

# Embedding
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
```

## Development

```bash
# Install dev dependencies
just install-dev

# Run linting
just lint

# Fix lint issues
just fix

# Run tests
just test

# Run all tests with coverage
just test-all

# Format code
just format

# Type checking
just typecheck
```

### Available Commands

```bash
just --list  # Show all available commands
```

## License

MIT
