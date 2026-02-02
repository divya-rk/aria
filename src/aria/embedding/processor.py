"""Embedding processor - orchestrates vectorization pipeline."""

import json
from datetime import datetime
from typing import Any

from aria.common import (
    ChunkMetadata,
    Document,
    JobRecord,
    JobStage,
    JobStatus,
    ProcessingResult,
    get_logger,
)
from aria.config import Settings
from aria.embedding.chunker import TextChunker
from aria.embedding.embedder import TextEmbedder
from aria.storage import DynamoDBClient, LanceDBStore, S3Client


logger = get_logger(__name__)


class EmbeddingProcessor:
    """Orchestrates the embedding pipeline."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize embedding processor.

        Args:
            settings: Application settings
        """
        self.settings = settings

        self._s3 = S3Client(settings)
        self._dynamodb = DynamoDBClient(settings)
        self._lancedb = LanceDBStore(settings)
        self._chunker = TextChunker(
            chunk_size=settings.embedding.chunk_size,
            chunk_overlap=settings.embedding.chunk_overlap,
        )
        self._embedder = TextEmbedder(
            model_name=settings.embedding.model_name,
        )

        # Initialize LanceDB
        self._lancedb.create_table_if_not_exists()

    def process_document(
        self,
        file_id: str,
        curated_location: str,
    ) -> ProcessingResult:
        """
        Process a curated document through embedding.

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
            stage=JobStage.EMBEDDING,
            status=JobStatus.PROCESSING,
        )
        self._dynamodb.put_job(job)

        try:
            # Download curated document
            bucket, key = self._parse_s3_uri(curated_location)
            content = self._s3.download_file(bucket, key)
            doc = json.loads(content.decode("utf-8"))

            text = doc.get("text", "")
            quality_score = doc.get("quality", {}).get("overall_score", 0.5)

            # Chunk text
            chunks = self._chunker.chunk_text(text, file_id)

            if not chunks:
                return self._handle_empty(file_id, start_time)

            # Generate embeddings
            chunk_texts = [c.text for c in chunks]
            embeddings = self._embedder.embed_batch(chunk_texts)

            # Build documents for LanceDB
            documents = []
            for chunk, embedding in zip(chunks, embeddings):
                metadata = ChunkMetadata(
                    chunk_id=chunk.chunk_id,
                    file_id=file_id,
                    chunk_index=chunk.chunk_index,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    speaker=None,  # Could be added from segments
                    quality_score=quality_score,
                )

                documents.append(
                    Document(
                        id=chunk.chunk_id,
                        file_id=file_id,
                        text=chunk.text,
                        vector=embedding,
                        metadata=metadata,
                    )
                )

            # Store in LanceDB
            self._lancedb.add_documents(documents)

            # Update job status
            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.EMBEDDING,
                status=JobStatus.COMPLETED,
                quality_score=quality_score,
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                "embedding_complete",
                file_id=file_id,
                chunks=len(chunks),
                processing_time=processing_time,
            )

            return ProcessingResult(
                file_id=file_id,
                success=True,
                stage=JobStage.EMBEDDING,
                processing_time_seconds=processing_time,
            )

        except Exception as e:
            logger.error("embedding_failed", file_id=file_id, error=str(e))

            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.EMBEDDING,
                status=JobStatus.FAILED,
                error_message=str(e),
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=False,
                stage=JobStage.EMBEDDING,
                error_message=str(e),
                processing_time_seconds=processing_time,
            )

    def _handle_empty(
        self,
        file_id: str,
        start_time: datetime,
    ) -> ProcessingResult:
        """Handle document with no content to embed."""
        self._dynamodb.update_job_status(
            file_id=file_id,
            stage=JobStage.EMBEDDING,
            status=JobStatus.COMPLETED,
            error_message="no_content",
        )

        processing_time = (datetime.utcnow() - start_time).total_seconds()

        return ProcessingResult(
            file_id=file_id,
            success=True,
            stage=JobStage.EMBEDDING,
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

    def process_batch(
        self,
        items: list[tuple[str, str]],
    ) -> list[ProcessingResult]:
        """
        Process multiple documents.

        Args:
            items: List of (file_id, curated_location) tuples

        Returns:
            List of ProcessingResults
        """
        results = []
        for file_id, location in items:
            result = self.process_document(file_id, location)
            results.append(result)
        return results

    def get_stats(self) -> dict[str, Any]:
        """Get embedding statistics."""
        return {
            "lancedb_stats": self._lancedb.get_stats(),
            "embedder_model": self.settings.embedding.model_name,
            "chunk_size": self.settings.embedding.chunk_size,
        }
