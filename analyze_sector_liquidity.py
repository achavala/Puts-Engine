#!/usr/bin/env python3
"""
SECTOR-RELATIVE LIQUIDITY ANALYSIS
Demonstrates the new Architect-4 sector context feature for liquidity vacuum detection.

Example: Analyze T (AT&T) and compare against Telecom sector peers
"""
import asyncio
import json
from datetime import datetime
import pytz

from putsengine.config import get_settings, EngineConfig
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.layers.liquidity import LiquidityVacuumLayer

et = pytz.timezone('US/Eastern')


async def analyze_sector_liquidity(symbol: str = "T"):
    """Analyze a symbol with full sector context."""
    
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    liquidity = LiquidityVacuumLayer(alpaca, polygon, settings)
    
    print("=" * 80)
    print("SECTOR-RELATIVE LIQUIDITY ANALYSIS")
    print(f"Analysis Time: {datetime.now(et).strftime('%Y-%m-%d %H:%M:%S ET')}")
    print("=" * 80)
    print()
    
    # Get sector info
    sector = liquidity._get_sector_for_symbol(symbol)
    peers = liquidity._get_sector_peers(symbol, max_peers=5)
    
    print(f"TARGET: {symbol}")
    print(f"SECTOR: {sector}")
    print(f"PEERS: {', '.join(peers)}")
    print()
    
    print("=" * 80)
    print("1. ANALYZING TARGET SYMBOL")
    print("=" * 80)
    
    # Analyze with sector context
    vacuum = await liquidity.analyze(symbol, include_sector_context=True)
    
    print()
    print(f"LIQUIDITY VACUUM RESULTS FOR {symbol}:")
    print("-" * 40)
    print(f"   Bid Collapsing:      {'✓' if vacuum.bid_collapsing else '✗'}")
    print(f"   Spread Widening:     {'✓' if vacuum.spread_widening else '✗'}")
    print(f"   Volume No Progress:  {'✓' if vacuum.volume_no_progress else '✗'}")
    print(f"   VWAP Retest Failed:  {'✓' if vacuum.vwap_retest_failed else '✗'}")
    print(f"   Final Score:         {vacuum.score:.2f}")
    print()
    
    print("=" * 80)
    print("2. SECTOR CONTEXT ANALYSIS")
    print("=" * 80)
    print()
    
    # Get detailed sector context
    sector_context = await liquidity.analyze_sector_context(symbol, vacuum)
    
    print(f"SECTOR: {sector_context['sector_name']}")
    print(f"PEERS ANALYZED: {sector_context['peer_count']}")
    print()
    
    print("PEER LIQUIDITY STATUS:")
    print("-" * 60)
    for peer in sector_context['peer_details']:
        signals = []
        if peer['bid_collapse']:
            signals.append("BID_COLLAPSE")
        if peer['spread_widening']:
            signals.append("SPREAD_WIDE")
        if peer['vwap_loss']:
            signals.append("VWAP_LOSS")
        
        signal_str = ", ".join(signals) if signals else "No signals"
        print(f"   {peer['symbol']:6} | {signal_str}")
    
    print()
    print("SECTOR SUMMARY:")
    print("-" * 40)
    print(f"   Peers with Bid Collapse:    {sector_context['peers_with_bid_collapse']}")
    print(f"   Peers with Spread Widening: {sector_context['peers_with_spread_widening']}")
    print(f"   Peers with VWAP Loss:       {sector_context['peers_with_vwap_loss']}")
    print(f"   Sector Liquidity Ratio:     {sector_context['sector_liquidity_ratio']:.0%}")
    print()
    print(f"   CONTEXT TYPE: {sector_context['context_type']}")
    print(f"   IS SECTOR-WIDE: {'YES' if sector_context['is_sector_wide'] else 'NO'}")
    print(f"   SCORE ADJUSTMENT: {sector_context['context_boost']:+.2f}")
    print()
    
    print("=" * 80)
    print("3. INTERPRETATION")
    print("=" * 80)
    print()
    
    if sector_context['context_type'] == "SECTOR_WIDE":
        print(f"🔴 SECTOR-WIDE LIQUIDITY WITHDRAWAL DETECTED")
        print(f"   {sector_context['sector_liquidity_ratio']:.0%} of {sector_context['sector_name']} peers")
        print(f"   showing liquidity stress signals.")
        print()
        print("   IMPLICATION: This is likely a MACRO or SECTOR-LEVEL event,")
        print("   not company-specific. Higher conviction for puts across sector.")
        print()
        print(f"   SCORE BOOST: +{sector_context['context_boost']:.2f} (strengthens signal)")
    elif sector_context['context_type'] == "MIXED":
        print(f"🟡 MIXED SECTOR LIQUIDITY")
        print(f"   Some peers affected, but not a clear sector-wide pattern.")
        print()
        print(f"   SCORE BOOST: +{sector_context['context_boost']:.2f} (moderate)")
    else:
        print(f"🟢 IDIOSYNCRATIC LIQUIDITY SIGNAL")
        print(f"   Only {symbol} is showing liquidity stress.")
        print(f"   Peers in {sector_context['sector_name']} appear normal.")
        print()
        print("   IMPLICATION: Could be company-specific issue OR noise.")
        print("   Requires additional confirmation before acting.")
        print()
        print(f"   SCORE ADJUSTMENT: {sector_context['context_boost']:.2f} (dampens signal)")
    
    print()
    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    
    return vacuum, sector_context


if __name__ == "__main__":
    asyncio.run(analyze_sector_liquidity("T"))
