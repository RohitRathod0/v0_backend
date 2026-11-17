#!/usr/bin/env python3
"""
Overview: Dump DB mein saare matches pending 0-0 hain, isliye regression snapshot
ke liye thoda real data chahiye. Ye script sirf EXISTING public APIs (/update-score,
/update-match-status, /knockout) use karke - bilkul referee screen jaisa flow (Start
Match -> on-going, Final -> update-score + status completed) - DB ko richer state mein
laata hai: kuch finished matches, ek tie, ek in-progress match, ek pending pool match
(12) aur ek knockout bracket jisme SF1 finished hai aur SF2 pending hai. Same script
purane aur naye code dono pe chalao, phir snapshots compare karo.

v0 `/knockout` placeholder rows mein team_id="TBD" daalta hai jo test dump ke FK ko
todta hai, isliye sirf test data ke liye ek `TBD` placeholder team row insert karte hain.

Usage: python scripts/seed_regression.py --base-url http://localhost:5001 --tournament-id 1
"""
import argparse
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

POOL_PLAN = [
    (7, "11-5", True),
    (8, "7-11", True),
    (9, "11-9", True),
    (10, "11-11", True),
    (11, "5-3", False),
]


def ensure_tbd_team(tournament_id):
    import MySQLdb
    from config import Config

    conn = MySQLdb.connect(host=Config.DB_HOST, user=Config.DB_USER, passwd=Config.DB_PASSWORD,
                           db=Config.DB_NAME, port=int(Config.DB_PORT))
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM team WHERE team_id='TBD'")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO team (team_id, name, points, checked_in, tournament_id) "
                        "VALUES ('TBD', 'TBD', 0, 0, %s)", (tournament_id,))
            conn.commit()
    finally:
        conn.close()


def post(base, path, body):
    r = requests.post(f"{base}{path}", json=body, timeout=30)
    if r.status_code >= 300:
        raise SystemExit(f"POST {path} failed {r.status_code}: {r.text}")
    return r.json()


def referee_flow(base, tid, match_id, score, final):
    post(base, f'/update-match-status/{match_id}', {"tournament_id": tid, "status": "on-going"})
    post(base, '/update-score', {"match_id": match_id, "score": score,
                                 "tournament_id": tid, "final": final})
    if final:
        post(base, f'/update-match-status/{match_id}', {"tournament_id": tid, "status": "completed"})


def get(base, path, **params):
    r = requests.get(f"{base}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', default='http://localhost:5001')
    ap.add_argument('--tournament-id', type=int, default=1)
    args = ap.parse_args()
    base, tid = args.base_url.rstrip('/'), args.tournament_id

    for match_id, score, final in POOL_PLAN:
        referee_flow(base, tid, match_id, score, final)

    fixtures = get(base, '/get-match-fixtures', tournament_id=tid)['matches']
    if not any(m['pool'] == 'knockout' for m in fixtures):
        ensure_tbd_team(tid)
        post(base, '/knockout', {"tournament_id": tid,
                                 "team_ids": ["T001", "T002", "T003", "T004"],
                                 "current_round_id": 1})
        fixtures = get(base, '/get-match-fixtures', tournament_id=tid)['matches']

    semis = sorted((m for m in fixtures if m['pool'] == 'knockout' and m['match_name'].startswith('SF')),
                   key=lambda m: m['match_id'])
    referee_flow(base, tid, semis[0]['match_id'], "11-4", True)
    print("seeded:", {"pool_finals": [7, 8, 9, 10], "in_progress": 11, "pending_pool": 12,
                      "sf1": semis[0]['match_id'], "sf2_pending": semis[1]['match_id']})


if __name__ == '__main__':
    main()
