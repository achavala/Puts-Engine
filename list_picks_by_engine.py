#!/usr/bin/env python3
"""List all picks by engine from scheduled_scan_results.json"""

import json
from pathlib import Path

results_file = Path("scheduled_scan_results.json")
with open(results_file, "r") as f:
    data = json.load(f)

print("=" * 90)
print("PUTS ENGINE - CANDIDATES BY ENGINE")
print("=" * 90)
print()

# Gamma Drain Engine
print("🔥 GAMMA DRAIN ENGINE (Flow-Driven, Highest Conviction)")
print("-" * 90)
gamma = data.get("gamma_drain", [])
if gamma:
    print(f"{'#':<4} {'Symbol':<8} {'Score':<8} {'Change %':<10} {'Price':<12} {'RVOL':<8} {'Tier':<15} {'Signals'}")
    print("-" * 90)
    for i, c in enumerate(gamma, 1):
        signals_str = ', '.join(c.get('signals', [])[:3])
        if len(signals_str) > 40:
            signals_str = signals_str[:37] + "..."
        print(f"{i:<4} {c['symbol']:<8} {c['score']:<8.2f} {c.get('change_pct', 0):<10.2f} "
              f"${c.get('current_price', 0):<11.2f} {c.get('rvol', 0):<8.2f} {c.get('tier', 'N/A'):<15} {signals_str}")
else:
    print("   No candidates")
print()

# Distribution Engine
print("📉 DISTRIBUTION ENGINE (Event-Driven, Confirmation-Heavy)")
print("-" * 90)
distribution = data.get("distribution", [])
if distribution:
    print(f"{'#':<4} {'Symbol':<8} {'Score':<8} {'Change %':<10} {'Price':<12} {'RVOL':<8} {'Tier':<15} {'Signals'}")
    print("-" * 90)
    for i, c in enumerate(distribution, 1):
        signals_str = ', '.join(c.get('signals', [])[:3])
        if len(signals_str) > 40:
            signals_str = signals_str[:37] + "..."
        print(f"{i:<4} {c['symbol']:<8} {c['score']:<8.2f} {c.get('change_pct', 0):<10.2f} "
              f"${c.get('current_price', 0):<11.2f} {c.get('rvol', 0):<8.2f} {c.get('tier', 'N/A'):<15} {signals_str}")
else:
    print("   No candidates")
print()

# Liquidity Engine
print("💧 LIQUIDITY ENGINE (Liquidity Vacuum, Dangerous/Constrained)")
print("-" * 90)
liquidity = data.get("liquidity", [])
if liquidity:
    print(f"{'#':<4} {'Symbol':<8} {'Score':<8} {'Change %':<10} {'Price':<12} {'RVOL':<8} {'Tier':<15} {'Signals'}")
    print("-" * 90)
    for i, c in enumerate(liquidity, 1):
        signals_str = ', '.join(c.get('signals', [])[:3])
        if len(signals_str) > 40:
            signals_str = signals_str[:37] + "..."
        print(f"{i:<4} {c['symbol']:<8} {c['score']:<8.2f} {c.get('change_pct', 0):<10.2f} "
              f"${c.get('current_price', 0):<11.2f} {c.get('rvol', 0):<8.2f} {c.get('tier', 'N/A'):<15} {signals_str}")
else:
    print("   No candidates")
print()

# Summary
print("=" * 90)
print("SUMMARY")
print("-" * 90)
print(f"Gamma Drain:  {len(gamma):2d} candidates")
print(f"Distribution: {len(distribution):2d} candidates")
print(f"Liquidity:    {len(liquidity):2d} candidates")
print(f"Total:        {len(gamma) + len(distribution) + len(liquidity):2d} candidates")
print(f"Last Scan:    {data.get('last_scan', 'N/A')[:19]}")
print(f"Market Regime: {data.get('market_regime', 'N/A')}")
print("=" * 90)
