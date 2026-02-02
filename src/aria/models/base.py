"""Base model configuration for strict validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base model with strict validation settings.

    All pipeline models should inherit from this to ensure:
    - Extra fields are forbidden (prevents data contamination)
    - Strings are stripped of whitespace
    - Enums use values
    - Validation happens on assignment
    """

    model_config = ConfigDict(
        strict=True,
        frozen=False,
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
        validate_assignment=True,
        validate_default=True,
        from_attributes=True,
    )


class ImmutableModel(StrictModel):
    """Immutable model for data that should not change after creation."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )


class TimestampedModel(StrictModel):
    """Model with automatic timestamp tracking."""

    created_at: datetime = datetime.utcnow()
    updated_at: datetime | None = None

    def touch(self) -> None:
        """Update the timestamp."""
        self.updated_at = datetime.utcnow()
