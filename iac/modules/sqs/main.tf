# SQS Module for Aria

variable "name" {
  description = "Queue name"
  type        = string
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "Visibility timeout in seconds"
  type        = number
  default     = 300
}

variable "message_retention_seconds" {
  description = "Message retention in seconds"
  type        = number
  default     = 1209600 # 14 days
}

variable "max_message_size" {
  description = "Max message size in bytes"
  type        = number
  default     = 262144 # 256 KB
}

variable "delay_seconds" {
  description = "Delay seconds for messages"
  type        = number
  default     = 0
}

variable "receive_wait_time_seconds" {
  description = "Long polling wait time"
  type        = number
  default     = 20
}

variable "enable_dlq" {
  description = "Enable dead letter queue"
  type        = bool
  default     = true
}

variable "max_receive_count" {
  description = "Max receives before sending to DLQ"
  type        = number
  default     = 3
}

variable "enable_s3_notifications" {
  description = "Allow S3 to send notifications"
  type        = bool
  default     = false
}

variable "s3_bucket_arns" {
  description = "S3 bucket ARNs allowed to send notifications"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

locals {
  common_tags = merge(var.tags, {
    Project     = "aria"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

# Dead Letter Queue
resource "aws_sqs_queue" "dlq" {
  count = var.enable_dlq ? 1 : 0
  name  = "${var.name}-dlq"

  message_retention_seconds = 1209600 # 14 days

  tags = merge(local.common_tags, {
    Name = "${var.name}-dlq"
  })
}

# Main Queue
resource "aws_sqs_queue" "main" {
  name = var.name

  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  max_message_size           = var.max_message_size
  delay_seconds              = var.delay_seconds
  receive_wait_time_seconds  = var.receive_wait_time_seconds

  redrive_policy = var.enable_dlq ? jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[0].arn
    maxReceiveCount     = var.max_receive_count
  }) : null

  tags = merge(local.common_tags, {
    Name = var.name
  })
}

# Policy to allow S3 notifications
resource "aws_sqs_queue_policy" "s3_notifications" {
  count     = var.enable_s3_notifications ? 1 : 0
  queue_url = aws_sqs_queue.main.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowS3Notifications"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.main.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = var.s3_bucket_arns
          }
        }
      }
    ]
  })
}

# CloudWatch alarm for DLQ
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  count               = var.enable_dlq ? 1 : 0
  alarm_name          = "${var.name}-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "DLQ has messages - check for processing failures"

  dimensions = {
    QueueName = aws_sqs_queue.dlq[0].name
  }

  tags = local.common_tags
}

# Outputs
output "queue_id" {
  description = "Queue ID"
  value       = aws_sqs_queue.main.id
}

output "queue_arn" {
  description = "Queue ARN"
  value       = aws_sqs_queue.main.arn
}

output "queue_url" {
  description = "Queue URL"
  value       = aws_sqs_queue.main.url
}

output "dlq_id" {
  description = "DLQ ID"
  value       = var.enable_dlq ? aws_sqs_queue.dlq[0].id : null
}

output "dlq_arn" {
  description = "DLQ ARN"
  value       = var.enable_dlq ? aws_sqs_queue.dlq[0].arn : null
}

output "dlq_url" {
  description = "DLQ URL"
  value       = var.enable_dlq ? aws_sqs_queue.dlq[0].url : null
}
