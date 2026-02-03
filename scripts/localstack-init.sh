#!/bin/bash
# LocalStack initialization script for local development
# Creates S3 buckets, SQS queues, and DynamoDB tables

set -e

echo "Initializing LocalStack resources..."

# Create S3 buckets
awslocal s3 mb s3://aria-raw-local
awslocal s3 mb s3://aria-output-local
awslocal s3 mb s3://aria-lancedb-local

echo "Created S3 buckets"

# Create SQS queues with DLQs
# Hydration
awslocal sqs create-queue --queue-name aria-hydration-input-local-dlq
awslocal sqs create-queue --queue-name aria-hydration-input-local \
    --attributes '{
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:aria-hydration-input-local-dlq\",\"maxReceiveCount\":\"3\"}",
        "VisibilityTimeout": "600"
    }'

# Curation
awslocal sqs create-queue --queue-name aria-curation-input-local-dlq
awslocal sqs create-queue --queue-name aria-curation-input-local \
    --attributes '{
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:aria-curation-input-local-dlq\",\"maxReceiveCount\":\"3\"}",
        "VisibilityTimeout": "300"
    }'

# Embedding
awslocal sqs create-queue --queue-name aria-embedding-input-local-dlq
awslocal sqs create-queue --queue-name aria-embedding-input-local \
    --attributes '{
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:aria-embedding-input-local-dlq\",\"maxReceiveCount\":\"3\"}",
        "VisibilityTimeout": "300"
    }'

# Tokenization
awslocal sqs create-queue --queue-name aria-tokenization-input-local-dlq
awslocal sqs create-queue --queue-name aria-tokenization-input-local \
    --attributes '{
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:aria-tokenization-input-local-dlq\",\"maxReceiveCount\":\"3\"}",
        "VisibilityTimeout": "300"
    }'

echo "Created SQS queues"

# Create DynamoDB table for pipeline state
awslocal dynamodb create-table \
    --table-name aria-pipeline-state-local \
    --attribute-definitions \
        AttributeName=file_id,AttributeType=S \
        AttributeName=stage,AttributeType=S \
    --key-schema \
        AttributeName=file_id,KeyType=HASH \
        AttributeName=stage,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST

echo "Created DynamoDB table"

# Set up S3 event notification to SQS (for hydration trigger)
awslocal s3api put-bucket-notification-configuration \
    --bucket aria-raw-local \
    --notification-configuration '{
        "QueueConfigurations": [{
            "QueueArn": "arn:aws:sqs:us-east-1:000000000000:aria-hydration-input-local",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {
                    "FilterRules": [
                        {"Name": "suffix", "Value": ".mp3"},
                        {"Name": "suffix", "Value": ".wav"},
                        {"Name": "suffix", "Value": ".flac"},
                        {"Name": "suffix", "Value": ".m4a"}
                    ]
                }
            }
        }]
    }'

echo "Configured S3 event notifications"
echo "LocalStack initialization complete!"
