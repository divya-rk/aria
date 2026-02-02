# Aria Infrastructure as Code

Terraform modules for deploying Aria data pipeline on AWS.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              STACKS                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐                                                            │
│  │   SHARED    │  VPC (optional), EKS, S3 buckets, DynamoDB                │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ├──────────────┬──────────────┬──────────────┬──────────────┐      │
│         ▼              ▼              ▼              ▼              ▼      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ COLLECTION │ │ HYDRATION  │ │  CURATION  │ │ EMBEDDING  │ │TOKENIZE  │ │
│  │            │ │            │ │            │ │            │ │          │ │
│  │ S3 Events  │ │ GPU Nodes  │ │ CPU Nodes  │ │ CPU Nodes  │ │CPU Nodes │ │
│  │ SQS Queue  │ │ SQS Queue  │ │ SQS Queue  │ │ SQS Queue  │ │Dashboard │ │
│  │ Lambda     │ │ IAM Policy │ │ Alarms     │ │ LanceDB    │ │          │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
iac/
├── modules/           # Reusable Terraform modules
│   ├── eks/          # EKS cluster, node IAM roles
│   ├── s3/           # S3 buckets with lifecycle
│   ├── sqs/          # SQS queues with DLQ
│   └── dynamodb/     # DynamoDB tables
│
├── shared/           # Shared infrastructure (deploy first)
├── collection/       # S3 events, SQS, Lambda validator
├── hydration/        # GPU node group for Whisper
├── curation/         # CPU node group for quality/dedup
├── embedding/        # CPU nodes, LanceDB S3 access
└── tokenization/     # CPU nodes, training data output
```

## Deployment Order

```bash
# 1. Deploy shared infrastructure first
cd shared
terraform init
terraform apply

# 2. Deploy pipeline stacks (can be parallel)
cd ../collection && terraform init && terraform apply
cd ../hydration && terraform init && terraform apply
cd ../curation && terraform init && terraform apply
cd ../embedding && terraform init && terraform apply
cd ../tokenization && terraform init && terraform apply
```

## Stack Dependencies

| Stack | Depends On | Outputs Used |
|-------|------------|--------------|
| shared | - | vpc_id, subnet_ids, eks_*, s3_*, dynamodb_* |
| collection | shared | s3_raw_bucket_arn, s3_raw_bucket_id |
| hydration | shared | eks_cluster_name, eks_node_role_arn, subnet_ids |
| curation | shared | eks_cluster_name, eks_node_role_arn, subnet_ids |
| embedding | shared | eks_cluster_name, eks_node_role_arn, subnet_ids, s3_lancedb_bucket |
| tokenization | shared | eks_cluster_name, eks_node_role_arn, subnet_ids, s3_output_bucket |

## Configuration

### Environment Variables

Create `terraform.tfvars` in each stack:

```hcl
# shared/terraform.tfvars
aws_region  = "us-east-1"
environment = "dev"
name_prefix = "aria"
```

```hcl
# hydration/terraform.tfvars
aws_region         = "us-east-1"
environment        = "dev"
eks_cluster_name   = "aria-eks"
eks_node_role_arn  = "arn:aws:iam::xxx:role/aria-eks-node-role"
subnet_ids         = ["subnet-xxx", "subnet-yyy"]
gpu_min_size       = 0
gpu_max_size       = 10
use_spot_instances = true
```

### Remote State

For team collaboration, configure S3 backend:

```hcl
# In each stack's main.tf
terraform {
  backend "s3" {
    bucket         = "aria-terraform-state"
    key            = "shared/terraform.tfstate"  # Change per stack
    region         = "us-east-1"
    dynamodb_table = "aria-terraform-locks"
    encrypt        = true
  }
}
```

## Cost Optimization

| Feature | Implementation |
|---------|---------------|
| Spot Instances | GPU and CPU node groups use spot by default |
| Scale to Zero | All node groups have `min_size = 0` |
| Lifecycle Rules | S3 buckets auto-tier to IA/Glacier |
| Pay-per-request | DynamoDB uses on-demand billing |

## Modules

### EKS Module
- EKS cluster with OIDC provider
- Node IAM role with S3 access
- Cluster logging enabled

### S3 Module
- Server-side encryption
- Lifecycle rules for cost optimization
- Optional event notifications

### SQS Module
- Dead letter queue
- CloudWatch alarms for DLQ depth
- S3 notification permissions

### DynamoDB Module
- On-demand billing
- Point-in-time recovery
- GSI for status queries
