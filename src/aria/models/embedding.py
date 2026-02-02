"""Pydantic models for the embedding (vectorization) stage."""

from pydantic import Field, field_validator
import numpy as np
from typing import Annotated

from aria.models.base import ImmutableModel, StrictModel
from aria.models.curation import QualityTier


class ChunkRecord(ImmutableModel):
    """A text chunk from the chunking process."""

    chunk_id: str = Field(..., min_length=1, description="Unique chunk identifier")
    file_id: str = Field(..., min_length=1, description="Parent file identifier")
    chunk_index: int = Field(..., ge=0, description="Index within the file")
    text: str = Field(..., min_length=1, description="Chunk text content")
    start_char: int = Field(..., ge=0, description="Start character position")
    end_char: int = Field(..., ge=0, description="End character position")
    token_count: int = Field(..., ge=1, description="Number of tokens in chunk")

    @field_validator("end_char")
    @classmethod
    def end_after_start(cls, v: int, info) -> int:
        """Ensure end position is after start."""
        if "start_char" in info.data and v <= info.data["start_char"]:
            raise ValueError("end_char must be greater than start_char")
        return v


class EmbeddingRecord(StrictModel):
    """A single embedding record for storage in vector DB."""

    id: str = Field(..., min_length=1, description="Unique record identifier")
    file_id: str = Field(..., min_length=1, description="Source file identifier")
    chunk_index: int = Field(..., ge=0, description="Chunk index within file")
    text: str = Field(..., min_length=1, description="Original text")
    start_char: int = Field(..., ge=0, description="Start character position")
    end_char: int = Field(..., ge=0, description="End character position")
    vector: list[float] = Field(..., min_length=1, description="Embedding vector")
    language: str | None = Field(default=None, description="Language code")
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Quality score")
    quality_tier: QualityTier | None = Field(default=None, description="Quality tier")

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, v: list[float]) -> list[float]:
        """Validate vector is not all zeros and has valid values."""
        if all(x == 0.0 for x in v):
            raise ValueError("vector cannot be all zeros")
        if any(x != x for x in v):  # NaN check
            raise ValueError("vector contains NaN values")
        if any(abs(x) > 1e6 for x in v):
            raise ValueError("vector contains values out of expected range")
        return v


class EmbeddingResult(StrictModel):
    """Result from embedding a file's chunks."""

    file_id: str = Field(..., min_length=1)
    chunk_count: int = Field(..., ge=1, description="Number of chunks created")
    embedding_dim: int = Field(..., ge=1, description="Embedding dimension")
    records: list[EmbeddingRecord] = Field(..., min_length=1, description="Embedding records")

    @field_validator("records")
    @classmethod
    def validate_records(cls, v: list[EmbeddingRecord], info) -> list[EmbeddingRecord]:
        """Validate all records have consistent dimensions."""
        if not v:
            return v
        first_dim = len(v[0].vector)
        for record in v[1:]:
            if len(record.vector) != first_dim:
                raise ValueError(f"Inconsistent vector dimensions: expected {first_dim}, got {len(record.vector)}")
        return v


class EmbeddingOutput(StrictModel):
    """Output message from embedding worker to next stage."""

    file_id: str = Field(..., min_length=1)
    output_bucket: str = Field(..., min_length=1)
    output_key: str = Field(..., min_length=1)
    chunk_count: int = Field(..., ge=1)
    quality_tier: QualityTier | None = None
