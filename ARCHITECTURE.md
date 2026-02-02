# Aria Architecture

## Overview

Aria is a scalable data pipeline for processing millions of audio files into LLM-ready training data.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              ARIA DATA PIPELINE                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

     ┌──────────────┐
     │   S3 Raw     │
     │   Audio      │
     │   (Millions) │
     └──────┬───────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              1. COLLECTION                                          │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                 │
│  │  S3 Inventory   │    │   S3 Event      │    │     Lambda      │                 │
│  │  (Backfill)     │───▶│  Notifications  │───▶│   (Validator)   │                 │
│  └─────────────────┘    └─────────────────┘    └────────┬────────┘                 │
│                                                         │                           │
│                                          ┌──────────────┴──────────────┐            │
│                                          ▼                             ▼            │
│                                   ┌────────────┐                ┌────────────┐     │
│                                   │ SQS Queue  │                │  SQS DLQ   │     │
│                                   │ (Process)  │                │ (Invalid)  │     │
│                                   └─────┬──────┘                └────────────┘     │
└─────────────────────────────────────────┼───────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              2. HYDRATION (GPU)                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         EKS + Ray Cluster                                    │   │
│  │   ┌───────────┐    ┌─────────────────────────────────────────────────────┐  │   │
│  │   │ Ray Head  │    │            GPU Workers (g4dn.xlarge)                │  │   │
│  │   │           │◄───│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │  │   │
│  │   │ Scheduler │    │  │ Whisper │ │ Whisper │ │ Whisper │ │ Whisper │   │  │   │
│  │   └───────────┘    │  │ large-v3│ │ large-v3│ │ large-v3│ │ large-v3│   │  │   │
│  │                    │  └─────────┘ └─────────┘ └─────────┘ └─────────┘   │  │   │
│  │                    └─────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  Output: JSON with transcript, confidence, segments, language                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              3. CURATION (CPU)                                      │
│                                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   Quality    │──▶│   Language   │──▶│     PII      │──▶│    Dedup     │        │
│  │   Scoring    │   │   Detection  │   │   Filtering  │   │  (MinHash)   │        │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘        │
│                                                                                     │
│  Quality Tiers:  HIGH (>0.8) │ MEDIUM (0.6-0.8) │ LOW (0.4-0.6) │ REJECTED (<0.4) │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
┌─────────────────────────────────────────┐   ┌─────────────────────────────────────┐
│           4. EMBEDDING                  │   │         5. TOKENIZATION             │
│                                         │   │                                     │
│  ┌──────────────┐   ┌──────────────┐   │   │  ┌──────────────┐   ┌────────────┐ │
│  │    Text      │──▶│   Sentence   │   │   │  │   Tiktoken   │──▶│   Shard    │ │
│  │   Chunking   │   │  Transformer │   │   │  │  Tokenizer   │   │  Creator   │ │
│  │  (512 tok)   │   │  Embeddings  │   │   │  │              │   │ (100M tok) │ │
│  └──────────────┘   └──────────────┘   │   │  └──────────────┘   └────────────┘ │
│           │                             │   │                            │       │
│           ▼                             │   │                            ▼       │
│  ┌──────────────────────┐              │   │  ┌──────────────────────────────┐  │
│  │      LanceDB         │              │   │  │    S3: Parquet Shards        │  │
│  │   (Vector Store)     │              │   │  │    + manifest.json           │  │
│  │                      │              │   │  │                              │  │
│  │  • Similarity search │              │   │  │  Ready for LLM pre-training  │  │
│  │  • Hybrid BM25+kNN   │              │   │  │                              │  │
│  └──────────────────────┘              │   │  └──────────────────────────────┘  │
└─────────────────────────────────────────┘   └─────────────────────────────────────┘
                    │                                           │
                    └─────────────────────┬─────────────────────┘
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE & STATE                                        │
│                                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                  │
│  │    DynamoDB      │  │     LanceDB      │  │       S3         │                  │
│  │   (Job State)    │  │  (Vector Store)  │  │   (Data Lake)    │                  │
│  │                  │  │                  │  │                  │                  │
│  │ • file_id (PK)   │  │ • id             │  │ /hydrated/       │                  │
│  │ • stage (SK)     │  │ • file_id        │  │ /curated/high/   │                  │
│  │ • status         │  │ • text           │  │ /curated/medium/ │                  │
│  │ • quality_score  │  │ • vector[1536]   │  │ /shards/         │                  │
│  │ • output_location│  │ • metadata       │  │ /rejected/       │                  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              ORCHESTRATION                                          │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           Dagster                                            │   │
│  │                                                                              │   │
│  │   Assets:  raw_audio → hydrated → curated → embedded → tokenized_shards     │   │
│  │   Sensors: SQS queue depth, training data threshold                          │   │
│  │   Jobs:    full_pipeline, hydration_only, training_data                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              OBSERVABILITY                                          │
│                                                                                     │
│  CloudWatch          Prometheus/Grafana       Alerts                               │
│  • SQS depth         • Ray metrics            • DLQ > threshold                    │
│  • Lambda errors     • GPU utilization        • Pipeline stalled                   │
│  • DLQ counts        • Processing rate        • Quality degradation                │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages

| Stage | Purpose | Technology | Input | Output |
|-------|---------|------------|-------|--------|
| **Collection** | Ingest files from S3 | S3 Events, SQS, Lambda | S3 audio files | SQS messages |
| **Hydration** | Transcribe audio | Ray, Whisper, EKS GPU | Audio bytes | JSON transcripts |
| **Curation** | Quality filter | MinHash, Presidio, langdetect | Transcripts | Curated JSON |
| **Embedding** | Vectorize for search | Sentence Transformers, LanceDB | Curated text | Vector embeddings |
| **Tokenization** | Prepare for LLM | tiktoken, PyArrow | Curated text | Parquet shards |

---

## Key Components

### Collection
```
S3 Inventory (backfill)  ──┐
                           ├──▶ Lambda (validate) ──▶ SQS Queue
S3 Event Notifications ────┘                              │
                                                          ▼
                                                    Invalid → DLQ
```

### Hydration (GPU Processing)
```
SQS Message
    │
    ▼
┌─────────────────────────────────────────┐
│  Ray Actor: WhisperTranscriber          │
│  ├── Download audio from S3             │
│  ├── Transcode to WAV                   │
│  ├── Run Whisper ASR                    │
│  ├── Extract segments + confidence      │
│  └── Upload JSON to S3                  │
└─────────────────────────────────────────┘
    │
    ▼
s3://output/hydrated/{file_id}.json
```

### Curation Pipeline
```
Input JSON
    │
    ├──▶ QualityScorer
    │       • Confidence score
    │       • Language detection
    │       • Word count / length
    │       • Repetition detection
    │
    ├──▶ Deduplicator (MinHash LSH)
    │       • Near-duplicate detection
    │       • Jaccard similarity > 0.8
    │
    ├──▶ PIIFilter (Presidio)
    │       • Email, phone, SSN
    │       • Names, addresses
    │       • Redact or flag
    │
    ▼
s3://output/curated/{tier}/{file_id}.json
```

### Embedding Pipeline
```
Curated JSON
    │
    ├──▶ TextChunker
    │       • 512 token chunks
    │       • 50 token overlap
    │
    ├──▶ TextEmbedder
    │       • sentence-transformers
    │       • 1536-dim vectors
    │
    ▼
LanceDB (vector store)
    • Similarity search
    • Filter by quality
    • Retrieve by file_id
```

### Tokenization Pipeline
```
Curated JSON (high quality)
    │
    ├──▶ Tokenizer (tiktoken)
    │       • GPT-4 tokenizer
    │       • Count tokens
    │
    ├──▶ Sharder
    │       • 100M tokens per shard
    │       • Track source file_ids
    │
    ▼
s3://output/shards/
    ├── shard_00000.parquet
    ├── shard_00001.parquet
    └── manifest.json
```

---

## Data Flow Summary

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│  S3     │───▶│  SQS    │───▶│  EKS    │───▶│  S3     │───▶│ LanceDB │
│  Raw    │    │  Queue  │    │  Ray    │    │ Curated │    │ Vectors │
│  Audio  │    │         │    │ Whisper │    │         │    │         │
└─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
                                                  │
                                                  ▼
                                            ┌─────────┐
                                            │   S3    │
                                            │ Shards  │
                                            │ (LLM)   │
                                            └─────────┘
```

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Compute** | EKS, Ray, Karpenter (autoscaling) |
| **GPU** | g4dn.xlarge (Spot instances) |
| **Storage** | S3, DynamoDB, LanceDB |
| **Queue** | SQS with DLQ |
| **Orchestration** | Dagster |
| **ML Models** | Whisper large-v3, Sentence Transformers |
| **Observability** | CloudWatch, Prometheus, Grafana |

---

## Error Handling

```
┌─────────────────────────────────────────────────────────────────┐
│                     ERROR HANDLING                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Collection:                                                    │
│    Invalid file format ──▶ DLQ (manual review)                 │
│    File too large ──▶ DLQ                                      │
│                                                                 │
│  Hydration:                                                     │
│    Transcription failed ──▶ Retry 3x ──▶ DLQ                   │
│    GPU OOM ──▶ Retry with smaller batch                        │
│    Spot interruption ──▶ Checkpoint + retry                    │
│                                                                 │
│  Curation:                                                      │
│    Quality < 0.4 ──▶ Rejected bucket                           │
│    Duplicate ──▶ Skip (logged)                                 │
│    PII detected ──▶ Redact and continue                        │
│                                                                 │
│  Embedding:                                                     │
│    Empty content ──▶ Skip                                      │
│    Model error ──▶ Retry                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Cost Optimization

| Strategy | Implementation | Savings |
|----------|---------------|---------|
| Spot Instances | Karpenter + spot pools | ~70% |
| Scale to Zero | No GPU nodes when idle | ~40% off-hours |
| Right-sizing | g4dn.xlarge vs p3.2xlarge | ~50% |
| S3 Tiering | Intelligent tiering for old data | ~30% storage |

---

## Query Interface

### CLI
```bash
aria search "machine learning" --top-k 10
aria validate --check embeddings
aria stats
aria report
```

### API
```
GET  /search?q=...&top_k=10
GET  /document/{id}
GET  /file/{file_id}/chunks
GET  /validate/embeddings
GET  /stats
POST /search (JSON body)
```
