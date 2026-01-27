#!/usr/bin/env python3
"""
List all tickers scanned by each engine with Dynamic Universe Injection (DUI) breakdown.

PIPELINE (Architect-4 Final):
  STATIC_CORE_UNIVERSE
          │
          ▼
  ENGINE 2: DISTRIBUTION  ──┐
  ENGINE 3: LIQUIDITY     ──┤
          │                 │
          ▼                 ▼
  DYNAMIC UNIVERSE INJECTION (DUI)  ← Promotes E2/E3 hits
          │
          ▼
  ENGINE 1: GAMMA DRAIN (CONFIRMATION)
          │
          ▼
  FINAL CANDIDATES
"""
import json
import sys
sys.path.insert(0, '/Users/chavala/PutsEngine')

from putsengine.config import EngineConfig, DynamicUniverseManager

# Load dashboard candidates
with open('dashboard_candidates.json') as f:
    data = json.load(f)

print('=' * 100)
print('PUTSENGINE TICKER BREAKDOWN - DYNAMIC UNIVERSE INJECTION (DUI) ARCHITECTURE')
print('=' * 100)

# ============================================================================
# STATIC CORE UNIVERSE
# ============================================================================
print('\n' + '─' * 100)
print('📊 STATIC CORE UNIVERSE (Always-On, Never Changes)')
print('─' * 100)

all_static = set(EngineConfig.get_all_tickers())
print(f'\nTotal Static Tickers: {len(all_static)}')

print('\nBy Sector:')
for sector, tickers in EngineConfig.UNIVERSE_SECTORS.items():
    ticker_str = ', '.join(sorted(tickers))
    print(f'  {sector.upper()} ({len(tickers)}): {ticker_str}')

# ============================================================================
# ENGINE SCAN RESULTS
# ============================================================================
print('\n' + '─' * 100)
print('🔍 ENGINE SCAN RESULTS')
print('─' * 100)

# Engine assignments
ENGINE_ASSIGNMENTS = {
    'gamma_drain': {
        'name': '🔥 ENGINE 1: GAMMA DRAIN (Flow-Driven)',
        'purpose': 'Primary engine - highest conviction - confirms all trades',
        'sectors': ['high_vol_tech', 'crypto', 'meme', 'quantum', 'ai_datacenters']
    },
    'distribution': {
        'name': '📉 ENGINE 2: DISTRIBUTION (Event-Driven)',
        'purpose': 'Discovers "sell the news" / institutional exit patterns',
        'sectors': ['mega_cap_tech', 'semiconductors', 'fintech', 'consumer', 'financials', 'healthcare']
    },
    'liquidity': {
        'name': '💧 ENGINE 3: LIQUIDITY (Vacuum Detection)',
        'purpose': 'Discovers when buyers disappear - enables DUI promotion',
        'sectors': ['space_aerospace', 'nuclear_energy', 'biotech', 'industrials', 'telecom', 'etfs']
    }
}

for engine, config in ENGINE_ASSIGNMENTS.items():
    candidates = data.get(engine, [])
    active = [c for c in candidates if c.get('score', 0) > 0]
    inactive = [c for c in candidates if c.get('score', 0) == 0]
    
    active.sort(key=lambda x: x.get('score', 0), reverse=True)
    inactive.sort(key=lambda x: x.get('symbol', ''))
    
    print(f'\n{config["name"]}')
    print(f'Purpose: {config["purpose"]}')
    print(f'Sectors: {", ".join(config["sectors"])}')
    print(f'Total Scanned: {len(candidates)} | Active Signals: {len(active)} | No Signal: {len(inactive)}')
    
    if active:
        print('\n  ✅ ACTIVE SIGNALS (Score > 0) - Eligible for DUI Promotion:')
        print('  ' + '-' * 95)
        print(f'  {"Symbol":<10} {"Score":>8} {"Tier":<18} {"Price":>12} {"Signals"}')
        print('  ' + '-' * 95)
        for c in active:
            symbol = c.get('symbol', 'N/A')
            score = c.get('score', 0)
            tier = c.get('tier', 'N/A')
            close = c.get('close', 0)
            signals = c.get('signals', [])
            signals_str = ', '.join(signals[:3]) + ('...' if len(signals) > 3 else '')
            print(f'  {symbol:<10} {score:>8.2f} {tier:<18} ${close:>10.2f} {signals_str}')
    
    print('\n  ⚪ NO SIGNAL (Score = 0) - Monitored but not triggered:')
    inactive_symbols = [c.get('symbol', 'N/A') for c in inactive]
    for i in range(0, len(inactive_symbols), 12):
        row = inactive_symbols[i:i+12]
        print(f'  {" ".join(f"{s:<6}" for s in row)}')

# ============================================================================
# DYNAMIC UNIVERSE INJECTION (DUI)
# ============================================================================
print('\n' + '─' * 100)
print('🚀 DYNAMIC UNIVERSE INJECTION (DUI) - STRUCTURAL PROMOTION')
print('─' * 100)

# Initialize DUI manager
dui_manager = DynamicUniverseManager()

# Get active signals from E2 (Distribution) and E3 (Liquidity)
distribution_hits = [c for c in data.get('distribution', []) if c.get('score', 0) >= 0.30]
liquidity_hits = [c for c in data.get('liquidity', []) if c.get('score', 0) >= 0.30]

print(f'\nDistribution Engine hits (score >= 0.30): {len(distribution_hits)}')
for c in distribution_hits:
    print(f'  → {c["symbol"]} (score: {c["score"]:.2f}) - PROMOTED to Dynamic Set')
    dui_manager.promote_from_distribution(c['symbol'], c['score'], c.get('signals', []))

print(f'\nLiquidity Engine hits (score >= 0.30): {len(liquidity_hits)}')
for c in liquidity_hits:
    print(f'  → {c["symbol"]} (score: {c["score"]:.2f}) - PROMOTED to Dynamic Set')
    dui_manager.promote_from_liquidity(c['symbol'], c['score'], c.get('signals', []))

# Show current dynamic set
dynamic_details = dui_manager.get_dynamic_details()
print(f'\nCurrent Dynamic Structural Set ({len(dynamic_details)} tickers):')
if dynamic_details:
    for symbol, info in sorted(dynamic_details.items(), key=lambda x: x[1].get('score', 0), reverse=True):
        print(f'  {symbol:<8} | Score: {info["score"]:.2f} | Source: {info["source"]:<12} | '
              f'Added: {info["added_date"]} | Expires: {info["expires_date"]}')
else:
    print('  (Empty - no E2/E3 hits met promotion threshold)')

# ============================================================================
# FINAL SCAN UNIVERSE
# ============================================================================
print('\n' + '─' * 100)
print('🎯 FINAL SCAN UNIVERSE (What Gamma Drain Engine Sees)')
print('─' * 100)

final_universe = dui_manager.get_final_scan_universe()
static_only = all_static - dui_manager.get_dynamic_set()
dynamic_only = dui_manager.get_dynamic_set() - all_static

print(f'\nTotal Final Universe: {len(final_universe)} tickers')
print(f'  ├─ From Static Core: {len(all_static)} tickers')
print(f'  └─ From Dynamic (DUI): {len(dynamic_only)} NEW tickers')

if dynamic_only:
    print(f'\n⚡ NEW TICKERS FROM DUI (Not in Static Universe):')
    for symbol in sorted(dynamic_only):
        info = dynamic_details.get(symbol, {})
        print(f'  {symbol:<8} - Promoted by {info.get("source", "unknown")} engine '
              f'(score: {info.get("score", 0):.2f})')

# ============================================================================
# SUMMARY
# ============================================================================
print('\n' + '=' * 100)
print('SUMMARY')
print('=' * 100)

total_active = sum(
    len([c for c in data.get(engine, []) if c.get('score', 0) > 0])
    for engine in ['gamma_drain', 'distribution', 'liquidity']
)

print(f'''
ARCHITECTURE:
  Static Core Universe ──────────────────────────────────────→ {len(all_static)} tickers (never changes)
          │
          ▼
  Engine 2 (Distribution) ───→ {len(distribution_hits)} hits ──→ PROMOTES ──┐
  Engine 3 (Liquidity) ──────→ {len(liquidity_hits)} hits ──→ PROMOTES ──┤
          │                                                   │
          ▼                                                   ▼
  Dynamic Universe Injection (DUI) ←──────────────────────────┘
          │
          ▼
  FINAL SCAN UNIVERSE ───────────────────────────────────────→ {len(final_universe)} tickers
          │
          ▼
  Engine 1 (Gamma Drain) ────→ CONFIRMS ──→ Final Candidates

CURRENT STATE:
  Total Active Signals: {total_active}
  Gamma Drain Signals: {len([c for c in data.get('gamma_drain', []) if c.get('score', 0) > 0])}
  Distribution Signals: {len([c for c in data.get('distribution', []) if c.get('score', 0) > 0])}
  Liquidity Signals: {len([c for c in data.get('liquidity', []) if c.get('score', 0) > 0])}
  Dynamic Set Size: {len(dynamic_details)}

KEY PRINCIPLE:
  ❌ Dynamic candidates are NOT "top movers"
  ✅ Dynamic candidates are STRUCTURE-VALIDATED names
  ✅ Only E2/E3 hits can be promoted (Distribution/Liquidity)
  ✅ TTL = {EngineConfig.DUI_TTL_TRADING_DAYS} trading days (auto-expire)
  ✅ Minimum promotion score = {EngineConfig.DUI_MIN_SCORE_FOR_PROMOTION}
''')
