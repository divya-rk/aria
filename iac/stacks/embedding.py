"""Embedding stack.

Resources:
- CPU node group for embedding generation
- SQS queue for embedding jobs
- IAM policy for LanceDB S3 access
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_eks as eks,
    aws_iam as iam,
    aws_s3 as s3,
    aws_sqs as sqs,
)
from constructs import Construct


class EmbeddingStack(Stack):
    """Infrastructure for vector embedding generation."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        lancedb_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # CPU Node Group
        self.cpu_nodegroup = eks_cluster.add_nodegroup_capacity(
            "EmbeddingNodeGroup",
            nodegroup_name=f"{project}-cpu-embedding-{environment}",
            instance_types=[
                ec2.InstanceType("c5.xlarge"),
                ec2.InstanceType("c5.2xlarge"),
            ],
            min_size=0,
            max_size=10,
            desired_size=1,
            capacity_type=eks.CapacityType.SPOT,
            labels={
                "aria.io/node-type": "cpu",
                "aria.io/workload": "embedding",
            },
        )

        # Grant LanceDB bucket access
        lancedb_bucket.grant_read_write(self.cpu_nodegroup.role)

        # DLQ
        self.dlq = sqs.Queue(
            self,
            "EmbeddingDlq",
            queue_name=f"{project}-embedding-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        # Embedding Queue
        self.queue = sqs.Queue(
            self,
            "EmbeddingQueue",
            queue_name=f"{project}-embedding-{environment}",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.dlq,
            ),
        )

        # CloudWatch Alarms
        cloudwatch.Alarm(
            self,
            "DlqAlarm",
            alarm_name=f"{project}-embedding-dlq-{environment}",
            metric=self.dlq.metric_approximate_number_of_messages_visible(),
            threshold=20,
            evaluation_periods=1,
            alarm_description="Embedding DLQ has messages",
        )

        # Outputs
        CfnOutput(self, "EmbeddingNodeGroupName", value=self.cpu_nodegroup.nodegroup_name)
        CfnOutput(self, "EmbeddingQueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "EmbeddingDlqUrl", value=self.dlq.queue_url)
