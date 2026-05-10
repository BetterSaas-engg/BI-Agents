"""One-shot script: load Olist CSVs into a DuckDB database.

Usage:
    python scripts/load_olist.py

Expects CSV files in data/raw/ (downloaded from Kaggle).
Produces data/olist.duckdb with 9 tables using clean names.

Table naming: strips 'olist_' prefix and '_dataset' suffix from CSV filenames.
  e.g. olist_orders_dataset.csv -> orders

FK constraints are declared for documentation but not enforced by DuckDB.
"""

import logging
import sys
from pathlib import Path

import duckdb

# Add project root to path so we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bi_agent.config import DUCKDB_PATH, RAW_DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Mapping from CSV filename (without .csv) to clean table name.
# Order matters: tables with FK dependencies come after the tables they reference.
CSV_TO_TABLE = {
    "olist_customers_dataset": "customers",
    "olist_geolocation_dataset": "geolocation",
    "olist_sellers_dataset": "sellers",
    "product_category_name_translation": "category_translation",
    "olist_products_dataset": "products",
    "olist_orders_dataset": "orders",
    "olist_order_items_dataset": "order_items",
    "olist_order_payments_dataset": "order_payments",
    "olist_order_reviews_dataset": "order_reviews",
}

# DDL for tables with explicit types and FK declarations.
# DuckDB will accept FK syntax but does not enforce referential integrity.
TABLE_DDL = {
    "customers": """
        CREATE TABLE customers (
            customer_id VARCHAR PRIMARY KEY,
            customer_unique_id VARCHAR NOT NULL,
            customer_zip_code_prefix VARCHAR,
            customer_city VARCHAR,
            customer_state VARCHAR(2)
        )
    """,
    "geolocation": """
        CREATE TABLE geolocation (
            geolocation_zip_code_prefix VARCHAR,
            geolocation_lat DOUBLE,
            geolocation_lng DOUBLE,
            geolocation_city VARCHAR,
            geolocation_state VARCHAR(2)
        )
    """,
    "sellers": """
        CREATE TABLE sellers (
            seller_id VARCHAR PRIMARY KEY,
            seller_zip_code_prefix VARCHAR,
            seller_city VARCHAR,
            seller_state VARCHAR(2)
        )
    """,
    "category_translation": """
        CREATE TABLE category_translation (
            product_category_name VARCHAR PRIMARY KEY,
            product_category_name_english VARCHAR
        )
    """,
    "products": """
        CREATE TABLE products (
            product_id VARCHAR PRIMARY KEY,
            product_category_name VARCHAR,
            product_name_lenght INTEGER,
            product_description_lenght INTEGER,
            product_photos_qty INTEGER,
            product_weight_g INTEGER,
            product_length_cm INTEGER,
            product_height_cm INTEGER,
            product_width_cm INTEGER
        )
    """,
    "orders": """
        CREATE TABLE orders (
            order_id VARCHAR PRIMARY KEY,
            customer_id VARCHAR NOT NULL,
            order_status VARCHAR,
            order_purchase_timestamp TIMESTAMP,
            order_approved_at TIMESTAMP,
            order_delivered_carrier_date TIMESTAMP,
            order_delivered_customer_date TIMESTAMP,
            order_estimated_delivery_date TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """,
    "order_items": """
        CREATE TABLE order_items (
            order_id VARCHAR NOT NULL,
            order_item_id INTEGER NOT NULL,
            product_id VARCHAR NOT NULL,
            seller_id VARCHAR NOT NULL,
            shipping_limit_date TIMESTAMP,
            price DOUBLE,
            freight_value DOUBLE,
            PRIMARY KEY (order_id, order_item_id),
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
        )
    """,
    "order_payments": """
        CREATE TABLE order_payments (
            order_id VARCHAR NOT NULL,
            payment_sequential INTEGER NOT NULL,
            payment_type VARCHAR,
            payment_installments INTEGER,
            payment_value DOUBLE,
            PRIMARY KEY (order_id, payment_sequential),
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """,
    "order_reviews": """
        CREATE TABLE order_reviews (
            review_id VARCHAR,
            order_id VARCHAR NOT NULL,
            review_score INTEGER,
            review_comment_title VARCHAR,
            review_comment_message VARCHAR,
            review_creation_date TIMESTAMP,
            review_answer_timestamp TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """,
}


def load_olist() -> None:
    """Load all Olist CSV files into a DuckDB database.

    Creates the database file fresh each run (drops if exists).
    Validates that all expected CSVs are present before starting.

    Raises:
        FileNotFoundError: If data/raw/ is missing or any expected CSV is not found.
    """
    if not RAW_DATA_DIR.exists():
        raise FileNotFoundError(
            f"Raw data directory not found: {RAW_DATA_DIR}\n"
            "Download the Olist dataset from Kaggle and unzip CSVs into data/raw/"
        )

    # Check all CSVs exist before starting
    missing = []
    for csv_name in CSV_TO_TABLE:
        csv_path = RAW_DATA_DIR / f"{csv_name}.csv"
        if not csv_path.exists():
            missing.append(csv_path.name)
    if missing:
        raise FileNotFoundError(f"Missing CSV files in {RAW_DATA_DIR}: {missing}")

    # Remove existing database to start fresh
    if DUCKDB_PATH.exists():
        DUCKDB_PATH.unlink()
        logger.info("Removed existing database at %s", DUCKDB_PATH)

    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DUCKDB_PATH))

    for csv_name, table_name in CSV_TO_TABLE.items():
        csv_path = RAW_DATA_DIR / f"{csv_name}.csv"
        ddl = TABLE_DDL[table_name]

        logger.info("Creating table '%s' ...", table_name)
        conn.execute(ddl)

        logger.info("Loading %s ...", csv_path.name)
        conn.execute(
            f"INSERT INTO \"{table_name}\" SELECT * FROM read_csv_auto('{csv_path}', "
            f"header=true, ignore_errors=true)"
        )

        count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        logger.info("  -> %s rows loaded into '%s'", f"{count:,}", table_name)

    # Summary
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    logger.info("Done. %d tables in %s: %s", len(tables), DUCKDB_PATH, [t[0] for t in tables])
    conn.close()


if __name__ == "__main__":
    load_olist()
