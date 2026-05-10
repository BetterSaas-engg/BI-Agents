# CLAUDE.md — Always-on context for `bi-agent`

This file is loaded into every Claude Code session in this repo. Read it before doing anything.

---

## Project in one paragraph

This is a **learning project** to understand the hard problems in LLM-driven BI work: schema grounding, evaluation, business semantics. We're building a tracer-bullet agent that answers natural-language business questions about the Olist e-commerce dataset. Architecture is a structured pipeline with one agentic step (SQL generation/repair). Backend is DuckDB now, BigQuery later. Read `SPEC.md` for the full plan and `DECISIONS.md` for what's been decided so far.

The goal is **insight**, not a shippable product. Optimize for legibility, reversibility, and eval-driven iteration.

---

## About the human

Akhil is not a seasoned software developer. He thinks in product terms and learns by building. He values:
- **Reversible, principled decisions** — flag tradeoffs, don't bury them
- **Understanding the "why"** — explain reasoning when you make a non-obvious call
- **Breaking problems down** — small, verifiable steps over big leaps

Talk to him like a senior engineer would talk to a smart product person. Don't assume deep familiarity with every Python idiom or library. Don't be condescending either.

---

## How to work in this repo

### Before you write code

1. **Find the relevant phase in `SPEC.md`.** Confirm the work fits in the current phase. If it doesn't, ask before proceeding.
2. **Check `DECISIONS.md`** for any decisions that affect what you're about to do.
3. **State your plan in 3–5 lines** before opening the editor. Akhil will say "go" or redirect.

### While you write code

- One module at a time. Don't sprawl across the codebase.
- New code goes in the file `SPEC.md` says it goes in. If a new file is needed, justify it.
- Every new public function gets a docstring with: what it does, what it takes, what it returns, what it can fail on.
- No silent error swallowing. If something can fail, raise. (Crash early.)
- Use Pydantic models for data passed between pipeline stages. Don't use raw dicts at stage boundaries.
- Type hints everywhere. We're using Python 3.14 — modern syntax (`list[str]`, `X | None`).

### After you write code

- Add or update tests in `tests/`. Phase 0–2 prioritize unit tests for `db.py`, `retriever.py`, `sql_agent.py`. Skip tests for prompt-shaped code (parser, presenter) — eval covers those.
- If you made a non-obvious decision, add a one-line entry to `DECISIONS.md` with date and reasoning.
- Run `ruff check` and `ruff format` before declaring done.

---

## Architectural rules (don't break these without raising it)

1. **`src/bi_agent/db.py` is the only place that knows DuckDB exists.** Everything else uses the `Database` interface. This is the BigQuery-swap seam.
2. **`src/bi_agent/llm.py` is the only place that imports the Anthropic SDK.** This is the model-swap seam.
3. **Pipeline stages communicate only via Pydantic models defined in `types.py`.** No tuples, no dicts, no positional args carrying meaning.
4. **The SQL agent is the only agentic component.** Don't sneak agent loops into other stages. If a stage needs to "think harder," that's a sign the stage boundaries are wrong — raise it.
5. **No mocking of LLM calls in tests.** Either the test doesn't need an LLM (most cases), or it's an eval (use the eval framework). Mocked LLM tests teach nothing.

---

## Defaults to use unless told otherwise

- **Model:** `claude-sonnet-4-5` for the SQL agent and judge. `claude-haiku-4-5` for the parser and explanation steps.
- **Temperature:** 0 for SQL generation. 0.3 for explanations.
- **Max tokens:** Per-call 4096 default. Agent loop budget: 6 iterations, 20K total tokens.
- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (local, fast, free).
- **Logging:** stdlib `logging` at INFO by default, DEBUG with `--verbose`.

---

## What to do when stuck

In this order:
1. Re-read the relevant section of `SPEC.md`. The answer is often there.
2. Check `DECISIONS.md` for related context.
3. Ask Akhil before guessing. A 30-second clarification beats a 30-minute wrong turn.
4. If the spec is wrong, propose a spec change *before* changing code.

---

## What to push back on

If Akhil asks for something that:
- Adds scope outside the current phase
- Violates an architectural rule above
- Skips eval or testing for "speed"
- Locks in a hard-to-reverse decision (new dependency, new abstraction, new framework)

…push back. Cite the relevant principle from this file or `SPEC.md`. He'd rather be questioned than shipped a mess.

---

## Things that are explicitly not in scope right now

(Repeated from `SPEC.md` so you don't have to flip back.)

- Web UI
- Multi-tenant anything
- Authentication
- Real semantic layer (stub only in v0)
- Recurring reports, anomaly detection, forecasting
- Production hardening

If you find yourself building any of these, stop.
