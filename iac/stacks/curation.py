"""Curation stack.

SQS-driven pipeline:
- Input: Curation Input Queue (from Hydration)
- Output: Embedding Input Queue (to Embedding)

Resources:
- Embedding input queue (output from Curation)
- KEDA ScaledObject for SQS-based autoscaling
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_eks as eks,
    aws_sqs as sqs,
)
from constructs import Construct


class CurationStack(Stack):
    """Curation infrastructure - quality filtering and dedup."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        curation_input_queue: sqs.IQueue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # =====================================================================
        # EMBEDDING INPUT QUEUE (Curation → Embedding)
        # =====================================================================
        # Curation produces messages here after quality filtering

        self.embedding_input_dlq = sqs.Queue(
            self,
            "EmbeddingInputDlq",
            queue_name=f"{project}-embedding-input-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        self.embedding_input_queue = sqs.Queue(
            self,
            "EmbeddingInputQueue",
            queue_name=f"{project}-embedding-input-{environment}",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.embedding_input_dlq,
            ),
        )

        # CloudWatch Alarms
        cloudwatch.Alarm(
            self,
            "EmbeddingInputDlqAlarm",
            alarm_name=f"{project}-embedding-input-dlq-{environment}",
            metric=self.embedding_input_dlq.metric_approximate_number_of_messages_visible(),
            threshold=20,
            evaluation_periods=1,
            alarm_description="Embedding input DLQ has messages - curation output failures",
        )

        # KEDA ScaledObject for Curation workers
        scaled_object = {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "ScaledObject",
            "metadata": {
                "name": "curation-scaledobject",
                "namespace": "aria",
            },
            "spec": {
                "scaleTargetRef": {
                    "name": "curation-worker",
                },
                "minReplicaCount": 0,
                "maxReplicaCount": 30,
                "pollingInterval": 15,
                "cooldownPeriod": 120,
                "triggers": [
                    {
                        "type": "aws-sqs-queue",
                        "metadata": {
                            "queueURL": curation_input_queue.queue_url,
                            "queueLength": "10",
                            "awsRegion": self.region,
                        },
                    }
                ],
            },
        }

        eks_cluster.add_manifest("CurationScaledObject", scaled_object)

        # Outputs
        CfnOutput(self, "EmbeddingInputQueueUrl", value=self.embedding_input_queue.queue_url)
        CfnOutput(self, "EmbeddingInputQueueArn", value=self.embedding_input_queue.queue_arn)
