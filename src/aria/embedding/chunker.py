"""Text chunking strategies for embedding."""

from dataclasses import dataclass

from aria.common import get_logger


logger = get_logger(__name__)


@dataclass
class Chunk:
    """A text chunk with metadata."""

    chunk_id: str
    text: str
    start_char: int
    end_char: int
    chunk_index: int
    token_count: int


class TextChunker:
    """Split text into chunks for embedding."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        tokenizer_name: str = "gpt-4",
    ) -> None:
        """
        Initialize text chunker.

        Args:
            chunk_size: Target chunk size in tokens
            chunk_overlap: Overlap between chunks in tokens
            tokenizer_name: Tokenizer to use for counting
        """
        import tiktoken

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._tokenizer = tiktoken.encoding_for_model(tokenizer_name)

    def chunk_text(
        self,
        text: str,
        file_id: str,
    ) -> list[Chunk]:
        """
        Split text into overlapping chunks.

        Args:
            text: Text to chunk
            file_id: Source file ID for chunk IDs

        Returns:
            List of Chunk objects
        """
        if not text.strip():
            return []

        tokens = self._tokenizer.encode(text)
        total_tokens = len(tokens)

        if total_tokens <= self.chunk_size:
            # Single chunk
            return [
                Chunk(
                    chunk_id=f"{file_id}_chunk_0",
                    text=text,
                    start_char=0,
                    end_char=len(text),
                    chunk_index=0,
                    token_count=total_tokens,
                )
            ]

        chunks = []
        chunk_index = 0
        start_token = 0

        while start_token < total_tokens:
            end_token = min(start_token + self.chunk_size, total_tokens)

            # Get chunk tokens and decode
            chunk_tokens = tokens[start_token:end_token]
            chunk_text = self._tokenizer.decode(chunk_tokens)

            # Calculate character positions (approximate)
            start_char = len(self._tokenizer.decode(tokens[:start_token]))
            end_char = start_char + len(chunk_text)

            chunks.append(
                Chunk(
                    chunk_id=f"{file_id}_chunk_{chunk_index}",
                    text=chunk_text,
                    start_char=start_char,
                    end_char=end_char,
                    chunk_index=chunk_index,
                    token_count=len(chunk_tokens),
                )
            )

            # Move to next chunk with overlap
            start_token = end_token - self.chunk_overlap
            if start_token >= total_tokens - self.chunk_overlap:
                break

            chunk_index += 1

        logger.debug(
            "text_chunked",
            file_id=file_id,
            total_tokens=total_tokens,
            num_chunks=len(chunks),
        )

        return chunks

    def chunk_by_sentences(
        self,
        text: str,
        file_id: str,
        max_sentences_per_chunk: int = 5,
    ) -> list[Chunk]:
        """
        Split text into chunks by sentence boundaries.

        Args:
            text: Text to chunk
            file_id: Source file ID
            max_sentences_per_chunk: Max sentences per chunk

        Returns:
            List of Chunk objects
        """
        import re

        # Simple sentence splitting
        sentences = re.split(r"(?<=[.!?])\s+", text)

        if len(sentences) <= max_sentences_per_chunk:
            tokens = self._tokenizer.encode(text)
            return [
                Chunk(
                    chunk_id=f"{file_id}_chunk_0",
                    text=text,
                    start_char=0,
                    end_char=len(text),
                    chunk_index=0,
                    token_count=len(tokens),
                )
            ]

        chunks = []
        chunk_index = 0
        current_sentences: list[str] = []
        current_start = 0

        for sentence in sentences:
            current_sentences.append(sentence)

            if len(current_sentences) >= max_sentences_per_chunk:
                chunk_text = " ".join(current_sentences)
                tokens = self._tokenizer.encode(chunk_text)

                chunks.append(
                    Chunk(
                        chunk_id=f"{file_id}_chunk_{chunk_index}",
                        text=chunk_text,
                        start_char=current_start,
                        end_char=current_start + len(chunk_text),
                        chunk_index=chunk_index,
                        token_count=len(tokens),
                    )
                )

                current_start += len(chunk_text) + 1
                # Keep last sentence for overlap
                current_sentences = [current_sentences[-1]]
                chunk_index += 1

        # Handle remaining sentences
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            tokens = self._tokenizer.encode(chunk_text)

            chunks.append(
                Chunk(
                    chunk_id=f"{file_id}_chunk_{chunk_index}",
                    text=chunk_text,
                    start_char=current_start,
                    end_char=current_start + len(chunk_text),
                    chunk_index=chunk_index,
                    token_count=len(tokens),
                )
            )

        return chunks

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._tokenizer.encode(text))
