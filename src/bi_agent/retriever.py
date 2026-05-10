"""Stage 2: Schema retriever.

Given a natural-language question, returns the most relevant tables from the
database using embedding similarity. This is the schema grounding step —
it decides which tables (and their columns) the SQL agent will see.

No LLM calls here. Pure embedding retrieval.
"""

import json
import logging

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

from bi_agent.config import (
    EMBEDDING_MODEL_NAME,
    RETRIEVER_TOP_K,
    SAMPLE_ROWS_N,
    SCHEMA_INDEX_DIR,
    SCHEMA_METADATA_PATH,
)
from bi_agent.db import Database
from bi_agent.types import RelevantColumn, RelevantSchema, RelevantTable

logger = logging.getLogger(__name__)


class SchemaRetriever:
    """Retrieves relevant tables for a question using embedding similarity.

    Loads a pre-built embedding index (from build_schema_index.py) and the
    schema metadata YAML. At query time, embeds the question and returns the
    top-k most similar tables with their full column metadata and sample rows.

    Args:
        db: Database instance for fetching sample rows and column types.
        top_k: Number of tables to return. Defaults to config.RETRIEVER_TOP_K.

    Raises:
        FileNotFoundError: If the embedding index or metadata file is missing.
    """

    def __init__(self, db: Database, top_k: int = RETRIEVER_TOP_K) -> None:
        self._db = db
        self._top_k = top_k

        # Load pre-built index
        embeddings_path = SCHEMA_INDEX_DIR / "embeddings.npy"
        names_path = SCHEMA_INDEX_DIR / "table_names.json"
        if not embeddings_path.exists() or not names_path.exists():
            raise FileNotFoundError(
                f"Schema index not found in {SCHEMA_INDEX_DIR}. "
                "Run: python scripts/build_schema_index.py"
            )

        self._embeddings = np.load(embeddings_path)
        with open(names_path) as f:
            self._table_names: list[str] = json.load(f)

        # Load metadata for descriptions
        with open(SCHEMA_METADATA_PATH) as f:
            self._metadata: dict = yaml.safe_load(f)["tables"]

        # Load embedding model (same one used to build the index)
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
        self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    def retrieve(self, question: str, top_k: int | None = None) -> RelevantSchema:
        """Retrieve the most relevant tables for a natural-language question.

        Args:
            question: The user's business question.
            top_k: Override the default number of tables to return.

        Returns:
            RelevantSchema with the top-k tables ordered by similarity score.
        """
        k = top_k if top_k is not None else self._top_k

        # Embed the question
        q_embedding = self._model.encode(
            question, normalize_embeddings=True, show_progress_bar=False
        )

        # Cosine similarity (embeddings are already L2-normalized)
        scores = self._embeddings @ q_embedding
        top_indices = np.argsort(scores)[::-1][:k]

        tables = []
        for idx in top_indices:
            table_name = self._table_names[idx]
            score = float(scores[idx])
            tables.append(self._build_relevant_table(table_name, score))
            logger.info("  Retrieved '%s' (score=%.3f)", table_name, score)

        return RelevantSchema(tables=tables, question=question)

    def _build_relevant_table(self, table_name: str, score: float) -> RelevantTable:
        """Build a RelevantTable from metadata and live DB data.

        Args:
            table_name: Name of the table.
            score: Cosine similarity score.

        Returns:
            RelevantTable with columns, descriptions, and sample rows.
        """
        table_meta = self._metadata[table_name]
        schema = self._db.describe_table(table_name)
        sample_rows = self._db.sample_rows(table_name, SAMPLE_ROWS_N)

        # Build column list: merge DB types with YAML descriptions
        columns = []
        for col in schema.columns:
            col_meta = table_meta["columns"].get(col.name, {})
            columns.append(
                RelevantColumn(
                    name=col.name,
                    dtype=col.dtype,
                    description=col_meta.get("description", "").strip(),
                )
            )

        return RelevantTable(
            name=table_name,
            description=table_meta["description"].strip(),
            columns=columns,
            sample_rows=sample_rows,
            similarity_score=score,
        )
