"""Hydration processor - orchestrates transcription pipeline."""

import json
from datetime import datetime
from typing import Any

import ray

from aria.common import (
    AudioFile,
    JobRecord,
    JobStage,
    JobStatus,
    ProcessingError,
    ProcessingResult,
    QualityScore,
    get_logger,
)
from aria.config import Settings
from aria.hydration.transcriber import TranscriptionResult, WhisperTranscriber
from aria.storage import DynamoDBClient, S3Client


logger = get_logger(__name__)


class HydrationProcessor:
    """Orchestrates the hydration (transcription) pipeline."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize hydration processor.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._s3 = S3Client(settings)
        self._dynamodb = DynamoDBClient(settings)
        self._transcriber_pool: list[ray.ObjectRef] | None = None

    def initialize_ray(self, num_workers: int = 4) -> None:
        """
        Initialize Ray cluster and transcriber pool.

        Args:
            num_workers: Number of GPU workers
        """
        if not ray.is_initialized():
            ray.init(address=self.settings.ray.address)

        # Create pool of transcriber actors
        self._transcriber_pool = [
            WhisperTranscriber.options(num_gpus=1).remote(
                model_size=self.settings.whisper.model_size,
                device=self.settings.whisper.device,
            )
            for _ in range(num_workers)
        ]
        logger.info("transcriber_pool_initialized", num_workers=num_workers)

    def process_file(self, audio_file: AudioFile) -> ProcessingResult:
        """
        Process a single audio file through hydration.

        Args:
            audio_file: Audio file to process

        Returns:
            ProcessingResult with status and output location
        """
        start_time = datetime.utcnow()
        file_id = audio_file.file_id

        # Create job record
        job = JobRecord(
            file_id=file_id,
            stage=JobStage.HYDRATION,
            status=JobStatus.PROCESSING,
        )
        self._dynamodb.put_job(job)

        try:
            # Download audio
            audio_bytes = self._s3.download_file(
                audio_file.s3_bucket,
                audio_file.s3_key,
            )

            # Transcribe
            result = self._transcribe(audio_bytes)

            # Build output
            output = self._build_output(audio_file, result)

            # Upload to S3
            output_key = f"hydrated/{file_id}.json"
            output_uri = self._s3.upload_file(
                content=json.dumps(output, indent=2),
                bucket=self.settings.s3.output_bucket,
                key=output_key,
                content_type="application/json",
            )

            # Calculate quality score
            quality = QualityScore(
                overall=result.confidence,
                confidence=result.confidence,
                language_score=1.0 if result.language == "en" else 0.8,
                word_count=result.word_count,
            )

            # Update job status
            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.HYDRATION,
                status=JobStatus.COMPLETED,
                output_location=output_uri,
                quality_score=quality.overall,
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=True,
                stage=JobStage.HYDRATION,
                output_location=output_uri,
                quality_score=quality,
                processing_time_seconds=processing_time,
            )

        except Exception as e:
            logger.error("hydration_failed", file_id=file_id, error=str(e))

            self._dynamodb.update_job_status(
                file_id=file_id,
                stage=JobStage.HYDRATION,
                status=JobStatus.FAILED,
                error_message=str(e),
            )

            processing_time = (datetime.utcnow() - start_time).total_seconds()

            return ProcessingResult(
                file_id=file_id,
                success=False,
                stage=JobStage.HYDRATION,
                error_message=str(e),
                processing_time_seconds=processing_time,
            )

    def _transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe audio using available method."""
        if self._transcriber_pool:
            # Use Ray actor
            transcriber = self._transcriber_pool[0]  # Simple round-robin could be added
            future = transcriber.transcribe.remote(audio_bytes)
            return ray.get(future)
        else:
            # Fallback to local
            from aria.hydration.transcriber import WhisperTranscriberLocal
            local = WhisperTranscriberLocal(self.settings)
            return local.transcribe(audio_bytes)

    def _build_output(
        self,
        audio_file: AudioFile,
        result: TranscriptionResult,
    ) -> dict[str, Any]:
        """Build output document from transcription result."""
        return {
            "file_id": audio_file.file_id,
            "source": {
                "bucket": audio_file.s3_bucket,
                "key": audio_file.s3_key,
                "size": audio_file.file_size,
                "content_type": audio_file.content_type,
            },
            "transcription": {
                "text": result.text,
                "language": result.language,
                "confidence": result.confidence,
                "duration_seconds": result.duration_seconds,
                "word_count": result.word_count,
            },
            "segments": result.segments,
            "metadata": {
                "processed_at": datetime.utcnow().isoformat(),
                "model": self.settings.whisper.model_size,
            },
        }

    def process_batch(
        self,
        audio_files: list[AudioFile],
    ) -> list[ProcessingResult]:
        """
        Process multiple audio files in parallel using Ray.

        Args:
            audio_files: List of audio files to process

        Returns:
            List of ProcessingResults
        """
        if not self._transcriber_pool:
            raise ProcessingError("Ray not initialized. Call initialize_ray() first.")

        # Download all files
        download_futures = []
        for audio_file in audio_files:
            future = ray.put(
                self._s3.download_file(audio_file.s3_bucket, audio_file.s3_key)
            )
            download_futures.append((audio_file, future))

        # Distribute transcription across workers
        transcription_futures = []
        for i, (audio_file, audio_ref) in enumerate(download_futures):
            worker = self._transcriber_pool[i % len(self._transcriber_pool)]
            future = worker.transcribe.remote(ray.get(audio_ref))
            transcription_futures.append((audio_file, future))

        # Collect results
        results = []
        for audio_file, future in transcription_futures:
            try:
                transcription = ray.get(future)
                result = self._finalize_result(audio_file, transcription)
                results.append(result)
            except Exception as e:
                logger.error("batch_item_failed", file_id=audio_file.file_id, error=str(e))
                results.append(
                    ProcessingResult(
                        file_id=audio_file.file_id,
                        success=False,
                        stage=JobStage.HYDRATION,
                        error_message=str(e),
                    )
                )

        return results

    def _finalize_result(
        self,
        audio_file: AudioFile,
        result: TranscriptionResult,
    ) -> ProcessingResult:
        """Finalize and store a transcription result."""
        output = self._build_output(audio_file, result)
        output_key = f"hydrated/{audio_file.file_id}.json"

        output_uri = self._s3.upload_file(
            content=json.dumps(output, indent=2),
            bucket=self.settings.s3.output_bucket,
            key=output_key,
            content_type="application/json",
        )

        quality = QualityScore(
            overall=result.confidence,
            confidence=result.confidence,
            language_score=1.0 if result.language == "en" else 0.8,
            word_count=result.word_count,
        )

        self._dynamodb.update_job_status(
            file_id=audio_file.file_id,
            stage=JobStage.HYDRATION,
            status=JobStatus.COMPLETED,
            output_location=output_uri,
            quality_score=quality.overall,
        )

        return ProcessingResult(
            file_id=audio_file.file_id,
            success=True,
            stage=JobStage.HYDRATION,
            output_location=output_uri,
            quality_score=quality,
        )
