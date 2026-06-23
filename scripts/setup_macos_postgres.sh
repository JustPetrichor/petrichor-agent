#!/usr/bin/env bash

set -euo pipefail

FORMULA="postgresql@16"
DB_NAME="${DB_NAME:-petrichor}"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required but was not found." >&2
  exit 1
fi

if ! brew list --versions "$FORMULA" >/dev/null 2>&1; then
  echo "Installing $FORMULA with Homebrew..."
  brew install "$FORMULA"
fi

echo "Starting $FORMULA with brew services..."
brew services start "$FORMULA"

BREW_PREFIX="$(brew --prefix "$FORMULA")"
PSQL_BIN="$BREW_PREFIX/bin/psql"
CREATEDB_BIN="$BREW_PREFIX/bin/createdb"

if [ ! -x "$PSQL_BIN" ] || [ ! -x "$CREATEDB_BIN" ]; then
  echo "Could not find psql/createdb under $BREW_PREFIX/bin." >&2
  exit 1
fi

if ! "$PSQL_BIN" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
  echo "Creating database $DB_NAME..."
  "$CREATEDB_BIN" "$DB_NAME"
else
  echo "Database $DB_NAME already exists."
fi

cat <<EOF

Postgres is ready for the local harness.

Recommended local-only env overrides for a no-Docker setup:
  export POSTGRES_DSN="postgresql://$(whoami)@127.0.0.1:5432/$DB_NAME"
  export CLICKHOUSE_ENABLED=false
  export APP_ENABLE_TELEMETRY=false

Then run:
  uv run uvicorn app.main:app --reload
EOF
