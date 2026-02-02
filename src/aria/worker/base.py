"""Base worker class for SQS-driven pipeline stages.

Each worker:
1. Polls messages from its input queue
2. Processes the message
3. Sends result to the output queue (if configured)
4. Deletes the message from input queue on success
5. On failure, message returns to queue (visibility timeout) for retry
"""

import json
import logging
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    """Configuration for a pipeline worker."""

    input_queue_url: str
    output_queue_url: str | None = None
    aws_region: str = "us-east-1"
    batch_size: int = 1
    visibility_timeout: int = 300
    wait_time_seconds: int = 20
    max_retries: int = 3
    health_file: Path = field(default_factory=lambda: Path("/tmp/healthy"))
    ready_file: Path = field(default_factory=lambda: Path("/tmp/ready"))

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        """Create config from environment variables."""
        return cls(
            input_queue_url=os.environ["INPUT_QUEUE_URL"],
            output_queue_url=os.environ.get("OUTPUT_QUEUE_URL"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            batch_size=int(os.environ.get("BATCH_SIZE", "1")),
            visibility_timeout=int(os.environ.get("VISIBILITY_TIMEOUT", "300")),
            wait_time_seconds=int(os.environ.get("WAIT_TIME_SECONDS", "20")),
            max_retries=int(os.environ.get("MAX_RETRIES", "3")),
        )


class BaseWorker(ABC):
    """Base class for SQS-driven pipeline workers."""

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.running = False
        self._setup_logging()
        self._setup_aws_clients()
        self._setup_signal_handlers()

    def _setup_logging(self) -> None:
        """Configure logging."""
        log_level = os.environ.get("LOG_LEVEL", "INFO")
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    def _setup_aws_clients(self) -> None:
        """Initialize AWS clients with retry configuration."""
        boto_config = Config(
            region_name=self.config.aws_region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        self.sqs = boto3.client("sqs", config=boto_config)
        self.s3 = boto3.client("s3", config=boto_config)
        self.dynamodb = boto3.resource("dynamodb", config=boto_config)

    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown handlers."""
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False

    def _mark_healthy(self) -> None:
        """Create health check file."""
        self.config.health_file.touch()

    def _mark_ready(self) -> None:
        """Create readiness check file."""
        self.config.ready_file.touch()

    def _mark_unhealthy(self) -> None:
        """Remove health check file."""
        self.config.health_file.unlink(missing_ok=True)

    def _mark_not_ready(self) -> None:
        """Remove readiness check file."""
        self.config.ready_file.unlink(missing_ok=True)

    @abstractmethod
    def initialize(self) -> None:
        """Initialize worker resources (models, connections, etc.).

        Called once before the main processing loop starts.
        """
        pass

    @abstractmethod
    def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process a single message.

        Args:
            message: The SQS message body (parsed JSON)

        Returns:
            Output message to send to the next queue, or None if no output.

        Raises:
            Exception: If processing fails (message will be retried)
        """
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Cleanup worker resources.

        Called once after the main processing loop ends.
        """
        pass

    def receive_messages(self) -> list[dict[str, Any]]:
        """Receive messages from the input queue."""
        response = self.sqs.receive_message(
            QueueUrl=self.config.input_queue_url,
            MaxNumberOfMessages=self.config.batch_size,
            WaitTimeSeconds=self.config.wait_time_seconds,
            VisibilityTimeout=self.config.visibility_timeout,
            MessageAttributeNames=["All"],
            AttributeNames=["All"],
        )
        return response.get("Messages", [])

    def delete_message(self, receipt_handle: str) -> None:
        """Delete a message from the input queue."""
        self.sqs.delete_message(
            QueueUrl=self.config.input_queue_url,
            ReceiptHandle=receipt_handle,
        )

    def send_to_output(self, message: dict[str, Any]) -> None:
        """Send a message to the output queue."""
        if not self.config.output_queue_url:
            return

        self.sqs.send_message(
            QueueUrl=self.config.output_queue_url,
            MessageBody=json.dumps(message),
        )

    def extend_visibility(self, receipt_handle: str, seconds: int) -> None:
        """Extend the visibility timeout for a message."""
        self.sqs.change_message_visibility(
            QueueUrl=self.config.input_queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=seconds,
        )

    def run(self) -> None:
        """Main worker loop."""
        self.logger.info(f"Starting {self.__class__.__name__}...")
        self.logger.info(f"Input queue: {self.config.input_queue_url}")
        self.logger.info(f"Output queue: {self.config.output_queue_url}")

        try:
            self.initialize()
            self._mark_healthy()
            self._mark_ready()
            self.running = True
            self.logger.info("Worker initialized and ready")

            while self.running:
                self._process_batch()

        except Exception as e:
            self.logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)

        finally:
            self.logger.info("Shutting down...")
            self._mark_not_ready()
            self.cleanup()
            self._mark_unhealthy()
            self.logger.info("Shutdown complete")

    def _process_batch(self) -> None:
        """Process a batch of messages."""
        messages = self.receive_messages()

        if not messages:
            self.logger.debug("No messages received, waiting...")
            return

        self.logger.info(f"Received {len(messages)} message(s)")

        for message in messages:
            if not self.running:
                break

            receipt_handle = message["ReceiptHandle"]
            message_id = message["MessageId"]

            try:
                body = json.loads(message["Body"])
                self.logger.info(f"Processing message {message_id}")

                start_time = time.time()
                result = self.process_message(body)
                elapsed = time.time() - start_time

                self.logger.info(f"Processed message {message_id} in {elapsed:.2f}s")

                if result:
                    self.send_to_output(result)
                    self.logger.info(f"Sent result to output queue for {message_id}")

                self.delete_message(receipt_handle)
                self.logger.info(f"Deleted message {message_id}")

            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON in message {message_id}: {e}")
                # Don't delete - will go to DLQ after max retries

            except Exception as e:
                self.logger.error(f"Error processing message {message_id}: {e}", exc_info=True)
                # Don't delete - will be retried after visibility timeout
