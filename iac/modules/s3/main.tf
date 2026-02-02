# S3 Module for Aria

variable "name" {
  description = "Bucket name"
  type        = string
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
}

variable "enable_versioning" {
  description = "Enable versioning"
  type        = bool
  default     = true
}

variable "enable_lifecycle" {
  description = "Enable lifecycle rules"
  type        = bool
  default     = true
}

variable "lifecycle_days_to_ia" {
  description = "Days before transitioning to IA"
  type        = number
  default     = 90
}

variable "lifecycle_days_to_glacier" {
  description = "Days before transitioning to Glacier"
  type        = number
  default     = 365
}

variable "enable_event_notifications" {
  description = "Enable S3 event notifications"
  type        = bool
  default     = false
}

variable "notification_queue_arn" {
  description = "SQS queue ARN for notifications"
  type        = string
  default     = ""
}

variable "notification_events" {
  description = "S3 events to notify on"
  type        = list(string)
  default     = ["s3:ObjectCreated:*"]
}

variable "notification_prefix" {
  description = "Object key prefix filter"
  type        = string
  default     = ""
}

variable "notification_suffix" {
  description = "Object key suffix filter"
  type        = string
  default     = ""
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

# S3 Bucket
resource "aws_s3_bucket" "main" {
  bucket = var.name

  tags = merge(local.common_tags, {
    Name = var.name
  })
}

# Block public access
resource "aws_s3_bucket_public_access_block" "main" {
  bucket = aws_s3_bucket.main.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning
resource "aws_s3_bucket_versioning" "main" {
  bucket = aws_s3_bucket.main.id

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Disabled"
  }
}

# Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Lifecycle rules
resource "aws_s3_bucket_lifecycle_configuration" "main" {
  count  = var.enable_lifecycle ? 1 : 0
  bucket = aws_s3_bucket.main.id

  rule {
    id     = "intelligent-tiering"
    status = "Enabled"

    transition {
      days          = var.lifecycle_days_to_ia
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = var.lifecycle_days_to_glacier
      storage_class = "GLACIER"
    }

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Event notifications
resource "aws_s3_bucket_notification" "main" {
  count  = var.enable_event_notifications ? 1 : 0
  bucket = aws_s3_bucket.main.id

  queue {
    queue_arn     = var.notification_queue_arn
    events        = var.notification_events
    filter_prefix = var.notification_prefix
    filter_suffix = var.notification_suffix
  }
}

# Outputs
output "bucket_id" {
  description = "Bucket ID"
  value       = aws_s3_bucket.main.id
}

output "bucket_arn" {
  description = "Bucket ARN"
  value       = aws_s3_bucket.main.arn
}

output "bucket_domain_name" {
  description = "Bucket domain name"
  value       = aws_s3_bucket.main.bucket_domain_name
}
