"""SQL backend abstraction.

This is the ONLY module that knows DuckDB exists. Everything else uses the
Database protocol. This is the seam for swapping to BigQuery in Phase 5.
"""

import logging
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from bi_agent.types import ColumnInfo, TableSchema

logger = logging.getLogger(__name__)


class Database(Protocol):
    """Abstract interface for a SQL backend.

    All pipeline stages depend on this protocol, never on a concrete implementation.
    """

    def list_tables(self) -> list[str]:
        """Return the names of all user tables in the database.

        Returns:
            Sorted list of table names.
        """
        ...

    def describe_table(self, table: str) -> TableSchema:
        """Return schema metadata for a single table.

        Args:
            table: Name of the table to describe.

        Returns:
            TableSchema with column info and row count.

        Raises:
            ValueError: If the table does not exist.
        """
        ...

    def sample_rows(self, table: str, n: int = 5) -> pd.DataFrame:
        """Return a sample of rows from a table.

        Args:
            table: Name of the table to sample from.
            n: Number of rows to return.

        Returns:
            DataFrame with up to n rows.

        Raises:
            ValueError: If the table does not exist.
        """
        ...

    def dry_run(self, sql: str) -> str:
        """Validate SQL without executing it. Returns the query plan.

        Args:
            sql: The SQL statement to validate.

        Returns:
            The EXPLAIN output as a string.

        Raises:
            duckdb.Error: If the SQL is invalid (syntax error, unknown table/column, etc.).
        """
        ...

    def run(self, sql: str) -> pd.DataFrame:
        """Execute a read-only SQL query and return the result as a DataFrame.

        Args:
            sql: The SQL statement to execute. Must be a SELECT query.

        Returns:
            Query results as a pandas DataFrame.

        Raises:
            duckdb.Error: If the SQL is invalid or execution fails.
            ValueError: If the SQL is not a SELECT statement.
        """
        ...


class DuckDBDatabase:
    """DuckDB implementation of the Database protocol."""

    def __init__(self, db_path: str | Path) -> None:
        """Open a connection to a DuckDB database file.

        Args:
            db_path: Path to the .duckdb file. Must exist.

        Raises:
            FileNotFoundError: If the database file does not exist.
        """
        self._path = Path(db_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Database file not found: {self._path}")
        self._conn = duckdb.connect(str(self._path), read_only=True)
        logger.info("Connected to DuckDB at %s", self._path)

    def list_tables(self) -> list[str]:
        """Return the names of all user tables in the database."""
        result = self._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' "
            "ORDER BY table_name"
        ).fetchall()
        return [row[0] for row in result]

    def describe_table(self, table: str) -> TableSchema:
        """Return schema metadata for a single table."""
        tables = self.list_tables()
        if table not in tables:
            raise ValueError(f"Table '{table}' not found. Available: {tables}")

        columns_raw = self._conn.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position",
            [table],
        ).fetchall()

        columns = [
            ColumnInfo(name=name, dtype=dtype, nullable=(nullable == "YES"))
            for name, dtype, nullable in columns_raw
        ]

        row_count = self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        return TableSchema(name=table, columns=columns, row_count=row_count)

    def sample_rows(self, table: str, n: int = 5) -> pd.DataFrame:
        """Return a sample of rows from a table."""
        tables = self.list_tables()
        if table not in tables:
            raise ValueError(f"Table '{table}' not found. Available: {tables}")

        return self._conn.execute(f'SELECT * FROM "{table}" LIMIT ?', [n]).fetchdf()

    def dry_run(self, sql: str) -> str:
        """Validate SQL via EXPLAIN without executing it."""
        result = self._conn.execute(f"EXPLAIN {sql}").fetchall()
        return "\n".join(str(row) for row in result)

    def run(self, sql: str) -> pd.DataFrame:
        """Execute a read-only SQL query and return results as a DataFrame."""
        stripped = sql.strip().rstrip(";").strip()
        if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
            raise ValueError("Only SELECT (and WITH ... SELECT) queries are allowed.")

        return self._conn.execute(sql).fetchdf()
