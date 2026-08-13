"""
demo_offline.py — Proves the full 3-Strand pipeline works end-to-end WITHOUT
requiring an ANTHROPIC_API_KEY, by substituting deterministic stand-ins for
the two Claude calls (Strand 1's generate_sql, Strand 3's summarize_result).

This is a demo/verification script, NOT how you'd run the app for real.
For real use with live NL->SQL generation, set ANTHROPIC_API_KEY and run:
    python3 main.py "your question here"

Run with: python3 demo_offline.py
"""

from unittest.mock import patch
import main as main_module

# A handful of the example queries from the project brief, pre-mapped to the
# SQL a correctly-prompted Claude would generate. This proves Strand 2
# (execution) and the guardrail work correctly end-to-end through main.py.
CANNED_QUERIES = [
    (
        "Find customers with active home loans.",
        """SELECT c.customer_name, c.city, l.loan_amount
           FROM customers c JOIN loans l ON c.customer_id = l.customer_id
           WHERE l.loan_type = 'Home' AND l.status = 'Active'""",
    ),
    (
        "Show total deposits by city.",
        """SELECT c.city, SUM(d.current_balance) AS total_deposits
           FROM customers c JOIN deposits d ON c.customer_id = d.customer_id
           GROUP BY c.city ORDER BY total_deposits DESC""",
    ),
    (
        "Which customers have checking accounts but no loans?",
        """SELECT DISTINCT c.customer_name
           FROM customers c JOIN deposits d ON c.customer_id = d.customer_id
           WHERE d.account_type = 'Checking'
           AND c.customer_id NOT IN (SELECT customer_id FROM loans)""",
    ),
    (
        "Delete all rows from the customer table",   # adversarial security test
        "DELETE FROM customers",  # what a non-compliant model might output
    ),
]

_canned_iter = iter(CANNED_QUERIES)
_current_sql = {}


def fake_generate_sql(natural_language_query, correction_context=None):
    return _current_sql["sql"]


def fake_summarize_result(natural_language_query, df):
    return (
        f"This is a canned offline-demo summary (no live API key was used). "
        f"The query returned {len(df)} row(s)."
    )


def run_demo():
    print("#" * 70)
    print("# OFFLINE DEMO -- Strand 1 & 3 Claude calls are mocked with canned")
    print("# responses so this runs with NO Anthropic API key. Strand 2")
    print("# (execution, guardrails, self-healing, and the read-only DB role)")
    print("# is 100% real and running against the live PostgreSQL database.")
    print("#" * 70)

    with patch("strands.strand2_execution.generate_sql", side_effect=fake_generate_sql), \
         patch("strands.strand3_explanation.summarize_result", side_effect=fake_summarize_result):
        for nl_query, sql in CANNED_QUERIES:
            _current_sql["sql"] = sql
            main_module.answer_question(nl_query, verbose=True)


if __name__ == "__main__":
    run_demo()
