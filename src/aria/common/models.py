"""Pydantic models for data structures."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Processing job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(str, Enum):
    """Processing pipeline stages."""

    COLLECTION = "collection"
    HYDRATION = "hydration"
    CURATION = "curation"
    EMBEDDING = "embedding"
    TOKENIZATION = "tokenization"


class AudioFile(BaseModel):
    """Represents an audio file to be processed."""

    file_id: str = Field(..., description="Unique file identifier (S3 key hash)")
    s3_bucket: str = Field(..., description="Source S3 bucket")
    s3_key: str = Field(..., description="Source S3 key")
    file_size: int = Field(..., description="File size in bytes")
    content_type: str = Field(default="audio/mpeg", description="MIME type")
    duration_seconds: float | None = Field(default=None, description="Audio duration")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class QualityScore(BaseModel):
    """Quality assessment scores for processed content."""

    overall: float = Field(..., ge=0.0, le=1.0, description="Overall quality score")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Transcription confidence")
    language_score: float = Field(..., ge=0.0, le=1.0, description="Language detection confidence")
    pii_detected: bool = Field(default=False, description="Whether PII was detected")
    is_duplicate: bool = Field(default=False, description="Whether content is duplicate")
    word_count: int = Field(default=0, description="Total word count")


class ProcessingResult(BaseModel):
    """Result of processing a single file."""

    file_id: str = Field(..., description="Processed file ID")
    success: bool = Field(..., description="Whether processing succeeded")
    stage: JobStage = Field(..., description="Processing stage")
    output_location: str | None = Field(default=None, description="Output S3 path")
    quality_score: QualityScore | None = Field(default=None, description="Quality assessment")
    error_message: str | None = Field(default=None, description="Error message if failed")
    processing_time_seconds: float = Field(default=0.0, description="Processing duration")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class JobRecord(BaseModel):
    """DynamoDB job record."""

    file_id: str = Field(..., description="Partition key - file identifier")
    stage: JobStage = Field(..., description="Sort key - processing stage")
    status: JobStatus = Field(default=JobStatus.PENDING, description="Current status")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    quality_score: float | None = Field(default=None, description="Quality score if computed")
    error_message: str | None = Field(default=None, description="Error message if failed")
    output_location: str | None = Field(default=None, description="Output S3 path")
    retry_count: int = Field(default=0, description="Number of retry attempts")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Convert to DynamoDB item format."""
        return {
            "file_id": {"S": self.file_id},
            "stage": {"S": self.stage.value},
            "status": {"S": self.status.value},
            "created_at": {"S": self.created_at.isoformat()},
            "updated_at": {"S": self.updated_at.isoformat()},
            "quality_score": {"N": str(self.quality_score)} if self.quality_score else {"NULL": True},
            "error_message": {"S": self.error_message} if self.error_message else {"NULL": True},
            "output_location": {"S": self.output_location} if self.output_location else {"NULL": True},
            "retry_count": {"N": str(self.retry_count)},
            "metadata": {"S": str(self.metadata)},
        }


class ChunkMetadata(BaseModel):
    """Metadata for a text chunk."""

    chunk_id: str = Field(..., description="Unique chunk identifier")
    file_id: str = Field(..., description="Source file identifier")
    chunk_index: int = Field(..., description="Chunk position in document")
    start_char: int = Field(..., description="Start character position")
    end_char: int = Field(..., description="End character position")
    speaker: str | None = Field(default=None, description="Speaker ID if diarized")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Chunk quality score")


class Document(BaseModel):
    """Document with embedding for vector storage."""

    id: str = Field(..., description="Unique document/chunk ID")
    file_id: str = Field(..., description="Source file reference")
    text: str = Field(..., description="Text content")
    vector: list[float] = Field(..., description="Embedding vector")
    metadata: ChunkMetadata = Field(..., description="Chunk metadata")

    class Config:
        """Pydantic config."""

        arbitrary_types_allowed = True


class TokenizedShard(BaseModel):
    """Represents a tokenized data shard."""

    shard_id: str = Field(..., description="Unique shard identifier")
    shard_index: int = Field(..., description="Shard sequence number")
    token_count: int = Field(..., description="Number of tokens in shard")
    file_ids: list[str] = Field(..., description="Source file IDs included")
    s3_location: str = Field(..., description="S3 output path")
    created_at: datetime = Field(default_factory=datetime.utcnow)
