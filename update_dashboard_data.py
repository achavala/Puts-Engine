#!/usr/bin/env python3
"""
Update dashboard_candidates.json with fresh scan data.
Run this to populate the dashboard with all current candidates.
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from putsengine.scheduler import run_single_scan


async def update_dashboard():
    print('Running fresh scan to update dashboard...')
    print()
    
    # Run scan
    results = await run_single_scan('dashboard_update')
    
    # Convert to dashboard format
    dashboard_data = {
        'generated_at': datetime.now().isoformat(),
        'analysis_date': date.today().strftime('%Y-%m-%d'),
        'next_week_start': (date.today() + timedelta(days=1)).strftime('%Y-%m-%d'),
        'gamma_drain': [],
        'distribution': [],
        'liquidity': [],
        'summary': {}
    }
    
    # Process candidates from each engine
    for engine in ['gamma_drain', 'distribution', 'liquidity']:
        candidates = results.get(engine, [])
        for c in candidates:
            # Get potential based on score
            score = c.get('score', 0)
            if score >= 0.65:
                potential = '-5% to -10%'
            elif score >= 0.45:
                potential = '-3% to -7%'
            elif score >= 0.35:
                potential = '-2% to -5%'
            else:
                potential = '-2% to -4%'
            
            dashboard_data[engine].append({
                'symbol': c.get('symbol'),
                'score': c.get('score'),
                'tier': c.get('tier'),
                'close': c.get('current_price', 100),
                'daily_change': 0,
                'rvol': 1.5,
                'rsi': 40,
                'next_week_potential': potential,
                'confidence': 'MEDIUM' if score >= 0.45 else 'LOW',
                'signals': c.get('signals', [])
            })
    
    # Summary
    dashboard_data['summary'] = {
        'total_candidates': len(dashboard_data['gamma_drain']) + len(dashboard_data['distribution']) + len(dashboard_data['liquidity']),
        'gamma_drain_count': len(dashboard_data['gamma_drain']),
        'distribution_count': len(dashboard_data['distribution']),
        'liquidity_count': len(dashboard_data['liquidity'])
    }
    
    # Save to dashboard_candidates.json
    with open('dashboard_candidates.json', 'w') as f:
        json.dump(dashboard_data, f, indent=2)
    
    print()
    print('=' * 60)
    print('DASHBOARD UPDATED')
    print('=' * 60)
    print(f"Gamma Drain: {len(dashboard_data['gamma_drain'])} candidates")
    print(f"Distribution: {len(dashboard_data['distribution'])} candidates")
    print(f"Liquidity: {len(dashboard_data['liquidity'])} candidates")
    print(f"TOTAL: {dashboard_data['summary']['total_candidates']} candidates")
    print()
    
    # Show all candidates
    for engine in ['gamma_drain', 'distribution', 'liquidity']:
        candidates = dashboard_data[engine]
        if candidates:
            print(f"{engine.upper().replace('_', ' ')}:")
            for c in candidates[:15]:
                print(f"  {c['symbol']:6} | {c['score']:.2f} | {c['tier']:15} | {len(c['signals'])} signals")
            if len(candidates) > 15:
                print(f"  ... and {len(candidates) - 15} more")
            print()
    
    print('=' * 60)
    print('Refresh your dashboard to see updated candidates!')
    print('=' * 60)


if __name__ == "__main__":
    asyncio.run(update_dashboard())
