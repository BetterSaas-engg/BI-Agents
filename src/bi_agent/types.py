"""Pydantic models for data contracts between pipeline stages.

Phase 0: schema-description types needed by db.py.
Phase 1: retriever types (RelevantColumn, RelevantTable, RelevantSchema).
Phase 2: parser, agent, presenter types (ParsedQuestion, AgentStep, AgentTrace, Answer).
"""

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


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


# --- Phase 2: Parser types ---


class ParsedQuestion(BaseModel):
    """Output of the question parser (Stage 1).

    Attributes:
        original: The raw user question.
        intent: What the user wants (e.g., "count", "compare", "trend", "list", "rank").
        entities: Business concepts mentioned (e.g., ["orders", "state", "2017"]).
        time_range: Extracted time constraint, if any (e.g., "2017", "last 6 months").
        filters: Any explicit filter conditions (e.g., ["status = delivered"]).
    """

    original: str
    intent: str
    entities: list[str]
    time_range: str | None = None
    filters: list[str] = Field(default_factory=list)


# --- Phase 2: SQL Agent types ---


class AgentStep(BaseModel):
    """One step in the SQL agent's tool-use loop.

    Attributes:
        step_number: 1-indexed step in the loop.
        tool_name: Which tool was called (inspect_schema, sample_rows, dry_run, run_sql).
        tool_input: The arguments passed to the tool.
        tool_output: The string result returned to the agent (truncated if large).
        was_error: Whether the tool call resulted in an error.
        dry_run_preceded: For run_sql calls only — True if a successful dry_run of the
            same SQL preceded this call. None for non-run_sql tools.
    """

    step_number: int
    tool_name: str
    tool_input: dict[str, Any]
    tool_output: str
    was_error: bool = False
    dry_run_preceded: bool | None = None


class AgentTrace(BaseModel):
    """Full trace of the SQL agent's execution for debugging.

    Attributes:
        steps: Ordered list of tool calls the agent made.
        total_iterations: Number of tool calls (= len(steps)).
        total_input_tokens: Cumulative input tokens across all LLM calls.
        total_output_tokens: Cumulative output tokens across all LLM calls.
        budget_exhausted: True if the agent hit its iteration or token limit.
        final_sql: The SQL the agent settled on (None if it never produced one).
        error: Error message if the agent failed.
    """

    steps: list[AgentStep]
    total_iterations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    budget_exhausted: bool = False
    final_sql: str | None = None
    error: str | None = None


# --- Phase 2: Presenter / Answer types ---


class Answer(BaseModel):
    """Final output of the full pipeline.

    Attributes:
        question: The original user question.
        sql: The generated SQL query.
        result: The query result as a DataFrame.
        chart_path: Path to a saved chart image, if one was generated.
        explanation: Plain-English explanation of the result.
        trace: The SQL agent's execution trace.
        relevant_tables: Names of tables the retriever selected.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str
    sql: str
    result: pd.DataFrame
    chart_path: str | None = None
    explanation: str = ""
    trace: AgentTrace
    relevant_tables: list[str]
