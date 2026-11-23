#!/bin/sh
set -eu

: "${SGW_DB_PASSWORD:?SGW_DB_PASSWORD missing: run 'uv run sgw bootstrap' before the first start}"
: "${SGW_RUNTIME_PASSWORD:?SGW_RUNTIME_PASSWORD missing: run 'uv run sgw bootstrap' before the first start}"
: "${SGW_GATEWAY_PASSWORD:?SGW_GATEWAY_PASSWORD missing: run 'uv run sgw bootstrap' before the first start}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=owner_password="$SGW_DB_PASSWORD" --set=runtime_password="$SGW_RUNTIME_PASSWORD" \
  --set=gateway_password="$SGW_GATEWAY_PASSWORD" <<'SQL'
CREATE ROLE sgw LOGIN CREATEDB CREATEROLE PASSWORD :'owner_password';
CREATE ROLE sgw_app NOLOGIN;
CREATE ROLE sgw_readonly NOLOGIN;
CREATE ROLE sgw_llm_writer NOLOGIN;
CREATE ROLE sgw_runtime LOGIN CONNECTION LIMIT 30 IN ROLE sgw_app PASSWORD :'runtime_password';
CREATE ROLE sgw_gateway LOGIN CONNECTION LIMIT 5 IN ROLE sgw_llm_writer PASSWORD :'gateway_password';
CREATE DATABASE sgw OWNER sgw;
REVOKE ALL ON DATABASE sgw FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE sgw TO sgw;
GRANT CONNECT ON DATABASE sgw TO sgw_runtime, sgw_readonly, sgw_gateway, sgw_llm_writer;
SQL
