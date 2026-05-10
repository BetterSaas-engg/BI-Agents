"""Stage 3: Semantic layer (STUB).

This module defines the interface for business-term resolution — mapping
informal terms like "revenue" to their SQL definitions (e.g., SUM(price)).

In v0, this is a pass-through: the RelevantSchema goes in and comes back
unchanged. The interface exists so that a real implementation can be swapped
in during Phase 4 without changing surrounding code.
"""

import logging

from bi_agent.types import RelevantSchema

logger = logging.getLogger(__name__)


def enrich_schema(schema: RelevantSchema) -> RelevantSchema:
    """Apply semantic enrichment to retrieved schema (STUB).

    In the future, this will:
    - Resolve business terms to SQL expressions (e.g., "revenue" -> SUM(price))
    - Add computed column definitions
    - Inject domain-specific join hints

    For now, returns the input unchanged.

    Args:
        schema: The retriever's output.

    Returns:
        The same RelevantSchema, unmodified.
    """
    logger.debug("Semantic layer: stub pass-through (no enrichment)")
    return schema
