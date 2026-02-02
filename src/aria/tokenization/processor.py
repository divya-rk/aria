"""Tokenization processor - orchestrates data preparation for LLM."""

import json
from datetime import datetime
from typing import Any

from aria.common import (
    JobRecord,
    JobStage,
    JobStatus,
    ProcessingResult,
    get_logger,
)
from aria.config import Settings
from aria.storage import DynamoDBClient, S3Client
from aria.tokenization.sharder import Sharder, ShardWriter
from aria.tokenization.tokenizer import Tokenizer


logger = get_logger(__name__)


class TokenizationProcessor:
    """Orchestrates the tokenization and sharding pipeline."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize tokenization processor.

        Args:
            settings: Application settings
        """
        self.settings = settings

        self._s3 = S3Client(settings)
        self._dynamodb = DynamoDBClient(settings)
        self._tokenizer = Tokenizer(model_name=settings.tokenizer.model_name)
        self._sharder = Sharder(shard_size=settings.tokenizer.shard_size)

    def process_document(
        self,
        file_id: str,
        curated_location: str,
    ) -> ProcessingResult:
        """
        Tokenize a single document.

        Args:
            file_id: Document file ID
            curated_location: S3 URI of curated document

        Returns:
            ProcessingResult with status
        """
        start_time = datetime.utcnow()

        # Create job record
        job = JobRecord(
            file_id=file_id,
            stage=JobStage.TOKENIZATION,
            status=JobStatus.PROCESSING,
        )
        self._dynamodb.put_job(job)

        try:
            # Download curated document
            bucket, key = self._parse_s3_uri(curated_location)
            content = self._s3.download_file(bucket, key)
            doc = json.loads(content.decode("utf-8"))

            text = doc.get("text", "")

            if not text.strip():
                return self._handle_empty(file_id, start_time)

            # Tokenize
            tokenized = self._tokenizer.tokenize(text, file_id)

            # Upload tokenized output
            output = {
                "file_id": file_id,
                "tokens": tokenized.tokens,
                "token_count": tokenized.token_count,
                "source": curated_location,
                "tokenized_at": datetime.utcnow().isoformat(),
            }

            output_key = f"tokenized/{file_id}.json"
            output_uri = self._s3.upload_file(
                content=json.dumps(output),
                bucket=self.settings.s3.output_bucket,
                key=output_key,
                content_type="application/json",
            )

            # Update job status
            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.TOKENIZATION,
                status=JobStatus.COMPLETED,
                output_location=output_uri,
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=True,
                stage=JobStage.TOKENIZATION,
                output_location=output_uri,
                processing_time_seconds=processing_time,
            )

        except Exception as e:
            logger.error("tokenization_failed", file_id=file_id, error=str(e))

            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.TOKENIZATION,
                status=JobStatus.FAILED,
                error_message=str(e),
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=False,
                stage=JobStage.TOKENIZATION,
                error_message=str(e),
                processing_time_seconds=processing_time,
            )

    def create_training_shards(
        self,
        curated_prefix: str = "curated/high/",
    ) -> dict[str, Any]:
        """
        Create training shards from all high-quality curated documents.

        Args:
            curated_prefix: S3 prefix for curated documents

        Returns:
            Summary of shard creation
        """
        logger.info("starting_shard_creation", prefix=curated_prefix)

        # List curated documents
        files = list(
            self._s3.list_files(
                bucket=self.settings.s3.output_bucket,
                prefix=curated_prefix,
                suffix=".json",
            )
        )

        logger.info("found_documents", count=len(files))

        # Tokenize all documents
        tokenized_docs = []
        for file_info in files:
            content = self._s3.download_file(
                file_info.s3_bucket,
                file_info.s3_key,
            )
            doc = json.loads(content.decode("utf-8"))
            text = doc.get("text", "")

            if text.strip():
                tokenized = self._tokenizer.tokenize(text, file_info.file_id)
                tokenized_docs.append(tokenized)

        # Create shards
        sharder = Sharder(shard_size=self.settings.tokenizer.shard_size)
        shards = sharder.create_shards(tokenized_docs)

        # Upload shards
        shard_uris = []
        for shard in shards:
            parquet_bytes = ShardWriter.to_parquet(shard)
            shard_key = f"shards/{shard.shard_id}.parquet"

            uri = self._s3.upload_file(
                content=parquet_bytes,
                bucket=self.settings.s3.output_bucket,
                key=shard_key,
                content_type="application/octet-stream",
            )
            shard_uris.append(uri)

        # Upload manifest
        manifest = ShardWriter.create_manifest(shards)
        manifest_uri = self._s3.upload_file(
            content=json.dumps(manifest, indent=2),
            bucket=self.settings.s3.output_bucket,
            key="shards/manifest.json",
            content_type="application/json",
        )

        summary = {
            "total_documents": len(tokenized_docs),
            "total_shards": len(shards),
            "total_tokens": sum(s.token_count for s in shards),
            "shard_uris": shard_uris,
            "manifest_uri": manifest_uri,
        }

        logger.info("shard_creation_complete", **summary)
        return summary

    def _handle_empty(
        self,
        file_id: str,
        start_time: datetime,
    ) -> ProcessingResult:
        """Handle document with no content."""
        self._dynamodb.update_job_status(
            file_id=file_id,
            stage=JobStage.TOKENIZATION,
            status=JobStatus.COMPLETED,
            error_message="no_content",
        )

        processing_time = (datetime.utcnow() - start_time).total_seconds()

        return ProcessingResult(
            file_id=file_id,
            success=True,
            stage=JobStage.TOKENIZATION,
            error_message="no_content",
            processing_time_seconds=processing_time,
        )

    def _parse_s3_uri(self, uri: str) -> tuple[str, str]:
        """Parse S3 URI into bucket and key."""
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {uri}")

        path = uri[5:]
        bucket, _, key = path.partition("/")
        return bucket, key

    def get_stats(self) -> dict[str, Any]:
        """Get tokenization statistics."""
        return {
            "tokenizer_model": self.settings.tokenizer.model_name,
            "vocab_size": self._tokenizer.vocab_size,
            "shard_size": self.settings.tokenizer.shard_size,
        }
