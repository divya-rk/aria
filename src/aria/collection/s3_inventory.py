"""S3 Inventory processor for backfill operations."""

import csv
import gzip
import io
from collections.abc import Iterator

import boto3
from botocore.exceptions import ClientError

from aria.common import AudioFile, StorageError, get_logger
from aria.config import Settings
from aria.storage import S3Client


logger = get_logger(__name__)


class S3InventoryProcessor:
    """Process S3 Inventory reports for bulk backfill."""

    SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm"}

    def __init__(self, settings: Settings) -> None:
        """
        Initialize inventory processor.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._client = boto3.client(
            "s3",
            region_name=settings.aws.region,
        )
        self._s3_client = S3Client(settings)

    def process_inventory_manifest(
        self,
        manifest_bucket: str,
        manifest_key: str,
    ) -> Iterator[AudioFile]:
        """
        Process S3 Inventory manifest and yield audio files.

        Args:
            manifest_bucket: Bucket containing inventory manifest
            manifest_key: Key to manifest.json

        Yields:
            AudioFile objects from inventory
        """
        # Download and parse manifest
        try:
            response = self._client.get_object(Bucket=manifest_bucket, Key=manifest_key)
            manifest = response["Body"].read().decode("utf-8")
        except ClientError as e:
            raise StorageError(f"Failed to read manifest: {e}") from e

        import json
        manifest_data = json.loads(manifest)

        # Get inventory file locations
        files = manifest_data.get("files", [])
        source_bucket = manifest_data.get("sourceBucket", "")

        logger.info(
            "processing_inventory",
            manifest_key=manifest_key,
            file_count=len(files),
            source_bucket=source_bucket,
        )

        for file_info in files:
            inventory_key = file_info.get("key")
            if not inventory_key:
                continue

            yield from self._process_inventory_file(
                manifest_bucket,
                inventory_key,
                source_bucket,
            )

    def _process_inventory_file(
        self,
        bucket: str,
        key: str,
        source_bucket: str,
    ) -> Iterator[AudioFile]:
        """
        Process a single inventory CSV file.

        Args:
            bucket: Inventory bucket
            key: Inventory file key
            source_bucket: Source data bucket

        Yields:
            AudioFile objects
        """
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read()

            # Inventory files are gzipped
            if key.endswith(".gz"):
                content = gzip.decompress(content)

            reader = csv.reader(io.StringIO(content.decode("utf-8")))

            for row in reader:
                if len(row) < 2:
                    continue

                # Standard inventory format: bucket, key, size, ...
                file_key = row[1]
                file_size = int(row[2]) if len(row) > 2 else 0

                # Filter for audio files
                if not self._is_audio_file(file_key):
                    continue

                yield AudioFile(
                    file_id=self._s3_client.generate_file_id(source_bucket, file_key),
                    s3_bucket=source_bucket,
                    s3_key=file_key,
                    file_size=file_size,
                    content_type=self._guess_content_type(file_key),
                )

        except ClientError as e:
            logger.error("inventory_file_error", key=key, error=str(e))

    def _is_audio_file(self, key: str) -> bool:
        """Check if file is an audio file based on extension."""
        lower_key = key.lower()
        return any(lower_key.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS)

    def _guess_content_type(self, key: str) -> str:
        """Guess content type from file extension."""
        extension_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".webm": "audio/webm",
        }
        lower_key = key.lower()
        for ext, content_type in extension_map.items():
            if lower_key.endswith(ext):
                return content_type
        return "application/octet-stream"

    def send_to_queue(
        self,
        audio_files: Iterator[AudioFile],
        queue_url: str,
        batch_size: int = 10,
    ) -> int:
        """
        Send audio files to SQS queue for processing.

        Args:
            audio_files: Iterator of AudioFile objects
            queue_url: Target SQS queue URL
            batch_size: Messages per batch

        Returns:
            Total messages sent
        """
        import json

        sqs = boto3.client("sqs", region_name=self.settings.aws.region)
        total_sent = 0
        batch: list[dict] = []

        for audio_file in audio_files:
            message = {
                "Id": audio_file.file_id,
                "MessageBody": json.dumps({
                    "Records": [{
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {"name": audio_file.s3_bucket},
                            "object": {
                                "key": audio_file.s3_key,
                                "size": audio_file.file_size,
                            },
                        },
                    }]
                }),
            }
            batch.append(message)

            if len(batch) >= batch_size:
                self._send_batch(sqs, queue_url, batch)
                total_sent += len(batch)
                batch = []

        # Send remaining
        if batch:
            self._send_batch(sqs, queue_url, batch)
            total_sent += len(batch)

        logger.info("inventory_queued", total_sent=total_sent)
        return total_sent

    def _send_batch(
        self,
        sqs: boto3.client,
        queue_url: str,
        batch: list[dict],
    ) -> None:
        """Send a batch of messages to SQS."""
        try:
            response = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
            failed = response.get("Failed", [])
            if failed:
                logger.warning("batch_send_failures", count=len(failed))
        except ClientError as e:
            raise StorageError(f"Failed to send batch: {e}") from e
