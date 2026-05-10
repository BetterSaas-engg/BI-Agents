"""Pydantic models for data contracts between pipeline stages.

Phase 0: schema-description types needed by db.py.
Phase 1: retriever types (RelevantColumn, RelevantTable, RelevantSchema).
"""

import pandas as pd
from pydantic import BaseModel, ConfigDict


class ColumnInfo(BaseModel):
    """Metadata for a single database column."""

    name: str
    dtype: str
    nullable: bool


class TableSchema(BaseModel):
    """Schema description for a single database table."""

    name: str
    columns: list[ColumnInfo]
    row_count: int


# --- Phase 1: Retriever types ---


class RelevantColumn(BaseModel):
    """A column selected by the retriever, enriched with its description."""

    name: str
    dtype: str
    description: str


class RelevantTable(BaseModel):
    """A table selected by the retriever with its metadata and sample data.

    Attributes:
        name: Table name in the database.
        description: Human-written description of what this table represents.
        columns: All columns in the table with types and descriptions.
        sample_rows: A small DataFrame of example rows for the SQL agent to reference.
        similarity_score: Cosine similarity between the question and the table's embedding.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    columns: list[RelevantColumn]
    sample_rows: pd.DataFrame
    similarity_score: float


class RelevantSchema(BaseModel):
    """Output of the schema retriever: the tables relevant to a user question.

    Attributes:
        tables: Ordered list of relevant tables, highest similarity first.
        question: The original question that was used for retrieval.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tables: list[RelevantTable]
    question: str
