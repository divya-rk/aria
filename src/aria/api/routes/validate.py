"""Validation API routes."""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from aria.config import get_settings
from aria.query.validate import DataValidator

router = APIRouter()

# Lazy initialization
_validator: DataValidator | None = None


def get_validator() -> DataValidator:
    """Get or create validator instance."""
    global _validator
    if _validator is None:
        settings = get_settings()
        _validator = DataValidator(settings)
    return _validator


class ValidationIssue(BaseModel):
    """Single validation issue."""

    type: str
    message: str
    record_id: str | None = None


class ValidationResponse(BaseModel):
    """Validation response."""

    total_checked: int = Field(..., ge=0)
    passed: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    pass_rate: float = Field(..., ge=0.0, le=1.0)
    issues: list[dict[str, Any]]


class QualityReport(BaseModel):
    """Comprehensive quality report."""

    overall_health: str
    embedding_quality: dict[str, Any]
    pipeline_completeness: dict[str, Any]
    lancedb_health: dict[str, Any]


@router.get("/validate/embeddings", response_model=ValidationResponse)
async def validate_embeddings(
    sample_size: int = Query(default=1000, ge=100, le=10000, description="Sample size for validation"),
) -> ValidationResponse:
    """
    Validate embedding quality by sampling.

    Checks for:
    - Correct vector dimensions
    - Zero vectors
    - NaN values
    - Proper normalization
    """
    validator = get_validator()
    report = validator.validate_embeddings(sample_size)

    return ValidationResponse(
        total_checked=report.total_checked,
        passed=report.passed,
        failed=report.failed,
        pass_rate=report.pass_rate,
        issues=report.issues,
    )


@router.get("/validate/pipeline", response_model=ValidationResponse)
async def validate_pipeline() -> ValidationResponse:
    """
    Validate pipeline completeness.

    Checks for:
    - Files that started but didn't complete
    - Orphaned records
    - Missing stages
    """
    validator = get_validator()
    report = validator.validate_pipeline_completeness()

    return ValidationResponse(
        total_checked=report.total_checked,
        passed=report.passed,
        failed=report.failed,
        pass_rate=report.pass_rate,
        issues=report.issues,
    )


@router.get("/validate/report", response_model=QualityReport)
async def quality_report() -> QualityReport:
    """Generate comprehensive quality report."""
    validator = get_validator()
    report = validator.generate_quality_report()

    return QualityReport(
        overall_health=report.get("overall_health", "unknown"),
        embedding_quality=report.get("embedding_quality", {}),
        pipeline_completeness=report.get("pipeline_completeness", {}),
        lancedb_health=report.get("lancedb_health", {}),
    )
