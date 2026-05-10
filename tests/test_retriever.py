"""Retrieval quality tests for SchemaRetriever.

Each test case asserts which tables MUST and MUST NOT appear in the top-k
results for a given question. These are not unit tests — they hit the real
embedding index and database. Run after build_schema_index.py.

The retriever uses top_k=4 by default. Tests use must_include / must_exclude
assertions rather than exact-set matching, because borderline tables (e.g.,
sellers appearing for a customer-focused question) are acceptable as long as
the critical tables are present.
"""

import pytest

from bi_agent.config import DUCKDB_PATH, SCHEMA_INDEX_DIR
from bi_agent.db import DuckDBDatabase
from bi_agent.retriever import SchemaRetriever


@pytest.fixture(scope="module")
def retriever():
    """Shared retriever instance for all tests (loads model once)."""
    if not DUCKDB_PATH.exists():
        pytest.skip("Database not found — run load_olist.py first")
    if not (SCHEMA_INDEX_DIR / "embeddings.npy").exists():
        pytest.skip("Schema index not found — run build_schema_index.py first")

    db = DuckDBDatabase(DUCKDB_PATH)
    return SchemaRetriever(db)


def retrieved_names(retriever: SchemaRetriever, question: str, top_k: int = 4) -> set[str]:
    """Helper: return the set of table names retrieved for a question."""
    result = retriever.retrieve(question, top_k=top_k)
    return {t.name for t in result.tables}


# --- Test cases ---


def test_orders_by_state(retriever):
    """Phase 1 definition-of-done question."""
    tables = retrieved_names(retriever, "How many orders were placed in 2017 by state?")
    assert "orders" in tables
    assert "customers" in tables
    assert "products" not in tables
    assert "order_reviews" not in tables


def test_revenue_by_category(retriever):
    """Revenue question should retrieve order_items + products + category_translation."""
    tables = retrieved_names(retriever, "What is the total revenue by product category?")
    assert "order_items" in tables
    assert "products" in tables


def test_average_review_score(retriever):
    """Review question should retrieve order_reviews."""
    tables = retrieved_names(retriever, "What is the average review score per seller?")
    assert "order_reviews" in tables


def test_payment_methods(retriever):
    """Payment question should retrieve order_payments."""
    tables = retrieved_names(retriever, "What payment methods do customers use most?")
    assert "order_payments" in tables


def test_delivery_time(retriever):
    """Delivery time question needs orders (has delivery timestamps)."""
    tables = retrieved_names(retriever, "What is the average delivery time in days?")
    assert "orders" in tables


def test_top_sellers(retriever):
    """Seller performance question should retrieve sellers and order_items."""
    tables = retrieved_names(retriever, "Who are the top 10 sellers by number of items sold?")
    assert "order_items" in tables
    assert "sellers" in tables


def test_product_categories_english(retriever):
    """Category translation should appear for English category questions."""
    tables = retrieved_names(retriever, "List all product categories in English")
    assert "category_translation" in tables


def test_customer_geography(retriever):
    """Geography question should retrieve customers or geolocation."""
    tables = retrieved_names(retriever, "Which cities have the most customers?")
    assert "customers" in tables


def test_freight_cost(retriever):
    """Freight/shipping cost question should retrieve order_items."""
    tables = retrieved_names(retriever, "What is the average freight cost per order?")
    assert "order_items" in tables


def test_installment_payments(retriever):
    """Installment question should retrieve order_payments."""
    tables = retrieved_names(
        retriever, "How many customers pay in more than 6 installments?"
    )
    assert "order_payments" in tables


def test_retrieved_tables_have_columns(retriever):
    """Each retrieved table should have non-empty columns and sample rows."""
    result = retriever.retrieve("Show me order trends over time")
    for table in result.tables:
        assert len(table.columns) > 0, f"{table.name} has no columns"
        assert len(table.sample_rows) > 0, f"{table.name} has no sample rows"
        assert table.description, f"{table.name} has no description"
        # Every column should have a description from the YAML
        for col in table.columns:
            assert col.description, f"{table.name}.{col.name} has no description"


def test_similarity_scores_ordered(retriever):
    """Tables should be returned in descending similarity order."""
    result = retriever.retrieve("What are the most popular product categories?")
    scores = [t.similarity_score for t in result.tables]
    assert scores == sorted(scores, reverse=True)
