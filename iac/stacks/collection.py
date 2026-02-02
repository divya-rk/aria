"""Collection stack.

Resources:
- SQS queue for ingestion
- S3 event notifications
- Lambda validator (optional)
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
)
from constructs import Construct


class CollectionStack(Stack):
    """Collection infrastructure for S3 event processing."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        raw_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # Dead Letter Queue
        self.dlq = sqs.Queue(
            self,
            "IngestionDlq",
            queue_name=f"{project}-ingestion-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        # Main Ingestion Queue
        self.queue = sqs.Queue(
            self,
            "IngestionQueue",
            queue_name=f"{project}-ingestion-{environment}",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.dlq,
            ),
        )

        # Allow S3 to send notifications to SQS
        self.queue.grant_send_messages(
            raw_bucket.grant_principal if hasattr(raw_bucket, 'grant_principal')
            else None
        )

        # S3 Event Notifications
        for suffix in [".mp3", ".wav", ".flac", ".m4a"]:
            raw_bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.SqsDestination(self.queue),
                s3.NotificationKeyFilter(suffix=suffix),
            )

        # CloudWatch Alarm for DLQ
        cloudwatch.Alarm(
            self,
            "DlqAlarm",
            alarm_name=f"{project}-ingestion-dlq-{environment}",
            metric=self.dlq.metric_approximate_number_of_messages_visible(),
            threshold=10,
            evaluation_periods=1,
            alarm_description="Ingestion DLQ has messages - check for failures",
        )

        # Queue depth alarm
        cloudwatch.Alarm(
            self,
            "QueueDepthAlarm",
            alarm_name=f"{project}-ingestion-queue-depth-{environment}",
            metric=self.queue.metric_approximate_number_of_messages_visible(),
            threshold=10000,
            evaluation_periods=2,
            alarm_description="Ingestion queue depth is high",
        )

        # Outputs
        CfnOutput(self, "IngestionQueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "IngestionQueueArn", value=self.queue.queue_arn)
        CfnOutput(self, "IngestionDlqUrl", value=self.dlq.queue_url)
