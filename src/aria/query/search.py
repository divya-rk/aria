"""Vector search functionality."""

from typing import Any

from aria.common import get_logger
from aria.config import Settings
from aria.embedding import TextEmbedder
from aria.storage import LanceDBStore


logger = get_logger(__name__)


class VectorSearch:
    """Search interface for vector database."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize vector search.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._lancedb = LanceDBStore(settings)
        self._embedder = TextEmbedder(model_name=settings.embedding.model_name)

        # Initialize connection
        self._lancedb.create_table_if_not_exists()

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        filter_quality: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar documents.

        Args:
            query: Search query text
            top_k: Number of results
            min_score: Minimum similarity score
            filter_quality: Optional quality tier filter

        Returns:
            List of search results
        """
        # Generate query embedding
        query_vector = self._embedder.embed(query)

        # Build filter
        filter_expr = None
        if filter_quality:
            filter_expr = f"quality_score >= {self._quality_to_score(filter_quality)}"

        # Search
        results = self._lancedb.search(
            query_vector=query_vector,
            top_k=top_k,
            filter_expr=filter_expr,
        )

        # Filter by score and format results
        formatted = []
        for result in results:
            score = 1 - result.get("_distance", 1)  # Convert distance to similarity
            if score >= min_score:
                formatted.append({
                    "id": result.get("id"),
                    "file_id": result.get("file_id"),
                    "text": result.get("text"),
                    "score": round(score, 4),
                    "quality_score": result.get("quality_score"),
                    "chunk_index": result.get("chunk_index"),
                })

        logger.debug("search_complete", query=query[:50], results=len(formatted))
        return formatted

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """
        Get a specific document by ID.

        Args:
            doc_id: Document/chunk ID

        Returns:
            Document if found, None otherwise
        """
        results = self._lancedb.search(
            query_vector=[0.0] * self.settings.lancedb.embedding_dim,
            top_k=1,
            filter_expr=f"id = '{doc_id}'",
        )

        if results:
            return results[0]
        return None

    def get_by_file(self, file_id: str) -> list[dict[str, Any]]:
        """
        Get all chunks for a file.

        Args:
            file_id: Source file ID

        Returns:
            List of chunks
        """
        return self._lancedb.get_by_file_id(file_id)

    def _quality_to_score(self, tier: str) -> float:
        """Convert quality tier to minimum score."""
        tiers = {
            "high": 0.8,
            "medium": 0.6,
            "low": 0.4,
        }
        return tiers.get(tier, 0.0)


class SemanticSearch(VectorSearch):
    """Extended semantic search with additional features."""

    def search_with_context(
        self,
        query: str,
        top_k: int = 5,
        context_chunks: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Search and include surrounding context chunks.

        Args:
            query: Search query
            top_k: Number of results
            context_chunks: Number of context chunks before/after

        Returns:
            Results with context
        """
        results = self.search(query, top_k=top_k)

        for result in results:
            file_id = result.get("file_id")
            chunk_index = result.get("chunk_index", 0)

            # Get surrounding chunks
            all_chunks = self.get_by_file(file_id)
            sorted_chunks = sorted(all_chunks, key=lambda x: x.get("chunk_index", 0))

            # Find context
            context_before = []
            context_after = []

            for chunk in sorted_chunks:
                idx = chunk.get("chunk_index", 0)
                if chunk_index - context_chunks <= idx < chunk_index:
                    context_before.append(chunk.get("text", ""))
                elif chunk_index < idx <= chunk_index + context_chunks:
                    context_after.append(chunk.get("text", ""))

            result["context_before"] = context_before
            result["context_after"] = context_after

        return results

    def find_similar_documents(
        self,
        file_id: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Find documents similar to a given document.

        Args:
            file_id: Source file ID
            top_k: Number of similar documents

        Returns:
            List of similar documents
        """
        # Get source document chunks
        chunks = self.get_by_file(file_id)
        if not chunks:
            return []

        # Use first chunk's embedding as representative
        first_chunk = chunks[0]
        query_vector = first_chunk.get("vector", [])

        if not query_vector:
            return []

        # Search excluding same file
        results = self._lancedb.search(
            query_vector=query_vector,
            top_k=top_k + 10,  # Get extra to filter
            filter_expr=f"file_id != '{file_id}'",
        )

        # Deduplicate by file_id
        seen_files: set[str] = set()
        unique_results = []

        for result in results:
            result_file_id = result.get("file_id")
            if result_file_id not in seen_files:
                seen_files.add(result_file_id)
                unique_results.append(result)
                if len(unique_results) >= top_k:
                    break

        return unique_results
