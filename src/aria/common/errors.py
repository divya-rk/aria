"""Custom exception classes for Aria."""


class AriaError(Exception):
    """Base exception for all Aria errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ConfigurationError(AriaError):
    """Raised when there's a configuration issue."""


class ValidationError(AriaError):
    """Raised when data validation fails."""


class ProcessingError(AriaError):
    """Raised when processing a file fails."""


class StorageError(AriaError):
    """Raised when storage operations fail."""


class EmbeddingError(AriaError):
    """Raised when embedding generation fails."""


class TokenizationError(AriaError):
    """Raised when tokenization fails."""


class QueueError(AriaError):
    """Raised when queue operations fail."""
