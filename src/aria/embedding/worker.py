"""Embedding worker - Vector generation and LanceDB storage.

Consumes from: Embedding Input Queue
Produces to: Tokenization Input Queue
"""

import json
import os
from typing import Any

from aria.worker.base import BaseWorker, WorkerConfig


class EmbeddingWorker(BaseWorker):
    """Worker that generates embeddings and stores in LanceDB."""

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__(config)
        self.output_bucket = os.environ.get("OUTPUT_BUCKET")
        self.lancedb_bucket = os.environ.get("LANCEDB_BUCKET")
        self.model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.chunk_size = int(os.environ.get("CHUNK_SIZE", "512"))
        self.chunk_overlap = int(os.environ.get("CHUNK_OVERLAP", "50"))
        self.embedder = None
        self.chunker = None
        self.vector_store = None

    def initialize(self) -> None:
        """Initialize embedding components."""
        self.logger.info("Initializing embedding components...")

        from aria.embedding.chunker import TextChunker
        from aria.embedding.embedder import TextEmbedder
        from aria.storage.lancedb import LanceDBStore

        self.embedder = TextEmbedder(model_name=self.model_name)
        self.chunker = TextChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self.vector_store = LanceDBStore(
            bucket=self.lancedb_bucket,
            region=self.config.aws_region,
        )

        self.logger.info("Embedding components initialized")

    def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process curated files and generate embeddings."""
        files = message.get("files", [])
        if not files:
            self.logger.warning("No files in message")
            return None

        embedded_files = []
        for file_info in files:
            # Only process high and medium quality files
            if file_info.get("quality_tier") not in ("high", "medium"):
                self.logger.info(f"Skipping {file_info['file_id']} (tier: {file_info.get('quality_tier')})")
                continue

            result = self._embed_file(file_info)
            if result:
                embedded_files.append(result)

        if not embedded_files:
            return None

        return {
            "source": "embedding",
            "files": embedded_files,
        }

    def _embed_file(self, file_info: dict[str, Any]) -> dict[str, Any] | None:
        """Generate embeddings for a single file."""
        file_id = file_info["file_id"]
        bucket = file_info["output_bucket"]
        key = file_info["output_key"]

        self.logger.info(f"Embedding {file_id}")

        # Download curated file
        response = self.s3.get_object(Bucket=bucket, Key=key)
        curated = json.loads(response["Body"].read())
        text = curated.get("text", "")

        if not text.strip():
            self.logger.warning(f"Empty text for {file_id}")
            return None

        # Chunk text
        chunks = self.chunker.chunk(text)
        self.logger.info(f"Created {len(chunks)} chunks for {file_id}")

        if not chunks:
            return None

        # Generate embeddings
        embeddings = self.embedder.embed_batch([c["text"] for c in chunks])
        self.logger.info(f"Generated {len(embeddings)} embeddings for {file_id}")

        # Prepare records for vector store
        records = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            records.append({
                "id": f"{file_id}_chunk_{i}",
                "file_id": file_id,
                "chunk_index": i,
                "text": chunk["text"],
                "start_char": chunk["start"],
                "end_char": chunk["end"],
                "vector": embedding.tolist(),
                "language": curated.get("language"),
                "quality_score": curated.get("quality_score"),
                "quality_tier": curated.get("quality_tier"),
            })

        # Store in LanceDB
        self.vector_store.add(records)
        self.logger.info(f"Stored {len(records)} vectors for {file_id}")

        return {
            "file_id": file_id,
            "output_bucket": bucket,
            "output_key": key,
            "chunk_count": len(chunks),
            "quality_tier": curated.get("quality_tier"),
        }

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.embedder = None
        self.chunker = None
        if self.vector_store:
            self.vector_store.close()
        self.vector_store = None


def main() -> None:
    """Entry point for the embedding worker."""
    config = WorkerConfig.from_env()
    worker = EmbeddingWorker(config)
    worker.run()


if __name__ == "__main__":
    main()
