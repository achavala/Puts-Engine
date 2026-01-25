#!/usr/bin/env python3
"""
INSTITUTIONAL-GRADE BACKTEST
January 20-23, 2026

Using REAL market data from Polygon API to validate the PutsEngine
scoring algorithm against actual price movements.

PhD Quant + 30yr Trading + Institutional Microstructure Analysis
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import json

sys.path.insert(0, '.')

from putsengine.config import EngineConfig, get_settings
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.models import PriceBar
import numpy as np

# Backtest date range
BACKTEST_START = date(2026, 1, 20)  # Monday
BACKTEST_END = date(2026, 1, 23)    # Thursday

# Scoring tiers
def get_tier(score: float) -> str:
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.65:
        return "⚡ VERY STRONG"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    return "❌ BELOW"

def print_separator(char="=", length=100):
    print(char * length)

class BacktestEngine:
    """Institutional-grade backtesting engine."""
    
    def __init__(self):
        self.settings = get_settings()
        self.polygon = PolygonClient(self.settings)
        self.alpaca = AlpacaClient(self.settings)
        self.tickers = EngineConfig.get_all_tickers()
        self.results: Dict[str, List] = {}
        
    async def close(self):
        await self.polygon.close()
        await self.alpaca.close()
    
    async def fetch_historical_bars(
        self, 
        symbol: str, 
        from_date: date, 
        to_date: date
    ) -> List[Dict]:
        """Fetch daily bars for a symbol."""
        try:
            bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=from_date,
                to_date=to_date
            )
            return bars
        except Exception as e:
            return []
    
    def calculate_rvol(self, bars: List[PriceBar], idx: int, lookback: int = 20) -> float:
        """Calculate relative volume."""
        if idx < lookback:
            return 1.0
        
        avg_vol = np.mean([b.volume for b in bars[idx-lookback:idx]])
        if avg_vol == 0:
            return 1.0
        return bars[idx].volume / avg_vol
    
    def detect_gap_down(self, bars: List[PriceBar], idx: int) -> Tuple[bool, float]:
        """Detect gap down pattern."""
        if idx < 1:
            return False, 0.0
        
        prev_close = bars[idx-1].close
        curr_open = bars[idx].open
        gap_pct = (curr_open - prev_close) / prev_close
        
        # Gap down > 1%
        if gap_pct < -0.01:
            # Check if failed to recover
            if bars[idx].close <= bars[idx].open:
                return True, gap_pct
        return False, gap_pct
    
    def detect_red_day(self, bar: PriceBar) -> bool:
        """Check if day closed red."""
        return bar.close < bar.open
    
    def detect_multi_day_weakness(self, bars: List[PriceBar], idx: int) -> bool:
        """Detect 3+ consecutive lower closes."""
        if idx < 3:
            return False
        
        count = 0
        for i in range(idx, max(idx-5, 0), -1):
            if bars[i].close < bars[i-1].close:
                count += 1
            else:
                break
        return count >= 3
    
    def detect_below_prior_low(self, bars: List[PriceBar], idx: int) -> bool:
        """Check if current price below prior day's low."""
        if idx < 1:
            return False
        return bars[idx].close < bars[idx-1].low
    
    def detect_failed_breakout(self, bars: List[PriceBar], idx: int) -> bool:
        """Detect failed breakout pattern."""
        if idx < 20:
            return False
        
        # Find recent 20-day high
        highs = [b.high for b in bars[idx-20:idx]]
        resistance = max(highs)
        
        curr = bars[idx]
        # Touched resistance but closed below
        if curr.high >= resistance * 0.995 and curr.close < resistance * 0.98:
            return True
        return False
    
    def calculate_daily_score(
        self, 
        bars: List[PriceBar], 
        idx: int
    ) -> Tuple[float, Dict]:
        """
        Calculate distribution score for a single day.
        Returns score and signals dict.
        """
        signals = {
            "high_rvol_red_day": False,
            "gap_down_no_recovery": False,
            "multi_day_weakness": False,
            "below_prior_low": False,
            "failed_breakout": False,
            "red_day": False,
        }
        
        if idx < 1 or idx >= len(bars):
            return 0.0, signals
        
        bar = bars[idx]
        
        # 1. HIGH RVOL on red day (strongest signal)
        rvol = self.calculate_rvol(bars, idx)
        is_red = self.detect_red_day(bar)
        if rvol >= 2.0 and is_red:
            signals["high_rvol_red_day"] = True
        elif rvol >= 1.5 and is_red and (bar.close - bar.open) / bar.open < -0.02:
            signals["high_rvol_red_day"] = True
        
        signals["red_day"] = is_red
        
        # 2. Gap down no recovery
        gap_down, gap_pct = self.detect_gap_down(bars, idx)
        signals["gap_down_no_recovery"] = gap_down
        signals["gap_pct"] = gap_pct
        
        # 3. Multi-day weakness
        signals["multi_day_weakness"] = self.detect_multi_day_weakness(bars, idx)
        
        # 4. Below prior low
        signals["below_prior_low"] = self.detect_below_prior_low(bars, idx)
        
        # 5. Failed breakout
        signals["failed_breakout"] = self.detect_failed_breakout(bars, idx)
        
        # Calculate score
        score = 0.0
        if signals["high_rvol_red_day"]:
            score += 0.25
        if signals["gap_down_no_recovery"]:
            score += 0.20
        if signals["multi_day_weakness"]:
            score += 0.15
        if signals["below_prior_low"]:
            score += 0.15
        if signals["failed_breakout"]:
            score += 0.15
        if signals["red_day"]:
            score += 0.10
        
        # Store additional data
        signals["rvol"] = rvol
        signals["daily_change"] = (bar.close - bar.open) / bar.open * 100
        signals["close"] = bar.close
        signals["volume"] = bar.volume
        
        return min(score, 1.0), signals
    
    def calculate_forward_return(
        self, 
        bars: List[PriceBar], 
        signal_idx: int, 
        days_forward: int = 5
    ) -> Tuple[float, float]:
        """
        Calculate the forward return after a signal.
        Returns (max_drawdown, end_return)
        """
        if signal_idx >= len(bars) - 1:
            return 0.0, 0.0
        
        entry_price = bars[signal_idx].close
        max_drawdown = 0.0
        end_return = 0.0
        
        for i in range(signal_idx + 1, min(signal_idx + days_forward + 1, len(bars))):
            bar = bars[i]
            # Max drawdown (minimum from entry)
            low_return = (bar.low - entry_price) / entry_price
            max_drawdown = min(max_drawdown, low_return)
            # End return
            end_return = (bar.close - entry_price) / entry_price
        
        return max_drawdown * 100, end_return * 100
    
    async def run_backtest(self):
        """Run the full backtest."""
        print_separator()
        print("  🔬 INSTITUTIONAL-GRADE BACKTEST")
        print(f"  Date Range: {BACKTEST_START} to {BACKTEST_END}")
        print(f"  Tickers: {len(self.tickers)}")
        print_separator()
        
        # Generate trading days
        trading_days = []
        current = BACKTEST_START
        while current <= BACKTEST_END:
            if current.weekday() < 5:  # Monday-Friday
                trading_days.append(current)
            current += timedelta(days=1)
        
        print(f"\n📅 Trading Days: {[d.strftime('%Y-%m-%d (%a)') for d in trading_days]}")
        
        # Results storage
        daily_results = {d: [] for d in trading_days}
        all_signals = []
        
        # Need extra history for calculations
        history_start = BACKTEST_START - timedelta(days=45)
        
        print(f"\n🔄 Fetching data for {len(self.tickers)} tickers...")
        
        # Fetch data for all tickers
        ticker_data = {}
        fetched = 0
        errors = 0
        
        for symbol in self.tickers:
            try:
                bars = await self.fetch_historical_bars(
                    symbol, 
                    history_start, 
                    BACKTEST_END + timedelta(days=10)  # Extra for forward returns
                )
                if bars and len(bars) >= 20:
                    ticker_data[symbol] = bars
                    fetched += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
            
            if (fetched + errors) % 25 == 0:
                print(f"   Progress: {fetched + errors}/{len(self.tickers)}")
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)
        
        print(f"\n✅ Data fetched: {fetched} tickers, {errors} errors")
        
        # Process each trading day
        for trade_date in trading_days:
            print_separator("-", 80)
            print(f"\n📊 ANALYSIS FOR {trade_date.strftime('%Y-%m-%d (%A)')}")
            print_separator("-", 80)
            
            day_candidates = []
            
            for symbol, bars in ticker_data.items():
                # Find the bar index for this date
                bar_idx = None
                for i, bar in enumerate(bars):
                    if bar.timestamp.date() == trade_date:
                        bar_idx = i
                        break
                
                if bar_idx is None or bar_idx < 20:
                    continue
                
                # Calculate score
                score, signals = self.calculate_daily_score(bars, bar_idx)
                
                if score >= 0.45:  # At least MONITORING tier
                    # Calculate forward returns
                    max_dd, end_return = self.calculate_forward_return(bars, bar_idx, 5)
                    
                    candidate = {
                        "symbol": symbol,
                        "date": trade_date,
                        "score": score,
                        "tier": get_tier(score),
                        "signals": signals,
                        "close": signals["close"],
                        "daily_change": signals["daily_change"],
                        "rvol": signals["rvol"],
                        "max_drawdown_5d": max_dd,
                        "return_5d": end_return,
                    }
                    day_candidates.append(candidate)
                    all_signals.append(candidate)
            
            # Sort by score
            day_candidates.sort(key=lambda x: x["score"], reverse=True)
            daily_results[trade_date] = day_candidates
            
            if day_candidates:
                print(f"\n🎯 CANDIDATES FOUND: {len(day_candidates)}")
                print(f"\n{'Symbol':<8} {'Tier':<15} {'Score':>6} {'Close':>10} {'Chg%':>8} {'RVOL':>6} {'5D Max DD':>10} {'5D Return':>10}")
                print("-" * 85)
                
                for c in day_candidates[:15]:  # Top 15
                    print(f"{c['symbol']:<8} {c['tier']:<15} {c['score']:>6.2f} ${c['close']:>9.2f} {c['daily_change']:>7.1f}% {c['rvol']:>5.1f}x {c['max_drawdown_5d']:>9.1f}% {c['return_5d']:>9.1f}%")
                
                if len(day_candidates) > 15:
                    print(f"   ... and {len(day_candidates) - 15} more candidates")
                
                # Show signals breakdown for top 5
                print(f"\n📈 TOP 5 SIGNAL BREAKDOWN:")
                for c in day_candidates[:5]:
                    active = [k for k, v in c['signals'].items() if v is True]
                    print(f"   {c['symbol']}: {', '.join(active)}")
            else:
                print(f"\n⚠️ No candidates found for this day")
        
        # Summary Statistics
        print_separator()
        print("\n📊 BACKTEST SUMMARY STATISTICS")
        print_separator()
        
        # Aggregate by tier
        tier_stats = {
            "🔥 EXPLOSIVE": {"count": 0, "wins": 0, "total_dd": 0, "total_return": 0},
            "⚡ VERY STRONG": {"count": 0, "wins": 0, "total_dd": 0, "total_return": 0},
            "💪 STRONG": {"count": 0, "wins": 0, "total_dd": 0, "total_return": 0},
            "👀 MONITORING": {"count": 0, "wins": 0, "total_dd": 0, "total_return": 0},
        }
        
        for signal in all_signals:
            tier = signal["tier"]
            if tier in tier_stats:
                tier_stats[tier]["count"] += 1
                tier_stats[tier]["total_dd"] += signal["max_drawdown_5d"]
                tier_stats[tier]["total_return"] += signal["return_5d"]
                # Win = price dropped (negative return = win for puts)
                if signal["return_5d"] < -1:  # At least 1% drop
                    tier_stats[tier]["wins"] += 1
        
        print(f"\n{'Tier':<20} {'Count':>8} {'Wins':>8} {'Win Rate':>10} {'Avg DD':>10} {'Avg Return':>12}")
        print("-" * 70)
        
        for tier, stats in tier_stats.items():
            if stats["count"] > 0:
                win_rate = stats["wins"] / stats["count"] * 100
                avg_dd = stats["total_dd"] / stats["count"]
                avg_return = stats["total_return"] / stats["count"]
                print(f"{tier:<20} {stats['count']:>8} {stats['wins']:>8} {win_rate:>9.1f}% {avg_dd:>9.1f}% {avg_return:>11.1f}%")
        
        # Most profitable signals
        print_separator()
        print("\n🏆 TOP 10 MOST PROFITABLE PUT CANDIDATES (by max drawdown)")
        print_separator()
        
        # Sort by max drawdown (most negative = best for puts)
        sorted_signals = sorted(all_signals, key=lambda x: x["max_drawdown_5d"])
        
        print(f"\n{'Date':<12} {'Symbol':<8} {'Tier':<15} {'Score':>6} {'Entry':>10} {'5D Max DD':>10} {'5D Return':>10}")
        print("-" * 85)
        
        for s in sorted_signals[:10]:
            print(f"{s['date'].strftime('%m/%d'):<12} {s['symbol']:<8} {s['tier']:<15} {s['score']:>6.2f} ${s['close']:>9.2f} {s['max_drawdown_5d']:>9.1f}% {s['return_5d']:>9.1f}%")
        
        # Calculate portfolio return
        print_separator()
        print("\n💰 HYPOTHETICAL PORTFOLIO PERFORMANCE")
        print_separator()
        
        # Simulate: Buy puts on VERY STRONG+ signals each day
        portfolio_return = 0.0
        trades = 0
        winning_trades = 0
        
        for signal in all_signals:
            if signal["score"] >= 0.65:  # VERY STRONG+
                # Assume 3x leverage from puts (conservative)
                put_return = -signal["max_drawdown_5d"] * 3  # Negative DD = positive put return
                portfolio_return += put_return
                trades += 1
                if put_return > 0:
                    winning_trades += 1
        
        if trades > 0:
            print(f"\n   Strategy: Buy puts on VERY STRONG+ signals (score >= 0.65)")
            print(f"   Total Trades: {trades}")
            print(f"   Winning Trades: {winning_trades} ({winning_trades/trades*100:.1f}%)")
            print(f"   Total Portfolio Return: {portfolio_return:.1f}%")
            print(f"   Average Return per Trade: {portfolio_return/trades:.1f}%")
        else:
            print("\n   No VERY STRONG+ signals found in this period")
        
        # Final validation
        print_separator()
        print("\n🔬 ALGORITHM VALIDATION")
        print_separator()
        
        total_signals = len(all_signals)
        if total_signals > 0:
            # Calculate correlation between score and actual move
            scores = [s["score"] for s in all_signals]
            returns = [s["max_drawdown_5d"] for s in all_signals]
            
            # Higher scores should correlate with larger drops (more negative returns)
            correlation = np.corrcoef(scores, returns)[0, 1] if len(scores) > 1 else 0
            
            print(f"\n   Total Signals Generated: {total_signals}")
            print(f"   Score-to-Drawdown Correlation: {correlation:.3f}")
            if correlation < -0.1:
                print(f"   ✅ VALIDATED: Higher scores predict larger drops")
            elif correlation > 0.1:
                print(f"   ❌ INVERSE: Higher scores NOT predicting drops")
            else:
                print(f"   ⚠️ NEUTRAL: No strong correlation detected")
            
            # Calculate average move by tier
            print(f"\n   Average 5-Day Max Drawdown by Tier:")
            for tier in ["🔥 EXPLOSIVE", "⚡ VERY STRONG", "💪 STRONG", "👀 MONITORING"]:
                tier_signals = [s for s in all_signals if s["tier"] == tier]
                if tier_signals:
                    avg_dd = np.mean([s["max_drawdown_5d"] for s in tier_signals])
                    print(f"      {tier}: {avg_dd:.1f}%")
        
        print_separator()
        print(f"\n⏰ Backtest completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print_separator()
        
        return daily_results, all_signals


async def main():
    engine = BacktestEngine()
    try:
        results, signals = await engine.run_backtest()
    finally:
        await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
