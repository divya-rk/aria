"""Dagster jobs for Aria pipeline."""

from dagster import AssetSelection, define_asset_job

# Full pipeline job - processes everything
full_pipeline_job = define_asset_job(
    name="full_pipeline",
    description="Run the complete Aria pipeline from raw audio to training shards",
    selection=AssetSelection.all(),
)

# Hydration only job
hydration_job = define_asset_job(
    name="hydration_only",
    description="Run only the hydration (transcription) stage",
    selection=AssetSelection.assets("raw_audio_files", "hydrated_documents"),
)

# Curation and embedding job
curation_embedding_job = define_asset_job(
    name="curation_and_embedding",
    description="Run curation and embedding stages",
    selection=AssetSelection.assets("curated_documents", "embedded_documents"),
)

# Training data preparation job
training_data_job = define_asset_job(
    name="training_data",
    description="Create tokenized training shards",
    selection=AssetSelection.assets("tokenized_shards"),
)
