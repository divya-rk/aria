"""Text embedding using sentence transformers."""

import numpy as np
from sentence_transformers import SentenceTransformer

from aria.common import EmbeddingError, get_logger
from aria.config import Settings


logger = get_logger(__name__)


class TextEmbedder:
    """Generate embeddings using sentence transformers."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        """
        Initialize embedder.

        Args:
            model_name: Sentence transformer model name
            device: Compute device (cuda/cpu/None for auto)
            batch_size: Batch size for encoding
        """
        self.model_name = model_name
        self.batch_size = batch_size

        try:
            self._model = SentenceTransformer(model_name, device=device)
            self.embedding_dim = self._model.get_sentence_embedding_dimension()
            logger.info(
                "embedder_initialized",
                model=model_name,
                dim=self.embedding_dim,
            )
        except Exception as e:
            raise EmbeddingError(f"Failed to load model: {e}") from e

    def embed(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        try:
            embedding = self._model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return embedding.tolist()
        except Exception as e:
            raise EmbeddingError(f"Embedding failed: {e}") from e

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            embeddings = self._model.encode(
                texts,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=len(texts) > 100,
            )

            logger.debug("batch_embedded", count=len(texts))
            return [emb.tolist() for emb in embeddings]

        except Exception as e:
            raise EmbeddingError(f"Batch embedding failed: {e}") from e

    def similarity(self, text1: str, text2: str) -> float:
        """
        Calculate cosine similarity between two texts.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Cosine similarity score (0-1)
        """
        emb1 = np.array(self.embed(text1))
        emb2 = np.array(self.embed(text2))

        # Cosine similarity (embeddings are normalized)
        similarity = float(np.dot(emb1, emb2))
        return similarity

    def get_embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self.embedding_dim


class TextEmbedderFactory:
    """Factory for creating embedders with different backends."""

    @staticmethod
    def create(
        settings: Settings,
        backend: str = "sentence_transformers",
    ) -> TextEmbedder:
        """
        Create embedder based on backend.

        Args:
            settings: Application settings
            backend: Backend type (sentence_transformers, openai, etc.)

        Returns:
            TextEmbedder instance
        """
        if backend == "sentence_transformers":
            return TextEmbedder(
                model_name=settings.embedding.model_name,
            )
        else:
            raise ValueError(f"Unknown backend: {backend}")
