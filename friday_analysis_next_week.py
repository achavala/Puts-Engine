#!/usr/bin/env python3
"""
FRIDAY JANUARY 23, 2026 - DETAILED VALIDATION
+ NEXT WEEK BEARISH CANDIDATES IDENTIFICATION

PhD Quant + 30yr Trading + Institutional Microstructure Analysis
Uses REAL market data from Polygon API

This script will:
1. Validate all Friday signals with detailed breakdown
2. Identify candidates likely to continue dropping next week
3. Categorize by engine type (Gamma Drain, Distribution, Liquidity)
4. Save results for dashboard display
"""

import asyncio
import sys
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

sys.path.insert(0, '.')

from putsengine.config import EngineConfig, get_settings
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.models import PriceBar, EngineType
import numpy as np

# Analysis date
FRIDAY_DATE = date(2026, 1, 23)
NEXT_WEEK_START = date(2026, 1, 27)  # Monday

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


class FridayAnalyzer:
    """Detailed analyzer for Friday data and next week projections."""
    
    def __init__(self):
        self.settings = get_settings()
        self.polygon = PolygonClient(self.settings)
        self.alpaca = AlpacaClient(self.settings)
        self.tickers = EngineConfig.get_all_tickers()
        
    async def close(self):
        await self.polygon.close()
        await self.alpaca.close()
    
    async def fetch_bars(self, symbol: str, from_date: date, to_date: date) -> List[PriceBar]:
        """Fetch daily bars."""
        try:
            return await self.polygon.get_daily_bars(symbol, from_date, to_date)
        except:
            return []
    
    def calculate_rvol(self, bars: List[PriceBar], idx: int, lookback: int = 20) -> float:
        """Calculate relative volume."""
        if idx < lookback:
            return 1.0
        avg_vol = np.mean([b.volume for b in bars[idx-lookback:idx]])
        return bars[idx].volume / avg_vol if avg_vol > 0 else 1.0
    
    def calculate_rsi(self, bars: List[PriceBar], period: int = 14) -> float:
        """Calculate RSI."""
        if len(bars) < period + 1:
            return 50.0
        
        prices = [b.close for b in bars]
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def detect_signals(self, bars: List[PriceBar], idx: int) -> Dict:
        """Detect all bearish signals for a given day."""
        signals = {
            "high_rvol_red_day": False,
            "gap_down_no_recovery": False,
            "multi_day_weakness": False,
            "below_prior_low": False,
            "failed_breakout": False,
            "below_20_ema": False,
            "below_50_sma": False,
            "rsi_declining": False,
            "volume_spike": False,
            "lower_highs": False,
        }
        
        if idx < 20:
            return signals
        
        bar = bars[idx]
        prev_bar = bars[idx-1]
        
        # 1. HIGH RVOL on red day
        rvol = self.calculate_rvol(bars, idx)
        is_red = bar.close < bar.open
        daily_change = (bar.close - bar.open) / bar.open
        
        if rvol >= 1.5 and is_red:
            signals["high_rvol_red_day"] = True
        
        # 2. Gap down no recovery
        gap_pct = (bar.open - prev_bar.close) / prev_bar.close
        if gap_pct < -0.01 and bar.close <= bar.open:
            signals["gap_down_no_recovery"] = True
        
        # 3. Multi-day weakness (3+ lower closes)
        count = 0
        for i in range(idx, max(idx-5, 0), -1):
            if bars[i].close < bars[i-1].close:
                count += 1
            else:
                break
        signals["multi_day_weakness"] = count >= 3
        
        # 4. Below prior low
        signals["below_prior_low"] = bar.close < prev_bar.low
        
        # 5. Failed breakout
        highs_20d = [b.high for b in bars[idx-20:idx]]
        resistance = max(highs_20d) if highs_20d else bar.high
        if bar.high >= resistance * 0.995 and bar.close < resistance * 0.98:
            signals["failed_breakout"] = True
        
        # 6. Below 20 EMA
        ema_20 = self._calculate_ema([b.close for b in bars[:idx+1]], 20)
        signals["below_20_ema"] = bar.close < ema_20 if ema_20 else False
        
        # 7. Below 50 SMA
        if idx >= 50:
            sma_50 = np.mean([b.close for b in bars[idx-50:idx]])
            signals["below_50_sma"] = bar.close < sma_50
        
        # 8. RSI declining
        rsi_now = self.calculate_rsi(bars[:idx+1])
        rsi_5d_ago = self.calculate_rsi(bars[:idx-4]) if idx > 5 else 50
        signals["rsi_declining"] = rsi_now < rsi_5d_ago
        
        # 9. Volume spike
        signals["volume_spike"] = rvol >= 2.0
        
        # 10. Lower highs pattern
        if idx >= 10:
            recent_highs = [b.high for b in bars[idx-10:idx+1]]
            local_peaks = []
            for i in range(1, len(recent_highs)-1):
                if recent_highs[i] > recent_highs[i-1] and recent_highs[i] > recent_highs[i+1]:
                    local_peaks.append(recent_highs[i])
            if len(local_peaks) >= 2 and local_peaks[-1] < local_peaks[-2]:
                signals["lower_highs"] = True
        
        # Store additional data
        signals["rvol"] = rvol
        signals["daily_change_pct"] = daily_change * 100
        signals["gap_pct"] = gap_pct * 100
        signals["rsi"] = self.calculate_rsi(bars[:idx+1])
        signals["close"] = bar.close
        signals["open"] = bar.open
        signals["high"] = bar.high
        signals["low"] = bar.low
        signals["volume"] = bar.volume
        
        return signals
    
    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = np.mean(prices[:period])
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema
    
    def determine_engine_type(self, signals: Dict) -> EngineType:
        """
        Determine which of the 3 engines triggered this signal.
        
        Engine 1: GAMMA DRAIN (Flow-Driven)
        - High RVOL + Volume spike + Red day
        - Price below key levels
        
        Engine 2: DISTRIBUTION TRAP (Event-Driven)
        - Gap down no recovery
        - Failed breakout
        - Multi-day weakness
        
        Engine 3: SNAPBACK (Liquidity/Overextension)
        - Below prior low
        - Lower highs
        - RSI declining
        """
        gamma_score = 0
        distribution_score = 0
        liquidity_score = 0
        
        # Gamma Drain signals
        if signals.get("high_rvol_red_day"):
            gamma_score += 3
        if signals.get("volume_spike"):
            gamma_score += 2
        if signals.get("below_20_ema"):
            gamma_score += 1
        
        # Distribution Trap signals
        if signals.get("gap_down_no_recovery"):
            distribution_score += 3
        if signals.get("failed_breakout"):
            distribution_score += 3
        if signals.get("multi_day_weakness"):
            distribution_score += 2
        
        # Liquidity/Snapback signals
        if signals.get("below_prior_low"):
            liquidity_score += 2
        if signals.get("lower_highs"):
            liquidity_score += 2
        if signals.get("rsi_declining"):
            liquidity_score += 1
        if signals.get("below_50_sma"):
            liquidity_score += 1
        
        # Determine primary engine
        if gamma_score >= distribution_score and gamma_score >= liquidity_score:
            return EngineType.GAMMA_DRAIN
        elif distribution_score >= liquidity_score:
            return EngineType.DISTRIBUTION_TRAP
        else:
            return EngineType.SNAPBACK  # Using SNAPBACK for liquidity signals
    
    def calculate_score(self, signals: Dict) -> float:
        """Calculate composite bearish score."""
        score = 0.0
        
        # Primary signals (high weight)
        if signals.get("high_rvol_red_day"):
            score += 0.20
        if signals.get("gap_down_no_recovery"):
            score += 0.15
        if signals.get("multi_day_weakness"):
            score += 0.12
        if signals.get("below_prior_low"):
            score += 0.10
        if signals.get("failed_breakout"):
            score += 0.10
        
        # Secondary signals
        if signals.get("below_20_ema"):
            score += 0.08
        if signals.get("below_50_sma"):
            score += 0.08
        if signals.get("volume_spike"):
            score += 0.07
        if signals.get("rsi_declining"):
            score += 0.05
        if signals.get("lower_highs"):
            score += 0.05
        
        return min(score, 1.0)
    
    def estimate_next_week_potential(self, signals: Dict, score: float) -> Dict:
        """
        Estimate potential move for next week based on signals.
        PhD Quant methodology.
        """
        # Base potential from score
        if score >= 0.75:
            base_potential = (-10, -15)  # EXPLOSIVE
        elif score >= 0.65:
            base_potential = (-5, -10)   # VERY STRONG
        elif score >= 0.55:
            base_potential = (-3, -7)    # STRONG
        else:
            base_potential = (-2, -5)    # MONITORING
        
        # Adjust based on signals
        adjustment = 0
        if signals.get("volume_spike"):
            adjustment -= 1  # More downside
        if signals.get("multi_day_weakness"):
            adjustment -= 1
        if signals.get("lower_highs"):
            adjustment -= 0.5
        
        return {
            "min_expected": base_potential[0] + adjustment,
            "max_expected": base_potential[1] + adjustment,
            "confidence": "HIGH" if score >= 0.65 else "MEDIUM" if score >= 0.55 else "LOW"
        }
    
    async def analyze_friday_and_project(self):
        """Run full Friday analysis and next week projection."""
        print_separator()
        print("  🔬 FRIDAY JANUARY 23, 2026 - DETAILED VALIDATION")
        print("  + NEXT WEEK BEARISH CANDIDATES")
        print_separator()
        
        # Fetch data
        history_start = FRIDAY_DATE - timedelta(days=60)
        history_end = FRIDAY_DATE
        
        print(f"\n🔄 Fetching data for {len(self.tickers)} tickers...")
        
        ticker_data = {}
        fetched = 0
        
        for symbol in self.tickers:
            bars = await self.fetch_bars(symbol, history_start, history_end)
            if bars and len(bars) >= 25:
                ticker_data[symbol] = bars
                fetched += 1
            if fetched % 30 == 0:
                print(f"   Progress: {fetched}/{len(self.tickers)}")
            await asyncio.sleep(0.05)
        
        print(f"\n✅ Data fetched: {fetched} tickers")
        
        # Analyze Friday
        print_separator("-", 80)
        print(f"\n📊 FRIDAY JANUARY 23, 2026 - SIGNAL ANALYSIS")
        print_separator("-", 80)
        
        # Categorize by engine
        gamma_drain_candidates = []
        distribution_candidates = []
        liquidity_candidates = []
        all_candidates = []
        
        for symbol, bars in ticker_data.items():
            # Find Friday's bar
            friday_idx = None
            for i, bar in enumerate(bars):
                if bar.timestamp.date() == FRIDAY_DATE:
                    friday_idx = i
                    break
            
            if friday_idx is None or friday_idx < 25:
                continue
            
            # Detect signals
            signals = self.detect_signals(bars, friday_idx)
            score = self.calculate_score(signals)
            
            if score >= 0.45:  # At least MONITORING
                engine_type = self.determine_engine_type(signals)
                next_week = self.estimate_next_week_potential(signals, score)
                
                candidate = {
                    "symbol": symbol,
                    "score": score,
                    "tier": get_tier(score),
                    "engine_type": engine_type.value,
                    "signals": signals,
                    "close": signals["close"],
                    "daily_change": signals["daily_change_pct"],
                    "rvol": signals["rvol"],
                    "rsi": signals["rsi"],
                    "next_week_min": next_week["min_expected"],
                    "next_week_max": next_week["max_expected"],
                    "confidence": next_week["confidence"],
                }
                
                all_candidates.append(candidate)
                
                if engine_type == EngineType.GAMMA_DRAIN:
                    gamma_drain_candidates.append(candidate)
                elif engine_type == EngineType.DISTRIBUTION_TRAP:
                    distribution_candidates.append(candidate)
                elif engine_type == EngineType.SNAPBACK:
                    liquidity_candidates.append(candidate)
                else:
                    # Default to distribution
                    distribution_candidates.append(candidate)
        
        # Sort by score
        for lst in [all_candidates, gamma_drain_candidates, distribution_candidates, liquidity_candidates]:
            lst.sort(key=lambda x: x["score"], reverse=True)
        
        # Print results by engine
        print(f"\n🔥 ENGINE 1: GAMMA DRAIN (Flow-Driven) - {len(gamma_drain_candidates)} candidates")
        print("-" * 90)
        if gamma_drain_candidates:
            print(f"{'Symbol':<8} {'Tier':<15} {'Score':>6} {'Close':>10} {'Chg%':>8} {'RVOL':>6} {'RSI':>6} {'Next Wk':>12}")
            print("-" * 90)
            for c in gamma_drain_candidates[:10]:
                nw = f"{c['next_week_min']}% to {c['next_week_max']}%"
                print(f"{c['symbol']:<8} {c['tier']:<15} {c['score']:>6.2f} ${c['close']:>9.2f} {c['daily_change']:>7.1f}% {c['rvol']:>5.1f}x {c['rsi']:>5.0f} {nw:>12}")
        
        print(f"\n📉 ENGINE 2: DISTRIBUTION TRAP (Event-Driven) - {len(distribution_candidates)} candidates")
        print("-" * 90)
        if distribution_candidates:
            print(f"{'Symbol':<8} {'Tier':<15} {'Score':>6} {'Close':>10} {'Chg%':>8} {'RVOL':>6} {'RSI':>6} {'Next Wk':>12}")
            print("-" * 90)
            for c in distribution_candidates[:10]:
                nw = f"{c['next_week_min']}% to {c['next_week_max']}%"
                print(f"{c['symbol']:<8} {c['tier']:<15} {c['score']:>6.2f} ${c['close']:>9.2f} {c['daily_change']:>7.1f}% {c['rvol']:>5.1f}x {c['rsi']:>5.0f} {nw:>12}")
        
        print(f"\n💧 ENGINE 3: LIQUIDITY VACUUM - {len(liquidity_candidates)} candidates")
        print("-" * 90)
        if liquidity_candidates:
            print(f"{'Symbol':<8} {'Tier':<15} {'Score':>6} {'Close':>10} {'Chg%':>8} {'RVOL':>6} {'RSI':>6} {'Next Wk':>12}")
            print("-" * 90)
            for c in liquidity_candidates[:10]:
                nw = f"{c['next_week_min']}% to {c['next_week_max']}%"
                print(f"{c['symbol']:<8} {c['tier']:<15} {c['score']:>6.2f} ${c['close']:>9.2f} {c['daily_change']:>7.1f}% {c['rvol']:>5.1f}x {c['rsi']:>5.0f} {nw:>12}")
        
        # Detailed signal breakdown for top candidates
        print_separator()
        print("\n🔬 DETAILED SIGNAL BREAKDOWN - TOP CANDIDATES BY ENGINE")
        print_separator()
        
        for engine_name, candidates in [
            ("GAMMA DRAIN", gamma_drain_candidates),
            ("DISTRIBUTION TRAP", distribution_candidates),
            ("LIQUIDITY VACUUM", liquidity_candidates)
        ]:
            if candidates:
                print(f"\n{engine_name} - Top 3:")
                for c in candidates[:3]:
                    active = [k for k, v in c['signals'].items() if v is True]
                    print(f"   {c['symbol']} ({c['tier']}): {', '.join(active)}")
        
        # Save results for dashboard
        dashboard_data = {
            "generated_at": datetime.now().isoformat(),
            "analysis_date": FRIDAY_DATE.isoformat(),
            "next_week_start": NEXT_WEEK_START.isoformat(),
            "gamma_drain": [
                {
                    "symbol": c["symbol"],
                    "score": round(c["score"], 4),
                    "tier": c["tier"],
                    "close": c["close"],
                    "daily_change": round(c["daily_change"], 2),
                    "rvol": round(c["rvol"], 2),
                    "rsi": round(c["rsi"], 1),
                    "next_week_potential": f"{c['next_week_min']}% to {c['next_week_max']}%",
                    "confidence": c["confidence"],
                    "signals": [k for k, v in c["signals"].items() if v is True]
                }
                for c in gamma_drain_candidates[:15]
            ],
            "distribution": [
                {
                    "symbol": c["symbol"],
                    "score": round(c["score"], 4),
                    "tier": c["tier"],
                    "close": c["close"],
                    "daily_change": round(c["daily_change"], 2),
                    "rvol": round(c["rvol"], 2),
                    "rsi": round(c["rsi"], 1),
                    "next_week_potential": f"{c['next_week_min']}% to {c['next_week_max']}%",
                    "confidence": c["confidence"],
                    "signals": [k for k, v in c["signals"].items() if v is True]
                }
                for c in distribution_candidates[:15]
            ],
            "liquidity": [
                {
                    "symbol": c["symbol"],
                    "score": round(c["score"], 4),
                    "tier": c["tier"],
                    "close": c["close"],
                    "daily_change": round(c["daily_change"], 2),
                    "rvol": round(c["rvol"], 2),
                    "rsi": round(c["rsi"], 1),
                    "next_week_potential": f"{c['next_week_min']}% to {c['next_week_max']}%",
                    "confidence": c["confidence"],
                    "signals": [k for k, v in c["signals"].items() if v is True]
                }
                for c in liquidity_candidates[:15]
            ],
            "summary": {
                "total_candidates": len(all_candidates),
                "gamma_drain_count": len(gamma_drain_candidates),
                "distribution_count": len(distribution_candidates),
                "liquidity_count": len(liquidity_candidates),
                "explosive_count": sum(1 for c in all_candidates if c["score"] >= 0.75),
                "very_strong_count": sum(1 for c in all_candidates if 0.65 <= c["score"] < 0.75),
                "strong_count": sum(1 for c in all_candidates if 0.55 <= c["score"] < 0.65),
                "monitoring_count": sum(1 for c in all_candidates if 0.45 <= c["score"] < 0.55),
            }
        }
        
        # Save to file
        output_path = Path("dashboard_candidates.json")
        with open(output_path, "w") as f:
            json.dump(dashboard_data, f, indent=2)
        
        print_separator()
        print(f"\n💾 Dashboard data saved to: {output_path}")
        
        # Summary
        print_separator()
        print("\n📊 SUMMARY - NEXT WEEK BEARISH CANDIDATES (Jan 27-31, 2026)")
        print_separator()
        
        summary = dashboard_data["summary"]
        print(f"\n   Total Candidates: {summary['total_candidates']}")
        print(f"   🔥 EXPLOSIVE (>=0.75): {summary['explosive_count']}")
        print(f"   ⚡ VERY STRONG (0.65-0.74): {summary['very_strong_count']}")
        print(f"   💪 STRONG (0.55-0.64): {summary['strong_count']}")
        print(f"   👀 MONITORING (0.45-0.54): {summary['monitoring_count']}")
        print(f"\n   By Engine:")
        print(f"   🔥 Gamma Drain: {summary['gamma_drain_count']}")
        print(f"   📉 Distribution Trap: {summary['distribution_count']}")
        print(f"   💧 Liquidity Vacuum: {summary['liquidity_count']}")
        
        print_separator()
        print(f"\n⏰ Analysis completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print_separator()
        
        return dashboard_data


async def main():
    analyzer = FridayAnalyzer()
    try:
        data = await analyzer.analyze_friday_and_project()
        return data
    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
