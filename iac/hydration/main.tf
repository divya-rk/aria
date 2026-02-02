# Hydration Stack
# GPU node group for Whisper transcription with Ray

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
      Stack       = "hydration"
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

variable "gpu_instance_types" {
  description = "GPU instance types for Whisper"
  type        = list(string)
  default     = ["g4dn.xlarge", "g4dn.2xlarge"]
}

variable "gpu_min_size" {
  description = "Minimum GPU nodes"
  type        = number
  default     = 0
}

variable "gpu_max_size" {
  description = "Maximum GPU nodes"
  type        = number
  default     = 10
}

variable "gpu_desired_size" {
  description = "Desired GPU nodes"
  type        = number
  default     = 0
}

variable "use_spot_instances" {
  description = "Use spot instances for cost savings"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# GPU Node Group
# -----------------------------------------------------------------------------

resource "aws_eks_node_group" "gpu" {
  cluster_name    = var.eks_cluster_name
  node_group_name = "${var.name_prefix}-gpu-${var.environment}"
  node_role_arn   = var.eks_node_role_arn
  subnet_ids      = var.subnet_ids

  capacity_type  = var.use_spot_instances ? "SPOT" : "ON_DEMAND"
  instance_types = var.gpu_instance_types
  ami_type       = "AL2_x86_64_GPU"

  scaling_config {
    min_size     = var.gpu_min_size
    max_size     = var.gpu_max_size
    desired_size = var.gpu_desired_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    "aria.io/node-type"   = "gpu"
    "aria.io/workload"    = "hydration"
    "nvidia.com/gpu"      = "true"
  }

  taint {
    key    = "nvidia.com/gpu"
    value  = "true"
    effect = "NO_SCHEDULE"
  }

  tags = {
    Name                                              = "${var.name_prefix}-gpu-${var.environment}"
    "k8s.io/cluster-autoscaler/enabled"               = "true"
    "k8s.io/cluster-autoscaler/${var.eks_cluster_name}" = "owned"
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

# -----------------------------------------------------------------------------
# SQS Queue for Hydration
# -----------------------------------------------------------------------------

module "sqs_hydration" {
  source = "../modules/sqs"

  name                       = "${var.name_prefix}-hydration-${var.environment}"
  environment                = var.environment
  visibility_timeout_seconds = 600 # 10 minutes for GPU processing
  enable_dlq                 = true
  max_receive_count          = 3
}

# -----------------------------------------------------------------------------
# IAM Policy for Ray Workers (S3 + SQS access)
# -----------------------------------------------------------------------------

resource "aws_iam_policy" "ray_worker" {
  name        = "${var.name_prefix}-ray-worker-${var.environment}"
  description = "Policy for Ray workers to access S3 and SQS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.name_prefix}-*",
          "arn:aws:s3:::${var.name_prefix}-*/*"
        ]
      },
      {
        Sid    = "SQSAccess"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:SendMessage"
        ]
        Resource = [
          module.sqs_hydration.queue_arn,
          module.sqs_hydration.dlq_arn
        ]
      },
      {
        Sid    = "DynamoDBAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = [
          "arn:aws:dynamodb:${var.aws_region}:*:table/${var.name_prefix}-jobs-*"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# CloudWatch Alarms
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "hydration_dlq" {
  alarm_name          = "${var.name_prefix}-hydration-dlq-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Hydration DLQ has messages - transcription failures"

  dimensions = {
    QueueName = "${var.name_prefix}-hydration-${var.environment}-dlq"
  }
}

resource "aws_cloudwatch_metric_alarm" "gpu_utilization" {
  alarm_name          = "${var.name_prefix}-gpu-utilization-${var.environment}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "node_gpu_utilization"
  namespace           = "ContainerInsights"
  period              = 300
  statistic           = "Average"
  threshold           = 50
  alarm_description   = "GPU utilization is low - consider scaling down"

  dimensions = {
    ClusterName = var.eks_cluster_name
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "gpu_node_group_name" {
  description = "GPU node group name"
  value       = aws_eks_node_group.gpu.node_group_name
}

output "hydration_queue_url" {
  description = "Hydration SQS queue URL"
  value       = module.sqs_hydration.queue_url
}

output "hydration_queue_arn" {
  description = "Hydration SQS queue ARN"
  value       = module.sqs_hydration.queue_arn
}

output "hydration_dlq_url" {
  description = "Hydration DLQ URL"
  value       = module.sqs_hydration.dlq_url
}

output "ray_worker_policy_arn" {
  description = "IAM policy ARN for Ray workers"
  value       = aws_iam_policy.ray_worker.arn
}
