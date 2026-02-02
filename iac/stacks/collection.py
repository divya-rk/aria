"""Collection stack.

SQS-driven pipeline:
- S3 events → Ingestion Queue → Hydration stage picks up

Resources:
- SQS queue for ingestion (input to Hydration)
- S3 event notifications
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
)
from constructs import Construct


class CollectionStack(Stack):
    """Collection infrastructure - S3 events to SQS."""

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

        # =====================================================================
        # HYDRATION INPUT QUEUE (Collection → Hydration)
        # =====================================================================
        # This queue is consumed by the Hydration stage

        self.hydration_input_dlq = sqs.Queue(
            self,
            "HydrationInputDlq",
            queue_name=f"{project}-hydration-input-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        self.hydration_input_queue = sqs.Queue(
            self,
            "HydrationInputQueue",
            queue_name=f"{project}-hydration-input-{environment}",
            visibility_timeout=Duration.minutes(10),  # GPU processing time
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.hydration_input_dlq,
            ),
        )

        # S3 Event Notifications → Hydration Input Queue
        for suffix in [".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm"]:
            raw_bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.SqsDestination(self.hydration_input_queue),
                s3.NotificationKeyFilter(suffix=suffix),
            )

        # CloudWatch Alarms
        cloudwatch.Alarm(
            self,
            "HydrationInputDlqAlarm",
            alarm_name=f"{project}-hydration-input-dlq-{environment}",
            metric=self.hydration_input_dlq.metric_approximate_number_of_messages_visible(),
            threshold=10,
            evaluation_periods=1,
            alarm_description="Hydration input DLQ has messages - S3 event processing failures",
        )

        cloudwatch.Alarm(
            self,
            "HydrationInputQueueDepthAlarm",
            alarm_name=f"{project}-hydration-input-depth-{environment}",
            metric=self.hydration_input_queue.metric_approximate_number_of_messages_visible(),
            threshold=10000,
            evaluation_periods=2,
            alarm_description="Hydration input queue depth is high - scale up GPU nodes",
        )

        # Outputs
        CfnOutput(self, "HydrationInputQueueUrl", value=self.hydration_input_queue.queue_url)
        CfnOutput(self, "HydrationInputQueueArn", value=self.hydration_input_queue.queue_arn)
        CfnOutput(self, "HydrationInputDlqUrl", value=self.hydration_input_dlq.queue_url)
