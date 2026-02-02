"""Files API routes for browsing the vector database."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aria.config import get_settings
from aria.storage import LanceDBStore

router = APIRouter()

# Lazy initialization
_lancedb: LanceDBStore | None = None


def get_lancedb() -> LanceDBStore:
    """Get or create LanceDB instance."""
    global _lancedb
    if _lancedb is None:
        settings = get_settings()
        _lancedb = LanceDBStore(settings)
        _lancedb.create_table_if_not_exists()
    return _lancedb


class FileInfo(BaseModel):
    """File information."""

    file_id: str
    chunk_count: int
    quality_score: float | None = None
    preview: str | None = None


class FilesResponse(BaseModel):
    """List files response."""

    files: list[FileInfo]
    total: int
    limit: int
    offset: int


class ChunkInfo(BaseModel):
    """Chunk information."""

    id: str
    file_id: str
    chunk_index: int
    text: str
    start_char: int | None = None
    end_char: int | None = None
    quality_score: float | None = None


@router.get("/files", response_model=FilesResponse)
async def list_files(
    limit: int = Query(default=50, ge=1, le=500, description="Number of files to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    quality_tier: str | None = Query(default=None, description="Filter by quality tier"),
) -> FilesResponse:
    """
    List all files in the vector database.

    Returns paginated list of files with their chunk counts and average quality scores.
    """
    lancedb = get_lancedb()
    df = lancedb._table.to_pandas()

    # Group by file_id and aggregate
    file_stats = (
        df.groupby("file_id")
        .agg({
            "chunk_index": "count",
            "quality_score": "mean",
            "text": lambda x: str(x.iloc[0])[:200] if len(x) > 0 else "",
        })
        .reset_index()
        .rename(columns={"chunk_index": "chunk_count", "text": "preview"})
    )

    # Filter by quality tier if specified
    if quality_tier:
        if quality_tier == "high":
            file_stats = file_stats[file_stats["quality_score"] >= 0.8]
        elif quality_tier == "medium":
            file_stats = file_stats[
                (file_stats["quality_score"] >= 0.6) & (file_stats["quality_score"] < 0.8)
            ]
        elif quality_tier == "low":
            file_stats = file_stats[file_stats["quality_score"] < 0.6]

    total = len(file_stats)
    files_slice = file_stats.iloc[offset : offset + limit]

    files = [
        FileInfo(
            file_id=row["file_id"],
            chunk_count=int(row["chunk_count"]),
            quality_score=float(row["quality_score"]) if row["quality_score"] else None,
            preview=row["preview"][:200] + "..." if len(row["preview"]) > 200 else row["preview"],
        )
        for _, row in files_slice.iterrows()
    ]

    return FilesResponse(
        files=files,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/files/{file_id}", response_model=list[ChunkInfo])
async def get_file_chunks(file_id: str) -> list[ChunkInfo]:
    """
    Get all chunks for a specific file.

    Returns all chunks ordered by chunk index.
    """
    lancedb = get_lancedb()
    chunks = lancedb.get_by_file_id(file_id)

    if not chunks:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")

    return [
        ChunkInfo(
            id=chunk.get("id", ""),
            file_id=chunk.get("file_id", ""),
            chunk_index=chunk.get("chunk_index", 0),
            text=chunk.get("text", ""),
            start_char=chunk.get("start_char"),
            end_char=chunk.get("end_char"),
            quality_score=chunk.get("quality_score"),
        )
        for chunk in sorted(chunks, key=lambda x: x.get("chunk_index", 0))
    ]


@router.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str) -> dict[str, Any]:
    """Get a specific chunk by ID."""
    lancedb = get_lancedb()

    # Search for the specific chunk
    df = lancedb._table.to_pandas()
    chunk = df[df["id"] == chunk_id]

    if chunk.empty:
        raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")

    return chunk.iloc[0].to_dict()


@router.delete("/files/{file_id}")
async def delete_file(file_id: str) -> dict[str, Any]:
    """
    Delete all chunks for a specific file.

    Returns the number of chunks deleted.
    """
    lancedb = get_lancedb()
    count = lancedb.delete_by_file_id(file_id)

    if count == 0:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")

    return {"deleted": count, "file_id": file_id}
