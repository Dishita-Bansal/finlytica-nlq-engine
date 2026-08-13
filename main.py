"""
main.py - Finlytica Banking NLQ-to-SQL Analytics Engine
==========================================================
Orchestrates the three Strands:
    Strand 1 (translation & guardrails) -> Strand 2 (execution & self-heal)
    -> Strand 3 (insight & presentation)

Usage:
    python3 main.py "Show customers who have more than 500000 in deposits"
    python3 main.py                 # interactive mode
"""

import sys
import pandas as pd

from strands.strand2_execution import run_with_self_healing, QueryExecutionError
from strands.strand1_sql_generation import SQLGuardrailError

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 120)

_MUTATION_WORDS = {"delete", "drop", "update", "insert", "alter", "truncate", "remove", "erase", "wipe"}


def answer_question(nl_query: str, verbose: bool = True) -> None:
    print(f"\n{'=' * 70}\nQ: {nl_query}\n{'=' * 70}")

    if any(word in nl_query.lower().split() for word in _MUTATION_WORDS):
        print("🛑 SECURITY GUARDRAIL BLOCKED THIS QUERY")
        print("   Reason: Input contains mutation intent. No SQL was executed.")
        return

    try:
        df, final_sql, attempt_log = run_with_self_healing(nl_query, verbose=verbose)
    except SQLGuardrailError as e:
        print("🛑 SECURITY GUARDRAIL BLOCKED THIS QUERY")
        print(f"   Reason: {e}")
        print("   No SQL was executed against the database.")
        return
    except QueryExecutionError as e:
        print(f"❌ Query failed after self-healing attempts.\n   {e}")
        return

    print(f"✅ Final SQL ({len(attempt_log)} attempt(s)):\n{final_sql}\n")
    print(f"📊 Result ({len(df)} row(s)):")
    if df.empty:
        print("   (no rows)")
    else:
        print(df.to_string(index=False))

    from strands.strand3_explanation import summarize_result
    summary = summarize_result(nl_query, df)
    print(f"\n💡 Insight: {summary}")


def main():
    if len(sys.argv) > 1:
        nl_query = " ".join(sys.argv[1:])
        answer_question(nl_query)
        return

    print("Finlytica Banking NLQ Engine - type a question in plain English.")
    print("Type 'exit' or 'quit' to stop.\n")
    while True:
        try:
            nl_query = input("Ask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not nl_query:
            continue
        if nl_query.lower() in ("exit", "quit"):
            print("Goodbye.")
            break
        answer_question(nl_query)


if __name__ == "__main__":
    main()
