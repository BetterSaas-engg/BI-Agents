# BI Agent — Build Spec

**Project codename:** `bi-agent` (working title)
**Author:** Akhil
**Goal:** Learn the hard problems in LLM-driven BI work — schema grounding, evaluation, business semantics — by building a tracer-bullet "BI engineer agent" against the Olist e-commerce dataset.

This spec is the contract for the build. If something here is wrong, fix the spec first, then the code.

---

## 1. What we are building

A locally-runnable Python application that takes a natural-language business question about an e-commerce dataset and returns:

1. The SQL query it generated
2. The result table
3. A chart (if appropriate)
4. A plain-English explanation of the result

The user is a BI-engineer-shaped persona. The first dataset is **Olist Brazilian E-Commerce** loaded into a local DuckDB file. The architecture is a structured pipeline with one agentic step (SQL generation/repair). Backend is swappable; DuckDB for v0, BigQuery in Phase 3.

**This is a learning project, not a product.** Optimization targets, in order: pedagogical clarity > correctness > speed > cost > polish.

---

## 2. Non-goals

Things we are explicitly NOT building in this iteration:

- A web UI. CLI only. (Web wrapper is a Phase-4 stretch.)
- Multi-tenant anything. Single user, single dataset.
- Authentication. There's nothing to authenticate.
- A semantic layer with full business-term resolution. We'll stub the interface and skip the implementation in v0.
- Recurring reports, anomaly detection, forecasting. These are future canonical tasks; not designed for here.
- Production hardening: retries with backoff against API outages, queueing, observability platforms, etc.

If you find yourself building any of the above, stop and re-read this section.

---

## 3. Architectural shape

```
User question (natural language)
       │
       ▼
┌──────────────────────┐
│  1. Question parser  │  LLM call. Extracts intent + entities. Cheap.
└──────────────────────┘
       │
       ▼
┌──────────────────────┐
│  2. Schema retriever │  Embedding retrieval. No LLM. Returns relevant tables/cols.
└──────────────────────┘
       │
       ▼
┌──────────────────────┐
│  3. Semantic layer   │  STUB in v0. Pass-through interface, real lookup later.
└──────────────────────┘
       │
       ▼
┌══════════════════════┐
║  4. SQL agent loop   ║  Tool-using agent. Tools: inspect_schema, sample_rows,
║                      ║   dry_run_sql, run_sql. Loops until valid query or budget.
└══════════════════════┘
       │
       ▼
┌──────────────────────┐
│  5. Presenter        │  Deterministic chart-type rules + LLM explanation.
└──────────────────────┘
       │
       ▼
   Answer object (sql, df, chart, explanation, metadata)
```

The double-bordered box is the only agentic step. Everything else is plain Python with discrete LLM calls. This is intentional: the hard problems live at the boundaries of the agent, not inside it.

---

## 4. Tech stack

Locked in:

- **Python 3.14** (matches Akhil's local setup)
- **DuckDB** for the SQL backend (Phase 0–2)
- **Anthropic Python SDK** for LLM calls (Claude Sonnet 4.5 default; downgrade to Haiku for cheap steps)
- **`uv`** for dependency management (faster than pip, lockfile-native)

Likely:

- **`sentence-transformers`** for embeddings (local, free, fine for 9 tables) — small model like `all-MiniLM-L6-v2`
- **`pandas`** for result handling
- **`matplotlib`** or **`plotly`** for charts (matplotlib for v0; less polish, fewer deps)
- **`pydantic`** for typed data contracts between pipeline stages
- **`pytest`** for tests
- **`ruff`** for lint/format
- **`rich`** for CLI output (tables, syntax highlighting)

Deferred / open:

- BigQuery client (Phase 3 only)
- Logging/tracing — start with stdlib `logging`, consider `logfire` if it gets painful
- Vector store — start with in-memory NumPy. No FAISS/Chroma needed at this scale.

---

## 5. Repository layout

```
bi-agent/
├── CLAUDE.md                 # Always-on context for Claude Code sessions
├── SPEC.md                   # This file
├── DECISIONS.md              # Running log of decisions made during build
├── README.md                 # How to run, for future-you
├── pyproject.toml            # uv-managed
├── uv.lock
├── .env.example              # ANTHROPIC_API_KEY=...
├── .gitignore
│
├── data/
│   ├── raw/                  # Olist CSVs, gitignored
│   └── olist.duckdb          # Built database, gitignored
│
├── scripts/
│   ├── load_olist.py         # One-shot: CSVs → DuckDB
│   └── build_schema_index.py # One-shot: schema → embeddings
│
├── src/bi_agent/
│   ├── __init__.py
│   ├── config.py             # Env vars, model names, budgets
│   ├── types.py              # Pydantic models for stage I/O contracts
│   ├── llm.py                # Thin Anthropic wrapper (one place to change)
│   ├── db.py                 # SQL backend abstraction (DuckDB impl)
│   │
│   ├── parser.py             # Stage 1: question → ParsedQuestion
│   ├── retriever.py          # Stage 2: question → RelevantSchema
│   ├── semantics.py          # Stage 3: stub interface
│   ├── sql_agent.py          # Stage 4: agentic SQL gen + repair
│   ├── presenter.py          # Stage 5: result → chart + explanation
│   │
│   ├── pipeline.py           # Orchestrates 1→5
│   └── cli.py                # `python -m bi_agent ask "..."`
│
├── eval/
│   ├── golden_set.yaml       # ~15–20 hand-curated Q+A
│   ├── judge.py              # LLM-as-judge for non-golden questions
│   ├── runner.py             # Runs full eval, produces report
│   └── reports/              # Eval run outputs, gitignored
│
└── tests/
    ├── test_db.py
    ├── test_retriever.py
    ├── test_sql_agent.py
    └── test_pipeline.py
```

Principles baked in here:
- One module per pipeline stage. Easy to reason about, easy to swap.
- `db.py` is the abstraction seam for the BigQuery swap. Treat it carefully.
- `llm.py` is the abstraction seam for the model change. Same.
- Eval is its own top-level concern, not buried in tests.

---

## 6. Phased build plan

Each phase has a **definition of done** that is verifiable by running a command and checking output. Don't move to the next phase without it.

### Phase 0 — Foundations (target: 2–3 sessions)

**Done when:** `python scripts/load_olist.py` produces `data/olist.duckdb`, and `python -c "import duckdb; print(duckdb.connect('data/olist.duckdb').execute('SELECT COUNT(*) FROM orders').fetchone())"` returns the expected order count.

Deliverables:
- Repo scaffolded with the layout above
- `pyproject.toml` with locked deps
- `CLAUDE.md` and `DECISIONS.md` populated
- Olist CSVs downloaded to `data/raw/`
- `scripts/load_olist.py` loads all 9 tables into DuckDB with proper types and FK relationships preserved
- `db.py` has a `Database` interface with a `DuckDBDatabase` implementation supporting: `list_tables()`, `describe_table(name)`, `sample_rows(table, n)`, `dry_run(sql)`, `run(sql) -> DataFrame`
- One smoke test per `db.py` method

### Phase 1 — Schema grounding (target: 2–3 sessions)

**Done when:** Given the question *"How many orders were placed in 2017 by state?"*, the retriever returns `orders`, `customers`, and their relevant columns — and excludes `products`, `sellers`, `reviews` etc. Verified via a small retrieval-quality test set.

Deliverables:
- Schema metadata file: a YAML or JSON with table descriptions, column descriptions, and example values per column. Hand-curated from Olist docs. **This is high-leverage work; spend time here.**
- `scripts/build_schema_index.py` embeds table+column descriptions into a NumPy array on disk
- `retriever.py` loads the index, embeds the question, returns top-k tables with all their columns + sample rows
- ~10 retrieval test cases asserting which tables should be retrieved for which questions

This is where you'll feel the first hard problem. Spend the time.

### Phase 2 — SQL agent + end-to-end pipeline (target: 4–5 sessions)

**Done when:** `python -m bi_agent ask "How many orders were placed in 2017 by state?"` returns valid SQL, a result table, and a coherent explanation. Works for at least 5 of the golden-set questions (we'll fix the rest in Phase 4).

Deliverables:
- `parser.py` (cheap LLM call: extract intent, entities, time range)
- `semantics.py` stub (interface defined, returns input unchanged)
- `sql_agent.py`:
  - Tools: `inspect_schema(table)`, `sample_rows(table, n)`, `dry_run(sql)`, `run_sql(sql)`
  - Loop with explicit budget (max iterations, max tokens)
  - Returns `(sql, result_df, agent_trace)` — the trace is critical for debugging
- `presenter.py`:
  - Rule-based chart picker (1 metric + 1 categorical → bar; 1 metric over time → line; etc.)
  - LLM explanation call
- `pipeline.py` glues stages 1–5
- `cli.py` exposes `ask`, `--verbose` shows the agent trace

### Phase 3 — Evaluation (target: 3–4 sessions)

**Done when:** `python -m eval.runner` runs the full golden set + judge, produces a markdown report under `eval/reports/`, and you can compare two runs to see if a change improved or regressed performance.

Deliverables:
- `eval/golden_set.yaml`: 15–20 questions covering: simple aggregations, joins, time ranges, ambiguous wording, deliberately-out-of-scope questions (the agent should refuse these), questions requiring semantic interpretation
- Each golden item has: question, expected SQL (canonical form), expected result shape (rows, key columns), notes
- Golden eval: runs agent, compares result shape to expected (not exact SQL match — execution-equivalent SQL is fine)
- Judge eval: separate LLM call scores agent output on (correctness, faithfulness to question, SQL quality) with rubric
- Report: per-question pass/fail/score, aggregate metrics, diff against previous run

Eval is the second hard problem. Don't skimp here — it's the only way to know if changes are helping.

### Phase 4 — Iteration (target: open-ended)

**Done when:** You stop learning new things, or 6 weeks elapse.

This is where the actual learning happens. Run eval, find failures, hypothesize fixes, implement, re-run. Things you'll likely confront:
- Ambiguous questions ("our top customers" — by what?). Where should that resolution happen?
- Schema retrieval missing relevant tables. Better metadata? Better embeddings? Hybrid keyword + embedding?
- SQL agent looping unproductively. Better tool design? Better prompting? Agent budget tuning?
- Judge disagreeing with golden truth. Why? What does that teach you?

Document each round of iteration in `DECISIONS.md`.

### Phase 5 — BigQuery swap (stretch)

**Done when:** Setting `BI_AGENT_BACKEND=bigquery` in `.env` makes everything work against a BigQuery copy of Olist with zero code changes outside `db.py`.

This is the test of whether the abstraction held. If it didn't, that's a learning moment.

---

## 7. Open decisions

These are flagged for resolution before the phase that needs them. Don't resolve them now.

- **`[OPEN — Phase 1]`** Embedding model choice. Default to `all-MiniLM-L6-v2`. Revisit if retrieval quality is poor.
- **`[OPEN — Phase 2]`** Agent budget: max iterations and max tokens. Default to 6 iterations / 20K total tokens. Revisit after seeing real traces.
- **`[OPEN — Phase 2]`** Should the agent be allowed to run `run_sql` (mutates nothing but is "real") or only `dry_run` until it's confident? Default: only run after a successful dry_run.
- **`[OPEN — Phase 3]`** Judge model — same as agent or stronger? Default to same model + different prompt. Worth experimenting.
- **`[OPEN — Phase 4]`** Whether to add a real semantic layer. Decide based on what fails in eval.

---

## 8. What "good" looks like for this project

We are explicitly not optimizing for: low cost per query, sub-second latency, demo polish, breadth of supported question types.

We are optimizing for:
- **Legible failures.** When something goes wrong, you can tell which stage and why.
- **Reversible decisions.** Backend, model, embedding, prompt — all swappable.
- **Eval-driven iteration.** Every change you make should be measurable.
- **Insight per dollar.** Each Claude Code session should teach you something you didn't know.

If by Phase 4 you can articulate, in your own words, *"the three things that make BI agents hard are X, Y, Z, and here's what I tried for each"* — the project succeeded regardless of how good the agent is.
