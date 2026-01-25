#!/usr/bin/env python3
"""
Basic usage example for PutsEngine.

This script demonstrates how to use the PutsEngine programmatically.
"""

import asyncio
import sys
sys.path.insert(0, '..')

from putsengine import PutsEngine
from putsengine.config import get_settings


async def example_single_analysis():
    """Example: Analyze a single stock."""
    print("\n" + "=" * 50)
    print("Example 1: Single Stock Analysis")
    print("=" * 50)

    engine = PutsEngine()

    try:
        # Analyze AAPL
        candidate = await engine.run_single_symbol("AAPL")

        print(f"\nSymbol: {candidate.symbol}")
        print(f"Current Price: ${candidate.current_price:.2f}")
        print(f"Composite Score: {candidate.composite_score:.2f}")
        print(f"Passed Gates: {candidate.passed_all_gates}")

        if candidate.block_reasons:
            print(f"Block Reasons: {candidate.block_reasons}")

        print("\nScore Breakdown:")
        print(f"  Distribution: {candidate.distribution_score:.2f}")
        print(f"  Dealer: {candidate.dealer_score:.2f}")
        print(f"  Liquidity: {candidate.liquidity_score:.2f}")
        print(f"  Flow: {candidate.flow_score:.2f}")

        if candidate.contract_symbol:
            print(f"\nRecommended Contract:")
            print(f"  Symbol: {candidate.contract_symbol}")
            print(f"  Strike: ${candidate.recommended_strike:.0f}")
            print(f"  Entry: ${candidate.entry_price:.2f}")

    finally:
        await engine.close()


async def example_market_regime():
    """Example: Check market regime."""
    print("\n" + "=" * 50)
    print("Example 2: Market Regime Check")
    print("=" * 50)

    engine = PutsEngine()

    try:
        regime = await engine.market_regime.analyze()

        print(f"\nRegime: {regime.regime.value}")
        print(f"Tradeable: {regime.is_tradeable}")
        print(f"SPY Below VWAP: {regime.spy_below_vwap}")
        print(f"QQQ Below VWAP: {regime.qqq_below_vwap}")
        print(f"Index GEX: {regime.index_gex:,.0f}")
        print(f"VIX: {regime.vix_level:.2f} ({regime.vix_change:+.2%})")

        if regime.block_reasons:
            print(f"Block Reasons: {regime.block_reasons}")

    finally:
        await engine.close()


async def example_full_pipeline():
    """Example: Run full daily pipeline."""
    print("\n" + "=" * 50)
    print("Example 3: Full Daily Pipeline")
    print("=" * 50)

    engine = PutsEngine()

    try:
        # Run on a small universe
        universe = ["AAPL", "TSLA", "NVDA", "AMD", "META"]

        report = await engine.run_daily_pipeline(universe)

        print(f"\nDate: {report.date}")
        print(f"Symbols Scanned: {report.total_scanned}")
        print(f"Shortlist: {report.shortlist_count}")
        print(f"Passed Gates: {report.passed_gates}")

        if report.candidates:
            print("\nTop Candidates:")
            for c in report.candidates[:3]:
                print(f"  {c.symbol}: Score={c.composite_score:.2f}")

    finally:
        await engine.close()


async def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("PutsEngine - Basic Usage Examples")
    print("=" * 60)

    try:
        await example_market_regime()
        await example_single_analysis()
        await example_full_pipeline()

    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure your API keys are configured in .env file")


if __name__ == "__main__":
    asyncio.run(main())
