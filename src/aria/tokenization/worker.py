"""Tokenization worker - Tokenizes text and creates shards for LLM training.

Consumes from: Tokenization Input Queue
Produces to: S3 shards (final output)
"""

import json
import os
from typing import Any

from aria.worker.base import BaseWorker, WorkerConfig


class TokenizationWorker(BaseWorker):
    """Worker that tokenizes text and creates training shards."""

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__(config)
        self.output_bucket = os.environ.get("OUTPUT_BUCKET")
        self.tokenizer_model = os.environ.get("TOKENIZER_MODEL", "cl100k_base")
        self.shard_size = int(os.environ.get("SHARD_SIZE_TOKENS", "100000000"))
        self.tokenizer = None
        self.sharder = None

    def initialize(self) -> None:
        """Initialize tokenization components."""
        self.logger.info("Initializing tokenization components...")

        from aria.tokenization.sharder import Sharder
        from aria.tokenization.tokenizer import Tokenizer

        self.tokenizer = Tokenizer(model=self.tokenizer_model)
        self.sharder = Sharder(
            output_bucket=self.output_bucket,
            shard_size_tokens=self.shard_size,
            s3_client=self.s3,
        )

        self.logger.info("Tokenization components initialized")

    def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process embedded files and add to shards."""
        files = message.get("files", [])
        if not files:
            self.logger.warning("No files in message")
            return None

        for file_info in files:
            # Only process high quality files for training
            if file_info.get("quality_tier") != "high":
                self.logger.info(f"Skipping {file_info['file_id']} (tier: {file_info.get('quality_tier')})")
                continue

            self._tokenize_file(file_info)

        # No output queue - this is the final stage
        return None

    def _tokenize_file(self, file_info: dict[str, Any]) -> None:
        """Tokenize a single file and add to shard buffer."""
        file_id = file_info["file_id"]
        bucket = file_info["output_bucket"]
        key = file_info["output_key"]

        self.logger.info(f"Tokenizing {file_id}")

        # Download curated file
        response = self.s3.get_object(Bucket=bucket, Key=key)
        curated = json.loads(response["Body"].read())
        text = curated.get("text", "")

        if not text.strip():
            self.logger.warning(f"Empty text for {file_id}")
            return

        # Tokenize
        tokens = self.tokenizer.encode(text)
        token_count = len(tokens)
        self.logger.info(f"Tokenized {file_id}: {token_count} tokens")

        # Add to sharder
        self.sharder.add(
            file_id=file_id,
            tokens=tokens,
            metadata={
                "language": curated.get("language"),
                "quality_score": curated.get("quality_score"),
                "source_key": key,
            },
        )

    def cleanup(self) -> None:
        """Cleanup resources and finalize any pending shards."""
        self.logger.info("Finalizing pending shards...")
        if self.sharder:
            self.sharder.finalize()
        self.tokenizer = None
        self.sharder = None


def main() -> None:
    """Entry point for the tokenization worker."""
    config = WorkerConfig.from_env()
    worker = TokenizationWorker(config)
    worker.run()


if __name__ == "__main__":
    main()
