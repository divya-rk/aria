"""Pydantic models for the tokenization (sharding) stage."""

from datetime import datetime

from pydantic import Field, field_validator

from aria.models.base import ImmutableModel, StrictModel


class ShardRecord(ImmutableModel):
    """A single record within a shard."""

    file_id: str = Field(..., min_length=1, description="Source file identifier")
    tokens: list[int] = Field(..., min_length=1, description="Token IDs")
    token_count: int = Field(..., ge=1, description="Number of tokens")
    language: str | None = Field(default=None, description="Language code")
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("token_count")
    @classmethod
    def validate_token_count(cls, v: int, info) -> int:
        """Ensure token_count matches actual tokens length."""
        if "tokens" in info.data and v != len(info.data["tokens"]):
            raise ValueError(f"token_count ({v}) doesn't match tokens length ({len(info.data['tokens'])})")
        return v

    @field_validator("tokens")
    @classmethod
    def validate_tokens(cls, v: list[int]) -> list[int]:
        """Validate token IDs are non-negative."""
        if any(t < 0 for t in v):
            raise ValueError("token IDs must be non-negative")
        return v


class ShardMetadata(ImmutableModel):
    """Metadata for a single shard file."""

    shard_id: str = Field(..., min_length=1, description="Unique shard identifier")
    shard_index: int = Field(..., ge=0, description="Shard index in sequence")
    file_path: str = Field(..., min_length=1, description="S3 path to shard file")
    token_count: int = Field(..., ge=1, description="Total tokens in shard")
    record_count: int = Field(..., ge=1, description="Number of records in shard")
    file_ids: list[str] = Field(..., min_length=1, description="Source file IDs in shard")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    checksum: str = Field(..., min_length=1, description="File checksum for integrity")


class ShardManifest(StrictModel):
    """Manifest tracking all shards produced."""

    project: str = Field(..., min_length=1, description="Project name")
    environment: str = Field(..., min_length=1, description="Environment (dev/prod)")
    tokenizer_model: str = Field(..., min_length=1, description="Tokenizer model name")
    total_tokens: int = Field(..., ge=0, description="Total tokens across all shards")
    total_records: int = Field(..., ge=0, description="Total records across all shards")
    total_shards: int = Field(..., ge=0, description="Number of shards")
    shard_size_target: int = Field(..., ge=1, description="Target tokens per shard")
    shards: list[ShardMetadata] = Field(default_factory=list, description="List of shard metadata")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None
    version: str = Field(default="1.0", description="Manifest version")

    @field_validator("total_shards")
    @classmethod
    def validate_shard_count(cls, v: int, info) -> int:
        """Ensure total_shards matches shards list length."""
        if "shards" in info.data and v != len(info.data["shards"]):
            raise ValueError(f"total_shards ({v}) doesn't match shards length ({len(info.data['shards'])})")
        return v

    def add_shard(self, shard: ShardMetadata) -> None:
        """Add a shard to the manifest and update totals."""
        self.shards.append(shard)
        self.total_shards = len(self.shards)
        self.total_tokens += shard.token_count
        self.total_records += shard.record_count
        self.updated_at = datetime.utcnow()


class TokenizationResult(StrictModel):
    """Result from tokenizing a file."""

    file_id: str = Field(..., min_length=1)
    token_count: int = Field(..., ge=1, description="Number of tokens")
    added_to_shard: str | None = Field(default=None, description="Shard ID if added")
    language: str | None = None
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
