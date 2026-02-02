"""Pydantic models for the hydration (transcription) stage."""

from pydantic import Field, field_validator

from aria.models.base import ImmutableModel, StrictModel


class TranscriptSegment(ImmutableModel):
    """A single segment from Whisper transcription."""

    start: float = Field(..., ge=0.0, description="Start time in seconds")
    end: float = Field(..., ge=0.0, description="End time in seconds")
    text: str = Field(..., min_length=1, description="Transcribed text")
    avg_logprob: float = Field(..., le=0.0, description="Average log probability")
    no_speech_prob: float = Field(..., ge=0.0, le=1.0, description="Probability of no speech")

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        """Ensure end time is after start time."""
        if "start" in info.data and v <= info.data["start"]:
            raise ValueError("end must be greater than start")
        return v


class HydrationResult(StrictModel):
    """Complete result from hydration/transcription."""

    file_id: str = Field(..., min_length=1, max_length=256, description="Unique file identifier")
    source_bucket: str = Field(..., min_length=1, description="S3 bucket containing source audio")
    source_key: str = Field(..., min_length=1, description="S3 key of source audio")
    language: str = Field(..., min_length=2, max_length=10, description="Detected language code")
    language_probability: float = Field(..., ge=0.0, le=1.0, description="Language detection confidence")
    duration: float = Field(..., ge=0.0, description="Audio duration in seconds")
    text: str = Field(..., min_length=1, description="Full transcript text")
    segments: list[TranscriptSegment] = Field(..., min_length=1, description="Transcript segments")

    @field_validator("segments")
    @classmethod
    def segments_ordered(cls, v: list[TranscriptSegment]) -> list[TranscriptSegment]:
        """Ensure segments are ordered by start time."""
        for i in range(1, len(v)):
            if v[i].start < v[i - 1].start:
                raise ValueError("segments must be ordered by start time")
        return v

    @property
    def avg_confidence(self) -> float:
        """Calculate average confidence across segments."""
        if not self.segments:
            return 0.0
        return sum(s.avg_logprob for s in self.segments) / len(self.segments)


class HydrationOutput(StrictModel):
    """Output message from hydration worker to next stage."""

    file_id: str = Field(..., min_length=1)
    output_bucket: str = Field(..., min_length=1)
    output_key: str = Field(..., min_length=1)
    language: str = Field(..., min_length=2)
    duration: float = Field(..., ge=0.0)
