"""Embedding stack.

SQS-driven pipeline:
- Input: Embedding Input Queue (from Curation)
- Output: Tokenization Input Queue (to Tokenization)

Resources:
- Tokenization input queue (output from Embedding)
- KEDA ScaledObject for SQS-based autoscaling
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_eks as eks,
    aws_s3 as s3,
    aws_sqs as sqs,
)
from constructs import Construct


class EmbeddingStack(Stack):
    """Embedding infrastructure - vector generation."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        lancedb_bucket: s3.IBucket,
        embedding_input_queue: sqs.IQueue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # =====================================================================
        # TOKENIZATION INPUT QUEUE (Embedding → Tokenization)
        # =====================================================================
        # Embedding produces messages here after vectorization

        self.tokenization_input_dlq = sqs.Queue(
            self,
            "TokenizationInputDlq",
            queue_name=f"{project}-tokenization-input-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        self.tokenization_input_queue = sqs.Queue(
            self,
            "TokenizationInputQueue",
            queue_name=f"{project}-tokenization-input-{environment}",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.tokenization_input_dlq,
            ),
        )

        # CloudWatch Alarms
        cloudwatch.Alarm(
            self,
            "TokenizationInputDlqAlarm",
            alarm_name=f"{project}-tokenization-input-dlq-{environment}",
            metric=self.tokenization_input_dlq.metric_approximate_number_of_messages_visible(),
            threshold=20,
            evaluation_periods=1,
            alarm_description="Tokenization input DLQ has messages - embedding output failures",
        )

        # KEDA ScaledObject for Embedding workers
        scaled_object = {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "ScaledObject",
            "metadata": {
                "name": "embedding-scaledobject",
                "namespace": "aria",
            },
            "spec": {
                "scaleTargetRef": {
                    "name": "embedding-worker",
                },
                "minReplicaCount": 0,
                "maxReplicaCount": 20,
                "pollingInterval": 15,
                "cooldownPeriod": 120,
                "triggers": [
                    {
                        "type": "aws-sqs-queue",
                        "metadata": {
                            "queueURL": embedding_input_queue.queue_url,
                            "queueLength": "10",
                            "awsRegion": self.region,
                        },
                    }
                ],
            },
        }

        eks_cluster.add_manifest("EmbeddingScaledObject", scaled_object)

        # Outputs
        CfnOutput(self, "TokenizationInputQueueUrl", value=self.tokenization_input_queue.queue_url)
        CfnOutput(self, "TokenizationInputQueueArn", value=self.tokenization_input_queue.queue_arn)
