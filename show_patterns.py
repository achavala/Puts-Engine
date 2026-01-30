#!/usr/bin/env python3
"""Show pattern-enhanced candidates."""
import json

with open('scheduled_scan_results.json', 'r') as f:
    r = json.load(f)

print('='*70)
print('PATTERN-ENHANCED CANDIDATES (Dashboard shows ⭐ in Pattern column)')
print('='*70)
print()

print('DISTRIBUTION ENGINE:')
print(f'{"Symbol":10} {"Pattern":15} {"Score":8} Signals')
print('-'*70)
for c in r.get('distribution', [])[:8]:
    sym = c.get('symbol', 'N/A')
    is_enh = c.get('pattern_enhanced', False)
    boost = c.get('pattern_boost', 0)
    pattern = "⭐ +{:.2f}".format(boost) if is_enh else ""
    score = c.get('score', 0)
    signals = c.get('signals', [])[:2]
    print("{:10} {:15} {:.3f}   {}".format(sym, pattern, score, signals))

print()
print('LIQUIDITY ENGINE:')
print(f'{"Symbol":10} {"Pattern":15} {"Score":8} Signals')
print('-'*70)
for c in r.get('liquidity', [])[:6]:
    sym = c.get('symbol', 'N/A')
    is_enh = c.get('pattern_enhanced', False)
    boost = c.get('pattern_boost', 0)
    pattern = "⭐ +{:.2f}".format(boost) if is_enh else ""
    score = c.get('score', 0)
    signals = c.get('signals', [])[:2]
    print("{:10} {:15} {:.3f}   {}".format(sym, pattern, score, signals))

print()
print('='*70)
print('Dashboard: http://localhost:8507')
print('Open in browser to see full table with ⭐ Pattern column')
print('='*70)
