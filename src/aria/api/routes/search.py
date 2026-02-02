"""Search API routes."""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from aria.config import get_settings
from aria.query.search import VectorSearch

router = APIRouter()

# Lazy initialization
_search: VectorSearch | None = None


def get_search() -> VectorSearch:
    """Get or create search instance."""
    global _search
    if _search is None:
        settings = get_settings()
        _search = VectorSearch(settings)
    return _search


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
    quality_score: float | None = None
    chunk_index: int | None = None


class SearchResponse(BaseModel):
    """Search response."""

    query: str
    results: list[SearchResult]
    total: int


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """
    Search for similar documents using semantic search.

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


@router.get("/search", response_model=SearchResponse)
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
