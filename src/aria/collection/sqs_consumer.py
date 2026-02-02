"""SQS consumer for processing file events."""

import json
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError

from aria.common import AudioFile, QueueError, get_logger
from aria.config import Settings
from aria.storage import S3Client


logger = get_logger(__name__)


class SQSConsumer:
    """Consumer for SQS messages containing S3 events."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize SQS consumer.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.queue_url = settings.sqs.ingestion_queue_url
        self.dlq_url = settings.sqs.dlq_url
        self.visibility_timeout = settings.sqs.visibility_timeout
        self.max_receive_count = settings.sqs.max_receive_count

        self._client = boto3.client(
            "sqs",
            region_name=settings.aws.region,
        )
        self._s3_client = S3Client(settings)

    def receive_messages(
        self,
        max_messages: int = 10,
        wait_time_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Receive messages from the queue.

        Args:
            max_messages: Maximum messages to receive (1-10)
            wait_time_seconds: Long polling wait time

        Returns:
            List of SQS messages
        """
        try:
            response = self._client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=wait_time_seconds,
                VisibilityTimeout=self.visibility_timeout,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
            messages = response.get("Messages", [])
            logger.debug("messages_received", count=len(messages))
            return messages
        except ClientError as e:
            raise QueueError(f"Failed to receive messages: {e}") from e

    def delete_message(self, receipt_handle: str) -> None:
        """
        Delete a processed message from the queue.

        Args:
            receipt_handle: Message receipt handle
        """
        try:
            self._client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.debug("message_deleted")
        except ClientError as e:
            raise QueueError(f"Failed to delete message: {e}") from e

    def send_to_dlq(self, message_body: str, error_reason: str) -> None:
        """
        Send failed message to dead letter queue.

        Args:
            message_body: Original message body
            error_reason: Reason for failure
        """
        if not self.dlq_url:
            logger.warning("dlq_not_configured")
            return

        try:
            self._client.send_message(
                QueueUrl=self.dlq_url,
                MessageBody=message_body,
                MessageAttributes={
                    "ErrorReason": {
                        "DataType": "String",
                        "StringValue": error_reason[:256],  # Limit length
                    }
                },
            )
            logger.info("message_sent_to_dlq", reason=error_reason)
        except ClientError as e:
            raise QueueError(f"Failed to send to DLQ: {e}") from e

    def parse_message(self, message: dict[str, Any]) -> list[AudioFile]:
        """
        Parse SQS message into AudioFile objects.

        Handles both direct S3 events and SNS-wrapped events.

        Args:
            message: SQS message

        Returns:
            List of AudioFile objects
        """
        body = message.get("Body", "{}")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("invalid_json_message", body=body[:100])
            return []

        # Handle SNS wrapper
        if "Message" in payload:
            try:
                payload = json.loads(payload["Message"])
            except json.JSONDecodeError:
                logger.warning("invalid_sns_message")
                return []

        return self._s3_client.parse_s3_event(payload)

    def process_messages(
        self,
        handler: Callable[[AudioFile], bool],
        batch_size: int = 10,
        max_iterations: int | None = None,
    ) -> int:
        """
        Continuously process messages from the queue.

        Args:
            handler: Function to process each AudioFile, returns success bool
            batch_size: Messages per batch
            max_iterations: Optional limit on iterations (for testing)

        Returns:
            Total messages processed
        """
        total_processed = 0
        iterations = 0

        while max_iterations is None or iterations < max_iterations:
            messages = self.receive_messages(max_messages=batch_size)

            if not messages:
                logger.debug("no_messages_available")
                iterations += 1
                continue

            for message in messages:
                receipt_handle = message["ReceiptHandle"]
                audio_files = self.parse_message(message)

                success = True
                for audio_file in audio_files:
                    try:
                        result = handler(audio_file)
                        if not result:
                            success = False
                    except Exception as e:
                        logger.error(
                            "handler_error",
                            file_id=audio_file.file_id,
                            error=str(e),
                        )
                        success = False

                if success:
                    self.delete_message(receipt_handle)
                    total_processed += len(audio_files)
                else:
                    # Will be retried or sent to DLQ by SQS
                    logger.warning("message_processing_failed")

            iterations += 1

        logger.info("processing_complete", total_processed=total_processed)
        return total_processed

    def get_queue_stats(self) -> dict[str, int]:
        """
        Get queue statistics.

        Returns:
            Dictionary with queue metrics
        """
        try:
            response = self._client.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed",
                ],
            )
            attrs = response.get("Attributes", {})
            return {
                "messages_available": int(attrs.get("ApproximateNumberOfMessages", 0)),
                "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "messages_delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
            }
        except ClientError as e:
            raise QueueError(f"Failed to get queue stats: {e}") from e
