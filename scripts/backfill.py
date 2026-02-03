#!/usr/bin/env python3
"""Backfill script for processing existing S3 files through the pipeline.

This script lists files in the raw S3 bucket and sends them to the hydration
input queue for processing. Useful for:
- Initial data load
- Reprocessing after pipeline changes
- Recovery from failures

Usage:
    python scripts/backfill.py --bucket aria-raw-prod --prefix audio/ --limit 1000
    python scripts/backfill.py --bucket aria-raw-prod --dry-run
    python scripts/backfill.py --file-list files.txt
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Supported audio extensions
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm"}


def get_aws_clients(region: str, endpoint_url: str | None = None):
    """Create AWS clients."""
    config = Config(
        region_name=region,
        retries={"max_attempts": 3, "mode": "adaptive"},
    )
    kwargs = {"config": config}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    s3 = boto3.client("s3", **kwargs)
    sqs = boto3.client("sqs", **kwargs)
    return s3, sqs


def list_audio_files(
    s3_client,
    bucket: str,
    prefix: str = "",
    limit: int | None = None,
) -> list[dict]:
    """List audio files in S3 bucket."""
    files = []
    paginator = s3_client.get_paginator("list_objects_v2")

    logger.info(f"Listing files in s3://{bucket}/{prefix}")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            ext = Path(key).suffix.lower()

            if ext in AUDIO_EXTENSIONS:
                files.append({
                    "bucket": bucket,
                    "key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                })

                if limit and len(files) >= limit:
                    logger.info(f"Reached limit of {limit} files")
                    return files

    logger.info(f"Found {len(files)} audio files")
    return files


def load_file_list(file_path: str) -> list[dict]:
    """Load file list from a text file (one S3 URI per line)."""
    files = []
    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse s3://bucket/key format
            if line.startswith("s3://"):
                parts = line[5:].split("/", 1)
                if len(parts) == 2:
                    files.append({
                        "bucket": parts[0],
                        "key": parts[1],
                        "size": 0,  # Unknown
                        "last_modified": None,
                    })

    logger.info(f"Loaded {len(files)} files from {file_path}")
    return files


def create_s3_event_message(file_info: dict) -> dict:
    """Create an S3 event notification message."""
    return {
        "Records": [
            {
                "eventSource": "aws:s3",
                "eventName": "ObjectCreated:Put",
                "eventTime": datetime.utcnow().isoformat() + "Z",
                "s3": {
                    "bucket": {"name": file_info["bucket"]},
                    "object": {
                        "key": file_info["key"],
                        "size": file_info["size"],
                    },
                },
            }
        ]
    }


def send_to_queue(
    sqs_client,
    queue_url: str,
    files: list[dict],
    batch_size: int = 10,
    dry_run: bool = False,
) -> int:
    """Send files to SQS queue in batches."""
    sent_count = 0

    for i in range(0, len(files), batch_size):
        batch = files[i : i + batch_size]
        entries = []

        for j, file_info in enumerate(batch):
            message = create_s3_event_message(file_info)
            entries.append({
                "Id": str(j),
                "MessageBody": json.dumps(message),
            })

        if dry_run:
            logger.info(f"[DRY RUN] Would send {len(entries)} messages")
            for entry in entries:
                body = json.loads(entry["MessageBody"])
                key = body["Records"][0]["s3"]["object"]["key"]
                logger.debug(f"  - {key}")
            sent_count += len(entries)
        else:
            response = sqs_client.send_message_batch(
                QueueUrl=queue_url,
                Entries=entries,
            )

            successful = len(response.get("Successful", []))
            failed = len(response.get("Failed", []))

            sent_count += successful

            if failed > 0:
                logger.warning(f"Failed to send {failed} messages")
                for failure in response.get("Failed", []):
                    logger.error(f"  - {failure['Id']}: {failure['Message']}")

        logger.info(f"Progress: {sent_count}/{len(files)} files sent")

    return sent_count


def main():
    parser = argparse.ArgumentParser(
        description="Backfill existing S3 files through the Aria pipeline"
    )
    parser.add_argument(
        "--bucket",
        required=False,
        help="S3 bucket containing audio files",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="S3 key prefix to filter files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of files to process",
    )
    parser.add_argument(
        "--file-list",
        help="Path to file containing S3 URIs (one per line)",
    )
    parser.add_argument(
        "--queue-url",
        required=True,
        help="Hydration input queue URL",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region",
    )
    parser.add_argument(
        "--endpoint-url",
        help="Custom AWS endpoint URL (for LocalStack)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="SQS batch size (max 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without sending to queue",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate arguments
    if not args.bucket and not args.file_list:
        parser.error("Either --bucket or --file-list is required")

    # Initialize AWS clients
    s3_client, sqs_client = get_aws_clients(args.region, args.endpoint_url)

    # Get file list
    if args.file_list:
        files = load_file_list(args.file_list)
    else:
        files = list_audio_files(
            s3_client,
            args.bucket,
            args.prefix,
            args.limit,
        )

    if not files:
        logger.warning("No files found to process")
        sys.exit(0)

    # Send to queue
    logger.info(f"Sending {len(files)} files to {args.queue_url}")
    sent_count = send_to_queue(
        sqs_client,
        args.queue_url,
        files,
        args.batch_size,
        args.dry_run,
    )

    logger.info(f"Backfill complete: {sent_count} files {'would be ' if args.dry_run else ''}sent to queue")


if __name__ == "__main__":
    main()
