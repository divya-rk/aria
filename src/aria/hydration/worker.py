"""Hydration worker - GPU-based audio transcription using Whisper.

Consumes from: Hydration Input Queue (S3 event notifications)
Produces to: Curation Input Queue
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from aria.worker.base import BaseWorker, WorkerConfig


class HydrationWorker(BaseWorker):
    """Worker that transcribes audio files using Whisper."""

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__(config)
        self.model = None
        self.raw_bucket = os.environ.get("RAW_BUCKET")
        self.output_bucket = os.environ.get("OUTPUT_BUCKET")
        self.model_name = os.environ.get("WHISPER_MODEL", "large-v3")
        self.device = os.environ.get("WHISPER_DEVICE", "cuda")
        self.compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "float16")

    def initialize(self) -> None:
        """Load Whisper model."""
        self.logger.info(f"Loading Whisper model: {self.model_name}")
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )
        self.logger.info("Whisper model loaded")

    def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process an S3 event notification and transcribe the audio file."""
        # Parse S3 event notification
        records = message.get("Records", [])
        if not records:
            self.logger.warning("No records in message")
            return None

        results = []
        for record in records:
            s3_info = record.get("s3", {})
            bucket = s3_info.get("bucket", {}).get("name")
            key = s3_info.get("object", {}).get("key")

            if not bucket or not key:
                self.logger.warning(f"Invalid S3 record: {record}")
                continue

            result = self._transcribe_file(bucket, key)
            if result:
                results.append(result)

        if not results:
            return None

        # Return message for next stage
        return {
            "source": "hydration",
            "files": results,
        }

    def _transcribe_file(self, bucket: str, key: str) -> dict[str, Any] | None:
        """Download and transcribe a single audio file."""
        file_id = Path(key).stem
        self.logger.info(f"Transcribing {bucket}/{key}")

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / Path(key).name

            # Download file
            self.s3.download_file(bucket, key, str(local_path))
            self.logger.info(f"Downloaded {key} ({local_path.stat().st_size} bytes)")

            # Transcribe
            segments, info = self.model.transcribe(
                str(local_path),
                beam_size=5,
                language=None,  # Auto-detect
                vad_filter=True,
            )

            # Collect segments
            transcript_segments = []
            full_text = []
            for segment in segments:
                transcript_segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "avg_logprob": segment.avg_logprob,
                    "no_speech_prob": segment.no_speech_prob,
                })
                full_text.append(segment.text)

            transcript = {
                "file_id": file_id,
                "source_bucket": bucket,
                "source_key": key,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "text": " ".join(full_text),
                "segments": transcript_segments,
            }

            # Upload result to S3
            output_key = f"hydrated/{file_id}.json"
            self.s3.put_object(
                Bucket=self.output_bucket,
                Key=output_key,
                Body=json.dumps(transcript),
                ContentType="application/json",
            )
            self.logger.info(f"Uploaded transcript to {self.output_bucket}/{output_key}")

            return {
                "file_id": file_id,
                "output_bucket": self.output_bucket,
                "output_key": output_key,
                "language": info.language,
                "duration": info.duration,
            }

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.model = None


def main() -> None:
    """Entry point for the hydration worker."""
    config = WorkerConfig.from_env()
    worker = HydrationWorker(config)
    worker.run()


if __name__ == "__main__":
    main()
