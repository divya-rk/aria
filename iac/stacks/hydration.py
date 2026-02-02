"""Hydration stack.

Resources:
- GPU node group for Whisper transcription
- SQS queue for hydration jobs
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


class HydrationStack(Stack):
    """GPU infrastructure for audio transcription."""

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

        # GPU Node Group
        self.gpu_nodegroup = eks_cluster.add_nodegroup_capacity(
            "GpuNodeGroup",
            nodegroup_name=f"{project}-gpu-{environment}",
            instance_types=[
                ec2.InstanceType("g4dn.xlarge"),
                ec2.InstanceType("g4dn.2xlarge"),
            ],
            min_size=0,
            max_size=10,
            desired_size=0,
            capacity_type=eks.CapacityType.SPOT,
            ami_type=eks.NodegroupAmiType.AL2_X86_64_GPU,
            labels={
                "aria.io/node-type": "gpu",
                "aria.io/workload": "hydration",
                "nvidia.com/gpu": "true",
            },
            taints=[
                eks.TaintSpec(
                    key="nvidia.com/gpu",
                    value="true",
                    effect=eks.TaintEffect.NO_SCHEDULE,
                )
            ],
        )

        # DLQ
        self.dlq = sqs.Queue(
            self,
            "HydrationDlq",
            queue_name=f"{project}-hydration-{environment}-dlq",
            retention_period=Duration.days(14),
        )

        # Hydration Queue
        self.queue = sqs.Queue(
            self,
            "HydrationQueue",
            queue_name=f"{project}-hydration-{environment}",
            visibility_timeout=Duration.minutes(10),  # GPU processing takes longer
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
            alarm_name=f"{project}-hydration-dlq-{environment}",
            metric=self.dlq.metric_approximate_number_of_messages_visible(),
            threshold=10,
            evaluation_periods=1,
            alarm_description="Hydration DLQ has messages - transcription failures",
        )

        # Outputs
        CfnOutput(self, "GpuNodeGroupName", value=self.gpu_nodegroup.nodegroup_name)
        CfnOutput(self, "HydrationQueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "HydrationDlqUrl", value=self.dlq.queue_url)
