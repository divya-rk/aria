"""Tokenization stack.

Resources:
- CPU node group for tokenization
- CloudWatch dashboard for training data
"""

from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_eks as eks,
    aws_s3 as s3,
)
from constructs import Construct


class TokenizationStack(Stack):
    """Infrastructure for tokenization and sharding."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        eks_cluster: eks.Cluster,
        output_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # CPU Node Group (smaller, tokenization is lightweight)
        self.cpu_nodegroup = eks_cluster.add_nodegroup_capacity(
            "TokenizationNodeGroup",
            nodegroup_name=f"{project}-cpu-tokenization-{environment}",
            instance_types=[
                ec2.InstanceType("m5.large"),
                ec2.InstanceType("m5.xlarge"),
            ],
            min_size=0,
            max_size=5,
            desired_size=0,
            capacity_type=eks.CapacityType.SPOT,
            labels={
                "aria.io/node-type": "cpu",
                "aria.io/workload": "tokenization",
            },
        )

        # Grant output bucket access
        output_bucket.grant_read_write(self.cpu_nodegroup.role)

        # CloudWatch Dashboard
        dashboard = cloudwatch.Dashboard(
            self,
            "TokenizationDashboard",
            dashboard_name=f"{project}-tokenization-{environment}",
        )

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="S3 Bucket Size",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/S3",
                        metric_name="BucketSizeBytes",
                        dimensions_map={
                            "BucketName": output_bucket.bucket_name,
                            "StorageType": "StandardStorage",
                        },
                        statistic="Average",
                    )
                ],
            ),
            cloudwatch.GraphWidget(
                title="S3 Object Count",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/S3",
                        metric_name="NumberOfObjects",
                        dimensions_map={
                            "BucketName": output_bucket.bucket_name,
                            "StorageType": "AllStorageTypes",
                        },
                        statistic="Average",
                    )
                ],
            ),
        )

        # Outputs
        CfnOutput(self, "TokenizationNodeGroupName", value=self.cpu_nodegroup.nodegroup_name)
        CfnOutput(
            self,
            "TrainingShardsPath",
            value=f"s3://{output_bucket.bucket_name}/shards/",
        )
        CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home?region={self.region}#dashboards:name={project}-tokenization-{environment}",
        )
