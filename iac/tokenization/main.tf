# Tokenization Stack
# Resources for tokenizing and sharding data for LLM training

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
      Stack       = "tokenization"
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

variable "s3_output_bucket" {
  description = "S3 bucket for output (from shared stack)"
  type        = string
}

# -----------------------------------------------------------------------------
# CPU Node Group for Tokenization
# -----------------------------------------------------------------------------

resource "aws_eks_node_group" "tokenization" {
  cluster_name    = var.eks_cluster_name
  node_group_name = "${var.name_prefix}-cpu-tokenization-${var.environment}"
  node_role_arn   = var.eks_node_role_arn
  subnet_ids      = var.subnet_ids

  capacity_type  = "SPOT"
  instance_types = ["m5.large", "m5.xlarge"]
  ami_type       = "AL2_x86_64"

  scaling_config {
    min_size     = 0
    max_size     = 5
    desired_size = 0
  }

  labels = {
    "aria.io/node-type" = "cpu"
    "aria.io/workload"  = "tokenization"
  }

  tags = {
    Name                                                = "${var.name_prefix}-cpu-tokenization-${var.environment}"
    "k8s.io/cluster-autoscaler/enabled"                 = "true"
    "k8s.io/cluster-autoscaler/${var.eks_cluster_name}" = "owned"
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

# -----------------------------------------------------------------------------
# S3 Bucket Policy for Training Shards
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_policy" "training_data_access" {
  bucket = var.s3_output_bucket

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowMLTeamAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_output_bucket}",
          "arn:aws:s3:::${var.s3_output_bucket}/shards/*"
        ]
      }
    ]
  })
}

data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# CloudWatch Dashboard for Tokenization
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "tokenization" {
  dashboard_name = "${var.name_prefix}-tokenization-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Shards Created"
          region = var.aws_region
          metrics = [
            ["AWS/S3", "NumberOfObjects", "BucketName", var.s3_output_bucket, "StorageType", "AllStorageTypes"]
          ]
          period = 3600
          stat   = "Average"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "S3 Bucket Size"
          region = var.aws_region
          metrics = [
            ["AWS/S3", "BucketSizeBytes", "BucketName", var.s3_output_bucket, "StorageType", "StandardStorage"]
          ]
          period = 86400
          stat   = "Average"
        }
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "tokenization_node_group_name" {
  description = "Tokenization node group name"
  value       = aws_eks_node_group.tokenization.node_group_name
}

output "training_shards_path" {
  description = "S3 path for training shards"
  value       = "s3://${var.s3_output_bucket}/shards/"
}

output "dashboard_url" {
  description = "CloudWatch dashboard URL"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${var.name_prefix}-tokenization-${var.environment}"
}
