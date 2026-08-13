"""
Strand 2 — Execution & Self-Correction Strand
================================================
Responsibility: run a validated SQL string against PostgreSQL and return a
pandas DataFrame. Contains ZERO Claude/Anthropic calls itself — pure
Python + psycopg2 logic, as required by the "Strands" separation.

Self-healing: if execution raises a syntax/semantic error, the caller
(main.py) feeds the error back to Strand 1 to regenerate the SQL. This
module exposes `run_query()` for a single execution attempt and
`run_with_self_healing()` which wraps the full retry loop, calling back
into Strand 1 for corrections.
"""

import pandas as pd
import psycopg2

from config import DB_CONFIG, MAX_SELF_HEAL_ATTEMPTS
from strands.strand1_sql_generation import generate_sql, validate_sql_safety, SQLGuardrailError


class QueryExecutionError(Exception):
    """Raised when a query fails and self-healing could not recover it."""
    pass


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def run_query(sql: str) -> pd.DataFrame:
    """
    Executes a single SQL string and returns the result as a DataFrame.
    Raises the underlying psycopg2 exception on failure (caller decides
    whether to retry/self-heal).

    Uses a raw psycopg2 cursor (rather than pandas.read_sql_query) so we
    aren't dependent on SQLAlchemy and get a clean DBAPI2 error object for
    the self-healing loop to inspect.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            colnames = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=colnames)
    finally:
        conn.close()


def run_with_self_healing(natural_language_query: str, verbose: bool = True) -> tuple[pd.DataFrame, str, list]:
    """
    Full pipeline: generate -> validate -> execute, with up to
    MAX_SELF_HEAL_ATTEMPTS retries if the DB raises an error.

    Returns (dataframe, final_sql, attempt_log).
    attempt_log is a list of dicts describing each attempt, useful for
    debugging/demoing the self-healing behavior to evaluators.
    """
    attempt_log = []
    correction_context = None
    last_error = None
    last_sql = None

    for attempt in range(1, MAX_SELF_HEAL_ATTEMPTS + 1):
        # --- Strand 1: generate ---
        sql = generate_sql(natural_language_query, correction_context=correction_context)
        last_sql = sql

        # --- Strand 1: guardrail check (security boundary) ---
        try:
            safe_sql = validate_sql_safety(sql)
        except SQLGuardrailError as e:
            # Guardrail failures are NOT retried/self-healed — they are a hard stop.
            # We never want the model "trying again" to sneak a mutation through.
            attempt_log.append({"attempt": attempt, "sql": sql, "status": "BLOCKED", "detail": str(e)})
            raise

        if verbose:
            print(f"  [Strand 1] Attempt {attempt} SQL:\n    {safe_sql}\n")

        # --- Strand 2: execute ---
        try:
            df = run_query(safe_sql)
            attempt_log.append({"attempt": attempt, "sql": safe_sql, "status": "SUCCESS", "detail": None})
            return df, safe_sql, attempt_log
        except Exception as e:
            last_error = str(e)
            attempt_log.append({"attempt": attempt, "sql": safe_sql, "status": "FAILED", "detail": last_error})
            if verbose:
                print(f"  [Strand 2] Execution failed: {last_error}")
                print(f"  [Self-heal] Feeding error back to Strand 1 for correction...\n")
            correction_context = {"failed_sql": safe_sql, "error": last_error}

    raise QueryExecutionError(
        f"Query failed after {MAX_SELF_HEAL_ATTEMPTS} self-healing attempts. "
        f"Last SQL: {last_sql}\nLast error: {last_error}"
    )
