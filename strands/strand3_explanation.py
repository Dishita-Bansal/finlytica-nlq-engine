"""
Strand 3 — Insight & Presentation Strand
===========================================
Responsibility: look at the resulting DataFrame and the original question,
and produce a short, direct, 2-sentence natural-language answer.

Uses a fast/cheap model (Haiku) since summarizing an already-computed,
already-small result table is a lightweight task that doesn't need the
heavier reasoning model used for SQL generation in Strand 1.
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

    sample = df.head(MAX_ROWS_FOR_SUMMARY)
    table_text = sample.to_csv(index=False)
    truncated_note = (
        f"\n(Showing first {MAX_ROWS_FOR_SUMMARY} of {len(df)} total rows.)"
        if len(df) > MAX_ROWS_FOR_SUMMARY else ""
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=250,
        system=(
            "You are a banking data analyst assistant. You are given a user's original "
            "question and the resulting data table. Write EXACTLY two sentences that "
            "directly answer the question using the actual numbers/names in the data. "
            "Be specific and concrete. No preamble, no markdown, just the two sentences."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Original question: {natural_language_query}\n\n"
                f"Result data (CSV):\n{table_text}{truncated_note}"
            ),
        }],
    )

    return "".join(block.text for block in response.content if block.type == "text").strip()
