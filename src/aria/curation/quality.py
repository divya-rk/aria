"""Quality scoring for transcribed content."""

from dataclasses import dataclass

from langdetect import detect, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from aria.common import get_logger


logger = get_logger(__name__)


@dataclass
class QualityMetrics:
    """Detailed quality metrics for content."""

    overall_score: float
    confidence_score: float
    language_score: float
    length_score: float
    repetition_score: float
    detected_language: str
    word_count: int
    unique_word_ratio: float
    avg_word_length: float


class QualityScorer:
    """Score content quality for filtering decisions."""

    def __init__(
        self,
        min_word_count: int = 50,
        max_word_count: int = 100000,
        min_confidence: float = 0.5,
        expected_language: str = "en",
    ) -> None:
        """
        Initialize quality scorer.

        Args:
            min_word_count: Minimum words for valid content
            max_word_count: Maximum words (likely noise if exceeded)
            min_confidence: Minimum transcription confidence
            expected_language: Expected content language
        """
        self.min_word_count = min_word_count
        self.max_word_count = max_word_count
        self.min_confidence = min_confidence
        self.expected_language = expected_language

    def score(
        self,
        text: str,
        transcription_confidence: float,
    ) -> QualityMetrics:
        """
        Calculate quality metrics for text content.

        Args:
            text: Text content to score
            transcription_confidence: Confidence from transcription

        Returns:
            QualityMetrics with detailed scores
        """
        words = text.split()
        word_count = len(words)

        # Length score
        length_score = self._calculate_length_score(word_count)

        # Language detection
        detected_language, language_score = self._detect_language(text)

        # Repetition detection
        unique_words = set(w.lower() for w in words)
        unique_ratio = len(unique_words) / word_count if word_count > 0 else 0
        repetition_score = min(unique_ratio * 1.5, 1.0)  # Scale up, cap at 1

        # Average word length (gibberish detection)
        avg_word_length = sum(len(w) for w in words) / word_count if word_count else 0
        # Normal English avg is ~4.5 chars
        word_length_penalty = 1.0 if 3 <= avg_word_length <= 8 else 0.7

        # Confidence score (from transcription)
        confidence_score = max(0, min(transcription_confidence, 1.0))

        # Overall score (weighted average)
        overall_score = (
            confidence_score * 0.3
            + language_score * 0.25
            + length_score * 0.2
            + repetition_score * 0.15
            + word_length_penalty * 0.1
        )

        return QualityMetrics(
            overall_score=round(overall_score, 3),
            confidence_score=round(confidence_score, 3),
            language_score=round(language_score, 3),
            length_score=round(length_score, 3),
            repetition_score=round(repetition_score, 3),
            detected_language=detected_language,
            word_count=word_count,
            unique_word_ratio=round(unique_ratio, 3),
            avg_word_length=round(avg_word_length, 2),
        )

    def _calculate_length_score(self, word_count: int) -> float:
        """Calculate score based on content length."""
        if word_count < self.min_word_count:
            return word_count / self.min_word_count
        elif word_count > self.max_word_count:
            return max(0.5, 1.0 - (word_count - self.max_word_count) / self.max_word_count)
        else:
            return 1.0

    def _detect_language(self, text: str) -> tuple[str, float]:
        """Detect language and return confidence."""
        if len(text.split()) < 10:
            # Too short for reliable detection
            return "unknown", 0.5

        try:
            detected = detect(text)
            langs = detect_langs(text)

            # Find confidence for detected language
            confidence = 0.5
            for lang in langs:
                if lang.lang == detected:
                    confidence = lang.prob
                    break

            # Bonus if matches expected
            if detected == self.expected_language:
                score = confidence
            else:
                score = confidence * 0.7  # Penalty for unexpected language

            return detected, score

        except LangDetectException:
            logger.warning("language_detection_failed")
            return "unknown", 0.3

    def passes_threshold(
        self,
        metrics: QualityMetrics,
        threshold: float = 0.6,
    ) -> bool:
        """
        Check if content passes quality threshold.

        Args:
            metrics: Quality metrics to check
            threshold: Minimum overall score

        Returns:
            True if content passes quality check
        """
        return metrics.overall_score >= threshold

    def get_quality_tier(self, metrics: QualityMetrics) -> str:
        """
        Categorize content into quality tiers.

        Args:
            metrics: Quality metrics

        Returns:
            Quality tier: 'high', 'medium', 'low', or 'rejected'
        """
        score = metrics.overall_score

        if score >= 0.8:
            return "high"
        elif score >= 0.6:
            return "medium"
        elif score >= 0.4:
            return "low"
        else:
            return "rejected"
