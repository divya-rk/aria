"""Content deduplication using MinHash LSH."""

from datasketch import MinHash, MinHashLSH

from aria.common import get_logger


logger = get_logger(__name__)


class Deduplicator:
    """Detect and filter duplicate content using MinHash LSH."""

    def __init__(
        self,
        threshold: float = 0.8,
        num_perm: int = 128,
    ) -> None:
        """
        Initialize deduplicator.

        Args:
            threshold: Jaccard similarity threshold for duplicates
            num_perm: Number of permutations for MinHash
        """
        self.threshold = threshold
        self.num_perm = num_perm
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._seen_ids: set[str] = set()

    def _create_minhash(self, text: str) -> MinHash:
        """Create MinHash signature from text."""
        minhash = MinHash(num_perm=self.num_perm)

        # Use word n-grams (shingles)
        words = text.lower().split()
        for i in range(len(words) - 2):
            shingle = " ".join(words[i:i + 3])
            minhash.update(shingle.encode("utf-8"))

        return minhash

    def is_duplicate(self, doc_id: str, text: str) -> bool:
        """
        Check if text is duplicate of existing content.

        Args:
            doc_id: Unique document identifier
            text: Text content to check

        Returns:
            True if text is a duplicate
        """
        if doc_id in self._seen_ids:
            return True

        if len(text.split()) < 10:
            # Too short for reliable dedup
            self._seen_ids.add(doc_id)
            return False

        minhash = self._create_minhash(text)

        # Query for similar documents
        similar = self._lsh.query(minhash)

        if similar:
            logger.debug("duplicate_found", doc_id=doc_id, similar_to=similar[0])
            return True

        # Add to index
        self._lsh.insert(doc_id, minhash)
        self._seen_ids.add(doc_id)

        return False

    def add_document(self, doc_id: str, text: str) -> None:
        """
        Add document to dedup index without checking.

        Args:
            doc_id: Unique document identifier
            text: Text content
        """
        if doc_id in self._seen_ids:
            return

        minhash = self._create_minhash(text)
        self._lsh.insert(doc_id, minhash)
        self._seen_ids.add(doc_id)

    def find_similar(self, text: str, top_k: int = 5) -> list[str]:
        """
        Find similar documents to given text.

        Args:
            text: Query text
            top_k: Maximum results to return

        Returns:
            List of similar document IDs
        """
        minhash = self._create_minhash(text)
        similar = self._lsh.query(minhash)
        return similar[:top_k]

    def get_stats(self) -> dict[str, int]:
        """Get deduplication statistics."""
        return {
            "total_documents": len(self._seen_ids),
            "threshold": self.threshold,
            "num_perm": self.num_perm,
        }

    def clear(self) -> None:
        """Clear the dedup index."""
        self._lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self._seen_ids.clear()
        logger.info("dedup_index_cleared")


class BatchDeduplicator:
    """Batch deduplication for large datasets."""

    def __init__(
        self,
        threshold: float = 0.8,
        num_perm: int = 128,
    ) -> None:
        """
        Initialize batch deduplicator.

        Args:
            threshold: Jaccard similarity threshold
            num_perm: Number of permutations for MinHash
        """
        self.threshold = threshold
        self.num_perm = num_perm

    def deduplicate_batch(
        self,
        documents: list[tuple[str, str]],
    ) -> tuple[list[str], list[str]]:
        """
        Deduplicate a batch of documents.

        Args:
            documents: List of (doc_id, text) tuples

        Returns:
            Tuple of (unique_ids, duplicate_ids)
        """
        lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        unique_ids: list[str] = []
        duplicate_ids: list[str] = []

        for doc_id, text in documents:
            if len(text.split()) < 10:
                unique_ids.append(doc_id)
                continue

            minhash = self._create_minhash(text)
            similar = lsh.query(minhash)

            if similar:
                duplicate_ids.append(doc_id)
            else:
                lsh.insert(doc_id, minhash)
                unique_ids.append(doc_id)

        logger.info(
            "batch_dedup_complete",
            unique=len(unique_ids),
            duplicates=len(duplicate_ids),
        )

        return unique_ids, duplicate_ids

    def _create_minhash(self, text: str) -> MinHash:
        """Create MinHash signature from text."""
        minhash = MinHash(num_perm=self.num_perm)
        words = text.lower().split()
        for i in range(len(words) - 2):
            shingle = " ".join(words[i:i + 3])
            minhash.update(shingle.encode("utf-8"))
        return minhash
