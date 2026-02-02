# Aria Infrastructure (AWS CDK)

AWS CDK Python infrastructure for the Aria data pipeline.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CDK STACKS                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐                                                            │
│  │   SHARED    │  EKS cluster, S3 buckets, DynamoDB                        │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ├──────────────┬──────────────┬──────────────┬──────────────┐      │
│         ▼              ▼              ▼              ▼              ▼      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ COLLECTION │ │ HYDRATION  │ │  CURATION  │ │ EMBEDDING  │ │TOKENIZE  │ │
│  │            │ │            │ │            │ │            │ │          │ │
│  │ S3 Events  │ │ GPU Nodes  │ │ CPU Nodes  │ │ CPU Nodes  │ │CPU Nodes │ │
│  │ SQS + DLQ  │ │ SQS + DLQ  │ │ SQS + DLQ  │ │ SQS + DLQ  │ │Dashboard │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.11+
- AWS CDK CLI: `npm install -g aws-cdk`
- AWS credentials configured

## Setup

```bash
cd iac

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e .

# Bootstrap CDK (first time only)
cdk bootstrap
```

## Deployment

```bash
# Deploy all stacks
cdk deploy --all

# Deploy specific stack
cdk deploy aria-shared-dev

# Deploy with specific environment
cdk deploy --all --context environment=prod
```

## Stacks

| Stack | Resources |
|-------|-----------|
| **shared** | EKS cluster, S3 buckets (raw, output, lancedb), DynamoDB |
| **collection** | SQS queue, S3 event notifications, DLQ alarms |
| **hydration** | GPU node group (g4dn spot), SQS queue |
| **curation** | CPU node group (c5 spot), SQS queue |
| **embedding** | CPU node group, LanceDB S3 access |
| **tokenization** | CPU node group, CloudWatch dashboard |

## Configuration

Edit `cdk.json` context:

```json
{
  "context": {
    "environment": "dev",
    "project": "aria",
    "region": "us-east-1"
  }
}
```

## Useful Commands

```bash
cdk ls              # List all stacks
cdk synth           # Synthesize CloudFormation
cdk diff            # Compare with deployed
cdk deploy --all    # Deploy all stacks
cdk destroy --all   # Destroy all stacks
```

## Cost Optimization

- All node groups use **Spot instances**
- GPU/CPU nodes **scale to zero** when idle
- S3 lifecycle rules auto-tier to IA/Glacier
- DynamoDB uses **pay-per-request** billing
