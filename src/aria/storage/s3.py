"""S3 client for file operations."""

import hashlib
import io
from typing import Any, Iterator

import boto3
from botocore.exceptions import ClientError

from aria.common import AudioFile, StorageError, get_logger
from aria.config import Settings


logger = get_logger(__name__)


class S3Client:
    """Client for S3 operations."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize S3 client.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._client = boto3.client(
            "s3",
            region_name=settings.aws.region,
        )
        self._resource = boto3.resource(
            "s3",
            region_name=settings.aws.region,
        )

    @staticmethod
    def generate_file_id(bucket: str, key: str) -> str:
        """
        Generate unique file ID from bucket and key.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            SHA256 hash of bucket/key
        """
        content = f"{bucket}/{key}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def download_file(self, bucket: str, key: str) -> bytes:
        """
        Download file content from S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            File content as bytes
        """
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            content: bytes = response["Body"].read()
            logger.debug("file_downloaded", bucket=bucket, key=key, size=len(content))
            return content
        except ClientError as e:
            raise StorageError(f"Failed to download {bucket}/{key}: {e}") from e

    def upload_file(
        self,
        content: bytes | str,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """
        Upload content to S3.

        Args:
            content: File content
            bucket: Destination bucket
            key: Destination key
            content_type: MIME type
            metadata: Optional metadata

        Returns:
            S3 URI of uploaded file
        """
        try:
            if isinstance(content, str):
                content = content.encode("utf-8")

            self._client.put_object(
                Bucket=bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata=metadata or {},
            )

            uri = f"s3://{bucket}/{key}"
            logger.debug("file_uploaded", uri=uri, size=len(content))
            return uri

        except ClientError as e:
            raise StorageError(f"Failed to upload to {bucket}/{key}: {e}") from e

    def upload_fileobj(
        self,
        fileobj: io.BytesIO,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload file-like object to S3.

        Args:
            fileobj: File-like object
            bucket: Destination bucket
            key: Destination key
            content_type: MIME type

        Returns:
            S3 URI of uploaded file
        """
        try:
            self._client.upload_fileobj(
                fileobj,
                bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
            uri = f"s3://{bucket}/{key}"
            logger.debug("fileobj_uploaded", uri=uri)
            return uri
        except ClientError as e:
            raise StorageError(f"Failed to upload to {bucket}/{key}: {e}") from e

    def file_exists(self, bucket: str, key: str) -> bool:
        """
        Check if file exists in S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            True if file exists
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise StorageError(f"Failed to check {bucket}/{key}: {e}") from e

    def get_file_metadata(self, bucket: str, key: str) -> AudioFile:
        """
        Get file metadata from S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            AudioFile with metadata
        """
        try:
            response = self._client.head_object(Bucket=bucket, Key=key)

            return AudioFile(
                file_id=self.generate_file_id(bucket, key),
                s3_bucket=bucket,
                s3_key=key,
                file_size=response["ContentLength"],
                content_type=response.get("ContentType", "audio/mpeg"),
                metadata=response.get("Metadata", {}),
            )
        except ClientError as e:
            raise StorageError(f"Failed to get metadata for {bucket}/{key}: {e}") from e

    def list_files(
        self,
        bucket: str,
        prefix: str = "",
        suffix: str | None = None,
        max_keys: int = 1000,
    ) -> Iterator[AudioFile]:
        """
        List files in S3 bucket with optional filtering.

        Args:
            bucket: S3 bucket name
            prefix: Key prefix filter
            suffix: Key suffix filter (e.g., '.mp3')
            max_keys: Maximum keys to return

        Yields:
            AudioFile objects
        """
        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=bucket,
            Prefix=prefix,
            PaginationConfig={"MaxItems": max_keys},
        )

        count = 0
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]

                if suffix and not key.endswith(suffix):
                    continue

                yield AudioFile(
                    file_id=self.generate_file_id(bucket, key),
                    s3_bucket=bucket,
                    s3_key=key,
                    file_size=obj["Size"],
                    content_type=self._guess_content_type(key),
                )

                count += 1
                if count >= max_keys:
                    return

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
        for ext, content_type in extension_map.items():
            if key.lower().endswith(ext):
                return content_type
        return "application/octet-stream"

    def parse_s3_event(self, event: dict[str, Any]) -> list[AudioFile]:
        """
        Parse S3 event notification into AudioFile objects.

        Args:
            event: S3 event notification payload

        Returns:
            List of AudioFile objects from the event
        """
        files: list[AudioFile] = []

        for record in event.get("Records", []):
            if record.get("eventSource") != "aws:s3":
                continue

            s3_info = record.get("s3", {})
            bucket = s3_info.get("bucket", {}).get("name")
            key = s3_info.get("object", {}).get("key")
            size = s3_info.get("object", {}).get("size", 0)

            if bucket and key:
                files.append(
                    AudioFile(
                        file_id=self.generate_file_id(bucket, key),
                        s3_bucket=bucket,
                        s3_key=key,
                        file_size=size,
                        content_type=self._guess_content_type(key),
                    )
                )

        return files
