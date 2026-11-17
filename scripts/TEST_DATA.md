# Test data

Overview: Local testing ke liye kaunse tournament/match ids use ho rahe hain, wo yahan
likha hai. Saare ids `dump-test-202512221924.sql` + `scripts/seed_regression.py` ke baad
ke state ke hain.

| What | Value |
|---|---|
| Tournament | `1` — "Men's Singles~Delhi~singles" (type `elimination`) |
| Teams | `T001` Thunder Smash, `T002` Lightning Serve, `T003` Smashers, `T004` Destroyers |
| Pool round | round `1`, pool `A`, matches `7`–`12` |
| Finalized regular matches (seed) | `7` 11-5, `8` 7-11, `9` 11-9, `10` 11-11 (tie) |
| In-progress (non-final) | `11` 5-3 |
| **Pending pool match** (walkover e2e) | `12` — T003 vs T004 |
| Knockout (seed via `/knockout`) | `13` SF1 (T001 vs T002, final 11-4), `14` SF2 (T003 vs T004, pending), `15` F1 |
| **Knockout match with successor** (walkover e2e) | `14` → successor `15` (slot `team2_id`, `predecessor_2 = 14`) |

The raw dump only has matches 7–12, all pending at 0-0. It has no finalized or knockout
matches, so the seed script creates them through the existing APIs before the
"before" snapshot is taken.

`/knockout` in v0 writes placeholder rows with `team_id = "TBD"`. That breaks the
`round.team_id → team.team_id` FK on the dump, so the seed inserts a `TBD` placeholder
team row. This affects test data only.

## Local environment used

- MySQL 8.0 in Docker: `docker run -d --name khel-mysql -e MYSQL_ROOT_PASSWORD=... -e MYSQL_DATABASE=khel_v0 -p 3307:3306 mysql:8.0`
- `.env` → `DB_PORT=3307`
- Reset: `MYSQL="docker exec -i khel-mysql mysql -uroot -p<pwd>" scripts/reset_db.sh [--migrate]`
