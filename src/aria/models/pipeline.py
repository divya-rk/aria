"""Pydantic models for pipeline state and message passing."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from aria.models.base import StrictModel, TimestampedModel


class StageType(str, Enum):
    """Pipeline stage types."""

    COLLECTION = "collection"
    HYDRATION = "hydration"
    CURATION = "curation"
    EMBEDDING = "embedding"
    TOKENIZATION = "tokenization"


class StageStatus(str, Enum):
    """Status of a file at a pipeline stage."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineMessage(StrictModel):
    """Message passed between pipeline stages via SQS.

    This is the standard envelope for all inter-stage communication.
    """

    source_stage: StageType = Field(..., description="Stage that produced this message")
    target_stage: StageType = Field(..., description="Intended consumer stage")
    file_id: str = Field(..., min_length=1, max_length=256, description="File being processed")
    payload: dict[str, Any] = Field(..., description="Stage-specific payload data")
    trace_id: str = Field(..., min_length=1, description="Distributed tracing ID")
    attempt: int = Field(default=1, ge=1, le=10, description="Processing attempt number")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("target_stage")
    @classmethod
    def validate_stage_order(cls, v: StageType, info) -> StageType:
        """Validate target stage comes after source stage."""
        source = info.data.get("source_stage")
        if source:
            stage_order = list(StageType)
            source_idx = stage_order.index(source)
            target_idx = stage_order.index(v)
            if target_idx <= source_idx:
                raise ValueError(f"target_stage {v} must come after source_stage {source}")
        return v


class FileStageState(StrictModel):
    """State of a file at a specific pipeline stage."""

    file_id: str = Field(..., min_length=1)
    stage: StageType
    status: StageStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    output_location: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineState(TimestampedModel):
    """Complete pipeline state for a file.

    Stored in DynamoDB to track progress through all stages.
    """

    file_id: str = Field(..., min_length=1, max_length=256, description="Unique file identifier")
    source_bucket: str = Field(..., min_length=1, description="Original S3 bucket")
    source_key: str = Field(..., min_length=1, description="Original S3 key")
    file_size: int = Field(..., ge=0, description="File size in bytes")
    content_type: str | None = Field(default=None, description="MIME type")

    # Stage states
    stages: dict[StageType, FileStageState] = Field(
        default_factory=dict,
        description="State for each pipeline stage",
    )

    # Final outputs
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_tier: str | None = None
    language: str | None = None
    duration: float | None = Field(default=None, ge=0.0)

    # Error tracking
    error_count: int = Field(default=0, ge=0)
    last_error: str | None = None

    def get_current_stage(self) -> StageType | None:
        """Get the current/latest stage being processed."""
        for stage in reversed(list(StageType)):
            if stage in self.stages:
                return stage
        return None

    def is_complete(self) -> bool:
        """Check if file has completed all stages."""
        return (
            StageType.TOKENIZATION in self.stages
            and self.stages[StageType.TOKENIZATION].status == StageStatus.COMPLETED
        )

    def is_failed(self) -> bool:
        """Check if file has failed at any stage."""
        return any(
            state.status == StageStatus.FAILED
            for state in self.stages.values()
        )

    def update_stage(
        self,
        stage: StageType,
        status: StageStatus,
        output_location: str | None = None,
        error_message: str | None = None,
        **metadata: Any,
    ) -> None:
        """Update state for a specific stage."""
        now = datetime.utcnow()

        if stage not in self.stages:
            self.stages[stage] = FileStageState(
                file_id=self.file_id,
                stage=stage,
                status=status,
                started_at=now,
            )
        else:
            self.stages[stage].status = status

        if status == StageStatus.COMPLETED:
            self.stages[stage].completed_at = now
            self.stages[stage].output_location = output_location

        if status == StageStatus.FAILED:
            self.stages[stage].error_message = error_message
            self.error_count += 1
            self.last_error = error_message

        if metadata:
            self.stages[stage].metadata.update(metadata)

        self.touch()


class S3EventRecord(StrictModel):
    """Parsed S3 event notification record."""

    event_name: str = Field(..., description="S3 event type")
    bucket_name: str = Field(..., min_length=1)
    object_key: str = Field(..., min_length=1)
    object_size: int = Field(..., ge=0)
    etag: str | None = None
    event_time: datetime

    @classmethod
    def from_sqs_record(cls, record: dict[str, Any]) -> "S3EventRecord":
        """Parse from SQS message containing S3 event."""
        s3_info = record.get("s3", {})
        return cls(
            event_name=record.get("eventName", ""),
            bucket_name=s3_info.get("bucket", {}).get("name", ""),
            object_key=s3_info.get("object", {}).get("key", ""),
            object_size=s3_info.get("object", {}).get("size", 0),
            etag=s3_info.get("object", {}).get("eTag"),
            event_time=datetime.fromisoformat(
                record.get("eventTime", "").replace("Z", "+00:00")
            ),
        )
