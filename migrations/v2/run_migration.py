#!/usr/bin/env python3
"""
Overview: v2 SQL migration runner. `.env` (config.Config) se DB padhta hai aur di gayi
.sql file ke statements chalata hai. Idempotent hai: har `ALTER TABLE ... ADD COLUMN`
/ `DROP COLUMN` clause ke liye pehle INFORMATION_SCHEMA.COLUMNS check karta hai - column
pehle se hai to ADD skip, nahi hai to DROP skip. Isliye up/down kitni bhi baar chalao,
safe hai. (Pattern: migrations/bul/add_match_bracket_columns.py)

Usage:
    python migrations/v2/run_migration.py migrations/v2/001_add_match_outcome.sql
    python migrations/v2/run_migration.py migrations/v2/001_add_match_outcome.down.sql
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from config import Config
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

ALTER_RE = re.compile(r'^\s*ALTER\s+TABLE\s+`?(\w+)`?\s+(.*)$', re.IGNORECASE | re.DOTALL)
ADD_RE = re.compile(r'^\s*ADD\s+COLUMN\s+`?(\w+)`?', re.IGNORECASE)
DROP_RE = re.compile(r'^\s*DROP\s+COLUMN\s+`?(\w+)`?', re.IGNORECASE)


def split_top_level(sql, sep):
    parts, buf, depth, quote = [], [], 0, None
    for ch in sql:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if ''.join(buf).strip():
        parts.append(''.join(buf).strip())
    return parts


def read_statements(path):
    with open(path, encoding='utf-8') as f:
        lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith('--')]
    return [s for s in split_top_level('\n'.join(lines), ';') if s]


def existing_columns(session, table):
    rows = session.execute(text("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :table
    """), {'db': Config.DB_NAME, 'table': table}).fetchall()
    return {r[0] for r in rows}


def plan_statement(session, stmt):
    m = ALTER_RE.match(stmt)
    if not m:
        return stmt
    table, body = m.group(1), m.group(2)
    cols = existing_columns(session, table)
    keep = []
    for clause in split_top_level(body, ','):
        add, drop = ADD_RE.match(clause), DROP_RE.match(clause)
        if add and add.group(1) in cols:
            print(f"skip: column `{table}`.`{add.group(1)}` already exists")
            continue
        if drop and drop.group(1) not in cols:
            print(f"skip: column `{table}`.`{drop.group(1)}` does not exist")
            continue
        keep.append(clause)
    if not keep:
        return None
    return f"ALTER TABLE `{table}`\n  " + ',\n  '.join(keep)


def run(path):
    app = Flask(__name__)
    app.config.from_object(Config)
    db = SQLAlchemy(app)
    with app.app_context():
        try:
            for stmt in read_statements(path):
                planned = plan_statement(db.session, stmt)
                if planned is None:
                    continue
                print(f"Executing:\n{planned}")
                db.session.execute(text(planned))
            db.session.commit()
            print(f"Migration {os.path.basename(path)} completed")
        except Exception as e:
            db.session.rollback()
            print(f"Error running migration: {e}")
            raise


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    run(sys.argv[1])
