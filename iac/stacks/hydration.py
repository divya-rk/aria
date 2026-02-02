"""Hydration stack.

SQS-driven pipeline:
- Input: Hydration Input Queue (from Collection)
- Output: Curation Input Queue (to Curation)

Resources:
- Curation input queue (output from Hydration)
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


class HydrationStack(Stack):
    """Hydration infrastructure - GPU transcription."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        hydration_input_queue: sqs.IQueue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # =====================================================================
        # CURATION INPUT QUEUE (Hydration → Curation)
        # =====================================================================
        # Hydration produces messages here after successful transcription

        self.curation_input_dlq = sqs.Queue(
            self,
            "CurationInputDlq",
            queue_name=f"{project}-curation-input-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        self.curation_input_queue = sqs.Queue(
            self,
            "CurationInputQueue",
            queue_name=f"{project}-curation-input-{environment}",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.curation_input_dlq,
            ),
        )

        # CloudWatch Alarms
        cloudwatch.Alarm(
            self,
            "CurationInputDlqAlarm",
            alarm_name=f"{project}-curation-input-dlq-{environment}",
            metric=self.curation_input_dlq.metric_approximate_number_of_messages_visible(),
            threshold=10,
            evaluation_periods=1,
            alarm_description="Curation input DLQ has messages - hydration output failures",
        )

        # Install KEDA for SQS-based scaling
        eks_cluster.add_helm_chart(
            "Keda",
            chart="keda",
            repository="https://kedacore.github.io/charts",
            namespace="keda",
            create_namespace=True,
            version="2.13.0",
        )

        # KEDA ScaledObject for Hydration workers
        scaled_object = {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "ScaledObject",
            "metadata": {
                "name": "hydration-scaledobject",
                "namespace": "aria",
            },
            "spec": {
                "scaleTargetRef": {
                    "name": "hydration-worker",
                },
                "minReplicaCount": 0,
                "maxReplicaCount": 20,
                "pollingInterval": 15,
                "cooldownPeriod": 300,
                "triggers": [
                    {
                        "type": "aws-sqs-queue",
                        "metadata": {
                            "queueURL": hydration_input_queue.queue_url,
                            "queueLength": "5",  # Messages per replica
                            "awsRegion": self.region,
                        },
                    }
                ],
            },
        }

        eks_cluster.add_manifest("HydrationScaledObject", scaled_object)

        # Outputs
        CfnOutput(self, "CurationInputQueueUrl", value=self.curation_input_queue.queue_url)
        CfnOutput(self, "CurationInputQueueArn", value=self.curation_input_queue.queue_arn)
