#!/usr/bin/env python3
"""AWS CDK app for Aria infrastructure.

SQS-driven pipeline architecture:
    S3 Events → [Hydration Input Q] → Hydration → [Curation Input Q] → Curation
        → [Embedding Input Q] → Embedding → [Tokenization Input Q] → Tokenization → S3 Shards

Each stage:
- Consumes from its input queue
- Produces to the next stage's input queue
- On failure, message goes to DLQ for retry/inspection
"""

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

# =============================================================================
# SHARED STACK
# =============================================================================
# EKS cluster with Karpenter, S3 buckets, DynamoDB
shared = SharedStack(
    app,
    f"{project}-shared-{environment}",
    project=project,
    environment=environment,
    env=env,
)

# =============================================================================
# COLLECTION STACK
# =============================================================================
# S3 events → Hydration Input Queue
collection = CollectionStack(
    app,
    f"{project}-collection-{environment}",
    project=project,
    environment=environment,
    raw_bucket=shared.raw_bucket,
    env=env,
)
collection.add_dependency(shared)

# =============================================================================
# HYDRATION STACK
# =============================================================================
# Hydration Input Queue → GPU processing → Curation Input Queue
hydration = HydrationStack(
    app,
    f"{project}-hydration-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    hydration_input_queue=collection.hydration_input_queue,
    env=env,
)
hydration.add_dependency(collection)

# =============================================================================
# CURATION STACK
# =============================================================================
# Curation Input Queue → CPU processing → Embedding Input Queue
curation = CurationStack(
    app,
    f"{project}-curation-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    curation_input_queue=hydration.curation_input_queue,
    env=env,
)
curation.add_dependency(hydration)

# =============================================================================
# EMBEDDING STACK
# =============================================================================
# Embedding Input Queue → CPU processing → Tokenization Input Queue
embedding = EmbeddingStack(
    app,
    f"{project}-embedding-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    lancedb_bucket=shared.lancedb_bucket,
    embedding_input_queue=curation.embedding_input_queue,
    env=env,
)
embedding.add_dependency(curation)

# =============================================================================
# TOKENIZATION STACK
# =============================================================================
# Tokenization Input Queue → CPU processing → S3 Shards
tokenization = TokenizationStack(
    app,
    f"{project}-tokenization-{environment}",
    project=project,
    environment=environment,
    eks_cluster=shared.eks_cluster,
    output_bucket=shared.output_bucket,
    tokenization_input_queue=embedding.tokenization_input_queue,
    env=env,
)
tokenization.add_dependency(embedding)

app.synth()
