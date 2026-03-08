#!/usr/bin/env python3
"""
Test script to verify search_listings_filtered RPC works with various filters.
Uses only httpx + python-dotenv (no app imports) for maximum compatibility.
Run: python backend/scripts/test_listings_query.py
"""
import asyncio
import json
import os
import sys

# Add project root for .env
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import httpx


async def main():
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key or "supabase" not in url:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        print("  SUPABASE_URL=https://xxx.supabase.co")
        print("  SUPABASE_SERVICE_ROLE_KEY=eyJ...")
        sys.exit(1)

    rpc_url = f"{url}/rest/v1/rpc/search_listings_filtered"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    test_cases = [
        ("No filters (limit 5)", {"p_limit": 5}),
        ("Budget max $30k", {"p_limit": 5, "p_budget_max": 30000}),
        ("Min year 2020", {"p_limit": 5, "p_min_year": 2020}),
        ("Make Toyota", {"p_limit": 5, "p_makes": ["Toyota"]}),
        ("Make Honda, model Civic", {"p_limit": 5, "p_makes": ["Honda"], "p_models": ["Civic"]}),
        ("Budget $20k + year 2018+", {"p_limit": 5, "p_budget_max": 20000, "p_min_year": 2018}),
        ("Max mileage 50k", {"p_limit": 5, "p_max_mileage": 50000}),
        ("Location Denver", {"p_limit": 5, "p_location": "Denver"}),
    ]

    print("Testing search_listings_filtered RPC...\n")
    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, body in test_cases:
            try:
                r = await client.post(rpc_url, json=body, headers=headers)
                if r.status_code == 200:
                    rows = r.json()
                    count = len(rows)
                    sample = rows[0] if rows else None
                    print(f"✓ {name}: {count} results")
                    if sample:
                        print(f"  Sample: {sample.get('year')} {sample.get('make')} {sample.get('model')} @ ${sample.get('price')}")
                else:
                    print(f"✗ {name}: HTTP {r.status_code}")
                    print(f"  {r.text[:300]}")
                print()
            except Exception as e:
                print(f"✗ {name}: {e}\n")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
