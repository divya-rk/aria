"""Tokenization stack.

SQS-driven pipeline:
- Input: Tokenization Input Queue (from Embedding)
- Output: S3 shards (final output)

Resources:
- KEDA ScaledObject for SQS-based autoscaling
- CloudWatch dashboard
"""

from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_eks as eks,
    aws_s3 as s3,
    aws_sqs as sqs,
)
from constructs import Construct


class TokenizationStack(Stack):
    """Tokenization infrastructure - sharding for LLM training."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        output_bucket: s3.IBucket,
        tokenization_input_queue: sqs.IQueue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # KEDA ScaledObject for Tokenization workers
        scaled_object = {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "ScaledObject",
            "metadata": {
                "name": "tokenization-scaledobject",
                "namespace": "aria",
            },
            "spec": {
                "scaleTargetRef": {
                    "name": "tokenization-worker",
                },
                "minReplicaCount": 0,
                "maxReplicaCount": 10,
                "pollingInterval": 30,
                "cooldownPeriod": 300,
                "triggers": [
                    {
                        "type": "aws-sqs-queue",
                        "metadata": {
                            "queueURL": tokenization_input_queue.queue_url,
                            "queueLength": "20",
                            "awsRegion": self.region,
                        },
                    }
                ],
            },
        }

        eks_cluster.add_manifest("TokenizationScaledObject", scaled_object)

        # CloudWatch Dashboard
        dashboard = cloudwatch.Dashboard(
            self,
            "PipelineDashboard",
            dashboard_name=f"{project}-pipeline-{environment}",
        )

        # Pipeline flow metrics
        dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown="# Aria Pipeline Dashboard\n\nSQS-driven pipeline: Collection → Hydration → Curation → Embedding → Tokenization",
                width=24,
                height=2,
            ),
        )

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Pipeline Queue Depths",
                width=24,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-hydration-input-{environment}"},
                        label="Hydration Input",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-curation-input-{environment}"},
                        label="Curation Input",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-embedding-input-{environment}"},
                        label="Embedding Input",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-tokenization-input-{environment}"},
                        label="Tokenization Input",
                    ),
                ],
            ),
        )

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="DLQ Messages (Failures)",
                width=12,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-hydration-input-{environment}-dlq"},
                        label="Hydration DLQ",
                        color="#d62728",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-curation-input-{environment}-dlq"},
                        label="Curation DLQ",
                        color="#ff7f0e",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-embedding-input-{environment}-dlq"},
                        label="Embedding DLQ",
                        color="#9467bd",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/SQS",
                        metric_name="ApproximateNumberOfMessagesVisible",
                        dimensions_map={"QueueName": f"{project}-tokenization-input-{environment}-dlq"},
                        label="Tokenization DLQ",
                        color="#8c564b",
                    ),
                ],
            ),
            cloudwatch.GraphWidget(
                title="S3 Output Bucket",
                width=12,
                height=6,
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/S3",
                        metric_name="BucketSizeBytes",
                        dimensions_map={
                            "BucketName": output_bucket.bucket_name,
                            "StorageType": "StandardStorage",
                        },
                        statistic="Average",
                        label="Bucket Size",
                    ),
                ],
            ),
        )

        # Outputs
        CfnOutput(
            self,
            "TrainingShardsPath",
            value=f"s3://{output_bucket.bucket_name}/shards/",
        )
        CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home?region={self.region}#dashboards:name={project}-pipeline-{environment}",
        )
