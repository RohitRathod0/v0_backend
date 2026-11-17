#!/usr/bin/env python3
"""
Overview: Do snapshot folders (scripts/snapshot.py ka output) compare karta hai. Koi bhi
difference mila to unified diff print karke exit 1. Fixtures JSON mein naye additive keys
(`outcome`, `outcome_label`, `outcome_reason`) ignore hote hain kyunki wo by design add
hue hain - baaki sab byte-identical hona chahiye.

Usage: python scripts/diff_snapshots.py snapshots/before snapshots/after
"""
import difflib
import json
import os
import sys

ADDITIVE_KEYS = {'outcome', 'outcome_label', 'outcome_reason'}
FIXTURE_FILES = {'fixtures.json'}


def strip_keys(obj):
    if isinstance(obj, dict):
        return {k: strip_keys(v) for k, v in obj.items() if k not in ADDITIVE_KEYS}
    if isinstance(obj, list):
        return [strip_keys(v) for v in obj]
    return obj


def load(path, name):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if name in FIXTURE_FILES:
        text = json.dumps(strip_keys(json.loads(text)), indent=2, sort_keys=True) + '\n'
    return text.splitlines(keepends=True)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    dir_a, dir_b = sys.argv[1], sys.argv[2]
    names = sorted(set(os.listdir(dir_a)) | set(os.listdir(dir_b)))
    failed = False
    for name in names:
        pa, pb = os.path.join(dir_a, name), os.path.join(dir_b, name)
        if not (os.path.exists(pa) and os.path.exists(pb)):
            print(f'MISSING: {name} only in {dir_a if os.path.exists(pa) else dir_b}')
            failed = True
            continue
        a, b = load(pa, name), load(pb, name)
        if a != b:
            failed = True
            sys.stdout.writelines(difflib.unified_diff(a, b, fromfile=pa, tofile=pb))
        else:
            print(f'OK: {name}')
    print('DIFF FOUND' if failed else 'ALL IDENTICAL')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
