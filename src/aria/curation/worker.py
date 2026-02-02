"""Curation worker - Quality filtering, deduplication, and PII detection.

Consumes from: Curation Input Queue
Produces to: Embedding Input Queue
"""

import json
import os
from typing import Any

from aria.worker.base import BaseWorker, WorkerConfig


class CurationWorker(BaseWorker):
    """Worker that performs quality filtering and curation."""

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__(config)
        self.output_bucket = os.environ.get("OUTPUT_BUCKET")
        self.threshold_high = float(os.environ.get("QUALITY_THRESHOLD_HIGH", "0.8"))
        self.threshold_medium = float(os.environ.get("QUALITY_THRESHOLD_MEDIUM", "0.6"))
        self.threshold_low = float(os.environ.get("QUALITY_THRESHOLD_LOW", "0.4"))
        self.quality_scorer = None
        self.deduplicator = None
        self.pii_filter = None

    def initialize(self) -> None:
        """Initialize curation components."""
        self.logger.info("Initializing curation components...")

        from aria.curation.deduplication import Deduplicator
        from aria.curation.pii import PIIFilter
        from aria.curation.quality import QualityScorer

        self.quality_scorer = QualityScorer()
        self.deduplicator = Deduplicator()
        self.pii_filter = PIIFilter()

        self.logger.info("Curation components initialized")

    def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process hydration output and apply curation filters."""
        files = message.get("files", [])
        if not files:
            self.logger.warning("No files in message")
            return None

        curated_files = []
        for file_info in files:
            result = self._curate_file(file_info)
            if result:
                curated_files.append(result)

        if not curated_files:
            return None

        return {
            "source": "curation",
            "files": curated_files,
        }

    def _curate_file(self, file_info: dict[str, Any]) -> dict[str, Any] | None:
        """Apply curation pipeline to a single file."""
        file_id = file_info["file_id"]
        bucket = file_info["output_bucket"]
        key = file_info["output_key"]

        self.logger.info(f"Curating {file_id}")

        # Download transcript
        response = self.s3.get_object(Bucket=bucket, Key=key)
        transcript = json.loads(response["Body"].read())
        text = transcript.get("text", "")

        if not text.strip():
            self.logger.warning(f"Empty transcript for {file_id}")
            return None

        # Quality scoring
        quality_result = self.quality_scorer.score(transcript)
        quality_score = quality_result["overall_score"]
        self.logger.info(f"Quality score for {file_id}: {quality_score:.3f}")

        # Determine quality tier
        if quality_score >= self.threshold_high:
            tier = "high"
        elif quality_score >= self.threshold_medium:
            tier = "medium"
        elif quality_score >= self.threshold_low:
            tier = "low"
        else:
            tier = "rejected"
            self.logger.info(f"Rejecting {file_id} (score: {quality_score:.3f})")
            self._save_rejected(file_id, transcript, quality_result)
            return None

        # Deduplication check
        is_duplicate = self.deduplicator.is_duplicate(text)
        if is_duplicate:
            self.logger.info(f"Duplicate detected for {file_id}")
            return None

        # Add to dedup index
        self.deduplicator.add(file_id, text)

        # PII filtering
        pii_result = self.pii_filter.analyze(text)
        if pii_result["has_pii"]:
            text = self.pii_filter.redact(text)
            self.logger.info(f"Redacted PII from {file_id}: {pii_result['entity_types']}")

        # Build curated record
        curated = {
            "file_id": file_id,
            "text": text,
            "language": transcript.get("language"),
            "duration": transcript.get("duration"),
            "quality_score": quality_score,
            "quality_tier": tier,
            "quality_details": quality_result,
            "pii_redacted": pii_result["has_pii"],
            "source_transcript": key,
        }

        # Save curated output
        output_key = f"curated/{tier}/{file_id}.json"
        self.s3.put_object(
            Bucket=self.output_bucket,
            Key=output_key,
            Body=json.dumps(curated),
            ContentType="application/json",
        )
        self.logger.info(f"Saved curated output to {output_key}")

        return {
            "file_id": file_id,
            "output_bucket": self.output_bucket,
            "output_key": output_key,
            "quality_tier": tier,
            "quality_score": quality_score,
        }

    def _save_rejected(
        self, file_id: str, transcript: dict, quality_result: dict
    ) -> None:
        """Save rejected file for analysis."""
        rejected = {
            "file_id": file_id,
            "text": transcript.get("text"),
            "quality_result": quality_result,
            "reason": "quality_below_threshold",
        }
        output_key = f"rejected/{file_id}.json"
        self.s3.put_object(
            Bucket=self.output_bucket,
            Key=output_key,
            Body=json.dumps(rejected),
            ContentType="application/json",
        )

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.quality_scorer = None
        self.deduplicator = None
        self.pii_filter = None


def main() -> None:
    """Entry point for the curation worker."""
    config = WorkerConfig.from_env()
    worker = CurationWorker(config)
    worker.run()


if __name__ == "__main__":
    main()
