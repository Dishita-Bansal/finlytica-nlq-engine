"""
Strand 1 — Translation & Safety Strand
========================================
Responsibility: turn an English question into a single, safe, read-only
PostgreSQL SELECT statement.

This module has two independent halves, deliberately kept separate:

1. `generate_sql()`      — calls Claude to produce a candidate SQL string.
2. `validate_sql_safety()` — a pure-Python guardrail with ZERO dependency on
                              the model. It re-checks the SQL text itself, so
                              a prompt-injected or hallucinated mutating
                              statement is still blocked even if Claude
                              "goes rogue" or the prompt is manipulated.

Defense in depth: this guardrail is layer 1. Layer 2 is the `nlq_readonly`
Postgres role (see db/schema.sql) which physically lacks INSERT/UPDATE/
DELETE/DDL grants, so even a query that slipped past this function would
still be rejected by the database itself.
"""

import os
import re
import anthropic

from config import SCHEMA_METADATA, ALLOWED_TABLES, SQL_GENERATION_MODEL

# --- Guardrail ----------------------------------------------------------------

# Any of these keywords appearing as a standalone SQL keyword = reject.
# Word-boundary regex avoids false positives like a city literally named
# "Updateville" inside a WHERE clause string.
_FORBIDDEN_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "GRANT",
    "REVOKE", "CREATE", "EXEC", "EXECUTE", "CALL", "MERGE", "COPY",
    "VACUUM", "REINDEX", "REPLACE", "LOCK", "COMMENT", "SET", "RESET",
    "DO", "PREPARE", "DEALLOCATE", "LISTEN", "NOTIFY", "SECURITY",
]

_FORBIDDEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(_FORBIDDEN_KEYWORDS) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

# Blocks SQL comment syntax often used to smuggle statements past naive filters.
_COMMENT_PATTERN = re.compile(r"(--|/\*|\*/)")


class SQLGuardrailError(Exception):
    """Raised when a candidate SQL statement fails the safety guardrail."""
    pass


def validate_sql_safety(sql: str) -> str:
    """
    Validates that `sql` is a single, read-only SELECT statement touching only
    the allowed tables. Raises SQLGuardrailError if any check fails.
    Returns the cleaned SQL (trailing semicolon stripped) on success.
    """
    if not sql or not sql.strip():
        raise SQLGuardrailError("Empty SQL statement.")

    cleaned = sql.strip()

    # Strip a single trailing semicolon (harmless), but reject multiple
    # statements (semicolon anywhere else = statement stacking attempt).
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if ";" in cleaned:
        raise SQLGuardrailError(
            "Multiple SQL statements detected (statement stacking is not allowed)."
        )

    # Block comment-based smuggling.
    if _COMMENT_PATTERN.search(cleaned):
        raise SQLGuardrailError("SQL comments are not permitted in generated queries.")

    # Must start with SELECT or a read-only CTE (WITH ... SELECT).
    first_token_match = re.match(r"\s*(\w+)", cleaned, re.IGNORECASE)
    first_token = first_token_match.group(1).upper() if first_token_match else ""
    if first_token not in ("SELECT", "WITH"):
        raise SQLGuardrailError(
            f"Only SELECT statements are allowed. Statement starts with '{first_token}'."
        )

    # Block any mutating/DDL/DCL keyword appearing anywhere in the statement.
    match = _FORBIDDEN_PATTERN.search(cleaned)
    if match:
        raise SQLGuardrailError(
            f"Blocked forbidden keyword '{match.group(1).upper()}'. "
            "Only read-only SELECT queries against customers/deposits/loans are permitted."
        )

    # Restrict table references to the known schema (best-effort allowlist check).
    # CTE names defined via WITH ... AS (...) are also allowed, since they're
    # not real tables -- they're aliases scoped to this query.
    cte_names = set(
        t.lower() for t in re.findall(r"\b(?:WITH|,)\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", cleaned, re.IGNORECASE)
    )
    referenced_tables = set(
        t.lower() for t in re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", cleaned, re.IGNORECASE)
    )
    unknown_tables = referenced_tables - ALLOWED_TABLES - cte_names
    if unknown_tables:
        raise SQLGuardrailError(
            f"Query references unknown/disallowed table(s): {', '.join(unknown_tables)}. "
            f"Only {', '.join(sorted(ALLOWED_TABLES))} are permitted."
        )

    return cleaned


# --- SQL generation via Claude ------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """You are a PostgreSQL query generator for a banking analytics system.

You are given the following database schema:
{schema}

Rules you MUST follow:
1. Output ONLY a single valid PostgreSQL SELECT statement. No prose, no markdown code fences, no explanation.
2. NEVER generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, GRANT, or any other mutating/DDL statement.
   You are a read-only analytics tool. If the user's request implies a mutation, still respond with a
   SELECT statement that best answers the analytical intent, never a mutating one.
3. Only reference the tables and columns listed above. Never invent columns or tables.
4. Use explicit JOINs with ON clauses (not implicit comma joins).
5. Use ILIKE for case-insensitive text matching where appropriate.
6. Do not include a trailing semicolon issue -- a single trailing semicolon is fine, but never multiple statements.
7. Prefer clear column aliases for aggregate/computed columns (e.g. SUM(current_balance) AS total_deposits).
8. Return only the raw SQL text, nothing else.
"""


def generate_sql(natural_language_query: str, correction_context: dict | None = None) -> str:
    """
    Calls Claude to translate `natural_language_query` into a PostgreSQL SELECT.

    If `correction_context` is provided (a dict with 'failed_sql' and 'error'),
    this is the self-healing retry path: the previous bad SQL and the DB error
    trace are fed back so the model can fix its own mistake.
    """
    client = anthropic.Anthropic()

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(schema=SCHEMA_METADATA)

    if correction_context:
        user_message = (
            f"Original question: {natural_language_query}\n\n"
            f"Your previous SQL attempt failed when executed against PostgreSQL:\n\n"
            f"--- Failed SQL ---\n{correction_context['failed_sql']}\n\n"
            f"--- Database error ---\n{correction_context['error']}\n\n"
            "Fix the query and return ONLY the corrected SQL statement."
        )
    else:
        user_message = f"Question: {natural_language_query}\n\nWrite the PostgreSQL SELECT statement."

    response = client.messages.create(
        model=SQL_GENERATION_MODEL,
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_sql = "".join(block.text for block in response.content if block.type == "text").strip()

    # Defensive cleanup in case the model wraps the SQL in markdown fences
    # despite instructions not to.
    raw_sql = re.sub(r"^```(?:sql)?\s*", "", raw_sql, flags=re.IGNORECASE)
    raw_sql = re.sub(r"\s*```$", "", raw_sql)

    return raw_sql.strip()
