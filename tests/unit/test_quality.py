"""Tests for quality scoring module."""

import pytest

from aria.curation.quality import QualityScorer, QualityMetrics


class TestQualityScorer:
    """Tests for QualityScorer."""

    @pytest.fixture
    def scorer(self) -> QualityScorer:
        """Create a quality scorer instance."""
        return QualityScorer(
            min_word_count=50,
            max_word_count=100000,
            min_confidence=0.5,
            expected_language="en",
        )

    def test_score_high_quality_text(self, scorer: QualityScorer) -> None:
        """Test scoring high quality text."""
        text = """
        Machine learning is a subset of artificial intelligence that enables
        systems to learn and improve from experience without being explicitly
        programmed. It focuses on developing computer programs that can access
        data and use it to learn for themselves. The process begins with
        observations or data, such as examples, direct experience, or instruction,
        in order to look for patterns in data and make better decisions in the
        future based on the examples that we provide.
        """
        metrics = scorer.score(text, transcription_confidence=0.9)

        assert isinstance(metrics, QualityMetrics)
        assert metrics.overall_score > 0.7
        assert metrics.confidence_score == 0.9
        assert metrics.word_count > 50

    def test_score_short_text(self, scorer: QualityScorer) -> None:
        """Test scoring short text gets penalized."""
        text = "This is too short."
        metrics = scorer.score(text, transcription_confidence=0.9)

        assert metrics.length_score < 1.0
        assert metrics.word_count < 50

    def test_score_low_confidence(self, scorer: QualityScorer) -> None:
        """Test low confidence affects score."""
        text = " ".join(["word"] * 100)  # 100 words
        metrics = scorer.score(text, transcription_confidence=0.3)

        assert metrics.confidence_score == 0.3
        assert metrics.overall_score < 0.7

    def test_quality_tier_high(self, scorer: QualityScorer) -> None:
        """Test high quality tier classification."""
        metrics = QualityMetrics(
            overall_score=0.85,
            confidence_score=0.9,
            language_score=0.95,
            length_score=1.0,
            repetition_score=0.9,
            detected_language="en",
            word_count=500,
            unique_word_ratio=0.7,
            avg_word_length=5.0,
        )

        tier = scorer.get_quality_tier(metrics)
        assert tier == "high"

    def test_quality_tier_medium(self, scorer: QualityScorer) -> None:
        """Test medium quality tier classification."""
        metrics = QualityMetrics(
            overall_score=0.65,
            confidence_score=0.7,
            language_score=0.8,
            length_score=0.9,
            repetition_score=0.6,
            detected_language="en",
            word_count=200,
            unique_word_ratio=0.5,
            avg_word_length=4.5,
        )

        tier = scorer.get_quality_tier(metrics)
        assert tier == "medium"

    def test_quality_tier_rejected(self, scorer: QualityScorer) -> None:
        """Test rejected quality tier classification."""
        metrics = QualityMetrics(
            overall_score=0.3,
            confidence_score=0.4,
            language_score=0.3,
            length_score=0.2,
            repetition_score=0.3,
            detected_language="unknown",
            word_count=20,
            unique_word_ratio=0.2,
            avg_word_length=2.0,
        )

        tier = scorer.get_quality_tier(metrics)
        assert tier == "rejected"

    def test_passes_threshold(self, scorer: QualityScorer) -> None:
        """Test threshold checking."""
        high_quality = QualityMetrics(
            overall_score=0.8,
            confidence_score=0.9,
            language_score=0.9,
            length_score=1.0,
            repetition_score=0.8,
            detected_language="en",
            word_count=500,
            unique_word_ratio=0.7,
            avg_word_length=5.0,
        )

        low_quality = QualityMetrics(
            overall_score=0.4,
            confidence_score=0.5,
            language_score=0.5,
            length_score=0.3,
            repetition_score=0.4,
            detected_language="en",
            word_count=30,
            unique_word_ratio=0.3,
            avg_word_length=3.0,
        )

        assert scorer.passes_threshold(high_quality, threshold=0.6)
        assert not scorer.passes_threshold(low_quality, threshold=0.6)
