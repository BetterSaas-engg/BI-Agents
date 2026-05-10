"""Application configuration. Reads from environment variables with sensible defaults."""

import os
from pathlib import Path

# Project root is three levels up from this file: src/bi_agent/config.py -> bi-agent/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Data paths
DATA_DIR = Path(os.environ.get("BI_AGENT_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DATA_DIR = Path(os.environ.get("BI_AGENT_RAW_DATA_DIR", DATA_DIR / "raw"))
DUCKDB_PATH = Path(os.environ.get("BI_AGENT_DUCKDB_PATH", DATA_DIR / "olist.duckdb"))

# Schema grounding (Phase 1)
SCHEMA_METADATA_PATH = DATA_DIR / "schema_metadata.yaml"
SCHEMA_INDEX_DIR = DATA_DIR / "schema_index"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
RETRIEVER_TOP_K = 4
SAMPLE_ROWS_N = 5
