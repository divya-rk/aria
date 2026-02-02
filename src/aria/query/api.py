"""FastAPI application for query interface."""

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from aria.common import get_logger, setup_logging
from aria.config import get_settings
from aria.query.search import VectorSearch
from aria.query.validate import DataValidator


# Initialize
setup_logging()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title="Aria Query API",
    description="Search and validate the Aria data pipeline",
    version="0.1.0",
)

# Initialize services (lazy)
_search: VectorSearch | None = None
_validator: DataValidator | None = None


def get_search() -> VectorSearch:
    """Get or create search instance."""
    global _search
    if _search is None:
        _search = VectorSearch(settings)
    return _search


def get_validator() -> DataValidator:
    """Get or create validator instance."""
    global _validator
    if _validator is None:
        _validator = DataValidator(settings)
    return _validator


# Request/Response models
class SearchRequest(BaseModel):
    """Search request body."""

    query: str = Field(..., min_length=1, description="Search query text")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum similarity")
    quality_filter: str | None = Field(default=None, description="Quality tier filter")


class SearchResult(BaseModel):
    """Single search result."""

    id: str
    file_id: str
    text: str
    score: float
    quality_score: float | None
    chunk_index: int | None


class SearchResponse(BaseModel):
    """Search response."""

    query: str
    results: list[SearchResult]
    total: int


class ValidationResponse(BaseModel):
    """Validation response."""

    total_checked: int
    passed: int
    failed: int
    pass_rate: float
    issues: list[dict[str, Any]]


class StatsResponse(BaseModel):
    """Statistics response."""

    lancedb: dict[str, Any]
    pipeline: dict[str, Any] | None = None


# Endpoints
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """
    Search for similar documents.

    - **query**: Text to search for
    - **top_k**: Maximum number of results (1-100)
    - **min_score**: Minimum similarity score (0-1)
    - **quality_filter**: Filter by quality tier (high/medium/low)
    """
    search_service = get_search()

    results = search_service.search(
        query=request.query,
        top_k=request.top_k,
        min_score=request.min_score,
        filter_quality=request.quality_filter,
    )

    return SearchResponse(
        query=request.query,
        results=[SearchResult(**r) for r in results],
        total=len(results),
    )


@app.get("/search")
async def search_get(
    q: str = Query(..., min_length=1, description="Search query"),
    top_k: int = Query(default=10, ge=1, le=100),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
) -> SearchResponse:
    """Search using GET request."""
    search_service = get_search()

    results = search_service.search(
        query=q,
        top_k=top_k,
        min_score=min_score,
    )

    return SearchResponse(
        query=q,
        results=[SearchResult(**r) for r in results],
        total=len(results),
    )


@app.get("/document/{doc_id}")
async def get_document(doc_id: str) -> dict[str, Any]:
    """Get a specific document by ID."""
    search_service = get_search()

    doc = search_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return doc


@app.get("/file/{file_id}/chunks")
async def get_file_chunks(file_id: str) -> list[dict[str, Any]]:
    """Get all chunks for a specific file."""
    search_service = get_search()

    chunks = search_service.get_by_file(file_id)
    return chunks


@app.get("/validate/embeddings", response_model=ValidationResponse)
async def validate_embeddings(
    sample_size: int = Query(default=1000, ge=100, le=10000),
) -> ValidationResponse:
    """Validate embedding quality by sampling."""
    validator = get_validator()

    report = validator.validate_embeddings(sample_size)

    return ValidationResponse(
        total_checked=report.total_checked,
        passed=report.passed,
        failed=report.failed,
        pass_rate=report.pass_rate,
        issues=report.issues,
    )


@app.get("/validate/pipeline", response_model=ValidationResponse)
async def validate_pipeline() -> ValidationResponse:
    """Validate pipeline completeness."""
    validator = get_validator()

    report = validator.validate_pipeline_completeness()

    return ValidationResponse(
        total_checked=report.total_checked,
        passed=report.passed,
        failed=report.failed,
        pass_rate=report.pass_rate,
        issues=report.issues,
    )


@app.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """Get database and pipeline statistics."""
    search_service = get_search()
    validator = get_validator()

    lancedb_stats = search_service._lancedb.get_stats()

    try:
        pipeline_stats = validator.get_pipeline_stats()
    except Exception:
        pipeline_stats = None

    return StatsResponse(
        lancedb=lancedb_stats,
        pipeline=pipeline_stats,
    )


@app.get("/report/quality")
async def quality_report() -> dict[str, Any]:
    """Generate comprehensive quality report."""
    validator = get_validator()
    return validator.generate_quality_report()


def create_app() -> FastAPI:
    """Factory function for creating the app."""
    return app
