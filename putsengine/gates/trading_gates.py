"""
TRADING GATES - Architect-4 Final Implementation
================================================

Three institutional-grade additions:
1. Opening Range Confirmation (No trades before 09:45 ET)
2. VWAP Reclaim Exit Rule (Exit if VWAP reclaimed for 15 min)
3. Sentiment Keyword Detection (Capped boost only)

PhD Quant + 30yr Trading + Institutional Microstructure
"""

from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
import pytz

# Sentiment keywords that matter for PUTS (institutional-grade)
BEARISH_KEYWORDS = [
    "guidance cut",
    "guidance lowered",
    "macro headwinds",
    "inventory build",
    "demand slowdown",
    "pricing pressure",
    "margin compression",
    "revenue miss",
    "earnings miss",
    "outlook reduced",
    "downgrade",
    "disappointing",
    "weaker than expected",
    "supply chain issues",
    "cost inflation",
    "workforce reduction",
    "layoffs",
]


class TradingGates:
    """
    Institutional trading gates that override all other signals.
    These are HARD BLOCKS, not score adjustments.
    """
    
    def __init__(self):
        self.et_tz = pytz.timezone('US/Eastern')
        # Track VWAP reclaim status per symbol
        self.vwap_reclaim_tracker: Dict[str, datetime] = {}
    
    # =========================================================================
    # GATE 1: OPENING RANGE CONFIRMATION (MANDATORY)
    # =========================================================================
    
    def is_after_opening_range(self) -> Tuple[bool, str]:
        """
        Check if we're past the opening range (09:45 ET).
        
        Rule: NEVER enter a PUT before 09:45 AM ET
        
        Why (microstructure):
        - First 15 minutes = liquidity discovery
        - Dealers hedging overnight inventory
        - False breakdowns common
        
        Returns:
            (can_trade, reason)
        """
        now_et = datetime.now(self.et_tz)
        market_open = time(9, 30)
        opening_range_end = time(9, 45)
        market_close = time(16, 0)
        
        current_time = now_et.time()
        
        # Market not open yet
        if current_time < market_open:
            return False, "PRE-MARKET: Market not open yet"
        
        # Within opening range - NO TRADES
        if market_open <= current_time < opening_range_end:
            minutes_remaining = (
                datetime.combine(now_et.date(), opening_range_end) -
                datetime.combine(now_et.date(), current_time)
            ).seconds // 60
            return False, f"OPENING RANGE: Wait {minutes_remaining} more minutes (until 09:45 ET)"
        
        # After market close
        if current_time >= market_close:
            return False, "MARKET CLOSED: No trades after 4:00 PM ET"
        
        # Clear to trade
        return True, "CLEAR: Past opening range"
    
    # =========================================================================
    # GATE 2: VWAP RECLAIM EXIT RULE (CRITICAL)
    # =========================================================================
    
    def check_vwap_reclaim_exit(
        self,
        symbol: str,
        current_price: float,
        vwap: float,
        timestamp: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Check if VWAP has been reclaimed for 15 consecutive minutes.
        
        Rule: If price RECLAIMS VWAP and HOLDS for 15 min → EXIT
        
        Why (institutional):
        - Liquidity vacuum has filled
        - Dealers are buying again
        - Downside asymmetry is gone
        
        This exit OVERRIDES PnL, conviction, or narrative.
        
        Returns:
            (should_exit, reason)
        """
        if timestamp is None:
            timestamp = datetime.now(self.et_tz)
        
        price_above_vwap = current_price > vwap
        
        if price_above_vwap:
            # Price is above VWAP
            if symbol not in self.vwap_reclaim_tracker:
                # First time seeing price above VWAP
                self.vwap_reclaim_tracker[symbol] = timestamp
                return False, f"VWAP RECLAIMED: Monitoring (just started)"
            
            # Calculate how long price has been above VWAP
            reclaim_start = self.vwap_reclaim_tracker[symbol]
            minutes_above = (timestamp - reclaim_start).total_seconds() / 60
            
            if minutes_above >= 15:
                # HARD EXIT
                return True, f"⚠️ EXIT SIGNAL: VWAP reclaimed for {minutes_above:.0f} minutes"
            else:
                return False, f"VWAP RECLAIMED: {minutes_above:.0f}/15 min (watching)"
        else:
            # Price is below VWAP - reset tracker
            if symbol in self.vwap_reclaim_tracker:
                del self.vwap_reclaim_tracker[symbol]
            return False, "VWAP NOT RECLAIMED: Position safe"
    
    def reset_vwap_tracker(self, symbol: str):
        """Reset VWAP tracker for a symbol (e.g., after exit)."""
        if symbol in self.vwap_reclaim_tracker:
            del self.vwap_reclaim_tracker[symbol]
    
    # =========================================================================
    # GATE 3: SENTIMENT KEYWORD DETECTION (CAPPED BOOST)
    # =========================================================================
    
    def analyze_sentiment_keywords(
        self,
        headlines: List[str],
        has_distribution_signal: bool = False
    ) -> Tuple[float, List[str]]:
        """
        Analyze headlines for bearish sentiment keywords.
        
        Rules:
        - Keyword-based ONLY (no NLP, no ML)
        - Capped boost: +0.05 to +0.10 max
        - NEVER triggers trades alone
        - NEVER overrides Gamma/Liquidity
        
        Args:
            headlines: List of news headlines
            has_distribution_signal: Whether distribution is already present
        
        Returns:
            (sentiment_boost, matched_keywords)
        """
        if not headlines:
            return 0.0, []
        
        matched_keywords = []
        
        # Convert all headlines to lowercase for matching
        headlines_lower = [h.lower() for h in headlines]
        
        for keyword in BEARISH_KEYWORDS:
            for headline in headlines_lower:
                if keyword.lower() in headline:
                    if keyword not in matched_keywords:
                        matched_keywords.append(keyword)
        
        # Calculate boost (capped)
        if not matched_keywords:
            return 0.0, []
        
        # Base boost per keyword (capped at 0.10 total)
        boost_per_keyword = 0.025
        raw_boost = len(matched_keywords) * boost_per_keyword
        
        # Only apply boost if distribution signal is present
        if has_distribution_signal:
            capped_boost = min(raw_boost, 0.10)
        else:
            # Without distribution, sentiment is just informational
            capped_boost = 0.0
        
        return capped_boost, matched_keywords
    
    # =========================================================================
    # COMBINED GATE CHECK
    # =========================================================================
    
    def check_all_gates(self) -> Dict[str, Tuple[bool, str]]:
        """
        Check all trading gates and return status.
        
        Returns dict with gate name -> (passed, reason)
        """
        results = {}
        
        # Gate 1: Opening Range
        passed, reason = self.is_after_opening_range()
        results["opening_range"] = (passed, reason)
        
        return results
    
    def can_trade(self) -> Tuple[bool, List[str]]:
        """
        Check if all gates pass and we can trade.
        
        Returns:
            (can_trade, list_of_blocking_reasons)
        """
        gates = self.check_all_gates()
        
        blocking_reasons = []
        for gate_name, (passed, reason) in gates.items():
            if not passed:
                blocking_reasons.append(reason)
        
        return len(blocking_reasons) == 0, blocking_reasons


# ============================================================================
# MONDAY MORNING / DAILY HARD-GATE REPORT
# ============================================================================

class DailyHardGateReport:
    """
    Generates the institutional daily hard-gate report.
    
    No scores. No trades. Just:
    - Market regime
    - GEX state
    - Passive inflow block
    - Earnings blocks
    - HTB flags
    """
    
    def __init__(self, settings):
        self.settings = settings
        self.et_tz = pytz.timezone('US/Eastern')
    
    async def generate_report(
        self,
        market_regime,
        gex_data=None,
        htb_symbols: List[str] = None
    ) -> Dict:
        """Generate the daily hard-gate report."""
        
        now_et = datetime.now(self.et_tz)
        
        # Check passive inflow windows
        day_of_month = now_et.day
        is_passive_inflow_window = day_of_month <= 3 or day_of_month >= 28
        
        # Check if Monday (potential rebalancing)
        is_monday = now_et.weekday() == 0
        
        # Build report
        report = {
            "timestamp": now_et.isoformat(),
            "date": now_et.strftime("%A, %B %d, %Y"),
            "time_et": now_et.strftime("%I:%M %p ET"),
            
            # Market Regime
            "market_regime": {
                "regime": market_regime.regime.value if market_regime else "unknown",
                "is_tradeable": market_regime.is_tradeable if market_regime else False,
                "spy_below_vwap": market_regime.spy_below_vwap if market_regime else False,
                "qqq_below_vwap": market_regime.qqq_below_vwap if market_regime else False,
                "vix_level": market_regime.vix_level if market_regime else 0,
                "vix_trend": "rising" if market_regime and market_regime.vix_change > 0 else "falling",
                "block_reasons": market_regime.block_reasons if market_regime else [],
            },
            
            # GEX State
            "gex_state": {
                "net_gex": gex_data.net_gex if gex_data else 0,
                "gex_signal": "NEGATIVE (Bearish)" if gex_data and gex_data.net_gex < 0 else "POSITIVE (Blocked)",
                "can_trade_puts": gex_data.net_gex <= 0 if gex_data else False,
            },
            
            # Passive Inflow Block
            "passive_inflow": {
                "is_blocked": is_passive_inflow_window,
                "day_of_month": day_of_month,
                "reason": f"Day {day_of_month} is passive inflow window (1-3 or 28-31)" if is_passive_inflow_window else "Clear",
            },
            
            # Monday Rebalancing Warning
            "monday_rebalance": {
                "is_monday": is_monday,
                "warning": "Monday often has institutional rebalancing - proceed with caution" if is_monday else None,
            },
            
            # HTB Flags
            "htb_flags": {
                "count": len(htb_symbols) if htb_symbols else 0,
                "symbols": htb_symbols[:10] if htb_symbols else [],
                "warning": f"{len(htb_symbols)} symbols are Hard-to-Borrow (squeeze risk)" if htb_symbols and len(htb_symbols) > 0 else None,
            },
            
            # Final Verdict
            "final_verdict": None,
            "hard_blocks": [],
        }
        
        # Calculate final verdict
        hard_blocks = []
        
        if not report["market_regime"]["is_tradeable"]:
            hard_blocks.append("Market Regime: NOT TRADEABLE")
        
        if report["gex_state"]["net_gex"] > 0:
            hard_blocks.append("GEX: POSITIVE (Blocked)")
        
        if report["passive_inflow"]["is_blocked"]:
            hard_blocks.append(f"Passive Inflow Window: Day {day_of_month}")
        
        report["hard_blocks"] = hard_blocks
        
        if hard_blocks:
            report["final_verdict"] = "🔴 BLOCKED - NO TRADES TODAY"
        else:
            report["final_verdict"] = "🟢 CLEAR - CAN EVALUATE PUTS"
        
        return report
    
    def format_report_text(self, report: Dict) -> str:
        """Format report as readable text."""
        lines = [
            "=" * 70,
            "🏛️ DAILY HARD-GATE REPORT",
            f"   {report['date']} | {report['time_et']}",
            "=" * 70,
            "",
            "📊 MARKET REGIME",
            f"   Regime: {report['market_regime']['regime']}",
            f"   Tradeable: {'✅ YES' if report['market_regime']['is_tradeable'] else '❌ NO'}",
            f"   SPY < VWAP: {'✅' if report['market_regime']['spy_below_vwap'] else '❌'}",
            f"   QQQ < VWAP: {'✅' if report['market_regime']['qqq_below_vwap'] else '❌'}",
            f"   VIX: {report['market_regime']['vix_level']:.1f} ({report['market_regime']['vix_trend']})",
            "",
            "📈 GEX STATE",
            f"   Net GEX: {report['gex_state']['net_gex']}",
            f"   Signal: {report['gex_state']['gex_signal']}",
            f"   Can Trade Puts: {'✅ YES' if report['gex_state']['can_trade_puts'] else '❌ NO'}",
            "",
            "💰 PASSIVE INFLOW",
            f"   Day of Month: {report['passive_inflow']['day_of_month']}",
            f"   Blocked: {'⚠️ YES' if report['passive_inflow']['is_blocked'] else '✅ NO'}",
        ]
        
        if report['monday_rebalance']['is_monday']:
            lines.extend([
                "",
                "📅 MONDAY WARNING",
                f"   {report['monday_rebalance']['warning']}",
            ])
        
        if report['htb_flags']['count'] > 0:
            lines.extend([
                "",
                "⚠️ HTB FLAGS",
                f"   {report['htb_flags']['warning']}",
                f"   Symbols: {', '.join(report['htb_flags']['symbols'])}",
            ])
        
        lines.extend([
            "",
            "=" * 70,
            f"🎯 FINAL VERDICT: {report['final_verdict']}",
        ])
        
        if report['hard_blocks']:
            lines.append("")
            lines.append("🚫 HARD BLOCKS:")
            for block in report['hard_blocks']:
                lines.append(f"   • {block}")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
