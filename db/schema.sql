-- Finlytica Banking NLQ Engine — Schema Definition
-- Three normalized tables: customers (parent), deposits & loans (children, FK -> customers)

DROP TABLE IF EXISTS deposits CASCADE;
DROP TABLE IF EXISTS loans CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    customer_id     VARCHAR(20) PRIMARY KEY,
    customer_name   VARCHAR(120) NOT NULL,
    customer_age    INT NOT NULL CHECK (customer_age > 0),
    monthly_income  NUMERIC(14, 2) NOT NULL CHECK (monthly_income >= 0),
    city            VARCHAR(80) NOT NULL
);

CREATE TABLE deposits (
    deposit_id       VARCHAR(20) PRIMARY KEY,
    customer_id      VARCHAR(20) NOT NULL REFERENCES customers(customer_id),
    account_type     VARCHAR(30) NOT NULL,
    current_balance  NUMERIC(14, 2) NOT NULL CHECK (current_balance >= 0),
    opened_date      DATE NOT NULL
);

CREATE TABLE loans (
    loan_id         VARCHAR(20) PRIMARY KEY,
    customer_id     VARCHAR(20) NOT NULL REFERENCES customers(customer_id),
    loan_type       VARCHAR(30) NOT NULL,
    loan_amount     NUMERIC(14, 2) NOT NULL CHECK (loan_amount >= 0),
    interest_rate   NUMERIC(5, 2) NOT NULL CHECK (interest_rate >= 0),
    status          VARCHAR(20) NOT NULL
);

-- Indexes to keep joins and filters fast on the FK / commonly-filtered columns
CREATE INDEX idx_deposits_customer_id ON deposits(customer_id);
CREATE INDEX idx_loans_customer_id ON loans(customer_id);
CREATE INDEX idx_loans_status ON loans(status);
CREATE INDEX idx_loans_type ON loans(loan_type);
CREATE INDEX idx_deposits_account_type ON deposits(account_type);
CREATE INDEX idx_customers_city ON customers(city);

-- A dedicated read-only role for the NLQ engine to connect as.
-- This is a second, defense-in-depth security layer beyond the app-level SQL guardrail:
-- even if a malicious query slipped past validation, Postgres itself would reject writes.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'nlq_readonly') THEN
        CREATE ROLE nlq_readonly WITH LOGIN PASSWORD 'nlq_readonly_pw';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE finlytica_bank TO nlq_readonly;
GRANT USAGE ON SCHEMA public TO nlq_readonly;
GRANT SELECT ON customers, deposits, loans TO nlq_readonly;
-- Explicitly no INSERT/UPDATE/DELETE/TRUNCATE grants -> DB refuses mutations regardless of app logic.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nlq_readonly;
