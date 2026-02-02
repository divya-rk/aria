"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AWSSettings(BaseSettings):
    """AWS-specific configuration."""

    model_config = SettingsConfigDict(env_prefix="AWS_")

    region: str = Field(default="us-east-1", description="AWS region")
    access_key_id: str | None = Field(default=None, description="AWS access key ID")
    secret_access_key: str | None = Field(default=None, description="AWS secret access key")


class S3Settings(BaseSettings):
    """S3 bucket configuration."""

    model_config = SettingsConfigDict(env_prefix="S3_")

    raw_bucket: str = Field(default="aria-raw", description="Raw audio input bucket")
    output_bucket: str = Field(default="aria-output", description="Processed output bucket")
    lancedb_bucket: str = Field(default="aria-lancedb", description="LanceDB storage bucket")


class SQSSettings(BaseSettings):
    """SQS queue configuration."""

    model_config = SettingsConfigDict(env_prefix="SQS_")

    ingestion_queue_url: str = Field(default="", description="Ingestion queue URL")
    dlq_url: str = Field(default="", description="Dead letter queue URL")
    max_receive_count: int = Field(default=3, description="Max retries before DLQ")
    visibility_timeout: int = Field(default=300, description="Message visibility timeout (seconds)")


class DynamoDBSettings(BaseSettings):
    """DynamoDB configuration."""

    model_config = SettingsConfigDict(env_prefix="DYNAMODB_")

    table_name: str = Field(default="aria-jobs", description="Jobs table name")
    endpoint_url: str | None = Field(default=None, description="Local endpoint for testing")


class LanceDBSettings(BaseSettings):
    """LanceDB configuration."""

    model_config = SettingsConfigDict(env_prefix="LANCEDB_")

    uri: str = Field(default="./data/lancedb", description="LanceDB URI (local path or S3)")
    table_name: str = Field(default="documents", description="Main documents table")
    embedding_dim: int = Field(default=1536, description="Embedding vector dimension")


class RaySettings(BaseSettings):
    """Ray cluster configuration."""

    model_config = SettingsConfigDict(env_prefix="RAY_")

    address: str | None = Field(default=None, description="Ray cluster address")
    num_cpus: int | None = Field(default=None, description="Number of CPUs per worker")
    num_gpus: int | None = Field(default=None, description="Number of GPUs per worker")


class WhisperSettings(BaseSettings):
    """Whisper model configuration."""

    model_config = SettingsConfigDict(env_prefix="WHISPER_")

    model_size: Literal["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"] = Field(
        default="large-v3", description="Whisper model size"
    )
    device: Literal["cpu", "cuda"] = Field(default="cuda", description="Compute device")
    batch_size: int = Field(default=16, description="Batch size for transcription")


class EmbeddingSettings(BaseSettings):
    """Embedding model configuration."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")

    model_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Sentence transformer model",
    )
    chunk_size: int = Field(default=512, description="Text chunk size in tokens")
    chunk_overlap: int = Field(default=50, description="Overlap between chunks")


class TokenizerSettings(BaseSettings):
    """Tokenizer configuration."""

    model_config = SettingsConfigDict(env_prefix="TOKENIZER_")

    model_name: str = Field(default="gpt-4", description="Tokenizer model name for tiktoken")
    shard_size: int = Field(default=100_000_000, description="Shard size in tokens")


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "staging", "prod"] = Field(
        default="dev", description="Deployment environment"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )
    debug: bool = Field(default=False, description="Enable debug mode")

    # Nested settings
    aws: AWSSettings = Field(default_factory=AWSSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    sqs: SQSSettings = Field(default_factory=SQSSettings)
    dynamodb: DynamoDBSettings = Field(default_factory=DynamoDBSettings)
    lancedb: LanceDBSettings = Field(default_factory=LanceDBSettings)
    ray: RaySettings = Field(default_factory=RaySettings)
    whisper: WhisperSettings = Field(default_factory=WhisperSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    tokenizer: TokenizerSettings = Field(default_factory=TokenizerSettings)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
