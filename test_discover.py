#!/usr/bin/env python3
"""Discover correct UW insider and earnings endpoints."""
import asyncio, aiohttp, json
from dotenv import dotenv_values
vals = dotenv_values('.env')
API_KEY = vals.get("UNUSUAL_WHALES_API_KEY")
BASE_URL = "https://api.unusualwhales.com"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}

async def test_path(session, path, params=None):
    url = f"{BASE_URL}{path}"
    try:
        async with session.get(url, params=params, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            s = resp.status
            if s == 200:
                d = await resp.json()
                inner = d.get('data', d) if isinstance(d, dict) else d
                cnt = len(inner) if isinstance(inner, list) else 1
                keys = []
                if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                    keys = sorted(inner[0].keys())[:8]
                elif isinstance(inner, dict):
                    keys = sorted(inner.keys())[:8]
                return s, cnt, keys, inner
            return s, 0, [], None
    except Exception as e:
        return "ERR", 0, [], str(e)

async def main():
    async with aiohttp.ClientSession() as session:
        # Insider endpoints
        print("=== INSIDER ENDPOINTS ===")
        insider_paths = [
            "/api/insider/9978",
            "/api/insider-transactions/COIN",
            "/api/stock/COIN/insider",
            "/api/sec-filings/COIN",
        ]
        for p in insider_paths:
            s, c, k, _ = await test_path(session, p)
            print(f"  {p}: {s} | {c} records | {k}")

        # Check /api/insider/9978 (person detail) for nested trades
        print("\n=== INSIDER PERSON DETAIL (/api/insider/9978) ===")
        s, c, k, data = await test_path(session, "/api/insider/9978")
        print(f"  Status: {s}, Records: {c}")
        if data:
            if isinstance(data, dict):
                print(f"  Keys: {sorted(data.keys())}")
                for key in ['trades', 'transactions', 'filings', 'history']:
                    if key in data:
                        val = data[key]
                        print(f"  Found '{key}': type={type(val).__name__}, len={len(val) if isinstance(val, list) else 'N/A'}")
                print(f"  Content: {json.dumps(data, default=str)[:800]}")
            elif isinstance(data, list) and data:
                print(f"  List[{len(data)}]")
                if isinstance(data[0], dict):
                    print(f"  Keys: {sorted(data[0].keys())}")
                    print(f"  First: {json.dumps(data[0], default=str)[:500]}")

        # Earnings endpoints
        print("\n=== EARNINGS ENDPOINTS ===")
        earn_paths = [
            "/api/earnings/upcoming",
            "/api/stock/COIN/overview",
        ]
        for p in earn_paths:
            s, c, k, _ = await test_path(session, p)
            print(f"  {p}: {s} | {c} records | {k}")

        # The stock_info has next_earnings_date - use that as fallback
        print("\n=== STOCK INFO (earnings fallback) ===")
        s, c, k, data = await test_path(session, "/api/stock/COIN/info")
        if data:
            inner = data.get('data', data) if isinstance(data, dict) else data
            if isinstance(inner, list) and inner:
                inner = inner[0]
            if isinstance(inner, dict):
                print(f"  next_earnings_date: {inner.get('next_earnings_date')}")
                print(f"  announce_time: {inner.get('announce_time')}")
                print(f"  sector: {inner.get('sector')}")

asyncio.run(main())
