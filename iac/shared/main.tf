# Shared Infrastructure Stack
# Resources used by all pipeline stages

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment for remote state
  # backend "s3" {
  #   bucket         = "aria-terraform-state"
  #   key            = "shared/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "aria-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "aria"
      Environment = var.environment
      ManagedBy   = "terraform"
      Stack       = "shared"
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

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_caller_identity" "current" {}

locals {
  vpc_id     = data.aws_vpc.default.id
  subnet_ids = data.aws_subnets.default.ids
}

# -----------------------------------------------------------------------------
# EKS Cluster
# -----------------------------------------------------------------------------

module "eks" {
  source = "../modules/eks"

  name               = var.name_prefix
  environment        = var.environment
  vpc_id             = local.vpc_id
  subnet_ids         = local.subnet_ids
  kubernetes_version = "1.29"
}

# -----------------------------------------------------------------------------
# S3 Buckets
# -----------------------------------------------------------------------------

module "s3_raw" {
  source = "../modules/s3"

  name              = "${var.name_prefix}-raw-${var.environment}"
  environment       = var.environment
  enable_versioning = false
  enable_lifecycle  = true
}

module "s3_output" {
  source = "../modules/s3"

  name              = "${var.name_prefix}-output-${var.environment}"
  environment       = var.environment
  enable_versioning = true
  enable_lifecycle  = true
}

module "s3_lancedb" {
  source = "../modules/s3"

  name              = "${var.name_prefix}-lancedb-${var.environment}"
  environment       = var.environment
  enable_versioning = false
  enable_lifecycle  = false
}

# -----------------------------------------------------------------------------
# DynamoDB
# -----------------------------------------------------------------------------

module "dynamodb_jobs" {
  source = "../modules/dynamodb"

  name        = "${var.name_prefix}-jobs-${var.environment}"
  environment = var.environment
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "vpc_id" {
  description = "VPC ID"
  value       = local.vpc_id
}

output "subnet_ids" {
  description = "Subnet IDs"
  value       = local.subnet_ids
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_node_role_arn" {
  description = "EKS node IAM role ARN"
  value       = module.eks.node_role_arn
}

output "eks_oidc_provider_arn" {
  description = "EKS OIDC provider ARN"
  value       = module.eks.oidc_provider_arn
}

output "s3_raw_bucket" {
  description = "Raw audio S3 bucket"
  value       = module.s3_raw.bucket_id
}

output "s3_output_bucket" {
  description = "Output S3 bucket"
  value       = module.s3_output.bucket_id
}

output "s3_lancedb_bucket" {
  description = "LanceDB S3 bucket"
  value       = module.s3_lancedb.bucket_id
}

output "dynamodb_jobs_table" {
  description = "DynamoDB jobs table name"
  value       = module.dynamodb_jobs.table_name
}
