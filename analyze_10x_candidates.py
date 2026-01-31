#!/usr/bin/env python3
"""
INSTITUTIONAL 10x PUT CANDIDATE ANALYSIS
30+ Years Trading + PhD Quant + Microstructure Lens
"""
import json
from datetime import datetime
import pytz

et = pytz.timezone('US/Eastern')
now = datetime.now(et)

# Load pattern scan results
with open('pattern_scan_results.json', 'r') as f:
    patterns = json.load(f)

# Load scheduled scan results  
with open('scheduled_scan_results.json', 'r') as f:
    scheduled = json.load(f)

print('='*80)
print('🎯 INSTITUTIONAL 10x PUT CANDIDATE ANALYSIS')
print(f'   Analysis Date: {now.strftime("%Y-%m-%d %H:%M")} ET')
print('   For Monday Feb 3 / Tuesday Feb 4 Plays')
print('   30+ Years Trading + PhD Quant + Microstructure Lens')
print('='*80)
print()

# Analyze pump reversal candidates
pump = patterns.get('pump_reversal', [])
print(f'📊 PUMP REVERSAL CANDIDATES ANALYZED: {len(pump)} total')
print()

# Score candidates for 10x potential
high_potential = []
for p in pump:
    score = 0
    reasons = []
    
    # Check pump magnitude
    g1 = p.get('gain_1d', 0)
    g2 = p.get('gain_2d', 0) 
    g3 = p.get('gain_3d', 0)
    max_single = max(abs(g1), abs(g2), abs(g3))
    
    if max_single >= 10:
        score += 3
        reasons.append(f'MASSIVE move {max_single:.1f}%')
    elif max_single >= 5:
        score += 2
        reasons.append(f'Strong move {max_single:.1f}%')
    elif max_single >= 3:
        score += 1
        reasons.append(f'Moderate move {max_single:.1f}%')
    
    # Check reversal signals
    signals = p.get('signals', [])
    if len(signals) >= 3:
        score += 3
        reasons.append(f'{len(signals)} reversal signals!')
    elif len(signals) >= 2:
        score += 2
        reasons.append(f'{len(signals)} reversal signals')
    elif len(signals) >= 1:
        score += 1
    
    # Check sector
    sector = p.get('sector', 'other')
    high_beta = ['uranium', 'uranium_nuclear', 'crypto', 'evtol_space', 'quantum', 
                 'silver_miners', 'gaming', 'ai_datacenter', 'btc_miners', 
                 'semiconductors', 'travel_cruise']
    if sector in high_beta:
        score += 2
        reasons.append(f'HIGH-BETA: {sector}')
    
    # Already crashing = momentum
    if g1 < -8:
        score += 2
        reasons.append('CRASHING NOW')
    elif g1 < -5:
        score += 1
        reasons.append('Reversing')
    
    # Price tier
    price = p.get('price', 0)
    if price < 30:
        score += 1
        reasons.append('Low $ = leverage')
    elif price < 100:
        score += 0.5
    
    if score >= 5:
        high_potential.append({
            'symbol': p['symbol'],
            'price': price,
            'sector': sector,
            'total_gain': p.get('total_gain', 0),
            'gain_1d': g1,
            'gain_2d': g2,
            'gain_3d': g3,
            'signals': signals,
            'score': score,
            'reasons': reasons,
            'strike': p.get('strike_display', 'N/A'),
            'expiry': p.get('expiry_display', 'N/A'),
            'delta': p.get('delta_target', '-0.30'),
            'otm': p.get('otm_pct', 0),
            'potential': p.get('potential_mult', '3x-5x')
        })

# Sort by score
high_potential.sort(key=lambda x: x['score'], reverse=True)

print('🔥 TOP 10x POTENTIAL CANDIDATES:')
print('-'*80)
for i, c in enumerate(high_potential[:8], 1):
    print()
    print(f"{i}. {c['symbol']} @ ${c['price']:.2f} | SCORE: {c['score']:.1f}/10")
    print(f"   Sector: {c['sector'].upper()}")
    print(f"   Price Action: Today={c['gain_1d']:+.1f}% | Yest={c['gain_2d']:+.1f}% | 2D ago={c['gain_3d']:+.1f}%")
    print(f"   Reversal Signals: {', '.join(c['signals']) if c['signals'] else 'pumped'}")
    print(f"   🎯 TRADE: {c['strike']} exp {c['expiry']} | OTM: {c['otm']:.1f}% | δ: {c['delta']}")
    print(f"   📈 Potential: {c['potential']}")
    print(f"   WHY: {' | '.join(c['reasons'])}")

# Final recommendation
print()
print('='*80)
print('🏆 TOP 2 RECOMMENDATIONS FOR 10x MONDAY/TUESDAY PLAYS')
print('='*80)

if len(high_potential) >= 2:
    top2 = high_potential[:2]
    for i, c in enumerate(top2, 1):
        print()
        print(f"{'='*40}")
        print(f"🥇 PICK #{i}: {c['symbol']}")
        print(f"{'='*40}")
        print(f"Current Price: ${c['price']:.2f}")
        print(f"Sector: {c['sector'].upper()}")
        print()
        print("📊 TECHNICAL SETUP:")
        print(f"   • Today's move: {c['gain_1d']:+.1f}%")
        print(f"   • Yesterday: {c['gain_2d']:+.1f}%")
        print(f"   • 2 days ago: {c['gain_3d']:+.1f}%")
        print(f"   • Reversal signals: {', '.join(c['signals'])}")
        print()
        print("🎯 RECOMMENDED TRADE:")
        print(f"   • Strike: {c['strike']}")
        print(f"   • Expiry: {c['expiry']}")
        print(f"   • OTM: {c['otm']:.1f}%")
        print(f"   • Target Delta: {c['delta']}")
        print(f"   • Expected Multiple: {c['potential']}")
        print()
        print("⚡ CONVICTION FACTORS:")
        for r in c['reasons']:
            print(f"   ✓ {r}")
        
        # Calculate 10x scenario
        strike_val = float(c['strike'].replace('$','').replace('P',''))
        crash_needed = ((c['price'] - strike_val) / c['price']) * 100
        print()
        print(f"💰 10x SCENARIO:")
        print(f"   • Stock needs to drop to ~${strike_val * 0.95:.2f} ({crash_needed + 5:.1f}% drop)")
        print(f"   • With high vol, put could go from $0.50-2.00 → $5.00-20.00")
        print(f"   • RISK: Stock bounces = lose premium")

print()
print('='*80)
print("⚠️  RISK MANAGEMENT:")
print("   • Position size: MAX 2-3% of portfolio per trade")
print("   • Stop loss: If stock rallies +5%, cut position")
print("   • Take profit: Scale out at 3x, 5x, let runner to 10x")
print("   • Monday = higher risk (weekend news), Tuesday = cleaner setup")
print('='*80)
