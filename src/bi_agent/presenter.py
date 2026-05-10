"""Stage 5: Presenter.

Produces the final output: a rule-based chart (if appropriate) and an
LLM-generated plain-English explanation of the result.
"""

import logging

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from bi_agent.config import PROJECT_ROOT
from bi_agent.llm import complete
from bi_agent.types import ParsedQuestion

matplotlib.use("Agg")  # Non-interactive backend

logger = logging.getLogger(__name__)

CHARTS_DIR = PROJECT_ROOT / "data" / "charts"


def _pick_chart_type(df: pd.DataFrame, parsed: ParsedQuestion) -> str | None:
    """Decide which chart type to use based on result shape and intent.

    Rules:
        - 1 categorical + 1 numeric column, <=20 rows -> bar
        - 1 time/date column + 1 numeric column -> line
        - 1 numeric column, many rows -> histogram (not yet)
        - Otherwise -> None (no chart)

    Args:
        df: The query result.
        parsed: Parsed question metadata.

    Returns:
        Chart type string ("bar", "line") or None.
    """
    if df.empty or len(df.columns) < 2:
        return None

    # Identify column types (include "str" for pandas 3.x string dtype)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    datetime_cols = df.select_dtypes(include="datetime").columns.tolist()
    object_cols = df.select_dtypes(include=["object", "string"]).columns.tolist()

    # Also check for columns that look like years/months (integers that could be time)
    time_intents = {"trend"}

    if len(datetime_cols) >= 1 and len(numeric_cols) >= 1:
        return "line"

    if parsed.intent in time_intents and len(numeric_cols) >= 1:
        return "line"

    if len(object_cols) >= 1 and len(numeric_cols) >= 1 and len(df) <= 30:
        return "bar"

    return None


def _make_chart(
    df: pd.DataFrame,
    chart_type: str,
    question: str,
) -> str:
    """Generate and save a chart, return the file path.

    Args:
        df: The query result.
        chart_type: "bar" or "line".
        question: The original question (used for the chart title).

    Returns:
        Path to the saved chart PNG.
    """
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    datetime_cols = df.select_dtypes(include="datetime").columns.tolist()
    object_cols = df.select_dtypes(include=["object", "string"]).columns.tolist()

    fig, ax = plt.subplots(figsize=(10, 6))

    if chart_type == "line":
        x_col = datetime_cols[0] if datetime_cols else df.columns[0]
        y_col = numeric_cols[0]
        plot_df = df.sort_values(x_col)
        ax.plot(plot_df[x_col], plot_df[y_col], marker="o", linewidth=2)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        plt.xticks(rotation=45, ha="right")

    elif chart_type == "bar":
        x_col = object_cols[0] if object_cols else df.columns[0]
        y_col = numeric_cols[0]
        # Sort by value descending for readability
        plot_df = df.sort_values(y_col, ascending=True).tail(20)
        ax.barh(plot_df[x_col].astype(str), plot_df[y_col])
        ax.set_xlabel(y_col)
        ax.set_ylabel(x_col)

    # Truncate title if too long
    title = question[:80] + "..." if len(question) > 80 else question
    ax.set_title(title, fontsize=11)
    fig.tight_layout()

    chart_path = CHARTS_DIR / "latest_chart.png"
    fig.savefig(chart_path, dpi=100)
    plt.close(fig)
    logger.info("Chart saved to %s", chart_path)
    return str(chart_path)


def _generate_explanation(
    question: str,
    sql: str,
    df: pd.DataFrame,
) -> str:
    """Generate a plain-English explanation of the query result.

    Args:
        question: The original user question.
        sql: The SQL query that was executed.
        df: The result DataFrame.

    Returns:
        A plain-English explanation string.
    """
    # Truncate result for the LLM context
    if len(df) > 20:
        result_str = df.head(20).to_string(index=False)
        result_str += f"\n... ({len(df)} total rows, showing first 20)"
    else:
        result_str = df.to_string(index=False)

    prompt = f"""\
A user asked a business question about an e-commerce dataset (Olist, Brazilian marketplace).
Here is the question, the SQL query that answered it, and the result.

Question: {question}

SQL:
{sql}

Result:
{result_str}

Write a concise (2-4 sentence) plain-English explanation of the result. \
Highlight the key insight. If there are notable patterns (top/bottom values, \
trends, outliers), mention them. Use specific numbers from the result. \
Do not explain the SQL — explain what the data means for the business.
"""

    return complete(prompt=prompt, temperature=0.3)


def present(
    question: str,
    sql: str,
    df: pd.DataFrame,
    parsed: ParsedQuestion,
) -> tuple[str | None, str]:
    """Generate chart and explanation for a query result.

    Args:
        question: The original user question.
        sql: The SQL query that was executed.
        df: The result DataFrame.
        parsed: Parsed question metadata (for chart type heuristics).

    Returns:
        Tuple of (chart_path or None, explanation string).
    """
    # Chart
    chart_path = None
    chart_type = _pick_chart_type(df, parsed)
    if chart_type:
        logger.info("Generating %s chart", chart_type)
        chart_path = _make_chart(df, chart_type, question)
    else:
        logger.info("No chart generated (result shape not suitable)")

    # Explanation
    if df.empty:
        explanation = "The query returned no results."
    else:
        explanation = _generate_explanation(question, sql, df)

    return chart_path, explanation
