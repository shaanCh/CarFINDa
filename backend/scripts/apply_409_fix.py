#!/usr/bin/env python3
"""
Apply the 409 Conflict fix migration to Supabase.

Uses DATABASE_URL from .env to run the migration SQL directly.
Requires: pip install psycopg2-binary python-dotenv

Usage:
  cd backend && python scripts/apply_409_fix.py

Or run the SQL manually in Supabase Dashboard:
  SQL Editor -> paste backend/supabase/migrations/004_fix_409_conflicts.sql -> Run
"""

import os
import sys
from pathlib import Path

# Load .env from project root
ROOT = Path(__file__).resolve().parents[2]
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL not set in .env")
    sys.exit(1)

MIGRATIONS = [
    "004_fix_409_conflicts.sql",
    "005_fix_search_listings_rpc_columns.sql",
    "006_align_with_actual_listings_schema.sql",
]

try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2


def main():
    migrations_dir = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    for name in MIGRATIONS:
        path = migrations_dir / name
        if not path.exists():
            print(f"Skipping {name} (not found)")
            continue
        sql = path.read_text()
        print(f"Applying migration: {name}")
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(sql)
            cur.close()
            conn.close()
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  FAILED: {e}")
            sys.exit(1)
    print("All migrations applied successfully.")


if __name__ == "__main__":
    main()
