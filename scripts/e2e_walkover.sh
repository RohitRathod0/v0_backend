#!/usr/bin/env bash
# Overview: Walkover feature ka end-to-end test (curl se real API hit karta hai). Fresh
# seeded DB pe chalta hai (RESET=1 dene pe khud reset + migrate + seed karta hai). Check
# karta hai: happy path, 400/404 validation, saare standings mein winner ko +1 win aur
# dono ko +1 played (points same), fixtures/CSV/DUPR export, regular score se override,
# knockout mein winner ka successor mein jaana aur re-declare pe duplicate Score rows na
# banna. JSON parsing ke liye jq ki jagah chhota python helper use hota hai.
#   MYSQL="docker exec -i khel-mysql mysql -uroot -p<pwd>" RESET=1 scripts/e2e_walkover.sh
set -uo pipefail
cd "$(dirname "$0")/.."

BASE="${BASE_URL:-http://localhost:5001}"
TID="${TOURNAMENT_ID:-1}"
PY="${PY:-python}"
DB_NAME="${DB_NAME:-khel_v0}"
MYSQL="${MYSQL:-mysql -h127.0.0.1 -P${DB_PORT:-3306} -uroot -p${DB_PASSWORD:-}}"
POOL_MATCH=12
POOL_T1=T003
POOL_T2=T004
KO_MATCH=14
KO_SUCC=15
TMP="$(mktemp -d)"
PASS=0
FAIL=0

if [[ "${RESET:-0}" == "1" ]]; then
  export PY
  bash scripts/reset_db.sh --migrate >/dev/null 2>&1
  $PY scripts/seed_regression.py --base-url "$BASE" --tournament-id "$TID" >/dev/null
fi

jget() { $PY -c "import json,sys; d=json.load(sys.stdin); v=eval(sys.argv[1]); print(json.dumps(v) if not isinstance(v,str) else v)" "$1"; }
sql() { $MYSQL -N -B "$DB_NAME" -e "$1" 2>/dev/null; }
check() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    PASS=$((PASS+1)); echo "  PASS  $name"
  else
    FAIL=$((FAIL+1)); echo "  FAIL  $name (expected: $expected, got: $actual)"
  fi
}
post() { curl -s -o "$TMP/body" -w "%{http_code}" -X POST "$BASE$1" -H 'Content-Type: application/json' -d "$2"; }
team_stat() { curl -s "$BASE/standings/$TID" | jget "[t for t in d['1']['pools']['A'] if t['team_id']=='$1'][0]['$2']"; }
overall_stat() { curl -s "$BASE/overall-standings/$TID" | jget "[t for t in d['standings'] if t['team_id']=='$1'][0]['$2']"; }
ko_stat() { curl -s "$BASE/knockout-top-teams?tournament_id=$TID&round_id=1&teams_per_pool=4" | jget "[t for t in d['top_teams']['A'] if t['team_id']=='$1'][0]['$2']"; }
round_stat() {
  $PY scripts/snapshot.py --base-url "$BASE" --tournament-id "$TID" --out-dir "$TMP/snap" --internal >/dev/null 2>&1
  jget "[t for t in d['1']['1']['pools']['A'] if t['team_id']=='$1'][0]['$2']" < "$TMP/snap/round_standings.json"
}
dupr_rows() { curl -s "$BASE/export-tournament-csv?tournament_id=$TID" | tail -n +2 | grep -c .; }

echo "== GET /match-outcomes"
OUT="$(curl -s "$BASE/match-outcomes")"
check "lists 2 outcomes" "2" "$(echo "$OUT" | jget 'len(d)')"
check "walkover is declared" "declared" "$(echo "$OUT" | jget "[o for o in d if o['key']=='walkover'][0]['winner_source']")"

echo "== validation (match $POOL_MATCH)"
check "unknown outcome -> 400" "400" "$(post /matches/$POOL_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"forfeit\",\"winner_team_id\":\"$POOL_T1\"}")"
check "unknown outcome message" "true" "$(jget "'Unknown outcome' in d['error']" < "$TMP/body")"
check "winner not in match -> 400" "400" "$(post /matches/$POOL_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"T001\"}")"
check "missing winner -> 400" "400" "$(post /matches/$POOL_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\"}")"
check "outcome regular -> 400" "400" "$(post /matches/$POOL_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"regular\",\"winner_team_id\":\"$POOL_T1\"}")"
check "regular message points to /update-score" "true" "$(jget "'/update-score' in d['error']" < "$TMP/body")"
check "missing tournament_id -> 400" "400" "$(post /matches/$POOL_MATCH/outcome "{\"outcome\":\"walkover\",\"winner_team_id\":\"$POOL_T1\"}")"
check "TBD team (match $KO_SUCC) -> 400" "400" "$(post /matches/$KO_SUCC/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"T001\"}")"
check "unknown match -> 404" "404" "$(post /matches/99999/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"$POOL_T1\"}")"
check "match still pending after bad requests" "pending" "$(sql "SELECT status FROM \`match\` WHERE id=$POOL_MATCH")"

echo "== walkover happy path (match $POOL_MATCH, winner $POOL_T2)"
declare -A B
for t in $POOL_T1 $POOL_T2; do
  for f in matches_played matches_won points_scored points_lost total_scores; do B[st_${t}_$f]="$(team_stat $t $f)"; done
  for f in matches_played matches_won points_scored total_scores; do B[ov_${t}_$f]="$(overall_stat $t $f)"; done
  for f in matches_played matches_won points_scored; do B[ko_${t}_$f]="$(ko_stat $t $f)"; done
  for f in matches_won total_scores points_scored; do B[rd_${t}_$f]="$(round_stat $t $f)"; done
done
DUPR_BEFORE="$(dupr_rows)"

check "declare -> 200" "200" "$(post /matches/$POOL_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"$POOL_T2\",\"reason\":\"$POOL_T1 did not show up\"}")"
check "response outcome" "walkover" "$(jget "d['outcome']" < "$TMP/body")"
check "response outcome_label" "Walkover" "$(jget "d['outcome_label']" < "$TMP/body")"
check "response winner" "$POOL_T2" "$(jget "d['winner_team_id']" < "$TMP/body")"
check "response is_final" "true" "$(jget "d['is_final']" < "$TMP/body")"
check "response scores 0-0" "0-0" "$(jget "f\"{d['team1_score']}-{d['team2_score']}\"" < "$TMP/body")"

SM="$(curl -s "$BASE/score/match?match_id=$POOL_MATCH&tournament_id=$TID")"
check "/score/match outcome" "walkover" "$(echo "$SM" | jget "d['outcome']")"
check "/score/match reason" "$POOL_T1 did not show up" "$(echo "$SM" | jget "d['outcome_reason']")"
check "/score/match status" "completed" "$(echo "$SM" | jget "d['status']")"
check "/score/match winner" "$POOL_T2" "$(echo "$SM" | jget "d['winner_team_id']")"
check "/score/match scores 0-0" "0-0" "$(echo "$SM" | jget "f\"{d['team1']['score']}-{d['team2']['score']}\"")"
check "db row" "walkover	1	completed	$POOL_T2" "$(sql "SELECT outcome, is_final, status, winner_team_id FROM \`match\` WHERE id=$POOL_MATCH")"
check "db score rows 0/0, no duplicates" "2	0" "$(sql "SELECT COUNT(*), SUM(score) FROM score WHERE match_id=$POOL_MATCH")"

FX="$(curl -s "$BASE/get-match-fixtures?tournament_id=$TID")"
check "fixtures match_status.outcome" "walkover" "$(echo "$FX" | jget "[m for m in d['matches'] if m['match_id']==$POOL_MATCH][0]['match_status']['outcome']")"
check "fixtures match_result stays 0-0" "0-0" "$(echo "$FX" | jget "[m for m in d['matches'] if m['match_id']==$POOL_MATCH][0]['match_result']")"
check "fixtures regular match outcome" "regular" "$(echo "$FX" | jget "[m for m in d['matches'] if m['match_id']==7][0]['match_status']['outcome']")"
check "fixtures CSV shows W/O" "1" "$(curl -s "$BASE/get-match-fixtures/csv?tournament_id=$TID" | grep -c ",$POOL_MATCH,.*W/O ($POOL_T2)")"
check "DUPR export excludes walkover" "$DUPR_BEFORE" "$(dupr_rows)"

echo "== standings after walkover"
check "/standings winner +1 win" "$((B[st_${POOL_T2}_matches_won]+1))" "$(team_stat $POOL_T2 matches_won)"
check "/standings winner +2 total_scores" "$((B[st_${POOL_T2}_total_scores]+2))" "$(team_stat $POOL_T2 total_scores)"
check "/standings winner +1 played" "$((B[st_${POOL_T2}_matches_played]+1))" "$(team_stat $POOL_T2 matches_played)"
check "/standings loser +1 played" "$((B[st_${POOL_T1}_matches_played]+1))" "$(team_stat $POOL_T1 matches_played)"
check "/standings loser wins unchanged" "${B[st_${POOL_T1}_matches_won]}" "$(team_stat $POOL_T1 matches_won)"
check "/standings winner points unchanged" "${B[st_${POOL_T2}_points_scored]}" "$(team_stat $POOL_T2 points_scored)"
check "/standings loser points_lost unchanged" "${B[st_${POOL_T1}_points_lost]}" "$(team_stat $POOL_T1 points_lost)"
check "/overall-standings winner +1 win" "$((B[ov_${POOL_T2}_matches_won]+1))" "$(overall_stat $POOL_T2 matches_won)"
check "/overall-standings loser +1 played" "$((B[ov_${POOL_T1}_matches_played]+1))" "$(overall_stat $POOL_T1 matches_played)"
check "/overall-standings points unchanged" "${B[ov_${POOL_T2}_points_scored]}" "$(overall_stat $POOL_T2 points_scored)"
check "/second-place-standings matches /standings pool A #2" "$(curl -s "$BASE/standings/$TID" | jget "d['1']['pools']['A'][1]['team_id']")" "$(curl -s "$BASE/second-place-standings/$TID" | jget "d['standings'][0]['team_id']")"
check "/second-place-standings same played/won as /standings" "$(curl -s "$BASE/standings/$TID" | jget "[d['1']['pools']['A'][1][k] for k in ('matches_played','matches_won')]")" "$(curl -s "$BASE/second-place-standings/$TID" | jget "[d['standings'][0][k] for k in ('matches_played','matches_won')]")"
check "/knockout-top-teams winner +1 win" "$((B[ko_${POOL_T2}_matches_won]+1))" "$(ko_stat $POOL_T2 matches_won)"
check "/knockout-top-teams played unchanged (0-0 already counted there)" "${B[ko_${POOL_T2}_matches_played]}" "$(ko_stat $POOL_T2 matches_played)"
check "/knockout-top-teams points unchanged" "${B[ko_${POOL_T2}_points_scored]}" "$(ko_stat $POOL_T2 points_scored)"
check "get_round_standings (/complete-round) winner +1 win" "$((B[rd_${POOL_T2}_matches_won]+1))" "$(round_stat $POOL_T2 matches_won)"
check "get_round_standings total_scores +1" "$((B[rd_${POOL_T2}_total_scores]+1))" "$(round_stat $POOL_T2 total_scores)"
check "get_round_standings loser wins unchanged" "${B[rd_${POOL_T1}_matches_won]}" "$(round_stat $POOL_T1 matches_won)"

echo "== override walkover with a real score"
check "/update-score final 11-5 -> 200" "200" "$(post /update-score "{\"match_id\":$POOL_MATCH,\"score\":\"11-5\",\"tournament_id\":$TID,\"final\":true}")"
check "override response outcome regular" "regular" "$(jget "d['outcome']" < "$TMP/body")"
check "override response winner from scores" "$POOL_T1" "$(jget "d['winner_team_id']" < "$TMP/body")"
check "override db row" "regular	$POOL_T1	NULL" "$(sql "SELECT outcome, winner_team_id, IFNULL(outcome_reason,'NULL') FROM \`match\` WHERE id=$POOL_MATCH")"
check "override standings: score winner gets the win" "$((B[st_${POOL_T1}_matches_won]+1))" "$(team_stat $POOL_T1 matches_won)"
check "override standings: former walkover winner loses it" "${B[st_${POOL_T2}_matches_won]}" "$(team_stat $POOL_T2 matches_won)"
check "override standings: points now count" "$((B[st_${POOL_T1}_points_scored]+11))" "$(team_stat $POOL_T1 points_scored)"
check "override DUPR export includes it again" "$((DUPR_BEFORE+1))" "$(dupr_rows)"

echo "== knockout walkover (match $KO_MATCH -> successor $KO_SUCC)"
check "declare knockout walkover -> 200" "200" "$(post /matches/$KO_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"T003\"}")"
check "successor team2 filled with winner" "T001	T003" "$(sql "SELECT team1_id, team2_id FROM \`match\` WHERE id=$KO_SUCC")"
SUCC_ROWS="$(sql "SELECT COUNT(*) FROM score WHERE match_id=$KO_SUCC")"
check "successor has winner score row once" "1" "$(sql "SELECT COUNT(*) FROM score WHERE match_id=$KO_SUCC AND team_id='T003'")"
check "re-declare -> 200" "200" "$(post /matches/$KO_MATCH/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"T003\"}")"
check "re-declare creates no duplicate successor Score rows" "$SUCC_ROWS" "$(sql "SELECT COUNT(*) FROM score WHERE match_id=$KO_SUCC")"
check "no duplicate (match, team) score rows" "0" "$(sql "SELECT COUNT(*) FROM (SELECT match_id, team_id FROM score WHERE match_id=$KO_SUCC GROUP BY match_id, team_id HAVING COUNT(*)>1) x")"
check "fixtures: successor shows winner" "T003" "$(curl -s "$BASE/get-match-fixtures?tournament_id=$TID" | jget "[m for m in d['matches'] if m['match_id']==$KO_SUCC][0]['team2']['team_id']")"
check "now the final can be declared (no TBD)" "200" "$(post /matches/$KO_SUCC/outcome "{\"tournament_id\":$TID,\"outcome\":\"walkover\",\"winner_team_id\":\"T001\"}")"

rm -rf "$TMP"
echo
echo "passed: $PASS  failed: $FAIL"
[[ $FAIL -eq 0 ]]
