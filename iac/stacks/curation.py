"""Curation stack.

Resources:
- CPU node group for quality/dedup processing
- SQS queue for curation jobs
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_eks as eks,
    aws_sqs as sqs,
)
from constructs import Construct


class CurationStack(Stack):
    """CPU infrastructure for quality filtering and deduplication."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # CPU Node Group
        self.cpu_nodegroup = eks_cluster.add_nodegroup_capacity(
            "CurationNodeGroup",
            nodegroup_name=f"{project}-cpu-curation-{environment}",
            instance_types=[
                ec2.InstanceType("c5.xlarge"),
                ec2.InstanceType("c5.2xlarge"),
            ],
            min_size=0,
            max_size=20,
            desired_size=1,
            capacity_type=eks.CapacityType.SPOT,
            labels={
                "aria.io/node-type": "cpu",
                "aria.io/workload": "curation",
            },
        )

        # DLQ
        self.dlq = sqs.Queue(
            self,
            "CurationDlq",
            queue_name=f"{project}-curation-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        # Curation Queue
        self.queue = sqs.Queue(
            self,
            "CurationQueue",
            queue_name=f"{project}-curation-{environment}",
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
            alarm_name=f"{project}-curation-dlq-{environment}",
            metric=self.dlq.metric_approximate_number_of_messages_visible(),
            threshold=50,
            evaluation_periods=1,
            alarm_description="Curation DLQ has messages - quality/dedup failures",
        )

        # Outputs
        CfnOutput(self, "CpuNodeGroupName", value=self.cpu_nodegroup.nodegroup_name)
        CfnOutput(self, "CurationQueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "CurationDlqUrl", value=self.dlq.queue_url)
