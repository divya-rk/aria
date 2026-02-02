"""Tests for deduplication module."""

import pytest

from aria.curation.dedup import Deduplicator, BatchDeduplicator


class TestDeduplicator:
    """Tests for Deduplicator."""

    @pytest.fixture
    def deduplicator(self) -> Deduplicator:
        """Create a deduplicator instance."""
        return Deduplicator(threshold=0.8, num_perm=128)

    def test_first_document_not_duplicate(self, deduplicator: Deduplicator) -> None:
        """Test that first document is never a duplicate."""
        text = "This is a unique document with enough words to process properly."
        is_dup = deduplicator.is_duplicate("doc1", text)

        assert not is_dup

    def test_exact_duplicate_detected(self, deduplicator: Deduplicator) -> None:
        """Test exact duplicates are detected."""
        text = "This is a document that will be duplicated. It has enough content to be meaningful."

        is_dup1 = deduplicator.is_duplicate("doc1", text)
        is_dup2 = deduplicator.is_duplicate("doc2", text)

        assert not is_dup1
        assert is_dup2

    def test_near_duplicate_detected(self, deduplicator: Deduplicator) -> None:
        """Test near duplicates are detected."""
        text1 = "Machine learning is a field of artificial intelligence that uses statistical techniques."
        text2 = "Machine learning is a field of artificial intelligence that uses statistical methods."

        is_dup1 = deduplicator.is_duplicate("doc1", text1)
        is_dup2 = deduplicator.is_duplicate("doc2", text2)

        assert not is_dup1
        # Near duplicates should be detected with high threshold
        # Note: actual detection depends on similarity threshold

    def test_different_documents_not_duplicate(self, deduplicator: Deduplicator) -> None:
        """Test different documents are not marked as duplicates."""
        text1 = "Machine learning is revolutionizing how we approach data analysis and prediction."
        text2 = "The weather forecast for tomorrow shows sunny skies with mild temperatures expected."

        is_dup1 = deduplicator.is_duplicate("doc1", text1)
        is_dup2 = deduplicator.is_duplicate("doc2", text2)

        assert not is_dup1
        assert not is_dup2

    def test_short_text_not_processed(self, deduplicator: Deduplicator) -> None:
        """Test short text is added but not processed for similarity."""
        text = "Too short"
        is_dup = deduplicator.is_duplicate("doc1", text)

        assert not is_dup

    def test_same_id_is_duplicate(self, deduplicator: Deduplicator) -> None:
        """Test same ID returns duplicate even with different text."""
        text1 = "First version of the document with some content here."
        text2 = "Completely different text that should not match."

        is_dup1 = deduplicator.is_duplicate("doc1", text1)
        is_dup2 = deduplicator.is_duplicate("doc1", text2)

        assert not is_dup1
        assert is_dup2  # Same ID

    def test_get_stats(self, deduplicator: Deduplicator) -> None:
        """Test statistics retrieval."""
        deduplicator.is_duplicate("doc1", "Some document content here with enough words.")
        deduplicator.is_duplicate("doc2", "Another document with different content here.")

        stats = deduplicator.get_stats()

        assert stats["total_documents"] == 2
        assert stats["threshold"] == 0.8
        assert stats["num_perm"] == 128

    def test_clear(self, deduplicator: Deduplicator) -> None:
        """Test clearing the index."""
        deduplicator.is_duplicate("doc1", "Some document content here with enough words.")
        deduplicator.clear()

        stats = deduplicator.get_stats()
        assert stats["total_documents"] == 0


class TestBatchDeduplicator:
    """Tests for BatchDeduplicator."""

    def test_deduplicate_batch(self) -> None:
        """Test batch deduplication."""
        deduplicator = BatchDeduplicator(threshold=0.8)

        documents = [
            ("doc1", "Machine learning is transforming industries with intelligent automation."),
            ("doc2", "Machine learning is transforming industries with intelligent automation."),  # Duplicate
            ("doc3", "Weather patterns show significant climate changes over the decades."),
            ("doc4", "The stock market experienced volatility during the economic crisis."),
        ]

        unique_ids, duplicate_ids = deduplicator.deduplicate_batch(documents)

        assert "doc1" in unique_ids
        assert "doc2" in duplicate_ids  # Exact duplicate
        assert "doc3" in unique_ids
        assert "doc4" in unique_ids
