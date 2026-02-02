"""DynamoDB client for job state management."""

from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from aria.common import (
    JobRecord,
    JobStage,
    JobStatus,
    StorageError,
    get_logger,
)
from aria.config import Settings


logger = get_logger(__name__)


class DynamoDBClient:
    """Client for DynamoDB operations."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize DynamoDB client.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.table_name = settings.dynamodb.table_name

        client_kwargs: dict[str, Any] = {
            "region_name": settings.aws.region,
        }
        if settings.dynamodb.endpoint_url:
            client_kwargs["endpoint_url"] = settings.dynamodb.endpoint_url

        self._client = boto3.client("dynamodb", **client_kwargs)
        self._resource = boto3.resource("dynamodb", **client_kwargs)
        self._table = self._resource.Table(self.table_name)

    def create_table_if_not_exists(self) -> None:
        """Create the jobs table if it doesn't exist."""
        try:
            self._client.describe_table(TableName=self.table_name)
            logger.info("dynamodb_table_exists", table=self.table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                self._create_table()
            else:
                raise StorageError(f"Failed to check table: {e}") from e

    def _create_table(self) -> None:
        """Create the DynamoDB table."""
        logger.info("creating_dynamodb_table", table=self.table_name)

        self._client.create_table(
            TableName=self.table_name,
            KeySchema=[
                {"AttributeName": "file_id", "KeyType": "HASH"},
                {"AttributeName": "stage", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "file_id", "AttributeType": "S"},
                {"AttributeName": "stage", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "stage", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        waiter = self._client.get_waiter("table_exists")
        waiter.wait(TableName=self.table_name)
        logger.info("dynamodb_table_created", table=self.table_name)

    def put_job(self, job: JobRecord) -> None:
        """
        Create or update a job record.

        Args:
            job: Job record to store
        """
        try:
            self._table.put_item(
                Item={
                    "file_id": job.file_id,
                    "stage": job.stage.value,
                    "status": job.status.value,
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                    "quality_score": job.quality_score,
                    "error_message": job.error_message,
                    "output_location": job.output_location,
                    "retry_count": job.retry_count,
                    "metadata": job.metadata,
                }
            )
            logger.debug("job_saved", file_id=job.file_id, stage=job.stage.value)
        except ClientError as e:
            raise StorageError(f"Failed to save job: {e}") from e

    def get_job(self, file_id: str, stage: JobStage) -> JobRecord | None:
        """
        Retrieve a job record.

        Args:
            file_id: File identifier
            stage: Processing stage

        Returns:
            JobRecord if found, None otherwise
        """
        try:
            response = self._table.get_item(
                Key={"file_id": file_id, "stage": stage.value}
            )
            item = response.get("Item")
            if not item:
                return None

            return JobRecord(
                file_id=item["file_id"],
                stage=JobStage(item["stage"]),
                status=JobStatus(item["status"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                updated_at=datetime.fromisoformat(item["updated_at"]),
                quality_score=item.get("quality_score"),
                error_message=item.get("error_message"),
                output_location=item.get("output_location"),
                retry_count=item.get("retry_count", 0),
                metadata=item.get("metadata", {}),
            )
        except ClientError as e:
            raise StorageError(f"Failed to get job: {e}") from e

    def update_job_status(
        self,
        file_id: str,
        stage: JobStage,
        status: JobStatus,
        error_message: str | None = None,
        output_location: str | None = None,
        quality_score: float | None = None,
    ) -> None:
        """
        Update job status and related fields.

        Args:
            file_id: File identifier
            stage: Processing stage
            status: New status
            error_message: Error message if failed
            output_location: Output path if completed
            quality_score: Quality score if computed
        """
        update_expr = "SET #status = :status, updated_at = :updated_at"
        expr_names = {"#status": "status"}
        expr_values: dict[str, Any] = {
            ":status": status.value,
            ":updated_at": datetime.utcnow().isoformat(),
        }

        if error_message is not None:
            update_expr += ", error_message = :error_message"
            expr_values[":error_message"] = error_message

        if output_location is not None:
            update_expr += ", output_location = :output_location"
            expr_values[":output_location"] = output_location

        if quality_score is not None:
            update_expr += ", quality_score = :quality_score"
            expr_values[":quality_score"] = quality_score

        try:
            self._table.update_item(
                Key={"file_id": file_id, "stage": stage.value},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
            logger.debug(
                "job_status_updated",
                file_id=file_id,
                stage=stage.value,
                status=status.value,
            )
        except ClientError as e:
            raise StorageError(f"Failed to update job status: {e}") from e

    def increment_retry_count(self, file_id: str, stage: JobStage) -> int:
        """
        Increment retry count for a job.

        Args:
            file_id: File identifier
            stage: Processing stage

        Returns:
            New retry count
        """
        try:
            response = self._table.update_item(
                Key={"file_id": file_id, "stage": stage.value},
                UpdateExpression="SET retry_count = retry_count + :inc, updated_at = :updated_at",
                ExpressionAttributeValues={
                    ":inc": 1,
                    ":updated_at": datetime.utcnow().isoformat(),
                },
                ReturnValues="UPDATED_NEW",
            )
            return int(response["Attributes"]["retry_count"])
        except ClientError as e:
            raise StorageError(f"Failed to increment retry count: {e}") from e

    def query_by_status(
        self,
        status: JobStatus,
        stage: JobStage | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        """
        Query jobs by status using GSI.

        Args:
            status: Job status to filter
            stage: Optional stage filter
            limit: Maximum records to return

        Returns:
            List of matching job records
        """
        key_condition = "#status = :status"
        expr_names = {"#status": "status"}
        expr_values: dict[str, Any] = {":status": status.value}

        if stage:
            key_condition += " AND stage = :stage"
            expr_values[":stage"] = stage.value

        try:
            response = self._table.query(
                IndexName="status-index",
                KeyConditionExpression=key_condition,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                Limit=limit,
            )

            return [
                JobRecord(
                    file_id=item["file_id"],
                    stage=JobStage(item["stage"]),
                    status=JobStatus(item["status"]),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    updated_at=datetime.fromisoformat(item["updated_at"]),
                    quality_score=item.get("quality_score"),
                    error_message=item.get("error_message"),
                    output_location=item.get("output_location"),
                    retry_count=item.get("retry_count", 0),
                    metadata=item.get("metadata", {}),
                )
                for item in response.get("Items", [])
            ]
        except ClientError as e:
            raise StorageError(f"Failed to query jobs: {e}") from e
