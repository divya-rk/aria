# DynamoDB Module for Aria

variable "name" {
  description = "Table name"
  type        = string
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
}

variable "billing_mode" {
  description = "Billing mode (PROVISIONED or PAY_PER_REQUEST)"
  type        = string
  default     = "PAY_PER_REQUEST"
}

variable "read_capacity" {
  description = "Read capacity units (only for PROVISIONED)"
  type        = number
  default     = 5
}

variable "write_capacity" {
  description = "Write capacity units (only for PROVISIONED)"
  type        = number
  default     = 5
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery"
  type        = bool
  default     = true
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

# DynamoDB Table
resource "aws_dynamodb_table" "main" {
  name         = var.name
  billing_mode = var.billing_mode

  # Only set capacity if provisioned
  read_capacity  = var.billing_mode == "PROVISIONED" ? var.read_capacity : null
  write_capacity = var.billing_mode == "PROVISIONED" ? var.write_capacity : null

  # Primary key: file_id (partition) + stage (sort)
  hash_key  = "file_id"
  range_key = "stage"

  attribute {
    name = "file_id"
    type = "S"
  }

  attribute {
    name = "stage"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  # GSI for querying by status
  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    range_key       = "stage"
    projection_type = "ALL"

    read_capacity  = var.billing_mode == "PROVISIONED" ? var.read_capacity : null
    write_capacity = var.billing_mode == "PROVISIONED" ? var.write_capacity : null
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(local.common_tags, {
    Name = var.name
  })
}

# Outputs
output "table_id" {
  description = "Table ID"
  value       = aws_dynamodb_table.main.id
}

output "table_arn" {
  description = "Table ARN"
  value       = aws_dynamodb_table.main.arn
}

output "table_name" {
  description = "Table name"
  value       = aws_dynamodb_table.main.name
}
