-- =====================================================================
-- One-time setup (run as a superuser, connected to the "postgres" database):
--   psql -U postgres -d postgres -f SQL/00_create_database.sql
--
-- The database gets its own tablespace so its files live on the D: drive.
-- Change the LOCATION to any empty folder the PostgreSQL service account can
-- write to (on Windows: NT AUTHORITY\NetworkService).
-- =====================================================================

CREATE TABLESPACE medicaid_ts LOCATION 'D:/PostgresData/medicaid_coverage';

CREATE DATABASE medicaid_coverage
    WITH TABLESPACE = medicaid_ts
         ENCODING = 'UTF8'
         TEMPLATE = template0;

COMMENT ON DATABASE medicaid_coverage IS
    'Medicaid expansion and health insurance coverage, US counties 2008-2023 (portfolio project)';
