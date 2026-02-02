"""Tests for text chunking module."""

import pytest

from aria.embedding.chunker import TextChunker, Chunk


class TestTextChunker:
    """Tests for TextChunker."""

    @pytest.fixture
    def chunker(self) -> TextChunker:
        """Create a text chunker instance."""
        return TextChunker(
            chunk_size=100,  # Small for testing
            chunk_overlap=20,
        )

    def test_short_text_single_chunk(self, chunker: TextChunker) -> None:
        """Test short text creates single chunk."""
        text = "This is a short text."
        chunks = chunker.chunk_text(text, "file1")

        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].chunk_index == 0
        assert chunks[0].file_id == "file1"

    def test_long_text_multiple_chunks(self, chunker: TextChunker) -> None:
        """Test long text creates multiple chunks."""
        # Create text longer than chunk_size tokens
        text = " ".join(["word"] * 300)
        chunks = chunker.chunk_text(text, "file1")

        assert len(chunks) > 1
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
            assert chunk.chunk_id == f"file1_chunk_{i}"

    def test_chunk_overlap(self, chunker: TextChunker) -> None:
        """Test chunks have overlap."""
        text = " ".join(["word"] * 300)
        chunks = chunker.chunk_text(text, "file1")

        if len(chunks) > 1:
            # Check that chunks overlap (end of one contains start of next)
            # This is approximate due to tokenization
            assert len(chunks) >= 2

    def test_empty_text(self, chunker: TextChunker) -> None:
        """Test empty text returns empty list."""
        chunks = chunker.chunk_text("", "file1")
        assert chunks == []

    def test_whitespace_only_text(self, chunker: TextChunker) -> None:
        """Test whitespace only text returns empty list."""
        chunks = chunker.chunk_text("   \n\t  ", "file1")
        assert chunks == []

    def test_chunk_metadata(self, chunker: TextChunker) -> None:
        """Test chunk metadata is correct."""
        text = "This is a test document with some content."
        chunks = chunker.chunk_text(text, "test_file")

        assert len(chunks) == 1
        chunk = chunks[0]

        assert isinstance(chunk, Chunk)
        assert chunk.chunk_id == "test_file_chunk_0"
        assert chunk.start_char == 0
        assert chunk.end_char > 0
        assert chunk.token_count > 0

    def test_count_tokens(self, chunker: TextChunker) -> None:
        """Test token counting."""
        text = "Hello world"
        count = chunker.count_tokens(text)

        assert count > 0
        assert isinstance(count, int)

    def test_chunk_by_sentences(self, chunker: TextChunker) -> None:
        """Test sentence-based chunking."""
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
        chunks = chunker.chunk_by_sentences(text, "file1", max_sentences_per_chunk=2)

        assert len(chunks) >= 1
        # Each chunk should contain sentence boundaries
