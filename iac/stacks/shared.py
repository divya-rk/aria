"""Shared infrastructure stack.

Resources:
- EKS cluster (uses default VPC)
- Karpenter for autoscaling
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

        # EKS Cluster (minimal default capacity - Karpenter will manage nodes)
        self.eks_cluster = eks.Cluster(
            self,
            "EksCluster",
            cluster_name=f"{project}-{environment}",
            version=eks.KubernetesVersion.V1_29,
            vpc=vpc,
            default_capacity=1,  # Minimal for system pods
            default_capacity_instance=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM
            ),
        )

        # Karpenter Controller IAM Role
        self.karpenter_role = self._create_karpenter_role()

        # Karpenter Node IAM Role
        self.karpenter_node_role = self._create_karpenter_node_role()

        # Install Karpenter via Helm
        self._install_karpenter()

        # Create Karpenter NodePools for GPU and CPU
        self._create_node_pools()

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

        # Grant Karpenter nodes access to resources
        self.raw_bucket.grant_read(self.karpenter_node_role)
        self.output_bucket.grant_read_write(self.karpenter_node_role)
        self.lancedb_bucket.grant_read_write(self.karpenter_node_role)
        self.jobs_table.grant_read_write_data(self.karpenter_node_role)

        # Outputs
        CfnOutput(self, "EksClusterName", value=self.eks_cluster.cluster_name)
        CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
        CfnOutput(self, "OutputBucketName", value=self.output_bucket.bucket_name)
        CfnOutput(self, "LanceDbBucketName", value=self.lancedb_bucket.bucket_name)
        CfnOutput(self, "JobsTableName", value=self.jobs_table.table_name)

    def _create_karpenter_role(self) -> iam.Role:
        """Create IAM role for Karpenter controller."""
        role = iam.Role(
            self,
            "KarpenterControllerRole",
            role_name=f"{self.project}-karpenter-controller-{self.environment}",
            assumed_by=iam.FederatedPrincipal(
                self.eks_cluster.open_id_connect_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        f"{self.eks_cluster.cluster_open_id_connect_issuer}:sub":
                            "system:serviceaccount:karpenter:karpenter",
                        f"{self.eks_cluster.cluster_open_id_connect_issuer}:aud":
                            "sts.amazonaws.com",
                    }
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )

        # Karpenter controller policy
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2:CreateFleet",
                    "ec2:CreateLaunchTemplate",
                    "ec2:CreateTags",
                    "ec2:DeleteLaunchTemplate",
                    "ec2:DescribeAvailabilityZones",
                    "ec2:DescribeImages",
                    "ec2:DescribeInstances",
                    "ec2:DescribeInstanceTypeOfferings",
                    "ec2:DescribeInstanceTypes",
                    "ec2:DescribeLaunchTemplates",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeSpotPriceHistory",
                    "ec2:DescribeSubnets",
                    "ec2:RunInstances",
                    "ec2:TerminateInstances",
                ],
                resources=["*"],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[self.karpenter_node_role.role_arn if hasattr(self, 'karpenter_node_role') else "*"],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "pricing:GetProducts",
                    "ssm:GetParameter",
                ],
                resources=["*"],
            )
        )

        return role

    def _create_karpenter_node_role(self) -> iam.Role:
        """Create IAM role for Karpenter-managed nodes."""
        role = iam.Role(
            self,
            "KarpenterNodeRole",
            role_name=f"{self.project}-karpenter-node-{self.environment}",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEKSWorkerNodePolicy"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEKS_CNI_Policy"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryReadOnly"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )

        # Add SQS permissions for all pipeline queues
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:SendMessage",
                    "sqs:GetQueueAttributes",
                    "sqs:GetQueueUrl",
                ],
                resources=[f"arn:aws:sqs:{self.region}:{self.account}:{self.project}-*"],
            )
        )

        # Create instance profile for nodes
        iam.CfnInstanceProfile(
            self,
            "KarpenterNodeInstanceProfile",
            instance_profile_name=f"{self.project}-karpenter-node-{self.environment}",
            roles=[role.role_name],
        )

        return role

    def _install_karpenter(self) -> None:
        """Install Karpenter via Helm chart."""
        self.eks_cluster.add_helm_chart(
            "Karpenter",
            chart="karpenter",
            repository="oci://public.ecr.aws/karpenter",
            namespace="karpenter",
            create_namespace=True,
            version="v0.33.0",
            values={
                "settings": {
                    "clusterName": self.eks_cluster.cluster_name,
                    "clusterEndpoint": self.eks_cluster.cluster_endpoint,
                    "interruptionQueue": f"{self.project}-karpenter-{self.environment}",
                },
                "serviceAccount": {
                    "annotations": {
                        "eks.amazonaws.com/role-arn": self.karpenter_role.role_arn,
                    },
                },
            },
        )

    def _create_node_pools(self) -> None:
        """Create Karpenter NodePool manifests."""
        # GPU NodePool for Hydration
        gpu_nodepool = {
            "apiVersion": "karpenter.sh/v1beta1",
            "kind": "NodePool",
            "metadata": {"name": "gpu-hydration"},
            "spec": {
                "template": {
                    "metadata": {
                        "labels": {
                            "aria.io/node-type": "gpu",
                            "aria.io/workload": "hydration",
                        },
                    },
                    "spec": {
                        "requirements": [
                            {"key": "node.kubernetes.io/instance-type", "operator": "In", "values": ["g4dn.xlarge", "g4dn.2xlarge"]},
                            {"key": "karpenter.sh/capacity-type", "operator": "In", "values": ["spot", "on-demand"]},
                            {"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]},
                        ],
                        "nodeClassRef": {"name": "default"},
                        "taints": [
                            {"key": "nvidia.com/gpu", "value": "true", "effect": "NoSchedule"},
                        ],
                    },
                },
                "limits": {"cpu": "100", "memory": "400Gi"},
                "disruption": {
                    "consolidationPolicy": "WhenEmpty",
                    "consolidateAfter": "30s",
                },
            },
        }

        # CPU NodePool for Curation/Embedding/Tokenization
        cpu_nodepool = {
            "apiVersion": "karpenter.sh/v1beta1",
            "kind": "NodePool",
            "metadata": {"name": "cpu-processing"},
            "spec": {
                "template": {
                    "metadata": {
                        "labels": {
                            "aria.io/node-type": "cpu",
                        },
                    },
                    "spec": {
                        "requirements": [
                            {"key": "node.kubernetes.io/instance-type", "operator": "In", "values": ["c5.xlarge", "c5.2xlarge", "c5.4xlarge", "m5.xlarge", "m5.2xlarge"]},
                            {"key": "karpenter.sh/capacity-type", "operator": "In", "values": ["spot", "on-demand"]},
                            {"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]},
                        ],
                        "nodeClassRef": {"name": "default"},
                    },
                },
                "limits": {"cpu": "200", "memory": "800Gi"},
                "disruption": {
                    "consolidationPolicy": "WhenEmpty",
                    "consolidateAfter": "30s",
                },
            },
        }

        # EC2NodeClass
        node_class = {
            "apiVersion": "karpenter.k8s.aws/v1beta1",
            "kind": "EC2NodeClass",
            "metadata": {"name": "default"},
            "spec": {
                "amiFamily": "AL2",
                "role": f"{self.project}-karpenter-node-{self.environment}",
                "subnetSelectorTerms": [{"tags": {"kubernetes.io/cluster/" + self.eks_cluster.cluster_name: "*"}}],
                "securityGroupSelectorTerms": [{"tags": {"kubernetes.io/cluster/" + self.eks_cluster.cluster_name: "*"}}],
                "tags": {
                    "Project": self.project,
                    "Environment": self.environment,
                    "ManagedBy": "karpenter",
                },
            },
        }

        # Apply manifests
        self.eks_cluster.add_manifest("GpuNodePool", gpu_nodepool)
        self.eks_cluster.add_manifest("CpuNodePool", cpu_nodepool)
        self.eks_cluster.add_manifest("DefaultNodeClass", node_class)
