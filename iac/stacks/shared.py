"""Shared infrastructure stack.

Resources:
- EKS cluster (uses default VPC)
- S3 buckets (raw, output, lancedb)
- DynamoDB table (jobs)
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_eks as eks,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class SharedStack(Stack):
    """Shared infrastructure for all pipeline stages."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project: str,
        environment: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.environment = environment

        # Use default VPC
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # EKS Cluster
        self.eks_cluster = eks.Cluster(
            self,
            "EksCluster",
            cluster_name=f"{project}-{environment}",
            version=eks.KubernetesVersion.V1_29,
            vpc=vpc,
            default_capacity=1,
            default_capacity_instance=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM
            ),
        )

        # S3 Buckets
        self.raw_bucket = s3.Bucket(
            self,
            "RawBucket",
            bucket_name=f"{project}-raw-{environment}",
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="transition-to-ia",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(90),
                        )
                    ],
                ),
                s3.LifecycleRule(
                    id="abort-incomplete-uploads",
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.output_bucket = s3.Bucket(
            self,
            "OutputBucket",
            bucket_name=f"{project}-output-{environment}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="transition-to-ia",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(90),
                        )
                    ],
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.lancedb_bucket = s3.Bucket(
            self,
            "LanceDbBucket",
            bucket_name=f"{project}-lancedb-{environment}",
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # DynamoDB Table
        self.jobs_table = dynamodb.Table(
            self,
            "JobsTable",
            table_name=f"{project}-jobs-{environment}",
            partition_key=dynamodb.Attribute(
                name="file_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="stage", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for querying by status
        self.jobs_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="stage", type=dynamodb.AttributeType.STRING
            ),
        )

        # Grant EKS nodes access to S3 buckets
        self.raw_bucket.grant_read(self.eks_cluster.default_nodegroup.role)
        self.output_bucket.grant_read_write(self.eks_cluster.default_nodegroup.role)
        self.lancedb_bucket.grant_read_write(self.eks_cluster.default_nodegroup.role)
        self.jobs_table.grant_read_write_data(self.eks_cluster.default_nodegroup.role)

        # Outputs
        CfnOutput(self, "EksClusterName", value=self.eks_cluster.cluster_name)
        CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
        CfnOutput(self, "OutputBucketName", value=self.output_bucket.bucket_name)
        CfnOutput(self, "LanceDbBucketName", value=self.lancedb_bucket.bucket_name)
        CfnOutput(self, "JobsTableName", value=self.jobs_table.table_name)
