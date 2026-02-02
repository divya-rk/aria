#!/usr/bin/env python3
"""AWS CDK app for Aria infrastructure."""

import aws_cdk as cdk

from stacks.shared import SharedStack
from stacks.collection import CollectionStack
from stacks.hydration import HydrationStack
from stacks.curation import CurationStack
from stacks.embedding import EmbeddingStack
from stacks.tokenization import TokenizationStack


app = cdk.App()

# Get configuration from context
environment = app.node.try_get_context("environment") or "dev"
project = app.node.try_get_context("project") or "aria"

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

# Shared stack (EKS, S3, DynamoDB)
shared = SharedStack(
    app,
    f"{project}-shared-{environment}",
    project=project,
    environment=environment,
    env=env,
)

# Collection stack (S3 events, SQS)
collection = CollectionStack(
    app,
    f"{project}-collection-{environment}",
    project=project,
    environment=environment,
    raw_bucket=shared.raw_bucket,
    env=env,
)

# Hydration stack (GPU nodes)
hydration = HydrationStack(
    app,
    f"{project}-hydration-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    env=env,
)

# Curation stack (CPU nodes)
curation = CurationStack(
    app,
    f"{project}-curation-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    env=env,
)

# Embedding stack (LanceDB)
embedding = EmbeddingStack(
    app,
    f"{project}-embedding-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    lancedb_bucket=shared.lancedb_bucket,
    env=env,
)

# Tokenization stack
tokenization = TokenizationStack(
    app,
    f"{project}-tokenization-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    output_bucket=shared.output_bucket,
    env=env,
)

app.synth()
