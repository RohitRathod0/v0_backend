#!/usr/bin/env bash
# Overview: AC6 regression gate ek command mein - fresh dump restore + migration,
# existing APIs se seed, snapshot lo, aur snapshots/before se diff karo. Backend
# (python app.py) pehle se chal raha hona chahiye. Exit 0 = regular behaviour same hai.
#   MYSQL="docker exec -i khel-mysql mysql -uroot -p<pwd>" scripts/regression_gate.sh snapshots/after
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-snapshots/after}"
BASE="${BASE_URL:-http://localhost:5001}"
TID="${TOURNAMENT_ID:-1}"
PY="${PY:-python}"
export PY

bash scripts/reset_db.sh --migrate
$PY scripts/seed_regression.py --base-url "$BASE" --tournament-id "$TID"
$PY scripts/snapshot.py --base-url "$BASE" --tournament-id "$TID" --out-dir "$OUT" --internal
$PY scripts/diff_snapshots.py snapshots/before "$OUT"
