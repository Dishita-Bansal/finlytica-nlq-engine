"""
Tests for Strand 1's SQL safety guardrail. These run with NO database and
NO Anthropic API key required — pure logic tests on the validator function.

Run with: python3 -m pytest tests/test_guardrail.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from strands.strand1_sql_generation import validate_sql_safety, SQLGuardrailError


# --- Queries that MUST be blocked -------------------------------------------

@pytest.mark.parametrize("bad_sql", [
    "DELETE FROM customers",
    "DELETE FROM customers WHERE customer_id = 'CUST001'",
    "DROP TABLE customers",
    "DROP TABLE customers CASCADE",
    "UPDATE customers SET customer_age = 99",
    "INSERT INTO customers VALUES ('X', 'Y', 1, 1, 'Z')",
    "ALTER TABLE customers ADD COLUMN hacked BOOLEAN",
    "TRUNCATE TABLE loans",
    "GRANT ALL ON customers TO PUBLIC",
    "SELECT * FROM customers; DROP TABLE customers;",  # statement stacking
    "SELECT * FROM customers WHERE 1=1; DELETE FROM loans;",
    "SELECT * FROM customers -- ; DROP TABLE customers",  # comment smuggling
    "SELECT * FROM pg_shadow",  # unknown/system table
    "SELECT * FROM information_schema.tables",
    "EXECUTE some_prepared_statement",
    "COPY customers TO '/tmp/dump.csv'",
])
def test_malicious_or_mutating_sql_is_blocked(bad_sql):
    with pytest.raises(SQLGuardrailError):
        validate_sql_safety(bad_sql)


def test_evaluator_delete_all_rows_scenario():
    """
    Mirrors the exact evaluation scenario from the project brief:
    'Delete all rows from the customer table' should never reach the DB.
    Here we simulate what a non-compliant model *might* generate if it
    ignored the system prompt, to prove the code-level guardrail (not just
    the prompt) is what actually stops it.
    """
    hypothetical_bad_output = "DELETE FROM customers"
    with pytest.raises(SQLGuardrailError) as exc_info:
        validate_sql_safety(hypothetical_bad_output)
    assert "DELETE" in str(exc_info.value)


# --- Queries that MUST pass --------------------------------------------------

@pytest.mark.parametrize("good_sql", [
    "SELECT * FROM customers",
    "SELECT customer_name FROM customers WHERE customer_age > 40",
    """SELECT c.customer_name, l.status
       FROM customers c JOIN loans l ON c.customer_id = l.customer_id
       WHERE l.status = 'Delinquent'""",
    "SELECT city, SUM(current_balance) AS total FROM deposits d JOIN customers c ON c.customer_id = d.customer_id GROUP BY city",
    "WITH high_earners AS (SELECT * FROM customers WHERE monthly_income > 150000) SELECT * FROM high_earners",
    "SELECT * FROM customers;",  # single trailing semicolon is fine
])
def test_valid_select_queries_pass(good_sql):
    cleaned = validate_sql_safety(good_sql)
    assert cleaned.strip().upper().startswith(("SELECT", "WITH"))


def test_empty_sql_is_rejected():
    with pytest.raises(SQLGuardrailError):
        validate_sql_safety("")
    with pytest.raises(SQLGuardrailError):
        validate_sql_safety("   ")


def test_false_positive_avoided_for_word_boundaries():
    """
    A city or column value that happens to CONTAIN a forbidden keyword as a
    substring (not as a standalone SQL keyword) should NOT be blocked.
    e.g. 'Updateville' contains 'UPDATE' as a substring but isn't the keyword.
    """
    sql = "SELECT * FROM customers WHERE city = 'Updateville'"
    # Should not raise
    validate_sql_safety(sql)
