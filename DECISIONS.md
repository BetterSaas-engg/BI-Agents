# DECISIONS.md

Running log of decisions made during the build. New entries at the top. Date format: YYYY-MM-DD.

Every entry has: **what was decided**, **why**, **what alternatives were considered**, and **how reversible it is**.

---

## 2026-05-10 — Phase 1 build decisions

### Table-level embedding granularity
- **Decision:** One embedding per table (table description + all column descriptions concatenated), not per-column.
- **Why:** With only 9 tables, table-level granularity is sufficient for retrieval. Per-column embeddings would add complexity (mapping columns back to tables, handling partial matches) without improving recall at this scale. The retriever returns full tables with all columns anyway.
- **Alternatives considered:** Per-column embeddings (more granular but overkill for 9 tables), hybrid table+column (unnecessary complexity).
- **Reversibility:** High — change `table_to_text()` in `build_schema_index.py` and rebuild.

### Top-k default of 4
- **Decision:** Retriever returns 4 tables by default.
- **Why:** With 9 total tables, 4 gives good coverage (~44%) while still filtering out irrelevant tables. Most business questions touch 2–3 tables. 4 gives headroom for borderline-relevant tables that the SQL agent can choose to ignore.
- **Alternatives considered:** 3 (too tight for multi-join questions), 5 (too loose, less filtering value).
- **Reversibility:** Trivial — change `RETRIEVER_TOP_K` in config.py.

### Normalized embeddings + dot product for similarity
- **Decision:** Embeddings are L2-normalized at index time and query time. Similarity is a simple dot product (equivalent to cosine similarity on normalized vectors).
- **Why:** Avoids recomputing norms at query time. sentence-transformers supports `normalize_embeddings=True` natively.
- **Reversibility:** Trivial.

---

## 2026-05-10 — Phase 0 build decisions

### Front-loaded full dependency list in pyproject.toml
- **Decision:** Added all spec-listed dependencies (anthropic, sentence-transformers, matplotlib, rich, pyyaml) to `pyproject.toml` upfront, rather than adding them incrementally as each module is built.
- **Why:** pyproject.toml initially only declared duckdb, pandas, pydantic — a subset of the spec (Section 4). Front-loading aligns the lockfile with the spec, prevents "works on my machine" drift, and surfaces version conflicts early while the project is small. Spec-code alignment is a stated preference.
- **Alternatives considered:** Lazy-install (add deps as needed). Rejected because it creates a gap between spec and reality that compounds over phases.
- **Reversibility:** Trivial — remove a line from pyproject.toml and re-sync.

### Table naming convention
- **Decision:** Strip `olist_` prefix and `_dataset` suffix from CSV filenames. `product_category_name_translation.csv` becomes `category_translation`.
- **Why:** Cleaner SQL for the agent to generate and read. Original names are noisy.
- **Reversibility:** High — rename in `load_olist.py` DDL only.

### FK declarations in DuckDB
- **Decision:** Declare foreign keys in CREATE TABLE DDL even though DuckDB doesn't enforce them.
- **Why:** Documentation value — makes relationships visible when inspecting schema. Zero runtime cost.
- **Reversibility:** Trivial to add or remove.

### dry_run uses EXPLAIN
- **Decision:** `db.dry_run(sql)` uses DuckDB's `EXPLAIN` to validate without executing.
- **Why:** EXPLAIN catches syntax errors, unknown tables/columns, and type mismatches — exactly what the SQL agent needs for validation. No true "dry run" mode in DuckDB.
- **Reversibility:** Swap to `PREPARE` or BigQuery's `dryRun` parameter when backend changes.

### Geolocation loaded raw
- **Decision:** Load the geolocation CSV as-is without deduplication (~1M rows, many duplicate zip codes).
- **Why:** Data cleaning decisions should be visible and intentional, not hidden in the load script. If it causes problems later, we'll address it then.
- **Reversibility:** Re-run load script with dedup logic.

### Pydantic from Phase 0
- **Decision:** `db.describe_table()` returns Pydantic models (`TableSchema`, `ColumnInfo`) from day one.
- **Why:** CLAUDE.md rule #3 says pipeline stages communicate via Pydantic models in `types.py`. Starting now avoids a retrofit later.
- **Reversibility:** N/A — this is the spec.

---

## 2026-05-09 — Initial planning session

These are the foundational decisions from the planning chat. Everything in `SPEC.md` flows from these.

### Project framing
- **Decision:** Build a vertical-specific BI agent prototype, exploration mode, 6-week window. Not a product, not for any current employer/client.
- **Why:** Akhil wants to understand what plug-and-play data agents could look like under the Optimacore banner.
- **Reversibility:** Fully reversible — it's a learning project.

### Vertical: e-commerce, public dataset
- **Decision:** Target e-commerce, use Olist Brazilian E-Commerce dataset.
- **Why:** Public, multi-table, realistically messy, good docs, ~100k orders. Ad-tech rejected because Eyeo data isn't usable. Privacy rejected because "data science" is a stretch for the domain. CRM was a strong second.
- **Reversibility:** Medium. Schema-handling is built generic; swapping datasets is hours, not days.

### Persona: BI engineer
- **Decision:** Mimic a BI engineer, not a data analyst or data scientist.
- **Why:** The work shape (question → SQL/transformation → ship) is the most agent-friendly of the three. Clearer inputs and outputs make the agent easier to evaluate.
- **Reversibility:** Persona-shifting later means new task definitions and new eval sets, but architecture should hold.

### Canonical task: question → SQL + chart + explanation
- **Decision:** First task is open-ended business Q&A. Recurring reports and anomaly investigation are future tasks, not designed for in v0.
- **Why:** Most pedagogically rich — hits every interesting problem (schema, SQL gen, validation, presentation). Anomaly investigation is the "why someone would pay for this" target but is significantly harder; comes later.
- **Reversibility:** High — each task type is a separate pipeline.

### Architecture: hybrid pipeline + agentic SQL step (Option C)
- **Decision:** Structured outer pipeline, agentic inner loop only at the SQL generation/repair step.
- **Why:** The hard problems Akhil wants to learn (schema grounding, eval, semantics) live at the *boundaries* of the agent, not inside it. C makes those boundaries legible. A would hide too much, B would obscure which part of grounding failed.
- **Alternatives considered:** A (pure pipeline), B (full agent loop), D (autonomous agent — rejected immediately).
- **Reversibility:** Medium. C → B is a refactor, C → A is a simplification. Either is doable.

### Backend: DuckDB for v0, BigQuery for Phase 5
- **Decision:** Local DuckDB file for development and eval. Swap to BigQuery as a Phase-5 stretch goal.
- **Why:** BigQuery was Akhil's first pick. Pushed back: in a learning project, BigQuery costs iteration speed and money but teaches nothing about agents. DuckDB is instant, free, and the abstraction layer (`db.py`) lets us swap later. The swap itself becomes a learning moment about whether the abstraction held.
- **Reversibility:** High by design. `db.py` is the seam.

### Schema grounding: retrieval-based from day 1
- **Decision:** Use embedding retrieval over schema metadata, even though Olist's 9 tables fit in context. In-memory NumPy, `all-MiniLM-L6-v2` embeddings.
- **Why:** Building the muscle now matters. Static dump would teach nothing about the actual hard problem. Cheap to do right at this scale.
- **Reversibility:** High. The retrieval interface is small.

### Evaluation: golden set + LLM-as-judge
- **Decision:** Hand-curated set of 15–20 golden questions with verified expected results, plus LLM-as-judge for exploratory queries beyond the golden set.
- **Why:** Eval is one of the hard problems Akhil wants to learn. Golden set gives ground truth; judge handles breadth. Eyeballing alone teaches nothing rigorous; judge alone shares blind spots with the agent.
- **Reversibility:** High. Both are additive.

### Workflow: Claude.ai for planning, Claude Code for build
- **Decision:** Spec produced in Claude.ai (this session). All build work happens in Claude Code with `CLAUDE.md` per-repo. Phase-by-phase, fresh context per phase if needed.
- **Why:** Akhil's preferred setup, and the right choice for context window management on a multi-week build. Files act as external memory.
- **Reversibility:** Trivial.

### Tech stack
- **Decision:** Python 3.14, `uv`, DuckDB, Anthropic SDK, sentence-transformers, pandas, matplotlib, pydantic, pytest, ruff, rich.
- **Why:** Matches Akhil's local setup. Standard, low-magic choices. No frameworks where libraries suffice.
- **Reversibility:** Medium per dependency. Adding things is easy; removing entrenched ones less so. Kept the list short on purpose.
