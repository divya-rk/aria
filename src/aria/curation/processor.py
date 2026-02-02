"""Curation processor - orchestrates quality filtering pipeline."""

import json
from datetime import datetime
from typing import Any

from aria.common import (
    JobRecord,
    JobStage,
    JobStatus,
    ProcessingResult,
    QualityScore,
    get_logger,
)
from aria.config import Settings
from aria.curation.dedup import Deduplicator
from aria.curation.pii_filter import PIIFilter
from aria.curation.quality import QualityScorer
from aria.storage import DynamoDBClient, S3Client


logger = get_logger(__name__)


class CurationProcessor:
    """Orchestrates the curation pipeline."""

    def __init__(
        self,
        settings: Settings,
        quality_threshold: float = 0.6,
        redact_pii: bool = True,
    ) -> None:
        """
        Initialize curation processor.

        Args:
            settings: Application settings
            quality_threshold: Minimum quality score to pass
            redact_pii: Whether to redact PII (True) or just flag it (False)
        """
        self.settings = settings
        self.quality_threshold = quality_threshold
        self.redact_pii = redact_pii

        self._s3 = S3Client(settings)
        self._dynamodb = DynamoDBClient(settings)
        self._quality_scorer = QualityScorer()
        self._deduplicator = Deduplicator()
        self._pii_filter = PIIFilter()

    def process_document(
        self,
        file_id: str,
        hydrated_location: str,
    ) -> ProcessingResult:
        """
        Process a single hydrated document through curation.

        Args:
            file_id: Document file ID
            hydrated_location: S3 URI of hydrated document

        Returns:
            ProcessingResult with status
        """
        start_time = datetime.utcnow()

        # Create job record
        job = JobRecord(
            file_id=file_id,
            stage=JobStage.CURATION,
            status=JobStatus.PROCESSING,
        )
        self._dynamodb.put_job(job)

        try:
            # Download hydrated document
            bucket, key = self._parse_s3_uri(hydrated_location)
            content = self._s3.download_file(bucket, key)
            doc = json.loads(content.decode("utf-8"))

            text = doc.get("transcription", {}).get("text", "")
            confidence = doc.get("transcription", {}).get("confidence", 0.5)

            # Step 1: Quality scoring
            quality_metrics = self._quality_scorer.score(text, confidence)
            quality_tier = self._quality_scorer.get_quality_tier(quality_metrics)

            if quality_tier == "rejected":
                return self._handle_rejection(
                    file_id, "quality_below_threshold", quality_metrics.overall_score, start_time
                )

            # Step 2: Deduplication
            is_duplicate = self._deduplicator.is_duplicate(file_id, text)
            if is_duplicate:
                return self._handle_rejection(
                    file_id, "duplicate_content", quality_metrics.overall_score, start_time
                )

            # Step 3: PII handling
            pii_result = self._pii_filter.redact(text)
            final_text = pii_result.redacted_text if self.redact_pii else text

            # Build curated document
            curated_doc = self._build_curated_document(
                doc=doc,
                file_id=file_id,
                text=final_text,
                quality_metrics=quality_metrics,
                quality_tier=quality_tier,
                pii_detected=pii_result.pii_detected,
                pii_types=pii_result.pii_types,
            )

            # Upload curated document
            output_key = f"curated/{quality_tier}/{file_id}.json"
            output_uri = self._s3.upload_file(
                content=json.dumps(curated_doc, indent=2),
                bucket=self.settings.s3.output_bucket,
                key=output_key,
                content_type="application/json",
            )

            # Update job status
            quality_score = QualityScore(
                overall=quality_metrics.overall_score,
                confidence=quality_metrics.confidence_score,
                language_score=quality_metrics.language_score,
                pii_detected=pii_result.pii_detected,
                is_duplicate=False,
                word_count=quality_metrics.word_count,
            )

            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.CURATION,
                status=JobStatus.COMPLETED,
                output_location=output_uri,
                quality_score=quality_metrics.overall_score,
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=True,
                stage=JobStage.CURATION,
                output_location=output_uri,
                quality_score=quality_score,
                processing_time_seconds=processing_time,
            )

        except Exception as e:
            logger.error("curation_failed", file_id=file_id, error=str(e))

            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.CURATION,
                status=JobStatus.FAILED,
                error_message=str(e),
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=False,
                stage=JobStage.CURATION,
                error_message=str(e),
                processing_time_seconds=processing_time,
            )

    def _handle_rejection(
        self,
        file_id: str,
        reason: str,
        quality_score: float,
        start_time: datetime,
    ) -> ProcessingResult:
        """Handle rejected document."""
        logger.info("document_rejected", file_id=file_id, reason=reason)

        self._dynamodb.update_job_status(
            file_id=file_id,
            stage=JobStage.CURATION,
            status=JobStatus.COMPLETED,
            quality_score=quality_score,
            error_message=f"rejected:{reason}",
        )

        processing_time = (datetime.utcnow() - start_time).total_seconds()

        return ProcessingResult(
            file_id=file_id,
            success=True,  # Not a failure, just filtered out
            stage=JobStage.CURATION,
            error_message=f"rejected:{reason}",
            processing_time_seconds=processing_time,
        )

    def _build_curated_document(
        self,
        doc: dict[str, Any],
        file_id: str,
        text: str,
        quality_metrics: Any,
        quality_tier: str,
        pii_detected: bool,
        pii_types: list[str],
    ) -> dict[str, Any]:
        """Build curated document structure."""
        return {
            "file_id": file_id,
            "text": text,
            "source": doc.get("source", {}),
            "quality": {
                "tier": quality_tier,
                "overall_score": quality_metrics.overall_score,
                "confidence_score": quality_metrics.confidence_score,
                "language_score": quality_metrics.language_score,
                "detected_language": quality_metrics.detected_language,
                "word_count": quality_metrics.word_count,
                "unique_word_ratio": quality_metrics.unique_word_ratio,
            },
            "pii": {
                "detected": pii_detected,
                "redacted": self.redact_pii and pii_detected,
                "types_found": pii_types,
            },
            "segments": doc.get("segments", []),
            "metadata": {
                **doc.get("metadata", {}),
                "curated_at": datetime.utcnow().isoformat(),
            },
        }

    def _parse_s3_uri(self, uri: str) -> tuple[str, str]:
        """Parse S3 URI into bucket and key."""
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {uri}")

        path = uri[5:]
        bucket, _, key = path.partition("/")
        return bucket, key

    def get_stats(self) -> dict[str, Any]:
        """Get curation statistics."""
        return {
            "dedup_stats": self._deduplicator.get_stats(),
            "quality_threshold": self.quality_threshold,
            "pii_redaction_enabled": self.redact_pii,
        }
