#!/usr/bin/env python3
"""
Show all validated PUT trades for manual execution.
"""

from datetime import date, timedelta
import json

def main():
    # Load validated candidates
    with open('dashboard_candidates.json', 'r') as f:
        data = json.load(f)

    print('=' * 80)
    print('ALL VALIDATED PUT TRADES FOR MANUAL EXECUTION')
    print('=' * 80)
    print()
    print(f'Analysis Date: {data["analysis_date"]} (Friday)')
    print(f'Next Week Start: {data["next_week_start"]} (Monday)')
    print()

    # Calculate expiry dates
    today = date.today()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    first_friday = today + timedelta(days=days_until_friday)
    second_friday = first_friday + timedelta(days=7)

    print(f'EXPIRY DATES (Fridays Only):')
    print(f'   Near-term: {first_friday.strftime("%b %d, %Y")} (DTE: {(first_friday - today).days})')
    print(f'   Extended:  {second_friday.strftime("%b %d, %Y")} (DTE: {(second_friday - today).days})')
    print()

    # Summary
    summary = data['summary']
    print('SUMMARY:')
    print(f'   Total Candidates: {summary["total_candidates"]}')
    print(f'   EXPLOSIVE (0.75+):      {summary["explosive_count"]}')
    print(f'   VERY STRONG (0.65-0.74): {summary["very_strong_count"]}')
    print(f'   STRONG (0.55-0.64):      {summary["strong_count"]}')
    print(f'   MONITORING (0.45-0.54):  {summary["monitoring_count"]}')
    print()

    print('=' * 80)
    print('GAMMA DRAIN ENGINE - Validated Candidates')
    print('=' * 80)

    if data['gamma_drain']:
        print(f'{"Symbol":<8} {"Score":>8} {"Tier":<18} {"Price":>10} {"Chg%":>8} {"RVOL":>6} {"RSI":>6} {"Potential":<15}')
        print('-' * 95)
        for c in data['gamma_drain']:
            expiry = first_friday if c['score'] >= 0.65 else second_friday
            strike = round(c['close'] * 0.95, 0)
            print(f"{c['symbol']:<8} {c['score']:>8.2f} {c['tier']:<18} ${c['close']:>8.2f} {c['daily_change']:>+7.2f}% {c['rvol']:>5.2f} {c['rsi']:>5.1f} {c['next_week_potential']:<15}")
            print(f"   Signals: {', '.join(c['signals'])}")
            print(f"   >> TRADE: Buy {c['symbol']} ${strike:.0f}P {expiry.strftime('%b %d')} | Entry: ${c['close']:.2f} | Confidence: {c['confidence']}")
            print()
    else:
        print('   No Gamma Drain candidates')
    print()

    print('=' * 80)
    print('DISTRIBUTION ENGINE - Validated Candidates')
    print('=' * 80)

    if data['distribution']:
        print(f'{"Symbol":<8} {"Score":>8} {"Tier":<18} {"Price":>10} {"Chg%":>8} {"RVOL":>6} {"RSI":>6} {"Potential":<15}')
        print('-' * 95)
        for c in data['distribution']:
            expiry = first_friday if c['score'] >= 0.65 else second_friday
            strike = round(c['close'] * 0.95, 0)
            print(f"{c['symbol']:<8} {c['score']:>8.2f} {c['tier']:<18} ${c['close']:>8.2f} {c['daily_change']:>+7.2f}% {c['rvol']:>5.2f} {c['rsi']:>5.1f} {c['next_week_potential']:<15}")
            print(f"   Signals: {', '.join(c['signals'])}")
            print(f"   >> TRADE: Buy {c['symbol']} ${strike:.0f}P {expiry.strftime('%b %d')} | Entry: ${c['close']:.2f} | Confidence: {c['confidence']}")
            print()
    else:
        print('   No Distribution candidates')
    print()

    print('=' * 80)
    print('LIQUIDITY ENGINE - Validated Candidates')
    print('=' * 80)

    if data['liquidity']:
        print(f'{"Symbol":<8} {"Score":>8} {"Tier":<18} {"Price":>10} {"Chg%":>8} {"RVOL":>6} {"RSI":>6} {"Potential":<15}')
        print('-' * 95)
        for c in data['liquidity']:
            expiry = first_friday if c['score'] >= 0.65 else second_friday
            strike = round(c['close'] * 0.95, 0)
            print(f"{c['symbol']:<8} {c['score']:>8.2f} {c['tier']:<18} ${c['close']:>8.2f} {c['daily_change']:>+7.2f}% {c['rvol']:>5.2f} {c['rsi']:>5.1f} {c['next_week_potential']:<15}")
            print(f"   Signals: {', '.join(c['signals'])}")
            print(f"   >> TRADE: Buy {c['symbol']} ${strike:.0f}P {expiry.strftime('%b %d')} | Entry: ${c['close']:.2f} | Confidence: {c['confidence']}")
            print()
    else:
        print('   No Liquidity candidates')
    print()

    # Combined list sorted by score
    print('=' * 80)
    print('ALL CANDIDATES RANKED BY SCORE')
    print('=' * 80)
    
    all_candidates = []
    for c in data['gamma_drain']:
        c['engine'] = 'Gamma Drain'
        all_candidates.append(c)
    for c in data['distribution']:
        c['engine'] = 'Distribution'
        all_candidates.append(c)
    for c in data['liquidity']:
        c['engine'] = 'Liquidity'
        all_candidates.append(c)
    
    all_candidates.sort(key=lambda x: x['score'], reverse=True)
    
    print(f'{"#":<3} {"Symbol":<8} {"Score":>8} {"Engine":<14} {"Price":>10} {"Chg%":>8} {"Potential":<15} {"Confidence":<10}')
    print('-' * 95)
    
    for i, c in enumerate(all_candidates, 1):
        expiry = first_friday if c['score'] >= 0.65 else second_friday
        strike = round(c['close'] * 0.95, 0)
        dte = (expiry - today).days
        print(f"{i:<3} {c['symbol']:<8} {c['score']:>8.2f} {c['engine']:<14} ${c['close']:>8.2f} {c['daily_change']:>+7.2f}% {c['next_week_potential']:<15} {c['confidence']:<10}")
        print(f"    >> ${strike:.0f}P exp {expiry.strftime('%b %d')} (DTE: {dte}) | Signals: {', '.join(c['signals'][:3])}")
        print()

    print('=' * 80)
    print('MANUAL EXECUTION CHECKLIST')
    print('=' * 80)
    print()
    print('TIMING RULES:')
    print('   * Wait until 09:45 ET before entering ANY trades')
    print('   * Primary window: 09:45 - 10:30 ET')
    print('   * Confirmation window: 10:30 - 12:00 ET')
    print('   * Do NOT enter after 2:30 PM (hedging noise)')
    print()
    print('ENTRY CONDITIONS (VERIFY BEFORE TRADING):')
    print('   * SPY and QQQ below VWAP')
    print('   * Net GEX negative or neutral')
    print('   * VIX stable or rising')
    print('   * No put wall within +/-1% of strike')
    print()
    print('POSITION SIZING:')
    print('   * Max 2% risk per trade')
    print('   * Max 2 positions per day')
    print('   * Scale into STRONG+ scores only')
    print()
    print('STRIKE SELECTION:')
    print('   * Delta: -0.30 to -0.325')
    print('   * Slightly OTM (~5% below current price)')
    print('   * Prefer liquid strikes')
    print()
    print('EXIT RULES:')
    print('   * If VWAP reclaimed and held 15 min -> EXIT IMMEDIATELY')
    print('   * No averaging down')
    print('   * Honor stop losses')
    print()
    print('=' * 80)
    print('WARNING: MARKET CURRENTLY CLOSED (SUNDAY)')
    print('Run: python monday_morning_report.py  (Monday 8:30 AM ET)')
    print('=' * 80)


if __name__ == "__main__":
    main()
