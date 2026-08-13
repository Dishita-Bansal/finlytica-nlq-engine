"""
seed.py — Loads Customer_File.xlsx, Loan_File.xlsx, and Deposit_File.xlsx
into the PostgreSQL `finlytica_bank` database, after (re)building the schema.

Usage:
    python3 db/seed.py
"""

import os
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# --- Config -----------------------------------------------------------------
DB_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": os.environ.get("PG_PORT", "5432"),
    "dbname": os.environ.get("PG_DB", "finlytica_bank"),
    "user": os.environ.get("PG_USER", "postgres"),
    "password": os.environ.get("PG_PASSWORD", "finlytica123"),
}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def apply_schema(conn):
    print("→ Applying schema (db/schema.sql)...")
    with open(SCHEMA_PATH, "r") as f:
        schema_sql = f.read()
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    print("  Schema applied: customers, deposits, loans (+ indexes + read-only role).")


def load_excel(filename):
    path = os.path.join(DATA_DIR, filename)
    return pd.read_excel(path)


def seed_customers(conn):
    df = load_excel("Customer_File.xlsx")
    rows = list(df[["customer_id", "customer_name", "customer_age", "monthly_income", "city"]]
                .itertuples(index=False, name=None))
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO customers (customer_id, customer_name, customer_age, monthly_income, city) VALUES %s",
            rows,
        )
    conn.commit()
    print(f"  Inserted {len(rows)} rows into customers.")


def seed_deposits(conn):
    df = load_excel("Deposit_File.xlsx")
    df["opened_date"] = pd.to_datetime(df["opened_date"]).dt.date
    rows = list(df[["deposit_id", "customer_id", "account_type", "current_balance", "opened_date"]]
                .itertuples(index=False, name=None))
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO deposits (deposit_id, customer_id, account_type, current_balance, opened_date) VALUES %s",
            rows,
        )
    conn.commit()
    print(f"  Inserted {len(rows)} rows into deposits.")


def seed_loans(conn):
    df = load_excel("Loan_File.xlsx")
    rows = list(df[["loan_id", "customer_id", "loan_type", "loan_amount", "interest_rate", "status"]]
                .itertuples(index=False, name=None))
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO loans (loan_id, customer_id, loan_type, loan_amount, interest_rate, status) VALUES %s",
            rows,
        )
    conn.commit()
    print(f"  Inserted {len(rows)} rows into loans.")


def main():
    print("=== Finlytica Banking DB Seeder ===")
    try:
        conn = get_connection()
    except psycopg2.OperationalError as e:
        print(f"ERROR: Could not connect to PostgreSQL: {e}")
        sys.exit(1)

    try:
        apply_schema(conn)
        print("→ Loading data from Excel files...")
        seed_customers(conn)
        seed_deposits(conn)
        seed_loans(conn)
        print("✅ Seed complete. Database 'finlytica_bank' is ready for querying.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
