"""Dagster assets for Aria pipeline."""

from dagster import AssetExecutionContext, asset

from aria.common import AudioFile
from aria.orchestration.resources import (
    AriaCuration,
    AriaEmbedding,
    AriaHydration,
    AriaS3,
    AriaSettings,
    AriaTokenization,
)


@asset(
    description="Raw audio files from S3",
    compute_kind="s3",
    group_name="collection",
)
def raw_audio_files(
    context: AssetExecutionContext,
    settings: AriaSettings,
    s3: AriaS3,
) -> list[AudioFile]:
    """
    Discover raw audio files in S3 bucket.

    This asset scans the raw audio bucket and returns a list of
    audio files to be processed.
    """
    app_settings = settings.get_settings()
    s3_client = s3.get_client()

    files = list(
        s3_client.list_files(
            bucket=app_settings.s3.raw_bucket,
            suffix=".mp3",
            max_keys=1000,  # Process in batches
        )
    )

    context.log.info(f"Found {len(files)} audio files")
    return files


@asset(
    description="Transcribed audio documents",
    compute_kind="gpu",
    group_name="hydration",
    deps=["raw_audio_files"],
)
def hydrated_documents(
    context: AssetExecutionContext,
    raw_audio_files: list[AudioFile],
    hydration: AriaHydration,
) -> list[str]:
    """
    Transcribe audio files using Whisper.

    Processes each audio file through the hydration pipeline,
    generating transcripts with metadata.
    """
    processor = hydration.get_processor()
    output_locations: list[str] = []

    for audio_file in raw_audio_files:
        context.log.info(f"Processing {audio_file.file_id}")

        result = processor.process_file(audio_file)

        if result.success and result.output_location:
            output_locations.append(result.output_location)
        else:
            context.log.warning(f"Failed to process {audio_file.file_id}: {result.error_message}")

    context.log.info(f"Hydrated {len(output_locations)} documents")
    return output_locations


@asset(
    description="Quality-filtered and deduplicated documents",
    compute_kind="cpu",
    group_name="curation",
)
def curated_documents(
    context: AssetExecutionContext,
    hydrated_documents: list[str],
    curation: AriaCuration,
) -> list[str]:
    """
    Curate transcribed documents.

    Applies quality scoring, deduplication, and PII filtering
    to hydrated documents.
    """
    processor = curation.get_processor()
    output_locations: list[str] = []

    for hydrated_location in hydrated_documents:
        # Extract file_id from location
        file_id = hydrated_location.split("/")[-1].replace(".json", "")

        context.log.info(f"Curating {file_id}")
        result = processor.process_document(file_id, hydrated_location)

        if result.success and result.output_location:
            output_locations.append(result.output_location)
        elif result.error_message and result.error_message.startswith("rejected:"):
            context.log.info(f"Rejected {file_id}: {result.error_message}")
        else:
            context.log.warning(f"Failed to curate {file_id}: {result.error_message}")

    context.log.info(f"Curated {len(output_locations)} documents")
    return output_locations


@asset(
    description="Vector embeddings stored in LanceDB",
    compute_kind="cpu",
    group_name="embedding",
)
def embedded_documents(
    context: AssetExecutionContext,
    curated_documents: list[str],
    embedding: AriaEmbedding,
) -> int:
    """
    Generate embeddings and store in LanceDB.

    Chunks curated documents and generates vector embeddings
    for similarity search.
    """
    processor = embedding.get_processor()
    success_count = 0

    for curated_location in curated_documents:
        # Extract file_id from location
        parts = curated_location.split("/")
        file_id = parts[-1].replace(".json", "")

        context.log.info(f"Embedding {file_id}")
        result = processor.process_document(file_id, curated_location)

        if result.success:
            success_count += 1
        else:
            context.log.warning(f"Failed to embed {file_id}: {result.error_message}")

    context.log.info(f"Embedded {success_count} documents")
    return success_count


@asset(
    description="Tokenized data shards for LLM training",
    compute_kind="cpu",
    group_name="tokenization",
)
def tokenized_shards(
    context: AssetExecutionContext,
    curated_documents: list[str],
    tokenization: AriaTokenization,
) -> dict:
    """
    Create tokenized shards for LLM training.

    Tokenizes curated documents and packages them into
    fixed-size shards ready for training.
    """
    processor = tokenization.get_processor()

    context.log.info("Creating training shards...")
    summary = processor.create_training_shards(curated_prefix="curated/high/")

    context.log.info(f"Created {summary['total_shards']} shards with {summary['total_tokens']} tokens")
    return summary
