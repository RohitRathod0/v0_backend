#!/usr/bin/env bash
# Overview: DB ko fresh dump se dobara banata hai (drop -> create -> import; dump ki
# GTID_PURGED line hata dete hain taaki baar-baar import ho sake), aur
# `--migrate` dene pe v2 migration bhi chala deta hai. MYSQL env var se client command
# override kar sakte ho, jaise docker ke liye:
#   MYSQL="docker exec -i khel-mysql mysql -uroot -pkhelroot" scripts/reset_db.sh --migrate
set -euo pipefail
cd "$(dirname "$0")/.."

DB_NAME="${DB_NAME:-khel_v0}"
MYSQL="${MYSQL:-mysql -h127.0.0.1 -P${DB_PORT:-3306} -uroot -p${DB_PASSWORD:-}}"
PY="${PY:-python}"

$MYSQL -e "DROP DATABASE IF EXISTS \`$DB_NAME\`; CREATE DATABASE \`$DB_NAME\`;"
sed '/GTID_PURGED/d' dump-test-202512221924.sql | $MYSQL "$DB_NAME"
echo "database $DB_NAME restored from dump"

if [[ "${1:-}" == "--migrate" ]]; then
  $PY migrations/v2/run_migration.py migrations/v2/001_add_match_outcome.sql
fi
