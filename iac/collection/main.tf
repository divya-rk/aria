# Collection Stack
# S3 events, SQS queues, Lambda validator

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
      Stack       = "collection"
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

variable "s3_raw_bucket_arn" {
  description = "ARN of raw audio S3 bucket (from shared stack)"
  type        = string
}

variable "s3_raw_bucket_id" {
  description = "ID of raw audio S3 bucket (from shared stack)"
  type        = string
}

# -----------------------------------------------------------------------------
# SQS Queues
# -----------------------------------------------------------------------------

module "sqs_ingestion" {
  source = "../modules/sqs"

  name                       = "${var.name_prefix}-ingestion-${var.environment}"
  environment                = var.environment
  visibility_timeout_seconds = 300 # 5 minutes for processing
  enable_dlq                 = true
  max_receive_count          = 3
  enable_s3_notifications    = true
  s3_bucket_arns             = [var.s3_raw_bucket_arn]
}

# -----------------------------------------------------------------------------
# S3 Event Notification
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_notification" "raw_audio" {
  bucket = var.s3_raw_bucket_id

  queue {
    queue_arn     = module.sqs_ingestion.queue_arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".mp3"
  }

  queue {
    queue_arn     = module.sqs_ingestion.queue_arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".wav"
  }

  queue {
    queue_arn     = module.sqs_ingestion.queue_arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".flac"
  }

  queue {
    queue_arn     = module.sqs_ingestion.queue_arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".m4a"
  }
}

# -----------------------------------------------------------------------------
# Lambda Validator (Optional - for pre-filtering)
# -----------------------------------------------------------------------------

data "archive_file" "validator_lambda" {
  type        = "zip"
  output_path = "${path.module}/lambda/validator.zip"

  source {
    content  = <<-EOF
      import json
      import boto3
      import os

      sqs = boto3.client('sqs')
      QUEUE_URL = os.environ['QUEUE_URL']
      DLQ_URL = os.environ['DLQ_URL']
      MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 500 * 1024 * 1024))  # 500MB

      VALID_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.webm'}

      def handler(event, context):
          for record in event.get('Records', []):
              body = json.loads(record['body'])

              for s3_record in body.get('Records', []):
                  bucket = s3_record['s3']['bucket']['name']
                  key = s3_record['s3']['object']['key']
                  size = s3_record['s3']['object'].get('size', 0)

                  # Validate extension
                  ext = '.' + key.lower().split('.')[-1] if '.' in key else ''
                  if ext not in VALID_EXTENSIONS:
                      send_to_dlq(record, f'Invalid extension: {ext}')
                      continue

                  # Validate size
                  if size > MAX_FILE_SIZE:
                      send_to_dlq(record, f'File too large: {size} bytes')
                      continue

                  # Valid - forward to processing queue
                  print(f'Valid file: s3://{bucket}/{key} ({size} bytes)')

          return {'statusCode': 200}

      def send_to_dlq(record, reason):
          print(f'Rejecting: {reason}')
          sqs.send_message(
              QueueUrl=DLQ_URL,
              MessageBody=record['body'],
              MessageAttributes={
                  'RejectReason': {'DataType': 'String', 'StringValue': reason}
              }
          )
    EOF
    filename = "index.py"
  }
}

resource "aws_iam_role" "validator_lambda" {
  name = "${var.name_prefix}-validator-lambda-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "validator_lambda" {
  name = "${var.name_prefix}-validator-lambda-policy"
  role = aws_iam_role.validator_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:SendMessage"
        ]
        Resource = [
          module.sqs_ingestion.queue_arn,
          module.sqs_ingestion.dlq_arn
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "validator" {
  filename         = data.archive_file.validator_lambda.output_path
  function_name    = "${var.name_prefix}-validator-${var.environment}"
  role             = aws_iam_role.validator_lambda.arn
  handler          = "index.handler"
  source_code_hash = data.archive_file.validator_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30

  environment {
    variables = {
      QUEUE_URL     = module.sqs_ingestion.queue_url
      DLQ_URL       = module.sqs_ingestion.dlq_url
      MAX_FILE_SIZE = "524288000" # 500MB
    }
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Alarms
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${var.name_prefix}-ingestion-queue-depth-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = 10000
  alarm_description   = "Ingestion queue depth is high"

  dimensions = {
    QueueName = "${var.name_prefix}-ingestion-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "ingestion_queue_url" {
  description = "Ingestion SQS queue URL"
  value       = module.sqs_ingestion.queue_url
}

output "ingestion_queue_arn" {
  description = "Ingestion SQS queue ARN"
  value       = module.sqs_ingestion.queue_arn
}

output "ingestion_dlq_url" {
  description = "Ingestion DLQ URL"
  value       = module.sqs_ingestion.dlq_url
}

output "validator_lambda_arn" {
  description = "Validator Lambda ARN"
  value       = aws_lambda_function.validator.arn
}
