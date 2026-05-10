"""One-shot script: build an embedding index from schema metadata.

Usage:
    python scripts/build_schema_index.py

Reads data/schema_metadata.yaml, embeds each table's description + column
descriptions into a single vector using sentence-transformers, and saves:
  - data/schema_index/embeddings.npy   (N x D float32 array)
  - data/schema_index/table_names.json (list of N table names, same order)

The retriever loads these at query time.
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

# Add project root to path so we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bi_agent.config import EMBEDDING_MODEL_NAME, SCHEMA_INDEX_DIR, SCHEMA_METADATA_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def table_to_text(table_name: str, table_meta: dict) -> str:
    """Convert a table's metadata into a single text chunk for embedding.

    Format:
        Table: orders. Each row is one customer order...
        Columns: order_id (unique order identifier), customer_id (foreign key to customers), ...

    Args:
        table_name: The clean table name.
        table_meta: Dict with 'description' and 'columns' from the YAML.

    Returns:
        A single string combining the table and column descriptions.
    """
    parts = [f"Table: {table_name}. {table_meta['description'].strip()}"]

    col_parts = []
    for col_name, col_meta in table_meta["columns"].items():
        col_parts.append(f"{col_name} ({col_meta['description'].strip()})")

    parts.append("Columns: " + ", ".join(col_parts))
    return "\n".join(parts)


def build_index() -> None:
    """Build the schema embedding index from the metadata YAML.

    Raises:
        FileNotFoundError: If schema_metadata.yaml is missing.
    """
    if not SCHEMA_METADATA_PATH.exists():
        raise FileNotFoundError(
            f"Schema metadata not found: {SCHEMA_METADATA_PATH}\n"
            "Create data/schema_metadata.yaml first."
        )

    with open(SCHEMA_METADATA_PATH) as f:
        metadata = yaml.safe_load(f)

    tables = metadata["tables"]
    table_names = list(tables.keys())
    texts = [table_to_text(name, tables[name]) for name in table_names]

    logger.info("Embedding %d tables with %s ...", len(texts), EMBEDDING_MODEL_NAME)
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    embeddings = np.array(embeddings, dtype=np.float32)

    SCHEMA_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(SCHEMA_INDEX_DIR / "embeddings.npy", embeddings)
    with open(SCHEMA_INDEX_DIR / "table_names.json", "w") as f:
        json.dump(table_names, f)

    logger.info(
        "Saved index to %s: %d tables, %d dimensions",
        SCHEMA_INDEX_DIR,
        len(table_names),
        embeddings.shape[1],
    )

    # Print the texts that were embedded for verification
    for name, text in zip(table_names, texts, strict=True):
        preview = text[:120].replace("\n", " ")
        logger.info("  %s: %s...", name, preview)


if __name__ == "__main__":
    build_index()
