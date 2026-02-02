"""Statistics API routes."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from aria.config import get_settings
from aria.query.validate import DataValidator
from aria.storage import LanceDBStore

router = APIRouter()

# Lazy initialization
_lancedb: LanceDBStore | None = None
_validator: DataValidator | None = None


def get_lancedb() -> LanceDBStore:
    """Get or create LanceDB instance."""
    global _lancedb
    if _lancedb is None:
        settings = get_settings()
        _lancedb = LanceDBStore(settings)
        _lancedb.create_table_if_not_exists()
    return _lancedb


def get_validator() -> DataValidator:
    """Get or create validator instance."""
    global _validator
    if _validator is None:
        settings = get_settings()
        _validator = DataValidator(settings)
    return _validator


class LanceDBStats(BaseModel):
    """LanceDB statistics."""

    table_name: str
    total_documents: int
    uri: str
    embedding_dim: int


class PipelineStageStats(BaseModel):
    """Pipeline stage statistics."""

    completed: int = 0
    failed: int = 0
    processing: int = 0


class PipelineStats(BaseModel):
    """Pipeline statistics."""

    stages: dict[str, PipelineStageStats]


class StatsResponse(BaseModel):
    """Combined statistics response."""

    lancedb: LanceDBStats
    pipeline: PipelineStats | None = None
    summary: dict[str, Any]


@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """
    Get comprehensive database and pipeline statistics.

    Returns statistics from LanceDB, pipeline state, and a summary.
    """
    lancedb = get_lancedb()
    validator = get_validator()

    # LanceDB stats
    db_stats = lancedb.get_stats()
    lancedb_stats = LanceDBStats(
        table_name=db_stats.get("table_name", "unknown"),
        total_documents=db_stats.get("total_documents", 0),
        uri=db_stats.get("uri", "unknown"),
        embedding_dim=db_stats.get("embedding_dim", 0),
    )

    # Pipeline stats
    pipeline_stats = None
    try:
        raw_pipeline_stats = validator.get_pipeline_stats()
        if raw_pipeline_stats and "stages" in raw_pipeline_stats:
            stages = {
                stage: PipelineStageStats(**counts)
                for stage, counts in raw_pipeline_stats["stages"].items()
            }
            pipeline_stats = PipelineStats(stages=stages)
    except Exception:
        pass

    # Calculate summary
    df = lancedb._table.to_pandas()
    summary = {
        "unique_files": int(df["file_id"].nunique()) if not df.empty else 0,
        "avg_quality_score": float(df["quality_score"].mean()) if not df.empty else 0,
        "avg_chunks_per_file": float(len(df) / max(df["file_id"].nunique(), 1)) if not df.empty else 0,
        "quality_distribution": df["quality_score"].describe().to_dict() if not df.empty else {},
    }

    return StatsResponse(
        lancedb=lancedb_stats,
        pipeline=pipeline_stats,
        summary=summary,
    )


@router.get("/stats/quality")
async def get_quality_distribution() -> dict[str, Any]:
    """Get quality score distribution."""
    lancedb = get_lancedb()
    df = lancedb._table.to_pandas()

    if df.empty:
        return {"distribution": {}, "total": 0}

    # Create quality tier buckets
    bins = [0, 0.4, 0.6, 0.8, 1.0]
    labels = ["rejected", "low", "medium", "high"]
    df["tier"] = pd.cut(df["quality_score"], bins=bins, labels=labels)

    distribution = df["tier"].value_counts().to_dict()

    return {
        "distribution": {str(k): int(v) for k, v in distribution.items()},
        "total": len(df),
        "mean": float(df["quality_score"].mean()),
        "median": float(df["quality_score"].median()),
        "std": float(df["quality_score"].std()),
    }


@router.get("/stats/languages")
async def get_language_distribution() -> dict[str, Any]:
    """Get language distribution of documents."""
    lancedb = get_lancedb()
    df = lancedb._table.to_pandas()

    if df.empty or "language" not in df.columns:
        return {"distribution": {}, "total": 0}

    # Get unique files per language
    file_langs = df.groupby("file_id")["language"].first().value_counts()

    return {
        "distribution": file_langs.to_dict(),
        "total": int(df["file_id"].nunique()),
    }


# Import pandas for quality distribution
import pandas as pd
