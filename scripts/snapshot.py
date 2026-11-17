#!/usr/bin/env python3
"""
Overview: Regression snapshot tool. Saare standings + fixtures endpoints ko hit karke
unka JSON (pretty, key-sorted) ek folder mein likhta hai, taaki code change se pehle aur
baad ka output byte-by-byte compare ho sake (scripts/diff_snapshots.py). `--internal`
flag se `get_round_standings` (jo sirf /complete-round ke andar use hota hai) ko bhi
directly call karke dump karta hai.

Usage:
    python scripts/snapshot.py --base-url http://localhost:5001 --tournament-id 1 \
        --out-dir snapshots/before [--internal]
"""
import argparse
import json
import os
import sys

import requests

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def to_jsonable(obj):
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def write_json(out_dir, name, data):
    with open(os.path.join(out_dir, name), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(to_jsonable(data), f, indent=2, sort_keys=True)
        f.write('\n')


def internal_snapshots(tid, out_dir):
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    from app import app
    from models import Match
    from routes.round.round_completion import get_round_standings

    with app.app_context():
        round_ids = sorted({m.round_id for m in Match.query.filter_by(tournament_id=tid).all()}, key=int)
        data = {rid: get_round_standings(tid, rid) for rid in round_ids}
    write_json(out_dir, 'round_standings.json', data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', required=True)
    ap.add_argument('--tournament-id', type=int, required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--internal', action='store_true')
    args = ap.parse_args()

    base, tid = args.base_url.rstrip('/'), args.tournament_id
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    json_endpoints = {
        'standings.json': (f'/standings/{tid}', None),
        'overall_standings.json': (f'/overall-standings/{tid}', None),
        'second_place_standings.json': (f'/second-place-standings/{tid}', None),
        'fixtures.json': ('/get-match-fixtures', {'tournament_id': tid}),
        'cumulative_points.json': (f'/points/cumulative/{tid}', None),
        'knockout_top_teams.json': ('/knockout-top-teams',
                                    {'tournament_id': tid, 'round_id': 1, 'teams_per_pool': 4}),
    }
    for name, (path, params) in json_endpoints.items():
        r = requests.get(base + path, params=params, timeout=30)
        write_json(out_dir, name, {'status_code': r.status_code, 'body': r.json()})

    r = requests.get(base + '/get-match-fixtures/csv', params={'tournament_id': tid}, timeout=30)
    with open(os.path.join(out_dir, 'fixtures.csv'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'status_code={r.status_code}\n')
        f.write(r.text.replace('\r\n', '\n'))

    if args.internal:
        internal_snapshots(tid, out_dir)

    print(f'snapshot written to {out_dir}')


if __name__ == '__main__':
    main()
