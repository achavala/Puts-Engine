#!/usr/bin/env python3
"""Display all candidates from the 3 engines."""
import json

with open("scheduled_scan_results.json", "r") as f:
    data = json.load(f)

print("=" * 80)
print("🏛️ PUTSENGINE - ALL CANDIDATES BY ENGINE")
print("=" * 80)
print(f"Last Scan: {data.get('last_scan', 'N/A')}")
print(f"Market Regime: {data.get('market_regime', 'N/A')}")
print(f"Tickers Scanned: {data.get('tickers_scanned', 'N/A')}")
print("=" * 80)

# Engine 1: Gamma Drain
print()
print("🔥 ENGINE 1: GAMMA DRAIN (Flow-Driven)")
print("-" * 80)
gamma = data.get("gamma_drain", [])
if gamma:
    for c in gamma:
        sym = c.get("symbol", "N/A")
        score = c.get("score", 0)
        tier = c.get("tier", "N/A")
        price = c.get("current_price", 0)
        signals = ", ".join(c.get("signals", [])[:2])
        print(f"  {sym:<8} | {score:.2f} | {tier:<18} | ${price:>9.2f} | {signals}")
else:
    print("  No candidates")
print(f"  TOTAL: {len(gamma)} candidates")

# Engine 2: Distribution
print()
print("📉 ENGINE 2: DISTRIBUTION TRAP (Event-Driven)")
print("-" * 80)
dist = data.get("distribution", [])
if dist:
    for c in dist:
        sym = c.get("symbol", "N/A")
        score = c.get("score", 0)
        tier = c.get("tier", "N/A")
        price = c.get("current_price", 0)
        signals = ", ".join(c.get("signals", [])[:2])
        print(f"  {sym:<8} | {score:.2f} | {tier:<18} | ${price:>9.2f} | {signals}")
else:
    print("  No candidates")
print(f"  TOTAL: {len(dist)} candidates")

# Engine 3: Liquidity
print()
print("💧 ENGINE 3: LIQUIDITY VACUUM (Buyer Disappearance)")
print("-" * 80)
liq = data.get("liquidity", [])
if liq:
    for c in liq:
        sym = c.get("symbol", "N/A")
        score = c.get("score", 0)
        tier = c.get("tier", "N/A")
        price = c.get("current_price", 0)
        signals = ", ".join(c.get("signals", [])[:2])
        print(f"  {sym:<8} | {score:.2f} | {tier:<18} | ${price:>9.2f} | {signals}")
else:
    print("  No candidates")
print(f"  TOTAL: {len(liq)} candidates")

# Summary
print()
print("=" * 80)
print("📊 SUMMARY")
print("=" * 80)
all_c = gamma + dist + liq
total = len(all_c)
class_a = len([c for c in all_c if c.get("score", 0) >= 0.68])
class_b = len([c for c in all_c if 0.35 <= c.get("score", 0) < 0.68])
watching = len([c for c in all_c if 0.25 <= c.get("score", 0) < 0.35])

print(f"Total Candidates: {total}")
print(f"🏛️ CLASS A (≥0.68): {class_a} - Full position eligible")
print(f"🟡 CLASS B (0.35-0.67): {class_b} - 1-2 contracts max")
print(f"📊 WATCHING (0.25-0.34): {watching} - Monitor only")
print("=" * 80)
