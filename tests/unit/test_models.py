"""Tests for Pydantic models with strict validation."""

import pytest
from pydantic import ValidationError

from aria.models.hydration import HydrationResult, TranscriptSegment
from aria.models.curation import CurationResult, QualityMetrics, QualityTier, PIIDetection
from aria.models.embedding import ChunkRecord, EmbeddingRecord
from aria.models.tokenization import ShardRecord, ShardManifest, ShardMetadata
from aria.models.pipeline import PipelineMessage, PipelineState, StageType, StageStatus


class TestTranscriptSegment:
    """Tests for TranscriptSegment model."""

    def test_valid_segment(self) -> None:
        """Test creating a valid segment."""
        segment = TranscriptSegment(
            start=0.0,
            end=5.5,
            text="Hello world",
            avg_logprob=-0.25,
            no_speech_prob=0.01,
        )
        assert segment.start == 0.0
        assert segment.end == 5.5
        assert segment.text == "Hello world"

    def test_end_must_be_after_start(self) -> None:
        """Test that end time must be after start time."""
        with pytest.raises(ValidationError) as exc_info:
            TranscriptSegment(
                start=5.0,
                end=3.0,  # Invalid: before start
                text="Hello",
                avg_logprob=-0.25,
                no_speech_prob=0.01,
            )
        assert "end must be greater than start" in str(exc_info.value)

    def test_no_speech_prob_range(self) -> None:
        """Test no_speech_prob must be between 0 and 1."""
        with pytest.raises(ValidationError):
            TranscriptSegment(
                start=0.0,
                end=5.0,
                text="Hello",
                avg_logprob=-0.25,
                no_speech_prob=1.5,  # Invalid: > 1
            )

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            TranscriptSegment(
                start=0.0,
                end=5.0,
                text="Hello",
                avg_logprob=-0.25,
                no_speech_prob=0.01,
                extra_field="not allowed",  # Should fail
            )
        assert "extra" in str(exc_info.value).lower()


class TestHydrationResult:
    """Tests for HydrationResult model."""

    @pytest.fixture
    def valid_segments(self) -> list[TranscriptSegment]:
        """Create valid segments."""
        return [
            TranscriptSegment(start=0.0, end=5.0, text="First", avg_logprob=-0.2, no_speech_prob=0.01),
            TranscriptSegment(start=5.0, end=10.0, text="Second", avg_logprob=-0.3, no_speech_prob=0.02),
        ]

    def test_valid_hydration_result(self, valid_segments: list[TranscriptSegment]) -> None:
        """Test creating a valid hydration result."""
        result = HydrationResult(
            file_id="test-001",
            source_bucket="raw-bucket",
            source_key="audio/test.mp3",
            language="en",
            language_probability=0.95,
            duration=120.0,
            text="First Second",
            segments=valid_segments,
        )
        assert result.file_id == "test-001"
        assert len(result.segments) == 2

    def test_segments_must_be_ordered(self) -> None:
        """Test that segments must be ordered by start time."""
        unordered_segments = [
            TranscriptSegment(start=5.0, end=10.0, text="Second", avg_logprob=-0.3, no_speech_prob=0.02),
            TranscriptSegment(start=0.0, end=5.0, text="First", avg_logprob=-0.2, no_speech_prob=0.01),
        ]
        with pytest.raises(ValidationError) as exc_info:
            HydrationResult(
                file_id="test-001",
                source_bucket="raw-bucket",
                source_key="audio/test.mp3",
                language="en",
                language_probability=0.95,
                duration=120.0,
                text="First Second",
                segments=unordered_segments,
            )
        assert "ordered by start time" in str(exc_info.value)


class TestQualityMetrics:
    """Tests for QualityMetrics model."""

    def test_valid_metrics(self) -> None:
        """Test creating valid quality metrics."""
        metrics = QualityMetrics(
            confidence_score=0.9,
            language_score=0.95,
            length_score=0.8,
            repetition_score=0.85,
            overall_score=0.87,
        )
        assert metrics.overall_score == 0.87

    def test_scores_must_be_in_range(self) -> None:
        """Test that scores must be between 0 and 1."""
        with pytest.raises(ValidationError):
            QualityMetrics(
                confidence_score=1.5,  # Invalid: > 1
                language_score=0.95,
                length_score=0.8,
                repetition_score=0.85,
                overall_score=0.87,
            )


class TestEmbeddingRecord:
    """Tests for EmbeddingRecord model."""

    def test_valid_embedding(self) -> None:
        """Test creating a valid embedding record."""
        record = EmbeddingRecord(
            id="test-001_chunk_0",
            file_id="test-001",
            chunk_index=0,
            text="Sample text",
            start_char=0,
            end_char=11,
            vector=[0.1] * 384,
        )
        assert len(record.vector) == 384

    def test_zero_vector_rejected(self) -> None:
        """Test that zero vectors are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EmbeddingRecord(
                id="test-001_chunk_0",
                file_id="test-001",
                chunk_index=0,
                text="Sample text",
                start_char=0,
                end_char=11,
                vector=[0.0] * 384,  # All zeros
            )
        assert "cannot be all zeros" in str(exc_info.value)

    def test_nan_vector_rejected(self) -> None:
        """Test that NaN values in vectors are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EmbeddingRecord(
                id="test-001_chunk_0",
                file_id="test-001",
                chunk_index=0,
                text="Sample text",
                start_char=0,
                end_char=11,
                vector=[float("nan")] + [0.1] * 383,
            )
        assert "NaN" in str(exc_info.value)


class TestShardRecord:
    """Tests for ShardRecord model."""

    def test_valid_shard_record(self) -> None:
        """Test creating a valid shard record."""
        record = ShardRecord(
            file_id="test-001",
            tokens=[100, 200, 300, 400],
            token_count=4,
        )
        assert record.token_count == 4

    def test_token_count_must_match(self) -> None:
        """Test that token_count must match actual tokens length."""
        with pytest.raises(ValidationError) as exc_info:
            ShardRecord(
                file_id="test-001",
                tokens=[100, 200, 300],
                token_count=5,  # Doesn't match
            )
        assert "doesn't match" in str(exc_info.value)

    def test_negative_tokens_rejected(self) -> None:
        """Test that negative token IDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ShardRecord(
                file_id="test-001",
                tokens=[100, -1, 300],  # Negative token
                token_count=3,
            )
        assert "non-negative" in str(exc_info.value)


class TestPipelineMessage:
    """Tests for PipelineMessage model."""

    def test_valid_message(self) -> None:
        """Test creating a valid pipeline message."""
        msg = PipelineMessage(
            source_stage=StageType.HYDRATION,
            target_stage=StageType.CURATION,
            file_id="test-001",
            payload={"output_key": "hydrated/test-001.json"},
            trace_id="trace-123",
        )
        assert msg.source_stage == StageType.HYDRATION

    def test_target_must_come_after_source(self) -> None:
        """Test that target stage must come after source stage."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineMessage(
                source_stage=StageType.CURATION,
                target_stage=StageType.HYDRATION,  # Invalid: before curation
                file_id="test-001",
                payload={},
                trace_id="trace-123",
            )
        assert "must come after" in str(exc_info.value)


class TestPipelineState:
    """Tests for PipelineState model."""

    def test_valid_state(self) -> None:
        """Test creating a valid pipeline state."""
        state = PipelineState(
            file_id="test-001",
            source_bucket="raw-bucket",
            source_key="audio/test.mp3",
            file_size=1024000,
        )
        assert state.file_id == "test-001"
        assert not state.is_complete()

    def test_update_stage(self) -> None:
        """Test updating stage status."""
        state = PipelineState(
            file_id="test-001",
            source_bucket="raw-bucket",
            source_key="audio/test.mp3",
            file_size=1024000,
        )

        state.update_stage(
            StageType.HYDRATION,
            StageStatus.COMPLETED,
            output_location="s3://output/hydrated/test-001.json",
        )

        assert StageType.HYDRATION in state.stages
        assert state.stages[StageType.HYDRATION].status == StageStatus.COMPLETED
        assert state.get_current_stage() == StageType.HYDRATION
