#!/usr/bin/env python3
"""
🏛️ MANUAL TRADING SCAN - ALL POSSIBLE TRADES
=============================================

Displays ALL PUT candidates across:
- All 3 engines (Gamma Drain, Distribution, Liquidity)
- All scoring tiers (Explosive → Monitoring)
- All signals detected

NO AUTOMATIC TRADING - Display only for manual execution.

PhD Quant + 30yr Trading + Institutional Microstructure
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
import pytz

sys.path.insert(0, '.')

from putsengine.config import get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.layers.market_regime import MarketRegimeLayer
from putsengine.layers.distribution import DistributionLayer
from putsengine.layers.liquidity import LiquidityVacuumLayer
from putsengine.layers.acceleration import AccelerationWindowLayer
from putsengine.scoring.scorer import PutScorer
from putsengine.gates.trading_gates import TradingGates, DailyHardGateReport

# All tickers to scan
ALL_TICKERS = [
    # Mega-cap Tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    # Semiconductors
    "AMD", "INTC", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "NXPI",
    # Software/Cloud
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "PLTR", "DDOG", "NET", "ZS", "CRWD", "PANW",
    # Fintech/Payments
    "V", "MA", "PYPL", "SQ", "COIN", "HOOD", "AFRM", "SOFI",
    # E-commerce/Consumer
    "SHOP", "ETSY", "EBAY", "CHWY", "W", "BABA", "JD", "PDD",
    # Streaming/Media
    "NFLX", "DIS", "WBD", "PARA", "ROKU", "SPOT",
    # EV/Auto
    "RIVN", "LCID", "F", "GM", "TM", "XPEV", "NIO", "LI",
    # Biotech/Pharma
    "MRNA", "BNTX", "PFE", "JNJ", "LLY", "ABBV", "BMY", "GILD", "REGN", "VRTX", "BIIB",
    # Healthcare
    "UNH", "CVS", "HCA", "ISRG", "DXCM", "TDOC",
    # Banks/Financial
    "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY", "HAL", "MPC", "VLO", "PSX",
    # Industrial
    "BA", "CAT", "DE", "GE", "HON", "UPS", "FDX", "LMT", "RTX", "NOC",
    # Retail
    "WMT", "TGT", "COST", "HD", "LOW", "DG", "DLTR", "ROST", "TJX",
    # Travel/Leisure
    "UAL", "DAL", "AAL", "LUV", "MAR", "HLT", "ABNB", "BKNG", "EXPE",
    # Gaming/Entertainment
    "DKNG", "PENN", "MGM", "WYNN", "LVS", "EA", "TTWO", "RBLX",
    # Crypto-adjacent
    "MARA", "RIOT", "CLSK", "MSTR",
    # REITs
    "SPG", "O", "AMT", "CCI", "EQIX", "PLD",
    # Telecom
    "T", "VZ", "TMUS",
    # Consumer Staples
    "KO", "PEP", "PG", "CL", "KMB", "GIS", "K", "CPB",
    # Misc Tech
    "UBER", "LYFT", "DASH", "ZM", "DOCU", "OKTA", "TWLO", "MDB", "ESTC",
    # Index ETFs (for regime reference)
    "SPY", "QQQ", "IWM", "DIA",
]


def get_tier(score: float) -> str:
    """Get signal tier from score."""
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.65:
        return "⚡ VERY STRONG"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    else:
        return "⬜ BELOW THRESHOLD"


def get_next_friday(from_date: date, offset_weeks: int = 0) -> date:
    """Get next Friday expiry date."""
    days_until_friday = (4 - from_date.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    next_friday = from_date + timedelta(days=days_until_friday)
    return next_friday + timedelta(weeks=offset_weeks)


async def scan_all_tickers():
    """Scan all tickers and display ALL possible trades."""
    
    print("=" * 80)
    print("🏛️ MANUAL TRADING SCAN - ALL POSSIBLE PUT CANDIDATES")
    print("=" * 80)
    print()
    
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    today = date.today()
    
    print(f"📅 Scan Date: {now_et.strftime('%A, %B %d, %Y')}")
    print(f"⏰ Scan Time: {now_et.strftime('%I:%M %p ET')}")
    print()
    
    # Calculate expiry dates
    first_friday = get_next_friday(today)
    second_friday = get_next_friday(today, offset_weeks=1)
    
    print(f"📆 EXPIRY DATES (Fridays Only):")
    print(f"   Near-term: {first_friday.strftime('%b %d, %Y')} (DTE: {(first_friday - today).days})")
    print(f"   Extended:  {second_friday.strftime('%b %d, %Y')} (DTE: {(second_friday - today).days})")
    print()
    
    # Initialize clients
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    # Initialize layers
    market_regime_layer = MarketRegimeLayer(alpaca, polygon, uw, settings)
    distribution_layer = DistributionLayer(alpaca, polygon, uw, settings)
    liquidity_layer = LiquidityVacuumLayer(alpaca, polygon, settings)
    acceleration_layer = AccelerationWindowLayer(alpaca, polygon, uw, settings)
    scorer = PutScorer(settings)
    trading_gates = TradingGates()
    
    # Check market regime first
    print("📊 MARKET REGIME CHECK")
    print("-" * 80)
    
    try:
        market_regime = await market_regime_layer.analyze()
        print(f"   Regime: {market_regime.regime.value}")
        print(f"   Tradeable: {'✅ YES' if market_regime.is_tradeable else '❌ NO'}")
        print(f"   SPY < VWAP: {'✅' if market_regime.spy_below_vwap else '❌'}")
        print(f"   QQQ < VWAP: {'✅' if market_regime.qqq_below_vwap else '❌'}")
        print(f"   VIX: {market_regime.vix_level:.2f}")
        print(f"   Net GEX: {market_regime.net_gex}")
        
        if market_regime.block_reasons:
            print(f"   ⚠️ Blocks: {', '.join(market_regime.block_reasons)}")
    except Exception as e:
        print(f"   ⚠️ Error fetching regime: {e}")
        market_regime = None
    
    print()
    
    # Check timing gate
    can_trade_time, time_reason = trading_gates.is_after_opening_range()
    print(f"⏰ TIMING: {time_reason}")
    print()
    
    # Storage for all candidates
    all_candidates: List[Dict] = []
    gamma_drain_candidates: List[Dict] = []
    distribution_candidates: List[Dict] = []
    liquidity_candidates: List[Dict] = []
    
    # Scan all tickers
    print("🔍 SCANNING ALL TICKERS...")
    print("-" * 80)
    
    total = len(ALL_TICKERS)
    success = 0
    errors = 0
    
    for i, symbol in enumerate(ALL_TICKERS):
        try:
            # Progress
            if (i + 1) % 20 == 0:
                print(f"   Progress: {i+1}/{total} ({success} candidates, {errors} errors)")
            
            # Get price data
            bars = await polygon.get_daily_bars(
                symbol=symbol,
                from_date=today - timedelta(days=30)
            )
            
            if not bars or len(bars) < 5:
                continue
            
            current_price = bars[-1].close
            prev_close = bars[-2].close if len(bars) >= 2 else current_price
            daily_change = (current_price - prev_close) / prev_close * 100
            
            # Calculate RSI
            if len(bars) >= 14:
                changes = [bars[i].close - bars[i-1].close for i in range(1, len(bars))]
                gains = [c if c > 0 else 0 for c in changes[-14:]]
                losses = [-c if c < 0 else 0 for c in changes[-14:]]
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100
            else:
                rsi = 50
            
            # Calculate RVOL
            if len(bars) >= 20:
                avg_vol = sum(b.volume for b in bars[-20:-1]) / 19
                rvol = bars[-1].volume / avg_vol if avg_vol > 0 else 1.0
            else:
                rvol = 1.0
            
            # Analyze distribution
            distribution = await distribution_layer.analyze(symbol)
            
            # Analyze liquidity
            liquidity = await liquidity_layer.analyze(symbol)
            
            # Analyze acceleration
            acceleration = await acceleration_layer.analyze(symbol, market_regime)
            
            # Score the candidate
            from putsengine.models import PutCandidate, EngineType
            
            candidate = PutCandidate(
                symbol=symbol,
                engine_type=acceleration.engine_type if acceleration else EngineType.NONE,
                current_price=current_price,
                entry_zone_low=current_price * 0.98,
                entry_zone_high=current_price * 1.02,
                target_price=current_price * 0.92,
                stop_price=current_price * 1.05,
                confidence=0.5,
                distribution=distribution,
                liquidity=liquidity,
                acceleration=acceleration,
                market_regime=market_regime,
                composite_score=0.0,
                signals=[],
                timestamp=datetime.now()
            )
            
            # Calculate composite score
            score = scorer.score(candidate)
            candidate.composite_score = score
            
            # Skip very low scores
            if score < 0.35:
                continue
            
            # Get active signals
            active_signals = []
            if distribution:
                for key, val in distribution.signals.items():
                    if val:
                        active_signals.append(key)
            
            if liquidity:
                if liquidity.bid_collapse:
                    active_signals.append("bid_collapse")
                if liquidity.spread_widening:
                    active_signals.append("spread_widening")
                if liquidity.vwap_retest_failed:
                    active_signals.append("vwap_retest_failed")
            
            if acceleration:
                if acceleration.gamma_flipping_short:
                    active_signals.append("gamma_flip")
                if acceleration.net_delta_negative:
                    active_signals.append("delta_negative")
                if acceleration.put_sweep_detected:
                    active_signals.append("put_sweep")
                if acceleration.price_below_vwap:
                    active_signals.append("below_vwap")
            
            # Determine engine type
            engine_type = "Unknown"
            if acceleration:
                if acceleration.engine_type.value == "gamma_drain":
                    engine_type = "Gamma Drain"
                elif acceleration.engine_type.value == "distribution_trap":
                    engine_type = "Distribution"
                elif acceleration.engine_type.value == "snapback":
                    engine_type = "Liquidity"
                else:
                    # Default classification based on signals
                    if acceleration.gamma_flipping_short or acceleration.net_delta_negative:
                        engine_type = "Gamma Drain"
                    elif distribution and (distribution.call_selling_at_bid or distribution.failed_breakout):
                        engine_type = "Distribution"
                    else:
                        engine_type = "Liquidity"
            
            # Calculate strike recommendation
            strike = round(current_price * 0.95, 0)  # ~5% OTM
            
            # Select expiry based on score
            if score >= 0.65:
                expiry = first_friday
            else:
                expiry = second_friday
            
            dte = (expiry - today).days
            
            # Build candidate dict
            candidate_data = {
                "symbol": symbol,
                "score": score,
                "tier": get_tier(score),
                "engine": engine_type,
                "price": current_price,
                "daily_change": daily_change,
                "rsi": rsi,
                "rvol": rvol,
                "strike": strike,
                "expiry": expiry.strftime("%b %d"),
                "dte": dte,
                "signals": active_signals,
                "signal_count": len(active_signals),
            }
            
            all_candidates.append(candidate_data)
            success += 1
            
            # Categorize by engine
            if engine_type == "Gamma Drain":
                gamma_drain_candidates.append(candidate_data)
            elif engine_type == "Distribution":
                distribution_candidates.append(candidate_data)
            else:
                liquidity_candidates.append(candidate_data)
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.3)
            
        except Exception as e:
            errors += 1
            continue
    
    # Close clients
    await alpaca.close()
    await polygon.close()
    await uw.close()
    
    # Sort all by score
    all_candidates.sort(key=lambda x: x['score'], reverse=True)
    gamma_drain_candidates.sort(key=lambda x: x['score'], reverse=True)
    distribution_candidates.sort(key=lambda x: x['score'], reverse=True)
    liquidity_candidates.sort(key=lambda x: x['score'], reverse=True)
    
    print()
    print(f"✅ Scan complete: {success} candidates found, {errors} errors")
    print()
    
    # =========================================================================
    # DISPLAY ALL RESULTS
    # =========================================================================
    
    print("=" * 80)
    print("🎯 ALL POSSIBLE PUT TRADES (SORTED BY SCORE)")
    print("=" * 80)
    print()
    
    # Summary by tier
    explosive = [c for c in all_candidates if c['tier'] == "🔥 EXPLOSIVE"]
    very_strong = [c for c in all_candidates if c['tier'] == "⚡ VERY STRONG"]
    strong = [c for c in all_candidates if c['tier'] == "💪 STRONG"]
    monitoring = [c for c in all_candidates if c['tier'] == "👀 MONITORING"]
    
    print("📊 SUMMARY BY TIER:")
    print(f"   🔥 EXPLOSIVE (0.75+):     {len(explosive)}")
    print(f"   ⚡ VERY STRONG (0.65-0.74): {len(very_strong)}")
    print(f"   💪 STRONG (0.55-0.64):     {len(strong)}")
    print(f"   👀 MONITORING (0.45-0.54): {len(monitoring)}")
    print()
    
    print("📊 SUMMARY BY ENGINE:")
    print(f"   🔥 Gamma Drain:  {len(gamma_drain_candidates)}")
    print(f"   📉 Distribution: {len(distribution_candidates)}")
    print(f"   💧 Liquidity:    {len(liquidity_candidates)}")
    print()
    
    # -------------------------------------------------------------------------
    # EXPLOSIVE TIER
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("🔥 EXPLOSIVE TIER (Score ≥ 0.75) - Expected Move: -10% to -15%")
    print("=" * 80)
    
    if explosive:
        print(f"{'Symbol':<8} {'Score':>8} {'Engine':<14} {'Price':>10} {'Chg%':>8} {'RSI':>6} {'Strike':>8} {'Expiry':>8} {'DTE':>5} {'Signals'}")
        print("-" * 100)
        for c in explosive:
            signals_str = ", ".join(c['signals'][:4])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['engine']:<14} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% {c['rsi']:>5.1f} ${c['strike']:>6.0f}P {c['expiry']:>8} {c['dte']:>5} {signals_str}")
    else:
        print("   No EXPLOSIVE candidates found")
    print()
    
    # -------------------------------------------------------------------------
    # VERY STRONG TIER
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("⚡ VERY STRONG TIER (Score 0.65-0.74) - Expected Move: -5% to -10%")
    print("=" * 80)
    
    if very_strong:
        print(f"{'Symbol':<8} {'Score':>8} {'Engine':<14} {'Price':>10} {'Chg%':>8} {'RSI':>6} {'Strike':>8} {'Expiry':>8} {'DTE':>5} {'Signals'}")
        print("-" * 100)
        for c in very_strong:
            signals_str = ", ".join(c['signals'][:4])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['engine']:<14} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% {c['rsi']:>5.1f} ${c['strike']:>6.0f}P {c['expiry']:>8} {c['dte']:>5} {signals_str}")
    else:
        print("   No VERY STRONG candidates found")
    print()
    
    # -------------------------------------------------------------------------
    # STRONG TIER
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("💪 STRONG TIER (Score 0.55-0.64) - Expected Move: -3% to -7%")
    print("=" * 80)
    
    if strong:
        print(f"{'Symbol':<8} {'Score':>8} {'Engine':<14} {'Price':>10} {'Chg%':>8} {'RSI':>6} {'Strike':>8} {'Expiry':>8} {'DTE':>5} {'Signals'}")
        print("-" * 100)
        for c in strong:
            signals_str = ", ".join(c['signals'][:4])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['engine']:<14} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% {c['rsi']:>5.1f} ${c['strike']:>6.0f}P {c['expiry']:>8} {c['dte']:>5} {signals_str}")
    else:
        print("   No STRONG candidates found")
    print()
    
    # -------------------------------------------------------------------------
    # MONITORING TIER
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("👀 MONITORING TIER (Score 0.45-0.54) - Expected Move: -2% to -5%")
    print("=" * 80)
    
    if monitoring:
        print(f"{'Symbol':<8} {'Score':>8} {'Engine':<14} {'Price':>10} {'Chg%':>8} {'RSI':>6} {'Strike':>8} {'Expiry':>8} {'DTE':>5} {'Signals'}")
        print("-" * 100)
        for c in monitoring[:20]:  # Limit to top 20
            signals_str = ", ".join(c['signals'][:4])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['engine']:<14} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% {c['rsi']:>5.1f} ${c['strike']:>6.0f}P {c['expiry']:>8} {c['dte']:>5} {signals_str}")
        if len(monitoring) > 20:
            print(f"   ... and {len(monitoring) - 20} more")
    else:
        print("   No MONITORING candidates found")
    print()
    
    # -------------------------------------------------------------------------
    # BY ENGINE BREAKDOWN
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("🔥 GAMMA DRAIN ENGINE - Top Candidates")
    print("=" * 80)
    
    if gamma_drain_candidates:
        print(f"{'Symbol':<8} {'Score':>8} {'Tier':<18} {'Price':>10} {'Chg%':>8} {'Strike':>8} {'Expiry':>8} {'Top Signals'}")
        print("-" * 100)
        for c in gamma_drain_candidates[:15]:
            signals_str = ", ".join(c['signals'][:3])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['tier']:<18} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% ${c['strike']:>6.0f}P {c['expiry']:>8} {signals_str}")
    else:
        print("   No Gamma Drain candidates")
    print()
    
    print("=" * 80)
    print("📉 DISTRIBUTION ENGINE - Top Candidates")
    print("=" * 80)
    
    if distribution_candidates:
        print(f"{'Symbol':<8} {'Score':>8} {'Tier':<18} {'Price':>10} {'Chg%':>8} {'Strike':>8} {'Expiry':>8} {'Top Signals'}")
        print("-" * 100)
        for c in distribution_candidates[:15]:
            signals_str = ", ".join(c['signals'][:3])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['tier']:<18} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% ${c['strike']:>6.0f}P {c['expiry']:>8} {signals_str}")
    else:
        print("   No Distribution candidates")
    print()
    
    print("=" * 80)
    print("💧 LIQUIDITY ENGINE - Top Candidates")
    print("=" * 80)
    
    if liquidity_candidates:
        print(f"{'Symbol':<8} {'Score':>8} {'Tier':<18} {'Price':>10} {'Chg%':>8} {'Strike':>8} {'Expiry':>8} {'Top Signals'}")
        print("-" * 100)
        for c in liquidity_candidates[:15]:
            signals_str = ", ".join(c['signals'][:3])
            print(f"{c['symbol']:<8} {c['score']:>8.4f} {c['tier']:<18} ${c['price']:>8.2f} {c['daily_change']:>+7.2f}% ${c['strike']:>6.0f}P {c['expiry']:>8} {signals_str}")
    else:
        print("   No Liquidity candidates")
    print()
    
    # -------------------------------------------------------------------------
    # EXECUTION GUIDANCE
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("📋 MANUAL EXECUTION GUIDANCE")
    print("=" * 80)
    print()
    print("⏰ TIMING RULES:")
    print("   • Wait until 09:45 ET before entering any trades")
    print("   • Primary window: 09:45 - 10:30 ET")
    print("   • Confirmation window: 10:30 - 12:00 ET")
    print()
    print("🎯 POSITION SIZING:")
    print("   • Max 2% risk per trade")
    print("   • Max 2 positions per day")
    print("   • Scale into EXPLOSIVE/VERY STRONG only")
    print()
    print("📉 STRIKE SELECTION:")
    print("   • Delta: -0.30 to -0.325")
    print("   • Slightly OTM (shown strikes are ~5% OTM)")
    print("   • Prefer higher liquidity strikes")
    print()
    print("⚠️ EXIT RULES:")
    print("   • If VWAP reclaimed and held 15 min → EXIT")
    print("   • No averaging down")
    print("   • Honor stop losses")
    print()
    print("=" * 80)
    print(f"⏰ Report generated: {now_et.strftime('%I:%M %p ET')}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(scan_all_tickers())
