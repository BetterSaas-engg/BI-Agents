"""Pipeline orchestrator: glues Stages 1-5 in sequence.

User question
    -> 1. Parser (LLM: extract intent/entities)
    -> 2. Retriever (embeddings: select relevant tables)
    -> 3. Semantic layer (stub: pass-through)
    -> 4. SQL agent (LLM + tools: generate and execute SQL)
    -> 5. Presenter (rules + LLM: chart + explanation)
    -> Answer
"""

import logging

from bi_agent.config import DUCKDB_PATH
from bi_agent.db import DuckDBDatabase
from bi_agent.parser import parse_question
from bi_agent.presenter import present
from bi_agent.retriever import SchemaRetriever
from bi_agent.semantics import enrich_schema
from bi_agent.sql_agent import run_sql_agent
from bi_agent.types import Answer

logger = logging.getLogger(__name__)


def ask(question: str) -> Answer:
    """Run the full BI agent pipeline for a natural-language question.

    Args:
        question: The user's business question in plain English.

    Returns:
        Answer with SQL, result table, chart path, explanation, and agent trace.

    Raises:
        FileNotFoundError: If the database or schema index is missing.
    """
    # --- Setup ---
    db = DuckDBDatabase(DUCKDB_PATH)
    retriever = SchemaRetriever(db)

    # --- Stage 1: Parse ---
    logger.info("Stage 1: Parsing question")
    parsed = parse_question(question)
    logger.info("  Intent: %s, Entities: %s", parsed.intent, parsed.entities)

    # --- Stage 2: Retrieve ---
    logger.info("Stage 2: Retrieving relevant schema")
    schema = retriever.retrieve(question)
    table_names = [t.name for t in schema.tables]
    logger.info("  Retrieved tables: %s", table_names)

    # --- Stage 3: Semantic enrichment (stub) ---
    logger.info("Stage 3: Semantic enrichment (stub)")
    enriched_schema = enrich_schema(schema)

    # --- Stage 4: SQL agent ---
    logger.info("Stage 4: SQL agent")
    sql, result_df, trace = run_sql_agent(parsed, enriched_schema, db)

    if trace.error:
        logger.warning("SQL agent error: %s", trace.error)
    else:
        logger.info(
            "  SQL agent completed: %d steps, %d+%d tokens",
            trace.total_iterations,
            trace.total_input_tokens,
            trace.total_output_tokens,
        )

    # --- Stage 5: Present ---
    logger.info("Stage 5: Presenting results")
    chart_path, explanation = present(question, sql, result_df, parsed)

    return Answer(
        question=question,
        sql=sql,
        result=result_df,
        chart_path=chart_path,
        explanation=explanation,
        trace=trace,
        relevant_tables=table_names,
    )
