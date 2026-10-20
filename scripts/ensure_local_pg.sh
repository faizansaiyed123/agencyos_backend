#!/usr/bin/env bash
# Sandbox/dev helper: make sure a local Postgres 16 cluster is running with the roles
# and databases AgencyOS expects. Idempotent.
set -euo pipefail
if ! pg_lsclusters | grep -q "online"; then
  pg_ctlcluster 16 main start
  for _ in $(seq 1 20); do pg_isready -q && break; sleep 0.5; done
fi
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='agencyos'\"" | grep -q 1 || \
  su postgres -c "psql -c \"CREATE ROLE agencyos WITH LOGIN SUPERUSER PASSWORD 'agencyos'\""
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='agencyos_app'\"" | grep -q 1 || \
  su postgres -c "psql -c \"CREATE ROLE agencyos_app WITH LOGIN PASSWORD 'agencyos_app' NOSUPERUSER NOBYPASSRLS\""
for db in agencyos agencyos_test; do
  su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$db'\"" | grep -q 1 || \
    su postgres -c "createdb -O agencyos $db"
done
