# Match outcomes: Walkover

This branch (`feature/walkover-outcome`) lets a referee or organizer finish a match as a **Walkover** by picking the winning team. The walkover counts in every standings endpoint, moves the winner on in knockouts, and shows up in the UI as a **Walkover** tag with **W/O** in place of the score. Regular matches behave exactly as before; a JSON snapshot diff proves it (see [Testing](#7-testing)).

Frontend changes are on the same branch name in `v0_frontend`. Its README links back here.

---

## 1. How scoring worked before this change

A match could only end one way: the referee typed a score and pressed **Final**. Nothing stored *how* the match ended, and each read path worked out the winner again from the raw scores (`team1_score > team2_score`) in its own copy of the logic.

| Concern | Where | Behaviour (v0) |
|---|---|---|
| Score write | `routes/score/score_core.py` → `POST /update-score` | Body `{match_id, score:"a-b", tournament_id, final, override}`. Upserts two `Score` rows. If `final`: `is_final=True`, `winner_team_id` = higher score (`None` on a tie), then `update_successor_match()` for knockouts. Emits `score_update` on `/scores`. `override` is read but unused. |
| Status write | `routes/match/match_core.py` → `POST /update-match-status/<id>` | `pending → on-going → completed`; `completed` also sets `is_final`. The referee screen sends this **in parallel** with update-score (`Promise.all`). |
| Knockout advance | `score_core.update_successor_match` | Writes the winner into the successor's `team1_id`/`team2_id` (via `predecessor_1/2`). When both slots are truthy it inserts 0-0 `Score` rows **without checking for existing ones**, so re-finalizing duplicates them. |
| Pool standings | `tournament_core.show_standings` → `GET /standings/<tid>` | Raw SQL JOINs `score s1`/`s2` (a match only shows up if both rows exist). **0-0 is skipped as "not played".** Win = higher score. `total_scores = wins × 2`. Sorted by `(total_scores, points_difference)`. |
| Overall standings | `show_overall_standings` → `GET /overall-standings/<tid>` | Same logic without the round grouping; also sorts by win %. |
| Second place | `show_second_place_standings` → `GET /second-place-standings/<tid>` | Same logic for round 1, grouped by pool; returns each pool's #2. |
| Round completion | `round_completion.get_round_standings` (used by `POST /complete-round`) | Iterates `Score` rows. Win = higher score. `total_scores = wins` (**not ×2**). Decides promotion. |
| Knockout seeding | `round_knockout.get_pool_standings` (used by `GET /knockout-top-teams`) | Counts a match as played when both teams are set, **even at 0-0**. Win = higher score. |
| Cumulative | `round_helpers.get_cumulative_points_for_round` | Points and points difference only; no wins. |
| Read APIs | `GET /get-match-fixtures`, `GET /score/match`, `GET /get-match-fixtures/csv` | `match_result:"a-b"`, `match_status:{winner_team_id,is_final,status}`. |
| DUPR export | `tournament_export.py` → `GET /export-tournament-csv` | Exports every `is_final` match as a rated game. |

**Root issue:** *how a match ended* (its outcome) and *what that outcome is worth* (scoring rules) were both implied by the raw scores, and that logic was copy-pasted across six functions. A walkover has no real score: stored as 0-0 it is skipped as "not played", and nothing can say "this team won without scoring more".

## 2. What changed and why

**State vs. scoring rules.** A match now stores its **state**, `match.outcome` (`regular` / `walkover`), which says *how* it ended. **What that state is worth** lives in one rule registry, `services/match_outcome.py`. Standings code never asks "is this a walkover?". It asks the registry what a match contributes, so adding an outcome never touches the standings code.

| Piece | File | What it does |
|---|---|---|
| `MatchOutcome` enum | `services/match_outcome.py` | `REGULAR`, `WALKOVER`. |
| `OutcomeRule` registry | `services/match_outcome.py` → `OUTCOME_RULES` | Per outcome: `label`, `winner_source` (`"scores"` or `"declared"`), `counts_points`, `always_counts_as_played`, `rating_eligible`. Frozen dataclasses: data, not `if` branches. |
| Central resolver | `resolve_winner()`, `standings_contribution()` | Every standings function calls `standings_contribution()` instead of comparing scores. For `scores` rules it reproduces the legacy comparison exactly; for `declared` rules the win comes from `winner_team_id`. |
| Single finalize path | `finalize_match()` | Used by `/update-score` (final) **and** the new outcome endpoint. In one transaction it validates against the rule, upserts both `Score` rows (walkover → 0/0, so the raw-SQL JOINs still find the match), sets `outcome`/`outcome_reason`/`winner_team_id`/`is_final`/`status='completed'`, advances the knockout successor, and commits (rolls back on error). Socket emission stays in the route layer so the module stays testable. |
| Idempotent knockout advance | `advance_to_successor()` (moved from `score_core.update_successor_match`, which is now a thin wrapper) | Creates successor `Score` rows only for `(match, team)` pairs that don't exist yet, so re-declaring or re-finalizing no longer duplicates them. |
| New endpoints | `routes/match/match_outcome_routes.py` | `POST /matches/<id>/outcome`, `GET /match-outcomes` (see §4). |
| Standings refactor | `tournament_core.show_standings`, `show_overall_standings`, `show_second_place_standings`, `round_completion.get_round_standings`, `round_knockout.get_pool_standings` | Only the **win/points arithmetic** moved to `standings_contribution()`. Each endpoint keeps its own quirks: the `×2` vs `×1` `total_scores`, its sort keys, and its "played" gate. The 0-0 gate became `if s1 == 0 and s2 == 0 and not contrib["counts_as_played_override"]`. |
| Read APIs | `match_fixtures.py`, `score_core.get_match_score` | Add `outcome`, `outcome_label`, `outcome_reason` (additive). The fixtures CSV shows `W/O (<winner>)`; the DUPR export skips non-`rating_eligible` outcomes. |
| Frontend | `v0_frontend` | `OutcomeTag` pill; `W/O` for the winner and `–` for the other side; existing winner highlight; referee **Declare Walkover** dialog driven by `GET /match-outcomes`. |

`round_helpers.get_cumulative_points_for_round` is deliberately untouched: it sums points only, and a walkover's 0-0 rows already contribute nothing.

## 3. Schema & migration

```sql
-- migrations/v2/001_add_match_outcome.sql
ALTER TABLE `match`
  ADD COLUMN `outcome` VARCHAR(20) NOT NULL DEFAULT 'regular',
  ADD COLUMN `outcome_reason` VARCHAR(255) NULL;
```

```bash
python migrations/v2/run_migration.py migrations/v2/001_add_match_outcome.sql        # up
python migrations/v2/run_migration.py migrations/v2/001_add_match_outcome.down.sql   # down
```

- `run_migration.py` reads `.env` through `config.Config`. Before each `ADD COLUMN`/`DROP COLUMN` it checks `INFORMATION_SCHEMA.COLUMNS`, so up and down are **idempotent** and safe to re-run. It follows the pattern of `migrations/bul/add_match_bracket_columns.py`.
- `db.create_all()` does not alter existing tables, so the migration must be run explicitly before starting the new code.
- **Why VARCHAR + app enum, not MySQL `ENUM`:** a new outcome (forfeit, bye) then needs no `ALTER TABLE`; the allowed values are validated in `get_rule()`.
- **Backfill:** `DEFAULT 'regular'` fills every existing row, so no data migration is needed. `get_rule(None/"")` also treats legacy/empty values as regular.
- `models.Match` has the matching columns (`server_default='regular'`).

## 4. API changes

All changes are additive: no field was renamed or removed.

| Change | Endpoint | Notes |
|---|---|---|
| **NEW** | `POST /matches/<id>/outcome` | Body `{tournament_id, outcome, winner_team_id, reason?}`. **400**: unknown outcome, winner not one of the two teams, a TBD team, missing fields, `outcome` decided by scores (`regular` → "use /update-score"), bad types, reason > 255 chars. **404**: match not found (or not in that tournament). **200**: update-score response shape plus outcome fields. Emits `score_update` on `/scores`. |
| **NEW** | `GET /match-outcomes` | `[{key, label, winner_source}]`. The frontend builds its "Declare …" buttons from this. |
| Modified | `POST /update-score` (`final: true`) | Goes through `finalize_match(regular)`, which also sets `status='completed'` (the referee screen already set that via its parallel call). Finalizing a former walkover with real scores turns it back into `regular`. Non-final updates are unchanged. Response adds `winner_team_id` + outcome fields. |
| Modified | `GET /get-match-fixtures` | `match_status` gains `outcome`, `outcome_label`, `outcome_reason`. `match_result` stays `"0-0"` for walkovers; the UI decides how to show it. |
| Modified | `GET /score/match` | Adds the outcome fields. |
| Modified | `GET /get-match-fixtures/csv` | Result column = `W/O (<winner_team_id>)` for declared outcomes. |
| Modified | `GET /export-tournament-csv` | Skips matches whose rule has `rating_eligible=False`. |
| Behaviour | 5 standings functions | Use `standings_contribution()`; output for regular data is byte-identical. |

```http
POST /matches/12/outcome
{"tournament_id": 1, "outcome": "walkover", "winner_team_id": "T004", "reason": "T003 did not show up"}

200 OK
{"message": "Match finalized as Walkover", "match_id": 12, "team1_id": "T003", "team1_score": 0,
 "team2_id": "T004", "team2_score": 0, "is_final": true, "status": "completed", "tournament_id": 1,
 "winner_team_id": "T004", "outcome": "walkover", "outcome_label": "Walkover",
 "outcome_reason": "T003 did not show up"}
```

```http
POST /matches/12/outcome   {"tournament_id": 1, "outcome": "walkover", "winner_team_id": "T001"}
400 {"error": "winner_team_id 'T001' is not one of the match teams (T003, T004)"}

POST /matches/12/outcome   {"tournament_id": 1, "outcome": "regular", "winner_team_id": "T003"}
400 {"error": "Outcome 'regular' is decided by scores; use /update-score"}

GET /match-outcomes
200 [{"key": "regular", "label": "Regular", "winner_source": "scores"},
     {"key": "walkover", "label": "Walkover", "winner_source": "declared"}]
```

## 5. Assumptions

| Field | Walkover winner | Walkover loser |
|---|---|---|
| matches_played | +1 | +1 |
| matches_won | +1 | 0 |
| points scored / lost / difference | unchanged (0) | unchanged (0) |
| total_scores | +2 in `/standings` family, +1 in `get_round_standings` (each endpoint keeps its own formula) | 0 |
| Knockout | moves into the successor slot | eliminated |
| DUPR export | excluded | excluded |

- **0 points:** inventing "11-0" would inflate points difference, which is the tiebreaker, and could unfairly change seeding. Changing this is one flag (`counts_points`).
- **Both teams +1 played.** Exception: `/knockout-top-teams` already counted every match with both teams set as played (even pending 0-0), so it only gains the win. That pre-existing quirk is kept.
- **Excluded from DUPR:** no game was played, so nothing should be rated.
- **Override:** finalizing a walkover with a real score through `/update-score` turns it back into `regular`, clears `outcome_reason` and recomputes the winner from the scores.
- **Correction allowed:** a walkover can be declared on an already-final match. Re-declaring is idempotent and creates no duplicate rows.
- **No auth:** v0 has none, so none was added.
- **Score rows** for the finalize path are keyed on `match.tournament_id`, not the request's `tournament_id`.

## 6. How to add Forfeit / Bye

**Forfeit** (a team withdraws mid-match; the organizer declares the winner):

1. `services/match_outcome.py`: add `FORFEIT = "forfeit"` to `MatchOutcome`.
2. Add one rule: `MatchOutcome.FORFEIT: OutcomeRule(MatchOutcome.FORFEIT, "Forfeit", WINNER_DECLARED, counts_points=<decision>, always_counts_as_played=True, rating_eligible=False)`.
3. That's it. `GET /match-outcomes` lists it, so the referee screen shows **Declare Forfeit** automatically; `OutcomeTag` shows the label from the API; the standings, CSV and DUPR export follow the rule flags. Optionally add a `.forfeit` colour to `OutcomeTag.module.scss`; it falls back to the default pill.

**Bye** (a team advances with no opponent) needs the same two lines plus one real change. A bye is a *single-team* match (`team2_id` is null). `resolve_winner()` currently requires both teams for declared outcomes and rejects TBD/null teams. A bye needs that check relaxed for its rule (for example a rule field like `requires_opponent=False`), and `finalize_match()` would upsert only the present team's `Score` row. The raw-SQL standings JOIN `s2` would then skip it, which is the right behaviour for a bye (it shouldn't count as a played match).

## 7. Testing

```bash
pip install -r requirements.txt pytest requests

# unit tests: pure logic, no DB, no Flask app (34 tests)
pytest tests/ -q

# regression gate (AC6): fresh dump + migration, seed through the existing APIs,
# snapshot every standings/fixtures endpoint (+ get_round_standings), diff vs snapshots/before
MYSQL="mysql -h127.0.0.1 -P3306 -uroot -p<pwd>" scripts/regression_gate.sh snapshots/after

# end-to-end walkover checks against the running API (64 checks)
MYSQL="mysql -h127.0.0.1 -P3306 -uroot -p<pwd>" RESET=1 scripts/e2e_walkover.sh
```

- `snapshots/before/` was taken from an **untouched checkout of the original commit**. `scripts/seed_regression.py` replays the real referee flow (Start Match → `on-going`; Final → update-score + status `completed`) to create finished, tied, in-progress and knockout matches, because the dump only contains pending 0-0 matches.
- `scripts/diff_snapshots.py` ignores only the new additive keys `outcome`, `outcome_label`, `outcome_reason` in the fixtures JSON.
- `e2e_walkover.sh` uses curl with a small inline Python JSON helper instead of `jq`.
- Outputs from the final run: `docs/evidence/`. Acceptance criteria walk-through: `docs/AC_CHECKLIST.md`. Test ids: `scripts/TEST_DATA.md`.
- Frontend browser walkthrough + screenshots: `v0_frontend/scripts/ui_walkthrough.py`, `v0_frontend/docs/screens/`.

## 8. Observed v0 issues (documented, not fixed unless touched)

- `override` in `/update-score` is never used, and the frontend checks for an `"already been finalized"` error the backend never sends.
- The frontend read `resp.winner_team_id` from update-score, but the backend never returned it. *(Fixed for free by the new response shape.)*
- `update_successor_match` inserted duplicate successor `Score` rows on re-finalize. *(Fixed in `advance_to_successor`, since that code was touched.)*
- `update_successor_match` treats the placeholder `"TBD"` as a real team (`if team1_id and team2_id`), so finalizing one semi already creates a `Score` row for `TBD` in the final. Kept as-is to preserve regular behaviour.
- `/knockout` inserts `Round`/`Match` rows with `team_id="TBD"`, which violates the `team` foreign key on the test dump unless a `TBD` team row exists (the seed script adds one for testing).
- `total_scores` is wins×2 in `/standings` but wins×1 in `get_round_standings`.
- `show_standings` treats a real 0-0 as "not played", while `get_pool_standings` counts it as played.
- Winner logic was duplicated across six functions. *(This refactor fixes it.)*
- Score and status are written by two parallel requests, so they aren't atomic. *(The walkover path is a single call.)*
- `Score.points` and `Team.points` are unused.
- Debug `print`s everywhere; CORS is `*`.
- The dump's `SET @@GLOBAL.GTID_PURGED` line fails on re-import into a server that already has GTIDs (`scripts/reset_db.sh` strips it).
- Frontend: `npm install` fails on a peer-dependency conflict (`@g-loot/react-tournament-brackets` wants `styled-components@^4`), so it needs `--legacy-peer-deps`. There is no ESLint config, so `npm run lint` only starts the interactive setup.
- The referee screen's **Table** tab (`RefereeMatchTable`) was outside the PRD's scope, so it still shows `0-0` for a walkover.

## 9. What I'd improve with more time

- **Alembic migrations** instead of ad-hoc SQL + runner scripts.
- **Atomic score + status write:** drop the frontend `Promise.all(update-score, update-match-status)` now that `finalize_match` sets the status.
- **Unify the six standings functions** into one service; they differ only in grouping, gates and formulas.
- **Per-tournament walkover points**, e.g. a tournament setting that overrides `counts_points` or awards a fixed score.
- **Audit log** for outcome changes (who declared, when, previous value).
- **Auth on referee endpoints.**
- **Integration tests against a MySQL test container** in CI instead of a local Docker + shell scripts.

---

## Pooling reference

| **# Pools** | **Same-Pool Pairing**                        | **Near-pool Pairing**                       | **Half-Pool Pairing**                     | **Far-Pool Pairing**                     |
|-------------|----------------------------------------------|---------------------------------------------|-------------------------------------------|------------------------------------------|
| **2 Pools** | A1 vs A2, B1 vs B2                           | A1 vs B2, A2 vs B1                         | A1 vs A2, B1 vs B2 (same as "same-pool")  | A1 vs B2, A2 vs B1                       |
| **4 Pools** | A1 vs A2, B1 vs B2, C1 vs C2, D1 vs D2       | A1 vs B2, A2 vs B1, C1 vs D2, C2 vs D1     | A1 vs B2, A2 vs B1, C1 vs D2, C2 vs D1    | A1 vs D2, A2 vs D1, B1 vs C2, B2 vs C1   |
| **8 Pools** | A1 vs A2, B1 vs B2, C1 vs C2, D1 vs D2, E1 vs E2, F1 vs F2, G1 vs G2, H1 vs H2 | A1 vs B2, A2 vs B1, C1 vs D2, C2 vs D1, E1 vs F2, E2 vs F1, G1 vs H2, G2 vs H1 | A1 vs D2, A2 vs D1, E1 vs H2, H1 vs E2    | A1 vs H2, A2 vs H1, B1 vs G2, B2 vs G1, C1 vs F2, C2 vs F1, D1 vs E2, D2 vs E1 |

