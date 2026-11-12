-- Zero-trust layer #1: dedicated read-only database role for the analyst agent.
-- The application never connects as the owner/superuser.
-- NOTE: demo password; change it for any non-local deployment.

CREATE ROLE analyst_ro LOGIN PASSWORD 'analyst_ro_password' CONNECTION LIMIT 20;

DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO analyst_ro', current_database());
END
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM analyst_ro;

-- Defence in depth: even if a write statement slipped through, the session is read-only
-- and runaway queries are cancelled by the server.
ALTER ROLE analyst_ro SET default_transaction_read_only = on;
ALTER ROLE analyst_ro SET statement_timeout = '5000ms';
ALTER ROLE analyst_ro SET idle_in_transaction_session_timeout = '10000ms';
