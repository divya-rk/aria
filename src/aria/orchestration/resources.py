"""Dagster resources for Aria pipeline."""

from dagster import ConfigurableResource, ResourceDependency

from aria.config import Settings, get_settings
from aria.curation import CurationProcessor
from aria.embedding import EmbeddingProcessor
from aria.hydration import HydrationProcessor
from aria.storage import DynamoDBClient, LanceDBStore, S3Client
from aria.tokenization import TokenizationProcessor


class AriaSettings(ConfigurableResource):
    """Aria settings resource."""

    environment: str = "dev"

    def get_settings(self) -> Settings:
        """Get application settings."""
        return get_settings()


class AriaS3(ConfigurableResource):
    """S3 client resource."""

    settings: ResourceDependency[AriaSettings]

    def get_client(self) -> S3Client:
        """Get S3 client."""
        return S3Client(self.settings.get_settings())


class AriaDynamoDB(ConfigurableResource):
    """DynamoDB client resource."""

    settings: ResourceDependency[AriaSettings]

    def get_client(self) -> DynamoDBClient:
        """Get DynamoDB client."""
        return DynamoDBClient(self.settings.get_settings())


class AriaLanceDB(ConfigurableResource):
    """LanceDB store resource."""

    settings: ResourceDependency[AriaSettings]

    def get_store(self) -> LanceDBStore:
        """Get LanceDB store."""
        return LanceDBStore(self.settings.get_settings())


class AriaHydration(ConfigurableResource):
    """Hydration processor resource."""

    settings: ResourceDependency[AriaSettings]

    def get_processor(self) -> HydrationProcessor:
        """Get hydration processor."""
        return HydrationProcessor(self.settings.get_settings())


class AriaCuration(ConfigurableResource):
    """Curation processor resource."""

    settings: ResourceDependency[AriaSettings]

    def get_processor(self) -> CurationProcessor:
        """Get curation processor."""
        return CurationProcessor(self.settings.get_settings())


class AriaEmbedding(ConfigurableResource):
    """Embedding processor resource."""

    settings: ResourceDependency[AriaSettings]

    def get_processor(self) -> EmbeddingProcessor:
        """Get embedding processor."""
        return EmbeddingProcessor(self.settings.get_settings())


class AriaTokenization(ConfigurableResource):
    """Tokenization processor resource."""

    settings: ResourceDependency[AriaSettings]

    def get_processor(self) -> TokenizationProcessor:
        """Get tokenization processor."""
        return TokenizationProcessor(self.settings.get_settings())


# Resource definitions for Dagster
aria_resources = {
    "settings": AriaSettings(),
    "s3": AriaS3(settings=AriaSettings()),
    "dynamodb": AriaDynamoDB(settings=AriaSettings()),
    "lancedb": AriaLanceDB(settings=AriaSettings()),
    "hydration": AriaHydration(settings=AriaSettings()),
    "curation": AriaCuration(settings=AriaSettings()),
    "embedding": AriaEmbedding(settings=AriaSettings()),
    "tokenization": AriaTokenization(settings=AriaSettings()),
}
