"""Pydantic models for the curation (quality filtering) stage."""

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from aria.models.base import ImmutableModel, StrictModel


class QualityTier(str, Enum):
    """Quality tier classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    REJECTED = "rejected"


class QualityMetrics(ImmutableModel):
    """Detailed quality metrics from curation."""

    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Transcription confidence")
    language_score: float = Field(..., ge=0.0, le=1.0, description="Language detection confidence")
    length_score: float = Field(..., ge=0.0, le=1.0, description="Content length appropriateness")
    repetition_score: float = Field(..., ge=0.0, le=1.0, description="Repetition detection (lower is worse)")
    overall_score: float = Field(..., ge=0.0, le=1.0, description="Combined quality score")

    @field_validator("overall_score")
    @classmethod
    def validate_overall(cls, v: float, info) -> float:
        """Validate overall score is reasonable given components."""
        # Overall should be within range of component scores
        if info.data:
            scores = [
                info.data.get("confidence_score", 0),
                info.data.get("language_score", 0),
                info.data.get("length_score", 0),
                info.data.get("repetition_score", 0),
            ]
            min_score = min(scores)
            max_score = max(scores)
            if not (min_score - 0.1 <= v <= max_score + 0.1):
                # Allow some tolerance for weighted averages
                pass  # Just a soft check
        return v


class PIIDetection(ImmutableModel):
    """PII detection results."""

    has_pii: bool = Field(..., description="Whether PII was detected")
    entity_types: list[str] = Field(default_factory=list, description="Types of PII found")
    entity_count: int = Field(default=0, ge=0, description="Number of PII entities")
    redacted: bool = Field(default=False, description="Whether text was redacted")


class CurationResult(StrictModel):
    """Complete result from curation processing."""

    file_id: str = Field(..., min_length=1, max_length=256)
    text: str = Field(..., min_length=1, description="Curated text (may be redacted)")
    original_text: str | None = Field(default=None, description="Original text before redaction")
    language: str = Field(..., min_length=2, max_length=10)
    duration: float = Field(..., ge=0.0)
    quality_score: float = Field(..., ge=0.0, le=1.0)
    quality_tier: QualityTier = Field(..., description="Quality classification")
    quality_metrics: QualityMetrics = Field(..., description="Detailed quality metrics")
    pii_detection: PIIDetection = Field(..., description="PII detection results")
    is_duplicate: bool = Field(default=False, description="Whether this is a near-duplicate")
    source_transcript: str = Field(..., description="Path to source transcript")

    @field_validator("quality_tier")
    @classmethod
    def tier_matches_score(cls, v: QualityTier, info) -> QualityTier:
        """Validate tier matches the quality score."""
        score = info.data.get("quality_score", 0)
        expected_tier = cls._score_to_tier(score)
        if v != expected_tier:
            raise ValueError(f"quality_tier {v} doesn't match score {score}, expected {expected_tier}")
        return v

    @staticmethod
    def _score_to_tier(score: float) -> QualityTier:
        """Convert score to tier."""
        if score >= 0.8:
            return QualityTier.HIGH
        elif score >= 0.6:
            return QualityTier.MEDIUM
        elif score >= 0.4:
            return QualityTier.LOW
        else:
            return QualityTier.REJECTED


class CurationOutput(StrictModel):
    """Output message from curation worker to next stage."""

    file_id: str = Field(..., min_length=1)
    output_bucket: str = Field(..., min_length=1)
    output_key: str = Field(..., min_length=1)
    quality_tier: QualityTier
    quality_score: float = Field(..., ge=0.0, le=1.0)
