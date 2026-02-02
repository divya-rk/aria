"""Data sharder for creating training data shards."""

import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from aria.common import get_logger
from aria.tokenization.tokenizer import TokenizedDocument


logger = get_logger(__name__)


@dataclass
class Shard:
    """A data shard for training."""

    shard_id: str
    shard_index: int
    tokens: list[int]
    token_count: int
    file_ids: list[str]
    created_at: datetime = field(default_factory=datetime.utcnow)


class Sharder:
    """Create fixed-size shards from tokenized documents."""

    def __init__(
        self,
        shard_size: int = 100_000_000,  # 100M tokens per shard
        prefix: str = "shard",
    ) -> None:
        """
        Initialize sharder.

        Args:
            shard_size: Target tokens per shard
            prefix: Shard name prefix
        """
        self.shard_size = shard_size
        self.prefix = prefix

        self._current_tokens: list[int] = []
        self._current_file_ids: list[str] = []
        self._shard_index = 0

    def add_document(
        self,
        doc: TokenizedDocument,
    ) -> Shard | None:
        """
        Add document to current shard.

        Args:
            doc: Tokenized document to add

        Returns:
            Completed Shard if shard is full, None otherwise
        """
        self._current_tokens.extend(doc.tokens)
        self._current_file_ids.append(doc.file_id)

        # Check if shard is full
        if len(self._current_tokens) >= self.shard_size:
            return self._finalize_shard()

        return None

    def _finalize_shard(self) -> Shard:
        """Finalize and return current shard."""
        shard = Shard(
            shard_id=f"{self.prefix}_{self._shard_index:05d}",
            shard_index=self._shard_index,
            tokens=self._current_tokens,
            token_count=len(self._current_tokens),
            file_ids=self._current_file_ids,
        )

        logger.info(
            "shard_created",
            shard_id=shard.shard_id,
            token_count=shard.token_count,
            file_count=len(shard.file_ids),
        )

        # Reset for next shard
        self._current_tokens = []
        self._current_file_ids = []
        self._shard_index += 1

        return shard

    def flush(self) -> Shard | None:
        """
        Flush remaining tokens as final shard.

        Returns:
            Final Shard if there are remaining tokens, None otherwise
        """
        if self._current_tokens:
            return self._finalize_shard()
        return None

    def create_shards(
        self,
        documents: list[TokenizedDocument],
    ) -> list[Shard]:
        """
        Create shards from list of documents.

        Args:
            documents: List of tokenized documents

        Returns:
            List of created shards
        """
        shards = []

        for doc in documents:
            shard = self.add_document(doc)
            if shard:
                shards.append(shard)

        # Flush remaining
        final_shard = self.flush()
        if final_shard:
            shards.append(final_shard)

        logger.info(
            "sharding_complete",
            total_shards=len(shards),
            total_tokens=sum(s.token_count for s in shards),
        )

        return shards

    def stream_shards(
        self,
        documents: Iterator[TokenizedDocument],
    ) -> Iterator[Shard]:
        """
        Stream shards from document iterator.

        Args:
            documents: Iterator of tokenized documents

        Yields:
            Shards as they are completed
        """
        for doc in documents:
            shard = self.add_document(doc)
            if shard:
                yield shard

        # Final shard
        final_shard = self.flush()
        if final_shard:
            yield final_shard


class ShardWriter:
    """Write shards to various formats."""

    @staticmethod
    def to_parquet(shard: Shard) -> bytes:
        """
        Serialize shard to Parquet format.

        Args:
            shard: Shard to serialize

        Returns:
            Parquet bytes
        """
        # Create Arrow table
        table = pa.table({
            "shard_id": [shard.shard_id],
            "shard_index": [shard.shard_index],
            "tokens": [shard.tokens],
            "token_count": [shard.token_count],
            "file_ids": [json.dumps(shard.file_ids)],
            "created_at": [shard.created_at.isoformat()],
        })

        # Write to bytes buffer
        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="snappy")
        buffer.seek(0)

        return buffer.read()

    @staticmethod
    def to_jsonl(shard: Shard) -> str:
        """
        Serialize shard to JSONL format.

        Args:
            shard: Shard to serialize

        Returns:
            JSONL string
        """
        record = {
            "shard_id": shard.shard_id,
            "shard_index": shard.shard_index,
            "tokens": shard.tokens,
            "token_count": shard.token_count,
            "file_ids": shard.file_ids,
            "created_at": shard.created_at.isoformat(),
        }
        return json.dumps(record)

    @staticmethod
    def create_manifest(shards: list[Shard]) -> dict[str, Any]:
        """
        Create manifest file for shard collection.

        Args:
            shards: List of shards

        Returns:
            Manifest dictionary
        """
        return {
            "version": "1.0",
            "created_at": datetime.utcnow().isoformat(),
            "total_shards": len(shards),
            "total_tokens": sum(s.token_count for s in shards),
            "total_files": sum(len(s.file_ids) for s in shards),
            "shards": [
                {
                    "shard_id": s.shard_id,
                    "shard_index": s.shard_index,
                    "token_count": s.token_count,
                    "file_count": len(s.file_ids),
                }
                for s in shards
            ],
        }
