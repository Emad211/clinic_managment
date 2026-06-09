-- Runs once on first Postgres init (mounted into /docker-entrypoint-initdb.d/).
-- Creates the UNPRIVILEGED application role the app process connects as.
--
-- RLS only truly isolates tenants when the runtime role is NOT a superuser and
-- does NOT have BYPASSRLS (proven by `manage.py verify_rls`). The superuser
-- (postgres) is used only for migrations + global seeding via the entrypoint.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clinic_app') THEN
    CREATE ROLE clinic_app LOGIN PASSWORD 'clinic_app_pw'
      NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;

GRANT CONNECT ON DATABASE clinic_platform TO clinic_app;
GRANT USAGE ON SCHEMA public TO clinic_app;
-- Tables are created later by migrations (as postgres). Default privileges make
-- future tables/sequences readable+writable by clinic_app automatically.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clinic_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO clinic_app;
