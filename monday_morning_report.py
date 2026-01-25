#!/usr/bin/env python3
"""
🏛️ MONDAY MORNING / DAILY HARD-GATE REPORT
==========================================

Run this FIRST thing every trading day.

No scores. No trades. Just:
- Market regime
- GEX state
- Passive inflow block
- Earnings blocks
- HTB flags

If ANY hard block is present → NO TRADES TODAY

PhD Quant + 30yr Trading + Institutional Microstructure
"""

import asyncio
import sys
from datetime import datetime
import pytz

sys.path.insert(0, '.')

from putsengine.config import get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.layers.market_regime import MarketRegimeLayer
from putsengine.gates.trading_gates import TradingGates, DailyHardGateReport


async def generate_morning_report():
    """Generate the daily hard-gate report."""
    
    print("=" * 70)
    print("🏛️ GENERATING DAILY HARD-GATE REPORT...")
    print("=" * 70)
    print()
    
    # Initialize
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    market_regime_layer = MarketRegimeLayer(alpaca, polygon, uw, settings)
    trading_gates = TradingGates()
    report_generator = DailyHardGateReport(settings)
    
    try:
        # 1. Check Opening Range Gate
        can_trade_time, time_reason = trading_gates.is_after_opening_range()
        print(f"⏰ TIMING CHECK: {time_reason}")
        print()
        
        # 2. Get Market Regime
        print("📊 Fetching market regime...")
        market_regime = await market_regime_layer.analyze()
        
        # 3. Get GEX data for SPY
        print("📈 Fetching GEX data...")
        try:
            gex_data = await uw.get_gex_data("SPY")
        except:
            gex_data = None
        
        # 4. Check for HTB symbols (placeholder - would need Alpaca data)
        htb_symbols = []  # Would populate from Alpaca ETB->HTB transitions
        
        # 5. Generate report
        report = await report_generator.generate_report(
            market_regime=market_regime,
            gex_data=gex_data,
            htb_symbols=htb_symbols
        )
        
        # 6. Print formatted report
        formatted = report_generator.format_report_text(report)
        print(formatted)
        
        # 7. Additional execution guidance
        print()
        print("📋 EXECUTION GUIDANCE")
        print("-" * 70)
        
        if report['final_verdict'].startswith("🔴"):
            print("   ❌ DO NOT TRADE TODAY")
            print("   ❌ Do not force signals")
            print("   ❌ Capital preservation is the goal")
        else:
            print("   ✅ Market conditions allow PUT evaluation")
            print("   ⏰ Wait until 09:45 ET to enter any trades")
            print("   📊 Focus on score >= 0.68 candidates only")
            print("   🎯 Max 2 trades per day")
            print("   💰 Max 2% risk per trade")
            print()
            print("   EXECUTION WINDOWS:")
            print("   • 09:45-10:30: Primary scan")
            print("   • 10:30-12:00: Confirmation")
            print("   • 14:30-15:30: Final evaluation")
        
        print()
        print("=" * 70)
        print(f"⏰ Report generated at: {datetime.now(pytz.timezone('US/Eastern')).strftime('%I:%M %p ET')}")
        print("=" * 70)
        
    finally:
        await alpaca.close()
        await polygon.close()
        await uw.close()


if __name__ == "__main__":
    asyncio.run(generate_morning_report())
