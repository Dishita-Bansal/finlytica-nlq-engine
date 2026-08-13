"""
Tests for Strand 2 (execution + self-healing). These run against the REAL
PostgreSQL database (no mocking of the DB layer), but MOCK Strand 1's
generate_sql() so no Anthropic API key is required to run them.

Run with: python3 -m pytest tests/test_execution.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch

from strands.strand2_execution import run_query, run_with_self_healing, QueryExecutionError
from strands.strand1_sql_generation import SQLGuardrailError


def test_run_query_basic_select():
    df = run_query("SELECT * FROM customers")
    assert len(df) == 20
    assert "customer_name" in df.columns


def test_run_query_join():
    df = run_query("""
        SELECT c.customer_name, l.status
        FROM customers c JOIN loans l ON c.customer_id = l.customer_id
        WHERE l.status = 'Delinquent'
    """)
    assert len(df) == 2
    names = set(df["customer_name"])
    assert names == {"Rohit Gupta", "Divya Nair"}


def test_readonly_role_cannot_mutate_even_if_guardrail_bypassed():
    """
    Defense-in-depth check: even a raw mutating statement sent straight to
    run_query() (bypassing the Strand 1 guardrail entirely) must be rejected
    by PostgreSQL itself, because the app connects as `nlq_readonly`.
    """
    with pytest.raises(Exception) as exc_info:
        run_query("DELETE FROM customers")
    assert "permission denied" in str(exc_info.value).lower()


@patch("strands.strand2_execution.generate_sql")
def test_self_healing_recovers_from_syntax_error(mock_generate_sql):
    """
    Simulates Strand 1 producing a broken query first (typo'd table name),
    then a corrected query on retry -- proving the self-heal loop works.
    """
    mock_generate_sql.side_effect = [
        "SELECT customer_nam FROM customers LIMIT 5",   # attempt 1: typo'd column, valid table -> DB error
        "SELECT * FROM customers LIMIT 5",               # attempt 2: corrected
    ]
    df, final_sql, log = run_with_self_healing("some question", verbose=False)
    assert len(df) == 5
    assert "customers" in final_sql
    assert log[0]["status"] == "FAILED"
    assert log[1]["status"] == "SUCCESS"


@patch("strands.strand2_execution.generate_sql")
def test_guardrail_block_is_not_retried(mock_generate_sql):
    """
    If Strand 1 generates a mutating statement, this must raise immediately
    and NOT consume a self-heal retry -- mutations are a hard stop, not a
    'try again' situation.
    """
    mock_generate_sql.return_value = "DELETE FROM customers"
    with pytest.raises(SQLGuardrailError):
        run_with_self_healing("delete everything", verbose=False)
    # generate_sql should have been called exactly once (no retries for security blocks)
    assert mock_generate_sql.call_count == 1


@patch("strands.strand2_execution.generate_sql")
def test_gives_up_after_max_attempts(mock_generate_sql):
    """If every attempt fails, we should raise QueryExecutionError, not loop forever."""
    # A known table with a nonexistent column: passes the guardrail's table
    # allowlist check, but fails at the database level every single time.
    mock_generate_sql.return_value = "SELECT nonexistent_column_xyz FROM customers"
    with pytest.raises(QueryExecutionError):
        run_with_self_healing("bad question", verbose=False)
