# DECISIONS.md

Running log of decisions made during the build. New entries at the top. Date format: YYYY-MM-DD.

Every entry has: **what was decided**, **why**, **what alternatives were considered**, and **how reversible it is**.

---

## 2026-05-11 — Phase 4, round 3, semantic layer design (planning session)

- **What was decided:** A semantic layer for named business metrics, to be implemented as the next build round. Seven decisions were made in this session, listed below. No code was written.
- **Why:** Three eval failures across rounds 1 and 2 — cancellation_rate, average_order_value, payment_trend — pointed at the same root cause: undefined business metrics get re-interpreted on each run, and the agent silently picks among defensible alternatives. SPEC.md flagged this as [OPEN — Phase 4]. Three data points is enough evidence to act.

**The seven decisions:**

1. **Metric shape: Hybrid** — each metric defined with a natural-language description, a canonical SQL fragment, and structured fields. Combines the readability of documentation, the determinism of SQL fragments, and the queryability of structured definitions.
2. **Schema: Four fields.** `description` (required, prose), `sql` (required, SQL fragment), `grain` (required: the entity being aggregated — orders, customers, items, reviews, payments), `synonyms` (optional list of strings for retrieval).
3. **Retrieval: Embedding-based**, using the same sentence-transformers model and NumPy index pattern as the existing schema retriever. Mirrors the day-1 decision to "build the muscle" even at small scale.
4. **Pipeline position:** Fills the existing semantics stage stub in `src/bi_agent/semantics.py`. SPEC-aligned — the stub was designed precisely for this.
5. **Binding strength: Mandatory-with-composition.** When a metric is matched, its SQL fragment MUST appear in the agent's output SQL. The agent may wrap the fragment in SELECT, GROUP BY, WHERE, joins, etc. — but may not redefine it. Advisory was considered and rejected: advisory is what the agent already does today, and it's what produced the AOV regression. A real semantic layer is authoritative or it's just documentation.
6. **v0 metric set: Three metrics** chosen to cover distinct shapes. `cancellation_rate` (scalar ratio, evidence from round 1), `average_order_value` (scalar aggregation with definitional ambiguity, evidence from round 1), `average_review_score` (composable aggregation, tests "by seller" / "by category" composition).
7. **Eval changes: Option 1b — flag mismatches, don't hard-fail.** Two checks run for each metric-relevant question: (a) fragment-use (canonical SQL fragment appears in agent output), (b) execution equivalence (agent's SQL produces same result as a reference query built from the metric definition). Mismatches between the two are logged, but neither alone is a hard fail. Gives data on contract use without forcing a binary judgment before we have evidence the contract is right.

**Alternatives considered and rejected:**

- Pure SQL fragments (no description/structure) — too rigid for v0, teaches less
- Pure natural-language definitions — too close to what the agent already does, no real contract
- Static dump of all metrics in the prompt instead of retrieval — too inconsistent with the schema retrieval choice and skips a real learning opportunity
- Advisory binding — recreates the original problem
- Hard-failing on fragment use — premature before retrieval and metric definitions are eval-validated

**Out of scope, deliberately:**

- `payment_trend` is not in the v0 metric set. It is an analytical-lens question ("trends") rather than a named calculation. Logged as a finding: not every BI failure is a metric-definition failure. May warrant a different abstraction (e.g. visualization hints) in a later round.
- Retrieval confidence threshold (tuning during build/eval, not design-time)
- The dry_run thread (separate round)

- **Reversibility:** High at this stage — no code written. Medium once built: the metrics file is YAML and trivially editable; the retrieval index rebuilds in seconds; the agent's binding behavior is one prompt instruction; eval checks are additive. The largest commitment is the `description` + `sql` + `grain` + `synonyms` schema — changing field shape later means editing every metric.
- **Next step:** Draft `docs/SEMANTIC_LAYER.md` as the build contract before any code is written.

---

## 2026-05-11 — Phase 4, round 2, fix C-lite (reverted)

- **What was attempted:** Added a `finish_with_assumptions` tool to the SQL agent so it could declare ambiguity-resolution assumptions as a structured terminal call. Option B (tool-as-contract) chosen over option A (parse prose from final message) on cleanliness grounds.
- **Result:** Reverted. Token usage roughly doubled (146K → 319K input tokens across the golden set), 3 questions hit budget exhaustion (was 0), 6 regressions vs 2 improvements. Shape pass rate held at 94% but avg overall dropped from 4.59 to 4.09.
- **Why it failed:** Every question now required an extra LLM round-trip — the agent can't declare assumptions until it has seen `run_sql` results, so `run_sql` and `finish_with_assumptions` can't be parallel tool calls. The terminal-tool pattern adds a guaranteed +1 iteration per question, which doesn't matter for simple queries but pushes complex ones past the iteration budget.
- **Lesson:** Terminal-tool patterns have a fixed cost we didn't price. When we picked B over A, we chose a clean contract without measuring it. A clean contract that costs 2x tokens may be worse than a fragile one that costs nothing — depending on what we're optimizing for. In this project we're optimizing for legible failures and insight per dollar, and this contract was neither legible (the cost was hidden) nor cheap.
- **Alternatives still on the table for the AOV / payment-trends / ambiguous-wording cluster:**
  - Option 1 from earlier (presenter-only assumption declaration) — cheap, no agent loop changes
  - Assumptions as a parameter on `run_sql` itself (commit before seeing result) — closer to BI-engineer mental model
  - A real semantic layer (option C from the very first round) — bigger swing, more evidence still needed
- **Reversibility:** Done — all changes undone.

---

## 2026-05-11 — Phase 4, round 1, fix A (shipped)

- **Decision:** Added instruction #11 to SQL agent system prompt, targeting result-shape mismatch for rate/ratio/percentage questions. Concrete example included (cancellation_rate using FILTER).
- **Why:** Cancellation-rate eval failure showed agent understood "rate" conceptually (computed 0.63% in explanation) but returned a GROUP BY status breakdown in SQL. Testing the cheap hypothesis first: does telling the agent fix it, or is the bug structural?
- **Result:** Worked. Cancellation rate flipped to pass (3.33 → 5.0). Overall: shape pass rate 89% → 94%, avg overall 4.26 → 4.59. 5 questions improved, 12 unchanged. The hint generalized beyond the target question.
- **Alternatives considered:** B (parser extracts result_shape hint), C (real semantic layer). Both deferred. A worked, so structural fixes aren't yet justified by this failure.
- **Reversibility:** Trivial — one prompt rule.
- **Open thread:** Rule #2 ("ALWAYS call dry_run") is still being ignored in some traces. Investigate separately.

## 2026-05-11 — Phase 4, round 1, AOV regression (evidence, not a fix)

- **What was observed:** semantic_02 ("What is the average order value?") regressed from 5.0 to 3.67 between baseline and fix-A runs. SQL changed from SUM(price) to SUM(price + freight_value) — a defensible but different interpretation of "order value." Result moved from 137.75 to 160.58 BRL.
- **Why this matters:** Both interpretations are defensible. The golden set encodes one definition; the agent picked the other this run. This is the failure mode a semantic layer is designed to solve — named business metrics (AOV, cancellation rate, churn rate) should have one definition the system looks up, not re-derives on each call.
- **Decision:** No fix. Logged as evidence. This is the second data point pointing at the same root cause (cancellation rate was the first). When the third arrives, revisit the semantic-layer decision ([OPEN — Phase 4] in SPEC.md).
- **Reversibility:** N/A — no change made.

---

## 2026-05-10 — Phase 3 baseline

First eval run against the 18-question golden set. This is the starting point for Phase 4 iteration.

| Metric | Value |
|---|---|
| Shape pass rate | 16/18 (89%) |
| Avg correctness | 4.11/5 |
| Avg faithfulness | 4.44/5 |
| Avg SQL quality | 4.22/5 |
| Avg overall | 4.26/5 |
| Dry-run compliant | 17/18 |
| Budget exhausted | 0/18 |

**Shape failures (2):**
- `ambig_03` ("Show me the payment trends") — returned 90 rows, expected 5–50. Agent cross-tabulated payment types by month, which is thorough but exceeded the range. Judge gave 4.33/5.
- `semantic_01` ("What is the cancellation rate?") — returned 8 rows (order status breakdown) instead of a single cancellation rate number. Agent interpreted "rate" as "distribution." Judge gave 3.33/5.

**Notable behaviors:**
- `oos_03` ("Show me customer phone numbers") — agent inspected schema, found no phone columns, refused with explanation. Exactly the right behavior.
- `simple_03` ("How many unique customers?") — agent correctly used `customer_unique_id`, not `customer_id`. The schema metadata descriptions did their job.
- Most questions complete in 2 steps (dry_run → run_sql), showing the system prompt's schema context eliminates redundant inspect_schema calls.

---

## 2026-05-10 — Phase 3 build decisions

### Shape check uses column count, not column names
- **Decision:** Shape validation checks that the result has at least as many columns as expected, but does not check column names. Column naming is left to the LLM judge.
- **Why:** The agent consistently produces correct SQL with reasonable column aliases (`total_orders`, `average_review_score`, etc.) that don't match the golden set's generic names (`count`, `avg`). Exact or even substring column name matching caused 7/18 false failures in the first eval run. Column naming is cosmetic — the judge is better positioned to evaluate it.
- **Alternatives considered:** Fuzzy/substring matching (still too fragile), semantic similarity on column names (overkill).
- **Reversibility:** Trivial — add column name checks back to `check_shape()` in runner.py.

### Judge uses same model as cheap calls (Haiku)
- **Decision:** The LLM judge uses Haiku (same as parser/presenter), not Sonnet.
- **Why:** Judge calls go through `llm.complete()` which defaults to CHEAP_MODEL. At 18 questions per eval run, cost matters. Haiku is capable enough for rubric-based scoring. If judge quality becomes a concern, can be overridden per-call.
- **Alternatives considered:** Using the agent model (Sonnet) for judging — more expensive, and the spec says "default to same model + different prompt" which we interpret as same-tier.
- **Reversibility:** Trivial — pass `model=AGENT_MODEL` in the judge call.

### Out-of-scope questions pass shape check unconditionally
- **Decision:** Questions with `expected_row_count: 0` always pass the shape check (whether the agent refuses or returns data). The judge evaluates whether the agent's response was appropriate.
- **Why:** Some out-of-scope questions (e.g., "predict next month's revenue") are better answered with historical data + caveats than with a flat refusal. Hard-failing on non-empty results would penalize thoughtful responses. The judge rubric specifically handles this: "if the agent correctly refuses or flags the limitation, score Correctness=5."
- **Reversibility:** Trivial — change the early return in `check_shape()`.

---

## 2026-05-10 — Phase 2 build decisions

### Token budget raised from 20K to 40K
- **Decision:** Increased the SQL agent's max_total_tokens from 20,000 (spec default) to 40,000.
- **Why:** The system prompt includes full schema context (~3K tokens of table descriptions, column types, and sample rows). Each LLM round-trip costs ~4K input tokens because this context is re-sent. At 20K, the agent hit the budget after 5 tool calls (inspect_schema x2, sample_rows x2, dry_run) before it could call run_sql — even though it had valid SQL. With the improved prompt telling the agent to skip redundant inspect_schema calls, typical queries now complete in 2-3 steps (~7K tokens), but 40K gives headroom for harder queries that need repair loops.
- **Alternatives considered:** Keep 20K and reduce system prompt size (would lose valuable schema context), or remove the token budget entirely (too risky for runaway loops).
- **Reversibility:** Trivial — change `MAX_TOTAL_TOKENS` in sql_agent.py.

### Agent prompt includes full schema context
- **Decision:** The SQL agent's system prompt includes table descriptions, column types/descriptions, and sample rows from the retriever output. The agent is instructed to use this context directly and only call inspect_schema/sample_rows if it needs additional detail.
- **Why:** Without this, the agent redundantly called inspect_schema and sample_rows on every table before writing SQL, burning 4 of its 6 iteration budget on information it already had. With the schema in the system prompt, the agent typically goes straight to dry_run + run_sql (2 steps).
- **Alternatives considered:** Remove inspect_schema/sample_rows tools entirely (too aggressive — agent may legitimately need more detail for complex queries).
- **Reversibility:** High — edit the system prompt in sql_agent.py.

### No hard gate on dry_run before run_sql
- **Decision:** The agent is instructed (via system prompt) to always dry_run before run_sql, but this is not enforced in code. Instead, the trace logs whether each run_sql call was preceded by a successful dry_run.
- **Why:** Hard-gating requires tracking state (which SQL strings have been dry-run'd) and blocking tool calls — complexity that doesn't teach anything. The soft approach lets us observe compliance via traces, which is itself a learning moment about agent instruction-following. Per SPEC.md Section 7, this was an open decision.
- **Reversibility:** Medium — adding a hard gate later is straightforward.

### Model IDs: claude-sonnet-4 for agent, claude-haiku-4-5 for cheap calls
- **Decision:** Using `claude-sonnet-4-20250514` for the SQL agent and `claude-haiku-4-5-20251001` for parser/explanation. Centralized in config.py as AGENT_MODEL and CHEAP_MODEL.
- **Why:** CLAUDE.md specifies Sonnet for agent and Haiku for cheap steps. These are the model IDs available on the current API key. Centralized in config.py so swapping is a one-line change.
- **Reversibility:** Trivial — change in config.py.

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
