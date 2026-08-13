"""
Strand 3 — Insight & Presentation Strand
===========================================
Responsibility: look at the resulting DataFrame and the original question,
and produce a short, direct, 2-sentence natural-language answer.

This strand describes the result table and nothing more. It never counts rows
(the count is computed here in Python and handed to the model as fact) and
never re-evaluates a numeric condition -- Strand 1's SQL has already decided
which rows qualify, so any re-derivation here can only introduce a
contradiction. See the SUMMARY_MODEL notes in config.py for the incident that
motivated both that rule and the model choice.
"""

import pandas as pd
import anthropic

from config import SUMMARY_MODEL

MAX_ROWS_FOR_SUMMARY = 30  # keep the prompt small; summarize a sample if huge


def summarize_result(natural_language_query: str, df: pd.DataFrame) -> str:
    """
    Returns a 2-sentence plain-English summary answering the original
    question, grounded in the actual query result.
    """
    if df.empty:
        return "No matching records were found for this query."

    # The row count is computed here, not by the model. Asking a model to count
    # rows in a CSV is exactly where the "four customers" / "7 rows" mismatch
    # came from, so we hand it the number as an authoritative fact instead.
    row_count = len(df)
    sample = df.head(MAX_ROWS_FOR_SUMMARY)
    table_text = sample.to_csv(index=False)
    sample_note = (
        f" — a truncated sample: the first {MAX_ROWS_FOR_SUMMARY} of {row_count} rows"
        if row_count > MAX_ROWS_FOR_SUMMARY else ""
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=250,
        system=(
            "You are a banking data analyst assistant. You are given a user's original "
            "question, the exact number of rows the query returned, and the result table.\n\n"
            "The result table is the ground truth. It was produced by a SQL query that has "
            "ALREADY applied every filter and condition in the question. Every row in the "
            "table satisfies the question's criteria by definition. Your only job is to "
            "describe what is already in the table.\n\n"
            "Rules — all of them are absolute:\n"
            "1. Report the row count exactly as given under ROW COUNT. Never count the rows "
            "yourself, never estimate, and never state any other number of records.\n"
            "2. Never recalculate or re-evaluate anything. Do no arithmetic, comparisons, "
            "ratios, multiples, percentages, or threshold checks on the values. Do not check "
            "whether a row 'really' meets the criteria — that question is already settled.\n"
            "3. Never state or imply that any row in the table fails the criteria, is an "
            "exception, an outlier, borderline, or included in error. There are no exceptions.\n"
            "4. Only cite names, values, and figures that appear literally in the table. Do "
            "not introduce any number that is not printed there.\n"
            "5. Never contradict yourself: if you mention a customer, they qualify.\n"
            "6. If the table is marked as a truncated sample, describe only the rows shown, "
            "but still report the full ROW COUNT as the total.\n\n"
            "Write EXACTLY two sentences that directly answer the question. Be specific and "
            "concrete. No preamble, no markdown, just the two sentences."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Original question: {natural_language_query}\n\n"
                f"ROW COUNT (authoritative — this is the number of matching records): {row_count}\n\n"
                f"Result data (CSV{sample_note}):\n{table_text}"
            ),
        }],
    )

    return "".join(block.text for block in response.content if block.type == "text").strip()
