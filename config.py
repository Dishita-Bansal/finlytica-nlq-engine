"""
config.py — Central configuration shared by all three Strands.

Keeping schema metadata and DB config here (instead of duplicated in each
strand) is what makes the "Strands" genuinely decoupled: each strand imports
what it needs from here rather than knowing about the others' internals.
"""

import os

# --- Database connection -----------------------------------------------------
# NOTE: The NLQ engine connects as `nlq_readonly`, a Postgres role that has
# only SELECT grants (see db/schema.sql). This is a second, DB-enforced
# security boundary that holds even if the app-level guardrail in Strand 1
# were ever bypassed.
DB_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": os.environ.get("PG_PORT", "5432"),
    "dbname": os.environ.get("PG_DB", "finlytica_bank"),
    "user": os.environ.get("PG_NLQ_USER", "nlq_readonly"),
    "password": os.environ.get("PG_NLQ_PASSWORD", "nlq_readonly_pw"),
}

# Admin config (used only by db/seed.py to build the schema and grants)
DB_ADMIN_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": os.environ.get("PG_PORT", "5432"),
    "dbname": os.environ.get("PG_DB", "finlytica_bank"),
    "user": os.environ.get("PG_USER", "postgres"),
    "password": os.environ.get("PG_PASSWORD", "finlytica123"),
}

# --- Models -------------------------------------------------------------------
# Strand 1 uses a stronger reasoning model since SQL generation, multi-table
# joins, and self-correction from error traces all benefit from stronger
# reasoning.
#
# Strand 3 was originally on Haiku, on the assumption that summarizing an
# already-computed, already-small result table is a lightweight task. That
# assumption turned out to be wrong for *numeric* summaries: on the query
# "customers whose loan amount is more than 20 times their monthly income",
# Haiku miscounted the 7 returned rows as "four customers" and then
# contradicted itself, claiming one of the customers in the table did not
# actually meet the criteria.
#
# The root cause was the Strand 3 prompt, and it is fixed there: the row count
# is now computed in Python rather than by the model, and the system prompt
# forbids recalculating or re-evaluating any numeric condition (the SQL has
# already settled which rows qualify). That fix alone mitigates the bug.
#
# Sonnet is used here for defense-in-depth rather than because the prompt fix
# is insufficient. Summaries are the only part of the pipeline a user reads
# without seeing the underlying data, so a hallucinated figure here is the
# hardest kind to catch -- unlike a bad SQL query, which surfaces as an error
# or an obviously wrong table. The extra cost per query is small relative to
# that risk, and stronger instruction-following makes the prompt's "describe
# only what is in the table" constraints likelier to hold.
SQL_GENERATION_MODEL = "claude-sonnet-5"
SUMMARY_MODEL = "claude-sonnet-5"

# --- Schema metadata ------------------------------------------------------
# This is injected into Strand 1's system prompt so the model knows exactly
# what tables/columns exist and doesn't hallucinate columns.
SCHEMA_METADATA = """
Table: customers
  - customer_id (VARCHAR, PRIMARY KEY)
  - customer_name (VARCHAR)
  - customer_age (INT)
  - monthly_income (NUMERIC)  -- monthly net income in INR
  - city (VARCHAR)

Table: deposits
  - deposit_id (VARCHAR, PRIMARY KEY)
  - customer_id (VARCHAR, FOREIGN KEY -> customers.customer_id)
  - account_type (VARCHAR)  -- e.g. 'Savings', 'Checking'
  - current_balance (NUMERIC)
  - opened_date (DATE)

Table: loans
  - loan_id (VARCHAR, PRIMARY KEY)
  - customer_id (VARCHAR, FOREIGN KEY -> customers.customer_id)
  - loan_type (VARCHAR)  -- e.g. 'Home', 'Auto', 'Personal', 'Business', 'Education'
  - loan_amount (NUMERIC)
  - interest_rate (NUMERIC)
  - status (VARCHAR)  -- e.g. 'Active', 'Closed', 'Delinquent'
"""

ALLOWED_TABLES = {"customers", "deposits", "loans"}

# Max self-healing retries in Strand 2 before giving up and surfacing the error.
MAX_SELF_HEAL_ATTEMPTS = 3
