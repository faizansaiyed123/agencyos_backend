-- One-time cluster setup (run as a superuser). The app role must NOT own tables
-- and must NOT have BYPASSRLS, otherwise Row-Level Security is not enforced.
CREATE ROLE agencyos WITH LOGIN PASSWORD 'agencyos';            -- schema owner (migrations)
CREATE ROLE agencyos_app WITH LOGIN PASSWORD 'agencyos_app'     -- runtime role
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE agencyos OWNER agencyos;
