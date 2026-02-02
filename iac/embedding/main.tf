# Embedding Stack
# Resources for vector embedding and LanceDB

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "aria"
      Environment = var.environment
      ManagedBy   = "terraform"
      Stack       = "embedding"
    }
  }
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
  default     = "dev"
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "aria"
}

variable "eks_cluster_name" {
  description = "EKS cluster name (from shared stack)"
  type        = string
}

variable "eks_node_role_arn" {
  description = "EKS node IAM role ARN (from shared stack)"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for node group (from shared stack)"
  type        = list(string)
}

variable "s3_lancedb_bucket" {
  description = "S3 bucket for LanceDB (from shared stack)"
  type        = string
}

variable "cpu_instance_types" {
  description = "CPU instance types for embedding"
  type        = list(string)
  default     = ["c5.xlarge", "c5.2xlarge"]
}

variable "cpu_min_size" {
  description = "Minimum CPU nodes"
  type        = number
  default     = 0
}

variable "cpu_max_size" {
  description = "Maximum CPU nodes"
  type        = number
  default     = 10
}

variable "cpu_desired_size" {
  description = "Desired CPU nodes"
  type        = number
  default     = 1
}

# -----------------------------------------------------------------------------
# CPU Node Group for Embedding
# -----------------------------------------------------------------------------

resource "aws_eks_node_group" "embedding" {
  cluster_name    = var.eks_cluster_name
  node_group_name = "${var.name_prefix}-cpu-embedding-${var.environment}"
  node_role_arn   = var.eks_node_role_arn
  subnet_ids      = var.subnet_ids

  capacity_type  = "SPOT"
  instance_types = var.cpu_instance_types
  ami_type       = "AL2_x86_64"

  scaling_config {
    min_size     = var.cpu_min_size
    max_size     = var.cpu_max_size
    desired_size = var.cpu_desired_size
  }

  labels = {
    "aria.io/node-type" = "cpu"
    "aria.io/workload"  = "embedding"
  }

  tags = {
    Name                                                = "${var.name_prefix}-cpu-embedding-${var.environment}"
    "k8s.io/cluster-autoscaler/enabled"                 = "true"
    "k8s.io/cluster-autoscaler/${var.eks_cluster_name}" = "owned"
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

# -----------------------------------------------------------------------------
# SQS Queue for Embedding
# -----------------------------------------------------------------------------

module "sqs_embedding" {
  source = "../modules/sqs"

  name                       = "${var.name_prefix}-embedding-${var.environment}"
  environment                = var.environment
  visibility_timeout_seconds = 300
  enable_dlq                 = true
  max_receive_count          = 3
}

# -----------------------------------------------------------------------------
# IAM Policy for LanceDB S3 Access
# -----------------------------------------------------------------------------

resource "aws_iam_policy" "lancedb_access" {
  name        = "${var.name_prefix}-lancedb-access-${var.environment}"
  description = "Policy for LanceDB S3 access"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LanceDBBucketAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_lancedb_bucket}",
          "arn:aws:s3:::${var.s3_lancedb_bucket}/*"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# CloudWatch Alarms
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "embedding_dlq" {
  alarm_name          = "${var.name_prefix}-embedding-dlq-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 20
  alarm_description   = "Embedding DLQ has messages"

  dimensions = {
    QueueName = "${var.name_prefix}-embedding-${var.environment}-dlq"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "embedding_node_group_name" {
  description = "Embedding node group name"
  value       = aws_eks_node_group.embedding.node_group_name
}

output "embedding_queue_url" {
  description = "Embedding SQS queue URL"
  value       = module.sqs_embedding.queue_url
}

output "embedding_queue_arn" {
  description = "Embedding SQS queue ARN"
  value       = module.sqs_embedding.queue_arn
}

output "lancedb_policy_arn" {
  description = "LanceDB IAM policy ARN"
  value       = aws_iam_policy.lancedb_access.arn
}
