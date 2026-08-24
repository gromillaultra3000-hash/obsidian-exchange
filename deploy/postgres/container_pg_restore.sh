#!/bin/sh
set -eu

container_name=${OBSIDIAN_POSTGRES_CONTAINER:-obsidian-postgres}
if [ "${1:-}" = "--version" ]; then
    exec docker exec -i "$container_name" pg_restore --version
fi
if [ "${1:-}" = "--list" ]; then
    exec docker exec -i "$container_name" pg_restore "$@"
fi

: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
exec docker exec -i -e PGOPTIONS="${PGOPTIONS:-}" "$container_name" \
    pg_restore -U "$PGUSER" -d "$PGDATABASE" "$@"
