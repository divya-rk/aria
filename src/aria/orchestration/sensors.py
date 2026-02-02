"""Dagster sensors for Aria pipeline."""

from dagster import RunRequest, SensorEvaluationContext, sensor

from aria.collection import SQSConsumer
from aria.config import get_settings


@sensor(
    job_name="hydration_only",
    minimum_interval_seconds=30,
    description="Monitor SQS queue for new audio files",
)
def sqs_sensor(context: SensorEvaluationContext):
    """
    Sensor that monitors SQS for new audio files.

    When messages are detected, triggers a hydration job run.
    """
    settings = get_settings()

    if not settings.sqs.ingestion_queue_url:
        context.log.warning("SQS queue URL not configured")
        return

    try:
        consumer = SQSConsumer(settings)
        stats = consumer.get_queue_stats()

        messages_available = stats.get("messages_available", 0)

        if messages_available > 0:
            context.log.info(f"Found {messages_available} messages in queue")

            yield RunRequest(
                run_key=f"sqs-{context.cursor or 0}",
                run_config={},
                tags={
                    "triggered_by": "sqs_sensor",
                    "queue_depth": str(messages_available),
                },
            )

    except Exception as e:
        context.log.error(f"Error checking SQS: {e}")


@sensor(
    job_name="training_data",
    minimum_interval_seconds=3600,  # Check hourly
    description="Trigger training shard creation when enough data is ready",
)
def training_data_sensor(context: SensorEvaluationContext):
    """
    Sensor that triggers training shard creation.

    Monitors curated document count and triggers sharding
    when threshold is reached.
    """
    settings = get_settings()

    from aria.storage import S3Client

    s3 = S3Client(settings)

    # Count high-quality curated documents
    files = list(
        s3.list_files(
            bucket=settings.s3.output_bucket,
            prefix="curated/high/",
            suffix=".json",
            max_keys=10000,
        )
    )

    document_count = len(files)
    threshold = 1000  # Minimum documents before creating shards

    context.log.info(f"Found {document_count} curated documents")

    if document_count >= threshold:
        last_run_count = int(context.cursor or "0")

        if document_count > last_run_count:
            context.log.info(f"Triggering shard creation: {document_count} > {last_run_count}")

            yield RunRequest(
                run_key=f"training-{document_count}",
                run_config={},
                tags={
                    "triggered_by": "training_data_sensor",
                    "document_count": str(document_count),
                },
            )

            # Update cursor
            context.update_cursor(str(document_count))
