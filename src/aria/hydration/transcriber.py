"""Whisper-based audio transcription."""

from dataclasses import dataclass
from typing import Any

import ray

from aria.common import ProcessingError, get_logger
from aria.config import Settings


logger = get_logger(__name__)


@dataclass
class TranscriptionResult:
    """Result of audio transcription."""

    text: str
    language: str
    confidence: float
    segments: list[dict[str, Any]]
    duration_seconds: float
    word_count: int


@ray.remote
class WhisperTranscriber:
    """Ray actor for Whisper transcription."""

    def __init__(self, model_size: str = "large-v3", device: str = "cuda") -> None:
        """
        Initialize Whisper model.

        Args:
            model_size: Whisper model variant
            device: Compute device (cuda/cpu)
        """
        import whisper

        self.model_size = model_size
        self.device = device
        self.model = whisper.load_model(model_size, device=device)
        logger.info("whisper_model_loaded", model_size=model_size, device=device)

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio content.

        Args:
            audio_bytes: Raw audio file bytes

        Returns:
            TranscriptionResult with text and metadata
        """
        import io
        import tempfile
        import numpy as np
        import whisper

        try:
            # Write to temp file (Whisper requires file path)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                tmp.write(audio_bytes)
                tmp.flush()

                # Transcribe
                result = self.model.transcribe(
                    tmp.name,
                    task="transcribe",
                    verbose=False,
                )

            # Extract segments with timing
            segments = []
            total_confidence = 0.0

            for seg in result.get("segments", []):
                segment_data = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                }
                segments.append(segment_data)

                # Average token probabilities for confidence
                if "avg_logprob" in seg:
                    # Convert log prob to probability
                    total_confidence += np.exp(seg["avg_logprob"])

            avg_confidence = (
                total_confidence / len(segments) if segments else 0.0
            )

            text = result.get("text", "").strip()
            word_count = len(text.split()) if text else 0

            # Calculate duration from last segment
            duration = segments[-1]["end"] if segments else 0.0

            return TranscriptionResult(
                text=text,
                language=result.get("language", "unknown"),
                confidence=min(avg_confidence, 1.0),
                segments=segments,
                duration_seconds=duration,
                word_count=word_count,
            )

        except Exception as e:
            raise ProcessingError(f"Transcription failed: {e}") from e

    def transcribe_batch(
        self,
        audio_batch: list[tuple[str, bytes]],
    ) -> list[tuple[str, TranscriptionResult | Exception]]:
        """
        Transcribe a batch of audio files.

        Args:
            audio_batch: List of (file_id, audio_bytes) tuples

        Returns:
            List of (file_id, result_or_error) tuples
        """
        results = []

        for file_id, audio_bytes in audio_batch:
            try:
                result = self.transcribe(audio_bytes)
                results.append((file_id, result))
            except Exception as e:
                logger.error("batch_transcription_error", file_id=file_id, error=str(e))
                results.append((file_id, e))

        return results


class WhisperTranscriberLocal:
    """Non-Ray Whisper transcriber for local/testing use."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize local transcriber.

        Args:
            settings: Application settings
        """
        import whisper

        self.settings = settings
        self.model = whisper.load_model(
            settings.whisper.model_size,
            device=settings.whisper.device,
        )
        logger.info(
            "whisper_model_loaded",
            model_size=settings.whisper.model_size,
            device=settings.whisper.device,
        )

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio content.

        Args:
            audio_bytes: Raw audio file bytes

        Returns:
            TranscriptionResult with text and metadata
        """
        import tempfile
        import numpy as np

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                tmp.write(audio_bytes)
                tmp.flush()

                result = self.model.transcribe(
                    tmp.name,
                    task="transcribe",
                    verbose=False,
                )

            segments = []
            total_confidence = 0.0

            for seg in result.get("segments", []):
                segment_data = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                }
                segments.append(segment_data)

                if "avg_logprob" in seg:
                    total_confidence += np.exp(seg["avg_logprob"])

            avg_confidence = total_confidence / len(segments) if segments else 0.0
            text = result.get("text", "").strip()
            word_count = len(text.split()) if text else 0
            duration = segments[-1]["end"] if segments else 0.0

            return TranscriptionResult(
                text=text,
                language=result.get("language", "unknown"),
                confidence=min(avg_confidence, 1.0),
                segments=segments,
                duration_seconds=duration,
                word_count=word_count,
            )

        except Exception as e:
            raise ProcessingError(f"Transcription failed: {e}") from e
