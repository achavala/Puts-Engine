#!/usr/bin/env python3
"""Show the optimized scan schedule with ticker counts and UW usage."""

from putsengine.config import EngineConfig
import json

# Get ticker counts
all_tickers = len(EngineConfig.get_all_tickers())
high_beta = len(EngineConfig.get_high_beta_tickers())
try:
    with open('dynamic_universe.json') as f:
        dui = len(json.load(f))
except:
    dui = 0

print("=" * 90)
print("OPTIMIZED SCAN SCHEDULE - COMPLETE ANALYSIS")
print("=" * 90)
print()

print("UNIVERSE COVERAGE")
print("-" * 90)
print(f"  Static Universe:        {all_tickers} tickers")
print(f"  High-Beta Subset:       {high_beta} tickers")
print(f"  Dynamic Universe (DUI): {dui} tickers")
print()

print("=" * 90)
print("SCANS USING UNUSUAL WHALES API (11 scans)")
print("=" * 90)
print(f"{'Time':^12} | {'Scan Name':<45} | {'Tickers':>8} | {'UW Calls':>10}")
print("-" * 90)

uw_scans = [
    ("7:00 AM", "Earnings Calendar Check", "-", "~50"),
    ("7:00 AM", "Earnings Priority Scan #1", str(all_tickers), "~400"),
    ("8:00 AM", "Pre-Market Full Scan (UW)", str(all_tickers), "~1,000"),
    ("10:30 AM", "Pump-Dump Reversal #1", str(high_beta), "~150"),
    ("12:00 PM", "Earnings Priority Scan #2", str(all_tickers), "~400"),
    ("2:00 PM", "Pre-Earnings Flow #1", str(all_tickers), "~400"),
    ("2:30 PM", "Pump-Dump Reversal #2", str(high_beta), "~150"),
    ("4:30 PM", "Earnings Priority Scan #3", str(all_tickers), "~400"),
    ("6:00 PM", "Pre-Catalyst Distribution", str(all_tickers), "~400"),
    ("10:00 PM", "Pre-Earnings Flow #2", "-", "~0 (cached)"),
    ("10:00 PM", "EWS Full Scan", str(all_tickers), "~1,200"),
]

total_uw = 0
for time, name, tickers, calls in uw_scans:
    print(f"{time:^12} | {name:<45} | {tickers:>8} | {calls:>10}")
    try:
        total_uw += int(calls.replace("~", "").replace(",", "").split()[0])
    except:
        pass

print("-" * 90)
print(f"{'TOTAL':^12} | {'':<45} | {'':>8} | {'~' + str(total_uw):>10}")
print()

print("=" * 90)
print("SCANS NOT USING UW (24 scans - Alpaca/Polygon only)")
print("=" * 90)
print(f"{'Time':^12} | {'Scan Name':<45} | {'Tickers':>8} | {'Source':>10}")
print("-" * 90)

non_uw_scans = [
    ("4:00 AM", "Pre-Market Gap Scan", str(all_tickers), "Alpaca"),
    ("6:00 AM", "Pre-Market Gap Scan", str(all_tickers), "Alpaca"),
    ("7:00 AM", "Pre-Market Gap Scan", str(all_tickers), "Alpaca"),
    ("7:30 AM", "Multi-Day Weakness Scan", str(all_tickers), "Alpaca"),
    ("8:00 AM", "Pre-Market Gap Scan", str(all_tickers), "Alpaca"),
    ("9:15 AM", "Pre-Market Gap Scan (Final)", str(all_tickers), "Alpaca"),
    ("9:15 AM", "Zero-Hour Gap Scanner", str(all_tickers), "Alpaca"),
    ("10:00 AM", "Intraday Big Mover", str(all_tickers), "Alpaca"),
    ("11:00 AM", "Sector Correlation", str(all_tickers), "Alpaca"),
    ("11:00 AM", "Intraday Big Mover", str(all_tickers), "Alpaca"),
    ("11:30 AM", "Volume-Price Divergence", str(all_tickers), "Alpaca"),
    ("12:00 PM", "Intraday Big Mover", str(all_tickers), "Alpaca"),
    ("1:00 PM", "Intraday Big Mover", str(all_tickers), "Alpaca"),
    ("2:00 PM", "Sector Correlation", str(all_tickers), "Alpaca"),
    ("2:00 PM", "Intraday Big Mover", str(all_tickers), "Alpaca"),
    ("3:00 PM", "Earnings AMC Alert", "-", "Calendar"),
    ("3:00 PM", "Daily Report (Email)", "-", "Cached"),
    ("3:00 PM", "Intraday Big Mover", str(all_tickers), "Alpaca"),
    ("3:30 PM", "Volume-Price Divergence", str(all_tickers), "Alpaca"),
    ("4:00 PM", "Pattern Scan", str(all_tickers), "Alpaca"),
    ("4:30 PM", "After-Hours Scan #1", str(all_tickers), "Alpaca"),
    ("5:00 PM", "Multi-Day Weakness", str(all_tickers), "Alpaca"),
    ("6:00 PM", "After-Hours Scan #2", str(all_tickers), "Alpaca"),
    ("8:00 PM", "After-Hours Scan #3", str(all_tickers), "Alpaca"),
]

for time, name, tickers, source in non_uw_scans:
    print(f"{time:^12} | {name:<45} | {tickers:>8} | {source:>10}")

print()
print("=" * 90)
print("SUMMARY")
print("=" * 90)
print(f"  Total Scans:            35 (down from 64)")
print(f"  Scans using UW API:     11 (down from 30)")
print(f"  Scans NOT using UW:     24")
print(f"  Est. Daily UW Calls:    ~4,550 (within 7,500 limit)")
print(f"  API Budget Savings:     ~40%")
print()
print("=" * 90)
print("SCANS REMOVED (29 scans)")
print("=" * 90)
print("  - Pre-Market Scans #1-4 (4:15, 6:15, 8:15, 9:15 AM) - 4 scans")
print("  - Regular Scans (10:15, 11:15, 12:45, 1:45, 2:45, 3:15) - 6 scans")
print("  - Market Close Scan (4:00 PM) - 1 scan")
print("  - End of Day Scan (5:00 PM) - 1 scan")
print("  - Overnight Full Scan (10:00 PM) - 1 scan")
print("  - EWS Scans (8 AM, 12 PM, 4:30 PM, 8 PM) - 4 scans (kept only 10 PM)")
print("  - Pattern Scans (every 30 min) - 13 scans (kept only 4 PM)")
print("=" * 90)
