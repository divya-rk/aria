# Aria Architecture

## Overview

Aria is a scalable data pipeline for processing millions of audio files into LLM-ready training data. The pipeline uses an SQS-driven architecture where each stage has its own input queue, enabling failure recovery and independent scaling.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           ARIA SQS-DRIVEN PIPELINE                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘

     ┌──────────────┐
     │   S3 Raw     │
     │   Audio      │
     │   (Millions) │
     └──────┬───────┘
            │ S3 Event Notification
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              SQS-DRIVEN PIPELINE                                     │
│                                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │  Hydration  │    │  Curation   │    │  Embedding  │    │Tokenization │          │
│  │ Input Queue │───▶│ Input Queue │───▶│ Input Queue │───▶│ Input Queue │          │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘          │
│         │                  │                  │                  │                  │
│    ┌────┴────┐        ┌────┴────┐        ┌────┴────┐        ┌────┴────┐            │
│    │   DLQ   │        │   DLQ   │        │   DLQ   │        │   DLQ   │            │
│    └─────────┘        └─────────┘        └─────────┘        └─────────┘            │
│                                                                                      │
│  Each stage: Consume from input queue → Process → Produce to next queue             │
│  On failure: Message goes to DLQ after 3 retries → Manual inspection/retry          │
└─────────────────────────────────────────────────────────────────────────────────────┘

                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              EKS CLUSTER + KARPENTER                                 │
│                                                                                      │
│  ┌───────────────────────────────────────────────────────────────────────────────┐  │
│  │                         KARPENTER NODE PROVISIONER                             │  │
│  │                                                                                │  │
│  │   ┌──────────────────────────┐    ┌──────────────────────────────────────┐   │  │
│  │   │     GPU NodePool         │    │          CPU NodePool                 │   │  │
│  │   │   (hydration workloads)  │    │   (curation/embedding/tokenization)  │   │  │
│  │   │                          │    │                                       │   │  │
│  │   │   • g4dn.xlarge/2xlarge  │    │   • c6i.xlarge-4xlarge (compute)     │   │  │
│  │   │   • Spot preferred       │    │   • m6i.xlarge-4xlarge (general)     │   │  │
│  │   │   • GPU taint            │    │   • Spot preferred                   │   │  │
│  │   │   • Scale 0-100 nodes    │    │   • Scale 0-200 nodes                │   │  │
│  │   └──────────────────────────┘    └──────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                      │
│  ┌───────────────────────────────────────────────────────────────────────────────┐  │
│  │                              KEDA AUTOSCALER                                   │  │
│  │                                                                                │  │
│  │   ScaledObject per stage: Scales pods based on SQS ApproximateMessages        │  │
│  │                                                                                │  │
│  │   hydration-worker: 5 msgs/pod, max 20 pods, cooldown 300s (GPU expensive)    │  │
│  │   curation-worker:  10 msgs/pod, max 30 pods, cooldown 120s                   │  │
│  │   embedding-worker: 10 msgs/pod, max 20 pods, cooldown 120s                   │  │
│  │   tokenization-worker: 20 msgs/pod, max 10 pods, cooldown 300s                │  │
│  └───────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## SQS-Driven Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           DETAILED PIPELINE FLOW                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

  S3 Upload                                                                    S3 Output
     │                                                                              ▲
     │ *.mp3, *.wav, *.flac, *.m4a, *.ogg, *.webm                                  │
     ▼                                                                              │
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│   S3    │────▶│Hydration│────▶│Curation │────▶│Embedding│────▶│Tokenizn │────▶│ Shards  │
│  Event  │     │  Input  │     │  Input  │     │  Input  │     │  Input  │     │ Parquet │
│         │     │  Queue  │     │  Queue  │     │  Queue  │     │  Queue  │     │         │
└─────────┘     └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘     └─────────┘
                     │               │               │               │
                     ▼               ▼               ▼               ▼
              ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
              │ Hydration│    │ Curation │    │ Embedding│    │Tokenizn  │
              │  Worker  │    │  Worker  │    │  Worker  │    │  Worker  │
              │  (GPU)   │    │  (CPU)   │    │  (CPU)   │    │  (CPU)   │
              │          │    │          │    │          │    │          │
              │ Whisper  │    │ Quality  │    │ Vector   │    │ tiktoken │
              │ large-v3 │    │ MinHash  │    │ LanceDB  │    │ Sharder  │
              │          │    │ Presidio │    │          │    │          │
              └──────────┘    └──────────┘    └──────────┘    └──────────┘
                     │               │               │               │
                     ▼               ▼               ▼               ▼
              ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
              │   DLQ    │    │   DLQ    │    │   DLQ    │    │   DLQ    │
              │(3 retries│    │(3 retries│    │(3 retries│    │(3 retries│
              │ → manual)│    │ → manual)│    │ → manual)│    │ → manual)│
              └──────────┘    └──────────┘    └──────────┘    └──────────┘

Key Features:
• Each queue acts as a BREAKPOINT - failures don't propagate downstream
• DLQ captures failures after 3 retries for manual inspection
• Workers scale independently based on queue depth (KEDA)
• Nodes scale dynamically based on pod demand (Karpenter)
• Scale to zero when queues are empty (cost optimization)
```

---

## Karpenter Node Autoscaling

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           KARPENTER ARCHITECTURE                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

                              ┌────────────────────┐
                              │  Karpenter         │
                              │  Controller        │
                              │                    │
                              │  Watches pending   │
                              │  pods, provisions  │
                              │  optimal nodes     │
                              └─────────┬──────────┘
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
   ┌───────────────────┐                                    ┌───────────────────┐
   │  GPU NodePool     │                                    │  CPU NodePool     │
   │                   │                                    │                   │
   │  Label: gpu       │                                    │  Label: cpu       │
   │  Workload:        │                                    │  Workload:        │
   │    hydration      │                                    │    curation       │
   │                   │                                    │    embedding      │
   │  Instances:       │                                    │    tokenization   │
   │    g4dn.xlarge    │                                    │                   │
   │    g4dn.2xlarge   │                                    │  Instances:       │
   │                   │                                    │    c6i.xlarge     │
   │  Capacity:        │                                    │    c6i.2xlarge    │
   │    spot (pref)    │                                    │    c6i.4xlarge    │
   │    on-demand      │                                    │    m6i.xlarge     │
   │                   │                                    │    m6i.2xlarge    │
   │  Taint:           │                                    │                   │
   │    nvidia.com/gpu │                                    │  Capacity:        │
   │                   │                                    │    spot (pref)    │
   │  Disruption:      │                                    │    on-demand      │
   │    consolidate    │                                    │                   │
   │    when empty     │                                    │  Disruption:      │
   │    after 30s      │                                    │    consolidate    │
   └───────────────────┘                                    │    when empty     │
                                                            │    after 30s      │
                                                            └───────────────────┘

Benefits over Managed Node Groups:
• Faster scaling (30-60s vs 5-10min)
• Right-sized instances for each workload
• Automatic consolidation reduces waste
• Native spot instance support with fallback
• Scale to zero capability
```

---

## KEDA Pod Autoscaling

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           KEDA SCALEDOBJECTS                                         │
└─────────────────────────────────────────────────────────────────────────────────────┘

  SQS Queue                ScaledObject                      Deployment
      │                        │                                 │
      │  ApproximateMessages   │                                 │
      │  Visible               │                                 │
      ▼                        ▼                                 ▼
┌──────────────┐        ┌──────────────┐                 ┌──────────────┐
│ aria-        │        │ hydration-   │                 │ hydration-   │
│ hydration-   │───────▶│ scaledobject │────────────────▶│ worker       │
│ input-dev    │        │              │                 │              │
│              │        │ queueLength:5│                 │ replicas:    │
│ ~100 msgs    │        │ min: 0       │                 │   0-20       │
│              │        │ max: 20      │                 │              │
└──────────────┘        │ cooldown:300s│                 │ (GPU pods)   │
                        └──────────────┘                 └──────────────┘

                        ┌──────────────┐                 ┌──────────────┐
                        │ curation-    │                 │ curation-    │
┌──────────────┐        │ scaledobject │                 │ worker       │
│ aria-        │───────▶│              │────────────────▶│              │
│ curation-    │        │ queueLength:10                │ replicas:    │
│ input-dev    │        │ min: 0       │                 │   0-30       │
└──────────────┘        │ max: 30      │                 └──────────────┘
                        └──────────────┘

Scaling Formula: replicas = ceil(messagesVisible / queueLength)

Example: 150 messages in curation queue
         queueLength = 10
         replicas = ceil(150/10) = 15 pods
```

---

## Pipeline Stages

| Stage | Purpose | Technology | Input Queue | Output Queue | Worker Scaling |
|-------|---------|------------|-------------|--------------|----------------|
| **Collection** | Ingest files from S3 | S3 Events → SQS | S3 Event | Hydration Input | N/A (event-driven) |
| **Hydration** | Transcribe audio | Ray, Whisper, GPU | Hydration Input | Curation Input | 0-20 pods, 5 msg/pod |
| **Curation** | Quality filter | MinHash, Presidio | Curation Input | Embedding Input | 0-30 pods, 10 msg/pod |
| **Embedding** | Vectorize for search | Sentence Transformers | Embedding Input | Tokenization Input | 0-20 pods, 10 msg/pod |
| **Tokenization** | Prepare for LLM | tiktoken, PyArrow | Tokenization Input | S3 Shards | 0-10 pods, 20 msg/pod |

---

## Failure Recovery

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           FAILURE RECOVERY MODEL                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

  Message Processing Lifecycle:

  1. Message arrives in queue
         │
         ▼
  2. Worker receives message (visibility timeout starts)
         │
         ├──▶ SUCCESS: Delete message, send to next queue
         │
         └──▶ FAILURE: Message returns to queue after visibility timeout
                   │
                   ├──▶ Retry 1: Process again
                   │
                   ├──▶ Retry 2: Process again
                   │
                   └──▶ Retry 3: Move to DLQ
                             │
                             ▼
                        ┌─────────┐
                        │   DLQ   │ ◀── CloudWatch Alarm (threshold: 10-20)
                        └─────────┘
                             │
                             ▼
                        Manual inspection:
                        • Check error logs
                        • Fix root cause
                        • Redrive to main queue

  Breakpoint Benefits:
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  • Stage failure doesn't affect other stages                                  │
  │  • Messages persist in queue (14 day retention)                               │
  │  • Can pause/resume any stage independently                                   │
  │  • Replay from any point by redriving DLQ                                     │
  │  • Easy debugging: inspect DLQ messages for failure patterns                  │
  └──────────────────────────────────────────────────────────────────────────────┘
```

---

## AWS CDK Stack Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           CDK STACK DEPENDENCIES                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │                        SharedStack                               │
  │                                                                  │
  │  • EKS Cluster (with Karpenter)                                 │
  │  • GPU NodePool (g4dn instances)                                │
  │  • CPU NodePool (c6i/m6i instances)                             │
  │  • S3 Buckets (raw, output, lancedb)                            │
  │  • DynamoDB Table (pipeline state)                              │
  └─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                      CollectionStack                             │
  │                                                                  │
  │  • Hydration Input Queue + DLQ                                  │
  │  • S3 Event Notifications (audio files → queue)                 │
  │  • CloudWatch Alarm (DLQ threshold)                             │
  └─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                       HydrationStack                             │
  │                                                                  │
  │  • Curation Input Queue + DLQ                                   │
  │  • KEDA Helm Chart                                              │
  │  • Hydration ScaledObject (SQS trigger)                         │
  └─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                        CurationStack                             │
  │                                                                  │
  │  • Embedding Input Queue + DLQ                                  │
  │  • Curation ScaledObject                                        │
  └─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                       EmbeddingStack                             │
  │                                                                  │
  │  • Tokenization Input Queue + DLQ                               │
  │  • Embedding ScaledObject                                       │
  └─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                     TokenizationStack                            │
  │                                                                  │
  │  • Tokenization ScaledObject                                    │
  │  • CloudWatch Pipeline Dashboard                                │
  │  • Output: S3 Shards                                            │
  └─────────────────────────────────────────────────────────────────┘
```

---

## Storage & State

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE & STATE                                         │
│                                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                   │
│  │    DynamoDB      │  │     LanceDB      │  │       S3         │                   │
│  │   (Job State)    │  │  (Vector Store)  │  │   (Data Lake)    │                   │
│  │                  │  │                  │  │                  │                   │
│  │ • file_id (PK)   │  │ • id             │  │ /raw/            │                   │
│  │ • stage (SK)     │  │ • file_id        │  │ /hydrated/       │                   │
│  │ • status         │  │ • text           │  │ /curated/high/   │                   │
│  │ • quality_score  │  │ • vector[1536]   │  │ /curated/medium/ │                   │
│  │ • output_location│  │ • metadata       │  │ /shards/         │                   │
│  └──────────────────┘  └──────────────────┘  │ /rejected/       │                   │
│                                              └──────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## CloudWatch Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE DASHBOARD                                         │
│                                                                                      │
│  Pipeline Queue Depths                                                              │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │     ▲                                                                          │ │
│  │ 500 │        ╭──╮                                                              │ │
│  │     │       ╱    ╲      Hydration ───                                          │ │
│  │ 400 │      ╱      ╲     Curation  - - -                                        │ │
│  │     │     ╱        ╲    Embedding ─ ─ ─                                        │ │
│  │ 300 │    ╱          ╲   Tokenization ···                                       │ │
│  │     │   ╱            ╲                                                         │ │
│  │ 200 │  ╱              ╲                                                        │ │
│  │     │ ╱                ╲                                                       │ │
│  │ 100 │╱                  ╲────────────────                                      │ │
│  │     │                                                                          │ │
│  │   0 └────────────────────────────────────────────────────────────────▶ Time    │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  DLQ Messages (Failures)                    S3 Output Bucket                        │
│  ┌─────────────────────────────────────┐   ┌─────────────────────────────────────┐ │
│  │  Hydration DLQ:  ████░░░ 12         │   │  Bucket Size: 1.2 TB                │ │
│  │  Curation DLQ:   ██░░░░░  5         │   │  Objects: 2.4M                      │ │
│  │  Embedding DLQ:  █░░░░░░  2         │   │  Shards: 847                        │ │
│  │  Tokenization:   ░░░░░░░  0         │   │                                     │ │
│  └─────────────────────────────────────┘   └─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Compute** | EKS, Karpenter (node scaling), KEDA (pod scaling) |
| **GPU** | g4dn.xlarge/2xlarge (Spot preferred) |
| **CPU** | c6i/m6i instances (Spot preferred) |
| **Queue** | SQS with DLQ (queue per stage) |
| **Storage** | S3, DynamoDB, LanceDB |
| **IaC** | AWS CDK (Python) |
| **ML Models** | Whisper large-v3, Sentence Transformers |
| **Observability** | CloudWatch (dashboards, alarms) |

---

## Cost Optimization

| Strategy | Implementation | Savings |
|----------|---------------|---------|
| Spot Instances | Karpenter spot pools with on-demand fallback | ~70% |
| Scale to Zero | KEDA minReplicas=0, Karpenter consolidation | ~40% off-hours |
| Right-sizing | Karpenter selects optimal instance type | ~30% |
| Node Consolidation | Karpenter consolidates when pods finish | ~20% |
| S3 Tiering | Intelligent tiering for old data | ~30% storage |

---

## Deployment Commands

```bash
# Install dependencies
cd iac && uv pip install -r requirements.txt

# Deploy all stacks
cdk deploy --all -c environment=dev -c project=aria

# Deploy specific stack
cdk deploy aria-shared-dev
cdk deploy aria-collection-dev
cdk deploy aria-hydration-dev

# Synthesize (preview)
cdk synth

# Diff changes
cdk diff
```

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
