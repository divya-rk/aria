# Curation Stack
# CPU node group for quality filtering, dedup, PII

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
      Stack       = "curation"
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

variable "cpu_instance_types" {
  description = "CPU instance types for curation"
  type        = list(string)
  default     = ["c5.2xlarge", "c5.4xlarge"]
}

variable "cpu_min_size" {
  description = "Minimum CPU nodes"
  type        = number
  default     = 0
}

variable "cpu_max_size" {
  description = "Maximum CPU nodes"
  type        = number
  default     = 20
}

variable "cpu_desired_size" {
  description = "Desired CPU nodes"
  type        = number
  default     = 1
}

variable "use_spot_instances" {
  description = "Use spot instances for cost savings"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# CPU Node Group
# -----------------------------------------------------------------------------

resource "aws_eks_node_group" "cpu" {
  cluster_name    = var.eks_cluster_name
  node_group_name = "${var.name_prefix}-cpu-curation-${var.environment}"
  node_role_arn   = var.eks_node_role_arn
  subnet_ids      = var.subnet_ids

  capacity_type  = var.use_spot_instances ? "SPOT" : "ON_DEMAND"
  instance_types = var.cpu_instance_types
  ami_type       = "AL2_x86_64"

  scaling_config {
    min_size     = var.cpu_min_size
    max_size     = var.cpu_max_size
    desired_size = var.cpu_desired_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    "aria.io/node-type" = "cpu"
    "aria.io/workload"  = "curation"
  }

  tags = {
    Name                                                = "${var.name_prefix}-cpu-curation-${var.environment}"
    "k8s.io/cluster-autoscaler/enabled"                 = "true"
    "k8s.io/cluster-autoscaler/${var.eks_cluster_name}" = "owned"
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

# -----------------------------------------------------------------------------
# SQS Queue for Curation
# -----------------------------------------------------------------------------

module "sqs_curation" {
  source = "../modules/sqs"

  name                       = "${var.name_prefix}-curation-${var.environment}"
  environment                = var.environment
  visibility_timeout_seconds = 300 # 5 minutes
  enable_dlq                 = true
  max_receive_count          = 3
}

# -----------------------------------------------------------------------------
# CloudWatch Alarms
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "curation_dlq" {
  alarm_name          = "${var.name_prefix}-curation-dlq-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 50
  alarm_description   = "Curation DLQ has messages - quality/dedup failures"

  dimensions = {
    QueueName = "${var.name_prefix}-curation-${var.environment}-dlq"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "cpu_node_group_name" {
  description = "CPU node group name"
  value       = aws_eks_node_group.cpu.node_group_name
}

output "curation_queue_url" {
  description = "Curation SQS queue URL"
  value       = module.sqs_curation.queue_url
}

output "curation_queue_arn" {
  description = "Curation SQS queue ARN"
  value       = module.sqs_curation.queue_arn
}

output "curation_dlq_url" {
  description = "Curation DLQ URL"
  value       = module.sqs_curation.dlq_url
}
