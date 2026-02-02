"""Pydantic models for strict type checking across the Aria pipeline.

All data flowing through the pipeline must conform to these models to prevent
data contamination and ensure type safety.
"""

from aria.models.embedding import ChunkRecord, EmbeddingRecord, EmbeddingResult
from aria.models.hydration import HydrationResult, TranscriptSegment
from aria.models.curation import CurationResult, QualityMetrics
from aria.models.tokenization import ShardManifest, ShardRecord, TokenizationResult
from aria.models.pipeline import PipelineMessage, PipelineState, StageStatus

__all__ = [
    # Hydration
    "TranscriptSegment",
    "HydrationResult",
    # Curation
    "QualityMetrics",
    "CurationResult",
    # Embedding
    "ChunkRecord",
    "EmbeddingRecord",
    "EmbeddingResult",
    # Tokenization
    "ShardRecord",
    "ShardManifest",
    "TokenizationResult",
    # Pipeline
    "PipelineMessage",
    "PipelineState",
    "StageStatus",
]
