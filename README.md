# Finlytica Banking NLQ-to-SQL Analytics Engine

A Natural Language Query (NLQ) → SQL engine built on a **Strands** architecture:
three independently-testable modules that translate English questions into safe,
read-only PostgreSQL, execute them with a self-healing retry loop, and summarize
the results in plain English.

```
[User Natural Language Input]
        │
        ▼
┌──────────────────────────────────────────┐
│ STRAND 1: SQL Generation & Guardrails     │ ◄── claude-sonnet-5
│  - NL -> PostgreSQL SELECT                │
│  - Code-level safety validator            │
└────────────────────┬─────────────────────┘
                      │ (validated SQL)
                      ▼
┌──────────────────────────────────────────┐
│ STRAND 2: Execution & Self-Correction     │ ◄── pure Python (psycopg2)
│  - Runs query as a READ-ONLY DB role      │
│  - Catches errors, retries via Strand 1   │
└────────────────────┬─────────────────────┘
                      │ (pandas DataFrame)
                      ▼
┌──────────────────────────────────────────┐
│ STRAND 3: Insight & Presentation          │ ◄── claude-sonnet-5
│  - 2-sentence plain-English answer        │
└──────────────────────────────────────────┘
```

## 1. Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt --break-system-packages

# 2. Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Make sure PostgreSQL is running, then seed the database
#    (this builds the schema, the read-only role, and loads the 3 Excel files)
python3 db/seed.py

# 4. Ask a question
python3 main.py "Show customers who have more than 500000 in deposits"

# ...or run interactively
python3 main.py
```

If you don't have an Anthropic API key handy but want to see the full pipeline
run end-to-end (execution, guardrails, self-healing, read-only DB enforcement)
against the real database, run:

```bash
python3 demo_offline.py
```

This mocks only the two Claude calls with canned responses — everything else
(DB connection, guardrail, execution, security enforcement) is real.

## 2. Project layout

```
finlytica_nlq/
├── config.py                      # Shared schema metadata, DB config, model names
├── main.py                        # Orchestrator / CLI entry point
├── demo_offline.py                # End-to-end demo without needing an API key
├── data/                          # Customer_File.xlsx, Loan_File.xlsx, Deposit_File.xlsx (+ .csv)
├── db/
│   ├── schema.sql                 # Table DDL + read-only role/grants
│   └── seed.py                    # Loads Excel -> Postgres
├── strands/
│   ├── strand1_sql_generation.py  # NL->SQL + validate_sql_safety() guardrail
│   ├── strand2_execution.py       # run_query() + run_with_self_healing()
│   └── strand3_explanation.py     # summarize_result()
└── tests/
    ├── test_guardrail.py          # 25 tests, incl. the "DELETE all rows" case
    └── test_execution.py          # DB execution, self-healing, defense-in-depth
```

## 3. How each evaluation criterion is met

**Multi-table join capability** — Strand 1's system prompt is given the full
relational schema (customers ↔ deposits, customers ↔ loans) and instructed to
use explicit JOINs. All 15 example queries from the brief (e.g. "customers who
have both deposits and loans", "savings account holders with a delinquent home
loan") are answerable with 2–3 table joins; see `demo_offline.py` for worked
examples.

**Self-healing robustness** — `strand2_execution.run_with_self_healing()` wraps
generation + execution in a retry loop (`config.MAX_SELF_HEAL_ATTEMPTS = 3`).
On a DB error, the failed SQL and the exact Postgres error trace are fed back
into Strand 1 (`correction_context`), which regenerates a corrected query. See
`tests/test_execution.py::test_self_healing_recovers_from_syntax_error`.

**Security boundaries** — Two independent layers, both proven by tests:
1. **App-level guardrail** (`strand1_sql_generation.validate_sql_safety`): a
   pure-Python function (no dependency on the model behaving) that blocks any
   non-SELECT statement, any DDL/DML keyword anywhere in the query, statement
   stacking (`;`), comment smuggling (`--`, `/* */`), and references to tables
   outside `customers/deposits/loans`. Guardrail failures are a **hard stop**
   — they are never retried, unlike execution errors.
2. **Database-level enforcement**: the app connects as `nlq_readonly`, a
   Postgres role with `SELECT`-only grants (see `db/schema.sql`). Even if a
   mutating query somehow bypassed the app guardrail, Postgres itself would
   reject it. This is proven directly in
   `tests/test_execution.py::test_readonly_role_cannot_mutate_even_if_guardrail_bypassed`.

Run `python3 -m pytest tests/ -v` to see all 31 tests pass, including the
exact "Delete all rows from the customer table" scenario from the brief.

**Code separation** — Strand 2 (`strands/strand2_execution.py`) contains zero
Anthropic API calls; Strand 1 and Strand 3 each own exactly one Claude call
and don't know about each other. `main.py` is the only place that wires them
together, so each strand can be tested, replaced, or swapped to a different
model independently (see `config.py` for the two model constants).

## 4. Example queries

All 15 example queries from the project brief work out of the box, e.g.:

```bash
python3 main.py "Find customers with active home loans"
python3 main.py "Which customers have checking accounts but no loans?"
python3 main.py "Find customers whose loan amount is more than 20 times their monthly income"
python3 main.py "Compare total deposits versus total loan exposure for each customer"
```

## 5. Notes on model choice

The original brief referenced `claude-3-5-sonnet` and `claude-3-haiku`, which
are older/deprecated model identifiers. This implementation uses the current
equivalents — `claude-sonnet-5` for SQL generation (needs stronger reasoning
for joins/self-correction) and `claude-sonnet-5` for summarization.

Strand 3 originally used `claude-haiku-4-5-20251001` on the assumption that
summarizing an already-small result table is a lightweight task. It was
upgraded after Haiku miscounted rows and contradicted itself on a numeric
query. The underlying cause was the Strand 3 prompt and is fixed there; Sonnet
is used for defense-in-depth, since a hallucinated figure in a summary is the
hardest error for a user to catch. See the `SUMMARY_MODEL` notes in
`config.py` for the full rationale.

Swap these in `config.py` if your account has access to different models.
