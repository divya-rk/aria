"""Common utilities and shared components."""

from aria.common.errors import (
    AriaError,
    ConfigurationError,
    ProcessingError,
    StorageError,
    ValidationError,
)
from aria.common.logging import get_logger, setup_logging
from aria.common.models import (
    AudioFile,
    ChunkMetadata,
    Document,
    JobRecord,
    JobStage,
    JobStatus,
    ProcessingResult,
    QualityScore,
)


__all__ = [
    # Errors
    "AriaError",
    "ConfigurationError",
    "ProcessingError",
    "StorageError",
    "ValidationError",
    # Logging
    "get_logger",
    "setup_logging",
    # Models
    "AudioFile",
    "ChunkMetadata",
    "Document",
    "JobRecord",
    "JobStage",
    "JobStatus",
    "ProcessingResult",
    "QualityScore",
]
