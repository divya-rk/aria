"""Tokenization utilities for LLM training data."""

from dataclasses import dataclass

import tiktoken

from aria.common import get_logger


logger = get_logger(__name__)


@dataclass
class TokenizedDocument:
    """A tokenized document ready for training."""

    file_id: str
    tokens: list[int]
    token_count: int
    text_length: int


class Tokenizer:
    """Tokenize text for LLM training."""

    def __init__(
        self,
        model_name: str = "gpt-4",
    ) -> None:
        """
        Initialize tokenizer.

        Args:
            model_name: Model name for tiktoken encoding
        """
        self.model_name = model_name
        self._encoding = tiktoken.encoding_for_model(model_name)

        logger.info(
            "tokenizer_initialized",
            model=model_name,
            vocab_size=self._encoding.n_vocab,
        )

    def tokenize(self, text: str, file_id: str) -> TokenizedDocument:
        """
        Tokenize text content.

        Args:
            text: Text to tokenize
            file_id: Source file identifier

        Returns:
            TokenizedDocument with tokens
        """
        tokens = self._encoding.encode(text)

        return TokenizedDocument(
            file_id=file_id,
            tokens=tokens,
            token_count=len(tokens),
            text_length=len(text),
        )

    def tokenize_batch(
        self,
        items: list[tuple[str, str]],
    ) -> list[TokenizedDocument]:
        """
        Tokenize multiple documents.

        Args:
            items: List of (file_id, text) tuples

        Returns:
            List of TokenizedDocuments
        """
        results = []
        for file_id, text in items:
            doc = self.tokenize(text, file_id)
            results.append(doc)

        total_tokens = sum(d.token_count for d in results)
        logger.info(
            "batch_tokenized",
            documents=len(results),
            total_tokens=total_tokens,
        )

        return results

    def decode(self, tokens: list[int]) -> str:
        """Decode tokens back to text."""
        return self._encoding.decode(tokens)

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._encoding.encode(text))

    @property
    def vocab_size(self) -> int:
        """Get vocabulary size."""
        return self._encoding.n_vocab

    @property
    def special_tokens(self) -> dict[str, int]:
        """Get special tokens."""
        return {
            "eot": self._encoding.eot_token,
        }
