"""LanceDB vector store for document embeddings."""

from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

from aria.common import Document, StorageError, get_logger
from aria.config import Settings


logger = get_logger(__name__)


class LanceDBStore:
    """Vector store using LanceDB."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize LanceDB connection.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.uri = settings.lancedb.uri
        self.table_name = settings.lancedb.table_name
        self.embedding_dim = settings.lancedb.embedding_dim

        self._db: lancedb.DBConnection | None = None
        self._table: lancedb.table.Table | None = None

    def connect(self) -> None:
        """Establish connection to LanceDB."""
        # Create local directory if using local storage
        if not self.uri.startswith("s3://"):
            Path(self.uri).mkdir(parents=True, exist_ok=True)

        self._db = lancedb.connect(self.uri)
        logger.info("lancedb_connected", uri=self.uri)

    def create_table_if_not_exists(self) -> None:
        """Create documents table if it doesn't exist."""
        if self._db is None:
            self.connect()

        assert self._db is not None

        if self.table_name in self._db.table_names():
            self._table = self._db.open_table(self.table_name)
            logger.info("lancedb_table_opened", table=self.table_name)
        else:
            self._create_table()

    def _create_table(self) -> None:
        """Create the documents table with schema."""
        assert self._db is not None

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("file_id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), self.embedding_dim)),
            pa.field("chunk_id", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("start_char", pa.int32()),
            pa.field("end_char", pa.int32()),
            pa.field("speaker", pa.string()),
            pa.field("quality_score", pa.float32()),
        ])

        self._table = self._db.create_table(self.table_name, schema=schema)
        logger.info("lancedb_table_created", table=self.table_name)

    def add_documents(self, documents: list[Document]) -> int:
        """
        Add documents to the vector store.

        Args:
            documents: List of documents with embeddings

        Returns:
            Number of documents added
        """
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None

        try:
            data = [
                {
                    "id": doc.id,
                    "file_id": doc.file_id,
                    "text": doc.text,
                    "vector": doc.vector,
                    "chunk_id": doc.metadata.chunk_id,
                    "chunk_index": doc.metadata.chunk_index,
                    "start_char": doc.metadata.start_char,
                    "end_char": doc.metadata.end_char,
                    "speaker": doc.metadata.speaker,
                    "quality_score": doc.metadata.quality_score,
                }
                for doc in documents
            ]

            self._table.add(data)
            logger.info("documents_added", count=len(documents))
            return len(documents)

        except Exception as e:
            raise StorageError(f"Failed to add documents: {e}") from e

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar documents.

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            filter_expr: Optional SQL filter expression

        Returns:
            List of matching documents with scores
        """
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None

        try:
            query = self._table.search(query_vector).limit(top_k)

            if filter_expr:
                query = query.where(filter_expr)

            results = query.to_list()

            logger.debug("search_completed", top_k=top_k, results=len(results))
            return results

        except Exception as e:
            raise StorageError(f"Search failed: {e}") from e

    def get_by_file_id(self, file_id: str) -> list[dict[str, Any]]:
        """
        Get all chunks for a specific file.

        Args:
            file_id: Source file identifier

        Returns:
            List of document chunks
        """
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None

        try:
            results = self._table.search().where(f"file_id = '{file_id}'").to_list()
            return results
        except Exception as e:
            raise StorageError(f"Failed to get documents: {e}") from e

    def delete_by_file_id(self, file_id: str) -> int:
        """
        Delete all chunks for a specific file.

        Args:
            file_id: Source file identifier

        Returns:
            Number of documents deleted
        """
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None

        try:
            # Get count before deletion
            existing = self.get_by_file_id(file_id)
            count = len(existing)

            if count > 0:
                self._table.delete(f"file_id = '{file_id}'")
                logger.info("documents_deleted", file_id=file_id, count=count)

            return count
        except Exception as e:
            raise StorageError(f"Failed to delete documents: {e}") from e

    def count(self) -> int:
        """Get total document count."""
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None
        return self._table.count_rows()

    def get_stats(self) -> dict[str, Any]:
        """
        Get table statistics.

        Returns:
            Dictionary with table stats
        """
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None

        return {
            "table_name": self.table_name,
            "total_documents": self._table.count_rows(),
            "uri": self.uri,
            "embedding_dim": self.embedding_dim,
        }

    def validate_embeddings(self, sample_size: int = 100) -> dict[str, Any]:
        """
        Validate embedding quality by sampling.

        Args:
            sample_size: Number of documents to sample

        Returns:
            Validation results
        """
        if self._table is None:
            self.create_table_if_not_exists()

        assert self._table is not None

        # Sample documents
        df = self._table.to_pandas()
        sample = df.sample(min(sample_size, len(df)))

        issues: list[str] = []
        valid_count = 0

        for _, row in sample.iterrows():
            vector = row["vector"]

            # Check vector dimension
            if len(vector) != self.embedding_dim:
                issues.append(f"Wrong dimension for {row['id']}: {len(vector)}")
                continue

            # Check for zero vectors
            if all(v == 0.0 for v in vector):
                issues.append(f"Zero vector for {row['id']}")
                continue

            # Check for NaN values
            if any(v != v for v in vector):  # NaN check
                issues.append(f"NaN in vector for {row['id']}")
                continue

            valid_count += 1

        return {
            "sample_size": len(sample),
            "valid_count": valid_count,
            "invalid_count": len(sample) - valid_count,
            "validation_rate": valid_count / len(sample) if sample.size > 0 else 0,
            "issues": issues[:10],  # First 10 issues
        }
