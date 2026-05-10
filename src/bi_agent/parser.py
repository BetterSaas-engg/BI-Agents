"""Stage 1: Question parser.

Takes a natural-language business question and extracts structured metadata
(intent, entities, time range, filters) via a cheap LLM call. This metadata
enriches the retriever and helps the SQL agent understand what's being asked.
"""

import json
import logging

from bi_agent.llm import complete
from bi_agent.types import ParsedQuestion

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a question parser for a BI system backed by an e-commerce database \
(the Olist Brazilian E-Commerce dataset).

Given a natural-language business question, extract:
1. **intent**: The type of analysis requested. One of: count, sum, average, \
compare, trend, rank, list, distribution, ratio, other.
2. **entities**: Business concepts mentioned (e.g., "orders", "customers", \
"revenue", "product category", "state", "seller"). Include time references \
as entities too.
3. **time_range**: Any time constraint (e.g., "2017", "Q3 2018", \
"last 6 months", "between 2017 and 2018"). null if none mentioned.
4. **filters**: Any explicit filter conditions the user stated \
(e.g., "only delivered orders", "in São Paulo", "credit card payments"). \
Empty list if none.

Respond with ONLY a JSON object, no markdown fencing:
{"intent": "...", "entities": [...], "time_range": "..." or null, "filters": [...]}
"""


def parse_question(question: str) -> ParsedQuestion:
    """Parse a natural-language question into structured metadata.

    Args:
        question: The user's raw business question.

    Returns:
        ParsedQuestion with extracted intent, entities, time_range, filters.

    Raises:
        ValueError: If the LLM response cannot be parsed as valid JSON.
    """
    logger.info("Parsing question: %s", question)

    raw = complete(prompt=question, system=_SYSTEM_PROMPT, temperature=0.0)

    # Strip markdown fencing if the model adds it despite instructions
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {raw!r}") from e

    return ParsedQuestion(
        original=question,
        intent=data.get("intent", "other"),
        entities=data.get("entities", []),
        time_range=data.get("time_range"),
        filters=data.get("filters", []),
    )
