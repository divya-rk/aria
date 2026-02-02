"""Data validation utilities."""

from dataclasses import dataclass
from typing import Any

from aria.common import get_logger
from aria.config import Settings
from aria.storage import DynamoDBClient, LanceDBStore, S3Client


logger = get_logger(__name__)


@dataclass
class ValidationReport:
    """Report from data validation."""

    total_checked: int
    passed: int
    failed: int
    pass_rate: float
    issues: list[dict[str, Any]]
    summary: dict[str, Any]


class DataValidator:
    """Validate data quality and integrity."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize validator.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._s3 = S3Client(settings)
        self._dynamodb = DynamoDBClient(settings)
        self._lancedb = LanceDBStore(settings)

    def validate_embeddings(self, sample_size: int = 1000) -> ValidationReport:
        """
        Validate embedding quality.

        Args:
            sample_size: Number of embeddings to sample

        Returns:
            ValidationReport with results
        """
        self._lancedb.create_table_if_not_exists()
        result = self._lancedb.validate_embeddings(sample_size)

        issues = [{"type": "embedding", "message": msg} for msg in result.get("issues", [])]

        return ValidationReport(
            total_checked=result.get("sample_size", 0),
            passed=result.get("valid_count", 0),
            failed=result.get("invalid_count", 0),
            pass_rate=result.get("validation_rate", 0),
            issues=issues,
            summary={
                "embedding_dim": self.settings.lancedb.embedding_dim,
                "table": self.settings.lancedb.table_name,
            },
        )

    def validate_pipeline_completeness(
        self,
        file_ids: list[str] | None = None,
    ) -> ValidationReport:
        """
        Validate that all files have completed all pipeline stages.

        Args:
            file_ids: Optional list of file IDs to check

        Returns:
            ValidationReport with results
        """
        from aria.common import JobStage, JobStatus

        stages = [
            JobStage.HYDRATION,
            JobStage.CURATION,
            JobStage.EMBEDDING,
            JobStage.TOKENIZATION,
        ]

        issues = []
        passed = 0
        failed = 0

        # If no file_ids provided, get from completed jobs
        if not file_ids:
            completed_jobs = self._dynamodb.query_by_status(
                status=JobStatus.COMPLETED,
                stage=JobStage.HYDRATION,
                limit=1000,
            )
            file_ids = [job.file_id for job in completed_jobs]

        for file_id in file_ids:
            file_complete = True
            missing_stages = []

            for stage in stages:
                job = self._dynamodb.get_job(file_id, stage)
                if not job or job.status != JobStatus.COMPLETED:
                    file_complete = False
                    missing_stages.append(stage.value)

            if file_complete:
                passed += 1
            else:
                failed += 1
                issues.append({
                    "type": "incomplete_pipeline",
                    "file_id": file_id,
                    "missing_stages": missing_stages,
                })

        total = passed + failed
        return ValidationReport(
            total_checked=total,
            passed=passed,
            failed=failed,
            pass_rate=passed / total if total > 0 else 0,
            issues=issues[:100],  # Limit issues
            summary={
                "stages_checked": [s.value for s in stages],
            },
        )

    def validate_lancedb_consistency(self) -> ValidationReport:
        """
        Validate LanceDB data consistency.

        Returns:
            ValidationReport with results
        """
        self._lancedb.create_table_if_not_exists()

        stats = self._lancedb.get_stats()
        total_docs = stats.get("total_documents", 0)

        issues = []

        # Check for orphaned documents (no corresponding job record)
        # This is a simplified check - in production would be more thorough
        if total_docs == 0:
            issues.append({
                "type": "empty_database",
                "message": "LanceDB table is empty",
            })

        return ValidationReport(
            total_checked=total_docs,
            passed=total_docs,
            failed=len(issues),
            pass_rate=1.0 if not issues else 0.0,
            issues=issues,
            summary=stats,
        )

    def get_pipeline_stats(self) -> dict[str, Any]:
        """
        Get overall pipeline statistics.

        Returns:
            Dictionary with pipeline stats
        """
        from aria.common import JobStage, JobStatus

        stats = {
            "stages": {},
            "lancedb": self._lancedb.get_stats(),
        }

        for stage in JobStage:
            stage_stats = {
                "completed": len(
                    self._dynamodb.query_by_status(JobStatus.COMPLETED, stage, limit=10000)
                ),
                "failed": len(
                    self._dynamodb.query_by_status(JobStatus.FAILED, stage, limit=10000)
                ),
                "processing": len(
                    self._dynamodb.query_by_status(JobStatus.PROCESSING, stage, limit=10000)
                ),
            }
            stats["stages"][stage.value] = stage_stats

        return stats

    def generate_quality_report(self) -> dict[str, Any]:
        """
        Generate comprehensive quality report.

        Returns:
            Quality report dictionary
        """
        embedding_validation = self.validate_embeddings(sample_size=500)
        pipeline_validation = self.validate_pipeline_completeness()
        lancedb_validation = self.validate_lancedb_consistency()

        return {
            "embedding_quality": {
                "pass_rate": embedding_validation.pass_rate,
                "issues": len(embedding_validation.issues),
            },
            "pipeline_completeness": {
                "pass_rate": pipeline_validation.pass_rate,
                "total_files": pipeline_validation.total_checked,
                "incomplete": pipeline_validation.failed,
            },
            "lancedb_health": {
                "total_documents": lancedb_validation.summary.get("total_documents", 0),
                "issues": len(lancedb_validation.issues),
            },
            "overall_health": "healthy"
            if all(
                [
                    embedding_validation.pass_rate > 0.95,
                    pipeline_validation.pass_rate > 0.9,
                    len(lancedb_validation.issues) == 0,
                ]
            )
            else "degraded",
        }
