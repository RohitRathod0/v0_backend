# Acceptance criteria checklist: Walkover outcome

Every criterion was checked on a freshly restored dump, using MySQL 8.0, Flask on :5001 and the Next.js production build on :3000.
Evidence files are in `docs/evidence/` (backend) and `v0_frontend/docs/screens/` (frontend).

## Backend

| AC | Criterion | Status | Evidence |
|---|---|---|---|
| AC1 | The migration runs cleanly on the dump DB; every existing row gets `outcome='regular'`; the down-migration reverses it | ✅ | `docs/evidence/migration.txt`: up → `regular 6`; down → columns gone; down again / up again → "skip" (idempotent); final state `regular 6`. |
| AC2 | `POST /matches/<id>/outcome` walkover → `is_final=1`, `status='completed'`, winner = declared team, scores 0-0, `outcome='walkover'` | ✅ | `docs/evidence/e2e_walkover.txt`, section "walkover happy path": response fields, `/score/match`, DB row `walkover 1 completed T004`, score rows `2 0`. |
| AC3 | The winner gets +1 win (+2 `total_scores` in `/standings`) in `/standings`, `/overall-standings`, `/second-place-standings`, `/complete-round` promotion and `/knockout-top-teams`; both teams +1 played; points unchanged | ✅ | `e2e_walkover.txt`, section "standings after walkover" (18 checks). `get_round_standings`, the function behind `/complete-round`, is checked directly via `snapshot.py --internal` (+1 win, `total_scores` +1). `/knockout-top-teams` already counted pending 0-0 matches as played, so there only the win changes (documented in README §5). |
| AC4 | A knockout walkover fills the right successor slot; re-declaring doesn't create duplicate `Score` rows | ✅ | `e2e_walkover.txt`, section "knockout walkover": successor `T001 T003`, row count unchanged after re-declare, no duplicate `(match, team)` rows. UI: `v0_frontend/docs/screens/09_knockout_bracket_walkover.png`. |
| AC5 | Bad input → 400 with a clear message | ✅ | `e2e_walkover.txt`, section "validation": unknown outcome, winner not in match, missing winner, `outcome:"regular"`, missing `tournament_id`, TBD team → 400; unknown match → 404; match untouched afterwards. |
| AC6 | Regression: JSON snapshots of all standings and fixtures endpoints are identical after the change | ✅ | `docs/evidence/regression_gate.txt`: fresh dump + migration + seed → 8 snapshot files `OK`, `ALL IDENTICAL`, exit 0. The baseline `snapshots/before/` comes from an untouched checkout of the original commit. |
| AC7 | Overriding a walkover with a normal final score → `outcome` back to `regular`, winner recalculated from scores | ✅ | `e2e_walkover.txt`, section "override walkover with a real score" (8 checks); UI: `walkthrough_output.txt` "override: outcome regular, winner T003 from 11-5". |
| AC8 | Walkovers excluded from the DUPR export | ✅ | `e2e_walkover.txt`: "DUPR export excludes walkover" (row count unchanged) and "override DUPR export includes it again" (+1). |
| AC9 | No winner-by-score comparisons in `routes/` outside `services/match_outcome.py` | ✅ | `docs/evidence/ac9_grep.txt`: both greps over `routes/` → no matches. The only score comparisons are in `services/match_outcome.py`. |

## Frontend

| AC | Criterion | Status | Evidence |
|---|---|---|---|
| AC10 | The referee can declare a walkover from the match screen in ≤3 clicks, with a confirmation step | ✅ | Pending match: **Declare Walkover** (on the "Match Not Started" prompt) → **team** → **Confirm** = 3 clicks. Confirm stays disabled until a team is picked. Screens `03_referee_pending_match_prompt.png`, `04_declare_walkover_dialog.png`; `walkthrough_output.txt` checks "confirm disabled/enabled". |
| AC11 | Tag, W/O and highlighted winner in public fixtures, the referee fixtures list, the match table and the knockout bracket | ✅ | `05_referee_list_walkover.png`, `06_public_fixtures_walkover.png`, `07_match_table_walkover.png`, `09_knockout_bracket_walkover.png`, `10_knockout_bracket_alt_walkover.png`, `11_referee_completed_walkover_tag.png`. |
| AC12 | Regular matches look exactly as before | ✅ | `OutcomeTag` renders nothing for `regular`; `formatSideResult` returns the raw score; the winner highlight is applied only to declared outcomes. Compare the regular cards in `01_public_fixtures_baseline.png` / `06_…` / `12_public_fixtures_after_override.png`. The normal Final flow still works ("regular Final flow unchanged" check). |
| AC13 | Outcome options come from `GET /match-outcomes`; no `'walkover'` literal in frontend logic | ✅ | `grep -rni walkover v0_frontend/src` → only a doc comment in `OutcomeTag.js` and the `.walkover` CSS modifier in `OutcomeTag.module.scss`. The buttons are built from `/match-outcomes` filtered by `winner_source`. |

## Other gates

- `pytest tests/ -q` → 34 passed (`docs/evidence/pytest.txt`).
- `npm run build` passes. It shows only the existing Sass "legacy JS API" deprecation warnings, which every SCSS module emits.
- `npm run lint`: the repo has no ESLint config, so `next lint` only starts its interactive setup. Not run; noted in README §8.
