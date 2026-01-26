#!/usr/bin/env python3
"""
Full dashboard update - shows ALL 163 tickers across 3 engines.

Engine Assignment Logic:
- Gamma Drain: Crypto, Quantum, Meme, AI/Data Centers
- Distribution: Mega-cap, Semiconductors, Financials, Consumer, Healthcare
- Liquidity: Space, Nuclear, Clean Energy, Industrials, Telecom, Biotech, ETFs
"""

import json
from datetime import datetime, date, timedelta
from putsengine.config import EngineConfig


# Engine assignments by sector
ENGINE_ASSIGNMENTS = {
    "gamma_drain": [
        "crypto", "quantum", "meme", "ai_datacenters", "high_vol_tech"
    ],
    "distribution": [
        "mega_cap_tech", "semiconductors", "financials", "consumer", "healthcare", "fintech"
    ],
    "liquidity": [
        "space_aerospace", "nuclear_energy", "industrials", "telecom", "biotech", "etfs"
    ]
}

# Signals detected from Monday scan (real data from 2:40 PM scan)
DETECTED_SIGNALS = {
    # Highest conviction (0.40-0.45)
    "QCOM": {"score": 0.45, "signals": ["vwap_loss", "gap_down_no_recovery", "multi_day_weakness"]},
    "TLN": {"score": 0.40, "signals": ["vwap_loss", "gap_down_no_recovery", "multi_day_weakness"]},
    "MARA": {"score": 0.40, "signals": ["vwap_loss", "repeated_sell_blocks", "multi_day_weakness"]},
    "ON": {"score": 0.40, "signals": ["vwap_loss", "gap_down_no_recovery", "multi_day_weakness"]},
    "CLSK": {"score": 0.40, "signals": ["vwap_loss", "repeated_sell_blocks", "multi_day_weakness"]},
    
    # Strong signals (0.35)
    "RDW": {"score": 0.35, "signals": ["repeated_sell_blocks", "is_post_earnings_negative"]},
    "LCID": {"score": 0.35, "signals": ["vwap_loss", "multi_day_weakness"]},
    "PL": {"score": 0.35, "signals": ["vwap_loss", "multi_day_weakness"]},
    "QUBT": {"score": 0.35, "signals": ["repeated_sell_blocks", "is_post_earnings_negative"]},
    "BBAI": {"score": 0.35, "signals": ["repeated_sell_blocks", "is_post_earnings_negative"]},
    "IWM": {"score": 0.35, "signals": ["vwap_loss", "is_post_earnings_negative"]},
    
    # Moderate signals (0.30)
    "CRDO": {"score": 0.30, "signals": ["gap_down_no_recovery", "multi_day_weakness"]},
    "BE": {"score": 0.30, "signals": ["vwap_loss", "multi_day_weakness"]},
    "DKNG": {"score": 0.30, "signals": ["repeated_sell_blocks", "is_post_earnings_negative"]},
    "OKLO": {"score": 0.30, "signals": ["vwap_loss", "multi_day_weakness"]},
    
    # Watching (0.25)
    "NRG": {"score": 0.25, "signals": ["vwap_loss", "multi_day_weakness"]},
    "BLDP": {"score": 0.25, "signals": ["vwap_loss", "multi_day_weakness"]},
    "RIOT": {"score": 0.25, "signals": ["repeated_sell_blocks"]},
    "IONQ": {"score": 0.25, "signals": ["is_post_earnings_negative"]},
    "AAPL": {"score": 0.25, "signals": ["is_post_earnings_negative"]},
    
    # More signals from scan
    "SOUN": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "RKLB": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "COIN": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "RBLX": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "JOBY": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "FCEL": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "MU": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "GEV": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "AMC": {"score": 0.15, "signals": ["repeated_sell_blocks"]},
    "NNE": {"score": 0.15, "signals": ["gap_down_no_recovery"]},
    "INOD": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "CLOV": {"score": 0.25, "signals": ["vwap_loss", "repeated_sell_blocks"]},
    "INTC": {"score": 0.10, "signals": ["gap_down_no_recovery"]},
    "ALAB": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "GOOG": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "LUNR": {"score": 0.15, "signals": ["gap_down_no_recovery"]},
    "RTX": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "EVTL": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "BNTX": {"score": 0.15, "signals": ["multi_day_weakness"]},
    "ARKK": {"score": 0.10, "signals": ["vwap_loss"]},
    "VRTX": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "PLUG": {"score": 0.15, "signals": ["repeated_sell_blocks"]},
    "ONDS": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "MSFT": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "MRVL": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "CRM": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "MA": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "ORCL": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "CMCSA": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "AI": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "AFRM": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "FSLR": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "LMT": {"score": 0.20, "signals": ["is_post_earnings_negative"]},
    "GLXY": {"score": 0.10, "signals": ["multi_day_weakness"]},
}


def get_tier(score):
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.68:
        return "🏛️ CLASS A"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    elif score >= 0.35:
        return "🟡 CLASS B"
    elif score >= 0.25:
        return "📊 WATCHING"
    elif score > 0:
        return "⚪ LOW SIGNAL"
    else:
        return "⬜ NO SIGNAL"


def get_potential(score):
    if score >= 0.45:
        return "-3% to -7%"
    elif score >= 0.35:
        return "-2% to -5%"
    elif score >= 0.25:
        return "-2% to -4%"
    elif score > 0:
        return "-1% to -3%"
    else:
        return "N/A"


def get_engine_for_ticker(symbol: str) -> str:
    """Determine which engine a ticker belongs to based on sector."""
    sectors = EngineConfig.UNIVERSE_SECTORS
    
    for engine, sector_list in ENGINE_ASSIGNMENTS.items():
        for sector in sector_list:
            if symbol in sectors.get(sector, []):
                return engine
    
    # Default to distribution if not found
    return "distribution"


def main():
    print("=" * 70)
    print("FULL DASHBOARD UPDATE - ALL 163 TICKERS")
    print("=" * 70)
    print()
    
    # Get all tickers
    all_tickers = EngineConfig.get_all_tickers()
    print(f"Total tickers in universe: {len(all_tickers)}")
    print()
    
    # Create dashboard format
    dashboard_data = {
        'generated_at': datetime.now().isoformat(),
        'analysis_date': date.today().strftime('%Y-%m-%d'),
        'next_week_start': (date.today() + timedelta(days=1)).strftime('%Y-%m-%d'),
        'gamma_drain': [],
        'distribution': [],
        'liquidity': [],
        'summary': {}
    }
    
    # Process EVERY ticker
    for symbol in sorted(all_tickers):
        # Get engine assignment
        engine = get_engine_for_ticker(symbol)
        
        # Get signals if detected
        signal_data = DETECTED_SIGNALS.get(symbol, {"score": 0, "signals": []})
        score = signal_data["score"]
        signals = signal_data["signals"]
        
        entry = {
            'symbol': symbol,
            'score': score,
            'tier': get_tier(score),
            'close': 100,  # Placeholder - will be updated by live scan
            'daily_change': 0,
            'rvol': 1.0,
            'rsi': 50,
            'next_week_potential': get_potential(score),
            'confidence': 'HIGH' if score >= 0.45 else ('MEDIUM' if score >= 0.25 else 'LOW'),
            'signals': signals
        }
        
        dashboard_data[engine].append(entry)
    
    # Sort each engine by score (highest first)
    for engine in ['gamma_drain', 'distribution', 'liquidity']:
        dashboard_data[engine].sort(key=lambda x: x['score'], reverse=True)
    
    # Summary
    dashboard_data['summary'] = {
        'total_candidates': len(all_tickers),
        'gamma_drain_count': len(dashboard_data['gamma_drain']),
        'distribution_count': len(dashboard_data['distribution']),
        'liquidity_count': len(dashboard_data['liquidity']),
        'with_signals': len([t for t in all_tickers if t in DETECTED_SIGNALS]),
        'high_conviction': len([t for t, d in DETECTED_SIGNALS.items() if d['score'] >= 0.35])
    }
    
    # Save
    with open('dashboard_candidates.json', 'w') as f:
        json.dump(dashboard_data, f, indent=2)
    
    # Print summary
    print(f"🔥 GAMMA DRAIN ENGINE: {len(dashboard_data['gamma_drain'])} tickers")
    with_signals = [c for c in dashboard_data['gamma_drain'] if c['score'] > 0]
    print(f"   With signals: {len(with_signals)}")
    for c in with_signals[:10]:
        print(f"   {c['symbol']:6} | {c['score']:.2f} | {c['tier']:15} | {len(c['signals'])} signals")
    if len(with_signals) > 10:
        print(f"   ... and {len(with_signals) - 10} more with signals")
    print()
    
    print(f"📉 DISTRIBUTION ENGINE: {len(dashboard_data['distribution'])} tickers")
    with_signals = [c for c in dashboard_data['distribution'] if c['score'] > 0]
    print(f"   With signals: {len(with_signals)}")
    for c in with_signals[:10]:
        print(f"   {c['symbol']:6} | {c['score']:.2f} | {c['tier']:15} | {len(c['signals'])} signals")
    if len(with_signals) > 10:
        print(f"   ... and {len(with_signals) - 10} more with signals")
    print()
    
    print(f"💧 LIQUIDITY ENGINE: {len(dashboard_data['liquidity'])} tickers")
    with_signals = [c for c in dashboard_data['liquidity'] if c['score'] > 0]
    print(f"   With signals: {len(with_signals)}")
    for c in with_signals[:10]:
        print(f"   {c['symbol']:6} | {c['score']:.2f} | {c['tier']:15} | {len(c['signals'])} signals")
    if len(with_signals) > 10:
        print(f"   ... and {len(with_signals) - 10} more with signals")
    print()
    
    total = (len(dashboard_data['gamma_drain']) + 
             len(dashboard_data['distribution']) + 
             len(dashboard_data['liquidity']))
    
    print("=" * 70)
    print(f"TOTAL: {total} tickers across 3 engines")
    print(f"HIGH CONVICTION (score >= 0.35): {dashboard_data['summary']['high_conviction']} tickers")
    print("=" * 70)
    print()
    print("Dashboard updated! Refresh to see all tickers.")


if __name__ == "__main__":
    main()
