"""Stage 4: SQL agent.

The only agentic component in the pipeline. Uses tool-calling to iteratively
inspect schema, sample data, write SQL, validate via dry_run, and execute.

Tools available to the agent:
  - inspect_schema(table): column names, types, descriptions
  - sample_rows(table, n): example rows from a table
  - dry_run(sql): EXPLAIN-based validation without execution
  - run_sql(sql): execute and return results (should follow a successful dry_run)

The agent loop has an explicit budget (max iterations, max tokens).
"""

import logging
from typing import Any

import pandas as pd
import yaml

from bi_agent.config import SCHEMA_METADATA_PATH
from bi_agent.db import Database
from bi_agent.llm import create_tool_use_message
from bi_agent.types import AgentStep, AgentTrace, ParsedQuestion, RelevantSchema

logger = logging.getLogger(__name__)

# --- Budget defaults (from SPEC.md Section 7) ---
MAX_ITERATIONS = 6
MAX_TOTAL_TOKENS = 40_000

# --- Tool definitions in Anthropic SDK format ---
TOOLS = [
    {
        "name": "inspect_schema",
        "description": (
            "Returns the full schema for a table: column names, types, and "
            "human-written descriptions of what each column means. Use this "
            "to understand table structure before writing SQL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Name of the table to inspect.",
                }
            },
            "required": ["table"],
        },
    },
    {
        "name": "sample_rows",
        "description": (
            "Returns a few example rows from a table. Use this to see real "
            "data values — date formats, category strings, numeric ranges — "
            "before writing SQL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Name of the table to sample.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of rows to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["table"],
        },
    },
    {
        "name": "dry_run",
        "description": (
            "Validates a SQL query without executing it. Returns the query plan "
            "if valid, or an error message if invalid (syntax error, unknown "
            "table/column, type mismatch). Always dry_run your SQL before "
            "calling run_sql."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to validate.",
                }
            },
            "required": ["sql"],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Executes a SQL query and returns the result rows. Only call this "
            "after a successful dry_run of the same query. Only SELECT/WITH "
            "queries are allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute.",
                }
            },
            "required": ["sql"],
        },
    },
]


def _build_system_prompt(
    parsed: ParsedQuestion,
    schema: RelevantSchema,
) -> str:
    """Build the system prompt for the SQL agent.

    Includes the relevant schema context and the parsed question metadata.

    Args:
        parsed: Structured question metadata from the parser.
        schema: Retrieved tables with columns and descriptions.

    Returns:
        The system prompt string.
    """
    # Build schema context block
    schema_lines = []
    for table in schema.tables:
        schema_lines.append(f"\n### Table: {table.name}")
        schema_lines.append(f"Description: {table.description}")
        schema_lines.append("Columns:")
        for col in table.columns:
            schema_lines.append(f"  - {col.name} ({col.dtype}): {col.description}")
        # Show sample rows as a compact table
        sample_str = table.sample_rows.head(3).to_string(index=False)
        schema_lines.append(f"Sample rows:\n{sample_str}")

    schema_block = "\n".join(schema_lines)

    return f"""\
You are a SQL agent for a DuckDB database containing the Olist Brazilian \
E-Commerce dataset. Your job is to write a correct SQL query that answers \
the user's business question.

## Available schema
{schema_block}

## Parsed question metadata
- Intent: {parsed.intent}
- Entities: {", ".join(parsed.entities)}
- Time range: {parsed.time_range or "none"}
- Filters: {", ".join(parsed.filters) if parsed.filters else "none"}

## Instructions
1. The schema above already contains table descriptions, column types, and \
sample rows. You can write SQL directly from this context. Use inspect_schema \
or sample_rows only if you need additional detail not shown above.
2. ALWAYS call dry_run to validate your SQL before calling run_sql.
3. If dry_run fails, read the error, fix the SQL, and try again.
4. Use DuckDB SQL syntax.
5. Keep queries simple and readable. Use CTEs over subqueries when it helps.
6. When the question mentions "revenue" or "sales", use SUM(price) from \
order_items (price is item price in BRL, freight_value is shipping cost).
7. When joining orders to location data, join through customers \
(orders.customer_id -> customers.customer_id -> customers.customer_state).
8. Product categories are in Portuguese in the products table. Join to \
category_translation for English names.
9. Return reasonable result sizes — use LIMIT if the result could be large.
10. After a successful run_sql, stop. Do not call more tools.
"""


def _execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    db: Database,
    metadata: dict,
) -> tuple[str, bool]:
    """Execute a single tool call and return (output_string, was_error).

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Arguments for the tool.
        db: Database instance.
        metadata: Schema metadata dict (from YAML).

    Returns:
        Tuple of (result string, was_error boolean).
    """
    try:
        if tool_name == "inspect_schema":
            table = tool_input["table"]
            if table not in metadata:
                avail = list(metadata.keys())
                return f"Error: table '{table}' not found. Available: {avail}", True
            table_meta = metadata[table]
            lines = [f"Table: {table}", f"Description: {table_meta['description']}"]
            lines.append("Columns:")
            for col_name, col_info in table_meta["columns"].items():
                lines.append(f"  - {col_name}: {col_info['description']}")
                if col_info.get("examples"):
                    lines.append(f"    Examples: {col_info['examples']}")
            return "\n".join(lines), False

        elif tool_name == "sample_rows":
            table = tool_input["table"]
            n = tool_input.get("n", 5)
            df = db.sample_rows(table, n)
            return df.to_string(index=False), False

        elif tool_name == "dry_run":
            sql = tool_input["sql"]
            plan = db.dry_run(sql)
            return f"Query is valid. Plan:\n{plan}", False

        elif tool_name == "run_sql":
            sql = tool_input["sql"]
            df = db.run(sql)
            # Truncate large results for the agent's context
            if len(df) > 50:
                result_str = df.head(50).to_string(index=False)
                result_str += f"\n... ({len(df)} total rows, showing first 50)"
            else:
                result_str = df.to_string(index=False)
            return result_str, False

        else:
            return f"Error: unknown tool '{tool_name}'", True

    except Exception as e:
        return f"Error: {e}", True


def _normalize_sql(sql: str) -> str:
    """Normalize SQL for comparison (strip whitespace and trailing semicolons)."""
    return sql.strip().rstrip(";").strip()


def run_sql_agent(
    parsed: ParsedQuestion,
    schema: RelevantSchema,
    db: Database,
    *,
    max_iterations: int = MAX_ITERATIONS,
    max_total_tokens: int = MAX_TOTAL_TOKENS,
) -> tuple[str, pd.DataFrame, AgentTrace]:
    """Run the SQL agent loop to generate and execute a query.

    Args:
        parsed: Parsed question from Stage 1.
        schema: Retrieved schema from Stage 2.
        db: Database instance for tool execution.
        max_iterations: Maximum number of tool calls before stopping.
        max_total_tokens: Maximum total tokens (input + output) before stopping.

    Returns:
        Tuple of (final_sql, result_dataframe, agent_trace).
        If the agent fails, result_dataframe will be empty and trace.error set.

    Raises:
        No exceptions — errors are captured in the trace.
    """
    # Load metadata for inspect_schema tool
    with open(SCHEMA_METADATA_PATH) as f:
        metadata = yaml.safe_load(f)["tables"]

    system_prompt = _build_system_prompt(parsed, schema)
    messages: list[dict] = [
        {"role": "user", "content": parsed.original},
    ]

    steps: list[AgentStep] = []
    total_input_tokens = 0
    total_output_tokens = 0
    final_sql: str | None = None
    result_df = pd.DataFrame()
    budget_exhausted = False
    error: str | None = None

    # Track which SQL strings have been successfully dry-run'd
    dry_run_successes: set[str] = set()

    for iteration in range(max_iterations):
        # Check token budget
        if total_input_tokens + total_output_tokens >= max_total_tokens:
            budget_exhausted = True
            error = (
                f"Token budget exhausted: {total_input_tokens + total_output_tokens} "
                f">= {max_total_tokens}"
            )
            logger.warning(error)
            break

        # Call the LLM
        response = create_tool_use_message(
            messages=messages,
            tools=TOOLS,
            system=system_prompt,
            temperature=0.0,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Check for tool use blocks
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if not tool_use_blocks:
            # Agent is done thinking — extract any SQL from text
            if text_blocks:
                text = text_blocks[0].text
                # Try to find SQL in the response
                if "SELECT" in text.upper() or "WITH" in text.upper():
                    # Extract SQL from markdown code blocks if present
                    if "```sql" in text:
                        sql_start = text.index("```sql") + 6
                        sql_end = text.index("```", sql_start)
                        final_sql = text[sql_start:sql_end].strip()
                    elif "```" in text:
                        sql_start = text.index("```") + 3
                        sql_end = text.index("```", sql_start)
                        final_sql = text[sql_start:sql_end].strip()
                logger.info("Agent finished without tool call (text response)")
            # Add assistant message to history
            messages.append({"role": "assistant", "content": response.content})
            break

        # Add assistant message with tool use to history
        messages.append({"role": "assistant", "content": response.content})

        # Process each tool call
        tool_results = []
        for tool_block in tool_use_blocks:
            tool_name = tool_block.name
            tool_input = tool_block.input

            logger.info(
                "Agent step %d: %s(%s)",
                iteration + 1,
                tool_name,
                tool_input,
            )

            output, was_error = _execute_tool(tool_name, tool_input, db, metadata)

            # Track dry_run successes
            if tool_name == "dry_run" and not was_error:
                normalized = _normalize_sql(tool_input["sql"])
                dry_run_successes.add(normalized)

            # Track dry_run compliance for run_sql calls
            dry_run_preceded: bool | None = None
            if tool_name == "run_sql":
                normalized = _normalize_sql(tool_input["sql"])
                dry_run_preceded = normalized in dry_run_successes
                final_sql = tool_input["sql"]
                if not was_error:
                    # Re-execute to get the actual DataFrame for the pipeline
                    result_df = db.run(tool_input["sql"])

            step = AgentStep(
                step_number=len(steps) + 1,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=output[:2000],  # Truncate for trace readability
                was_error=was_error,
                dry_run_preceded=dry_run_preceded,
            )
            steps.append(step)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": output[:4000],  # Truncate for context window
                }
            )

            # If run_sql succeeded, we're done
            if tool_name == "run_sql" and not was_error:
                logger.info("Agent completed: run_sql succeeded")
                messages.append({"role": "user", "content": tool_results})
                # One more call to let the agent see the result (but don't require tools)
                # Actually we have the data — just stop here.
                break

        else:
            # No break from the for loop — add tool results and continue
            messages.append({"role": "user", "content": tool_results})
            continue

        # Break from the outer loop if run_sql succeeded
        break
    else:
        # for loop completed without break — budget exhausted
        if not budget_exhausted:
            budget_exhausted = True
            error = f"Iteration budget exhausted: {max_iterations} iterations"
            logger.warning(error)

    trace = AgentTrace(
        steps=steps,
        total_iterations=len(steps),
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        budget_exhausted=budget_exhausted,
        final_sql=final_sql,
        error=error,
    )

    return final_sql or "", result_df, trace
