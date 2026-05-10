"""Smoke tests for db.py — one test per Database method.

These run against the real DuckDB file (data/olist.duckdb).
The database must exist before running tests: `python scripts/load_olist.py`
"""

import pytest

from bi_agent.config import DUCKDB_PATH
from bi_agent.db import DuckDBDatabase
from bi_agent.types import TableSchema


@pytest.fixture(scope="module")
def db() -> DuckDBDatabase:
    """Provide a shared DuckDBDatabase instance for all tests."""
    if not DUCKDB_PATH.exists():
        pytest.skip(f"Database not found at {DUCKDB_PATH}. Run scripts/load_olist.py first.")
    return DuckDBDatabase(DUCKDB_PATH)


def test_list_tables(db: DuckDBDatabase) -> None:
    """list_tables returns all 9 Olist tables."""
    tables = db.list_tables()
    assert isinstance(tables, list)
    assert len(tables) == 9
    assert "orders" in tables
    assert "customers" in tables
    assert "order_items" in tables


def test_describe_table(db: DuckDBDatabase) -> None:
    """describe_table returns a TableSchema with correct structure."""
    schema = db.describe_table("orders")
    assert isinstance(schema, TableSchema)
    assert schema.name == "orders"
    assert schema.row_count > 0

    col_names = [c.name for c in schema.columns]
    assert "order_id" in col_names
    assert "customer_id" in col_names
    assert "order_purchase_timestamp" in col_names


def test_describe_table_missing(db: DuckDBDatabase) -> None:
    """describe_table raises ValueError for a nonexistent table."""
    with pytest.raises(ValueError, match="not found"):
        db.describe_table("nonexistent_table")


def test_sample_rows(db: DuckDBDatabase) -> None:
    """sample_rows returns a DataFrame with the requested number of rows."""
    df = db.sample_rows("orders", n=3)
    assert len(df) == 3
    assert "order_id" in df.columns


def test_sample_rows_missing(db: DuckDBDatabase) -> None:
    """sample_rows raises ValueError for a nonexistent table."""
    with pytest.raises(ValueError, match="not found"):
        db.sample_rows("nonexistent_table")


def test_dry_run_valid(db: DuckDBDatabase) -> None:
    """dry_run returns a plan string for valid SQL."""
    plan = db.dry_run("SELECT COUNT(*) FROM orders")
    assert isinstance(plan, str)
    assert len(plan) > 0


def test_dry_run_invalid(db: DuckDBDatabase) -> None:
    """dry_run raises an error for invalid SQL."""
    with pytest.raises(Exception):
        db.dry_run("SELECT * FROM nonexistent_table_xyz")


def test_run_select(db: DuckDBDatabase) -> None:
    """run executes a SELECT and returns a DataFrame."""
    df = db.run("SELECT COUNT(*) AS cnt FROM orders")
    assert len(df) == 1
    assert df["cnt"].iloc[0] > 0


def test_run_with_cte(db: DuckDBDatabase) -> None:
    """run supports WITH (CTE) queries."""
    df = db.run("WITH o AS (SELECT * FROM orders LIMIT 5) SELECT COUNT(*) AS cnt FROM o")
    assert df["cnt"].iloc[0] == 5


def test_run_rejects_non_select(db: DuckDBDatabase) -> None:
    """run raises ValueError for non-SELECT statements."""
    with pytest.raises(ValueError, match="SELECT"):
        db.run("DROP TABLE orders")
