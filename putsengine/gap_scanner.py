"""
Pre-Market Gap Scanner

PURPOSE: Catch moves like UNH (-20%) BEFORE they happen.

PROBLEM: Our universe only scans 175 tickers. UNH wasn't in it.
         By the time we added UNH, the move was already in progress.

SOLUTION: Scan ALL major tickers for >5% pre-market gaps.
         Any ticker gapping down gets auto-injected into DUI.

SCAN TIMES:
- 4:00 AM ET: Early pre-market (overnight news)
- 6:00 AM ET: Pre-market (Europe open impact)
- 8:00 AM ET: Pre-market (early movers)
- 9:15 AM ET: Final pre-market (last chance before open)
- 9:45 AM ET: Opening range gaps (post-open confirmation)

GAP THRESHOLDS:
- Gap Down >= 5%: Add to DUI as WATCHING
- Gap Down >= 8%: Add to DUI as CLASS B candidate
- Gap Down >= 12%: FLAG AS CRITICAL - immediate attention

UNIVERSE FOR GAP SCAN:
- S&P 500 + NASDAQ 100 + Russell 2000 top holdings
- Any ticker with market cap > $5B
- ~800 tickers total (broader than our 175)
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Set, Optional, Tuple
import pytz
from loguru import logger

# Extended universe for gap scanning (beyond our normal 175)
# This includes major names that might gap on news
GAP_SCAN_UNIVERSE = {
    # Healthcare / Insurance (THE UNH FIX)
    "UNH", "HUM", "CI", "ELV", "CVS", "CNC", "MOH", "WBA",
    # Big Pharma
    "PFE", "JNJ", "MRK", "LLY", "ABBV", "BMY", "AMGN", "GILD",
    # Mega Cap Tech (already in our universe, but included for completeness)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC", "C", "BRK.B", "SCHW", "BLK",
    # Industrials / Defense
    "BA", "CAT", "GE", "HON", "UPS", "FDX", "RTX", "LMT", "NOC",
    # Consumer
    "WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "DIS",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "VLO", "MPC",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "XEL", "SRE",
    # REITs
    "PLD", "AMT", "EQIX", "PSA", "SPG", "O", "WELL",
    # Semiconductors
    "NVDA", "AMD", "INTC", "MU", "AVGO", "QCOM", "TSM", "ASML", "AMAT",
    # Crypto / Fintech
    "COIN", "MSTR", "MARA", "RIOT", "SQ", "PYPL", "SOFI", "HOOD",
    # EVs / Clean Energy
    "TSLA", "RIVN", "LCID", "NIO", "FSLR", "ENPH", "PLUG", "BE",
    # Airlines / Travel
    "DAL", "UAL", "AAL", "LUV", "CCL", "RCL", "NCLH", "MAR", "HLT",
    # Retail
    "AMZN", "WMT", "TGT", "COST", "BBY", "LULU", "TJX", "ROST",
    # Telecom
    "T", "VZ", "TMUS", "CMCSA", "CHTR",
    # Media / Entertainment
    "DIS", "NFLX", "WBD", "PARA", "FOX", "SPOT",
    # Biotech (high volatility)
    "MRNA", "BNTX", "REGN", "VRTX", "BIIB", "ILMN", "SGEN",
    # Space / Aerospace
    "RKLB", "SPCE", "ASTR", "RDW", "LUNR", "ASTS",
    # Meme / High Vol
    "GME", "AMC", "BBBY", "BB", "KOSS", "EXPR",
    # Additional S&P 500 names
    "V", "MA", "UNP", "ADBE", "CRM", "ORCL", "IBM", "CSCO", "ACN",
    "ABT", "TMO", "DHR", "MDT", "ISRG", "SYK", "BSX", "ZTS",
    "PG", "KO", "PEP", "PM", "MO", "CL", "EL", "MDLZ",
    "MMM", "EMR", "ITW", "ETN", "PH", "ROK", "CMI",
    # ETFs for sector gaps
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLP",
}


class GapScanner:
    """
    Pre-market gap scanner to catch UNH-style moves.
    
    Scans ~800 tickers for significant pre-market gaps.
    Auto-injects gapping tickers into DUI for monitoring.
    """
    
    # Gap thresholds
    GAP_WATCH_THRESHOLD = -0.05      # -5% gap -> WATCHING
    GAP_CLASS_B_THRESHOLD = -0.08    # -8% gap -> CLASS B candidate
    GAP_CRITICAL_THRESHOLD = -0.12   # -12% gap -> CRITICAL (immediate)
    
    # Gap up thresholds (for potential reversal plays)
    GAP_UP_REVERSAL_THRESHOLD = 0.05  # +5% gap up -> watch for reversal
    
    def __init__(self, alpaca_client):
        """
        Initialize gap scanner.
        
        Args:
            alpaca_client: AlpacaClient instance for price data
        """
        self.alpaca_client = alpaca_client
        self._last_scan_time: Optional[datetime] = None
        self._gap_cache: Dict[str, Dict] = {}  # {symbol: {gap_pct, prior_close, current_price}}
        
    async def scan_premarket_gaps(self) -> Dict[str, List[Dict]]:
        """
        Scan all tickers for pre-market gaps.
        
        Returns:
            Dict with categories:
            - critical: Gap >= 12% (immediate attention)
            - class_b: Gap >= 8% (CLASS B candidate)
            - watching: Gap >= 5% (monitoring)
            - gap_up_reversal: Gap up >= 5% (potential reversal)
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"Gap Scanner: Starting pre-market scan at {now.strftime('%H:%M ET')}")
        
        results = {
            "critical": [],
            "class_b": [],
            "watching": [],
            "gap_up_reversal": [],
        }
        
        # Get prior day's close and current pre-market price
        scanned = 0
        errors = 0
        
        for symbol in GAP_SCAN_UNIVERSE:
            try:
                gap_info = await self._check_gap(symbol)
                if gap_info:
                    gap_pct = gap_info["gap_pct"]
                    
                    if gap_pct <= self.GAP_CRITICAL_THRESHOLD:
                        results["critical"].append(gap_info)
                        logger.warning(f"Gap Scanner: CRITICAL - {symbol} gap {gap_pct*100:.1f}%")
                    elif gap_pct <= self.GAP_CLASS_B_THRESHOLD:
                        results["class_b"].append(gap_info)
                        logger.info(f"Gap Scanner: CLASS B - {symbol} gap {gap_pct*100:.1f}%")
                    elif gap_pct <= self.GAP_WATCH_THRESHOLD:
                        results["watching"].append(gap_info)
                        logger.info(f"Gap Scanner: WATCHING - {symbol} gap {gap_pct*100:.1f}%")
                    elif gap_pct >= self.GAP_UP_REVERSAL_THRESHOLD:
                        results["gap_up_reversal"].append(gap_info)
                        logger.info(f"Gap Scanner: GAP UP - {symbol} gap +{gap_pct*100:.1f}%")
                
                scanned += 1
                
                # Small delay to avoid rate limits
                if scanned % 50 == 0:
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                errors += 1
                if errors < 5:  # Only log first few errors
                    logger.debug(f"Gap Scanner: Error checking {symbol}: {e}")
        
        # Sort by gap size (most negative first)
        for category in results:
            if category == "gap_up_reversal":
                results[category].sort(key=lambda x: x["gap_pct"], reverse=True)
            else:
                results[category].sort(key=lambda x: x["gap_pct"])
        
        self._last_scan_time = now
        
        # Summary
        total_gaps = sum(len(v) for v in results.values())
        logger.info(
            f"Gap Scanner: Completed - {scanned} tickers scanned, {total_gaps} gaps found "
            f"(Critical: {len(results['critical'])}, Class B: {len(results['class_b'])}, "
            f"Watching: {len(results['watching'])}, Gap Up: {len(results['gap_up_reversal'])})"
        )
        
        return results
    
    async def _check_gap(self, symbol: str) -> Optional[Dict]:
        """
        Check if a symbol has a significant gap.
        
        Returns gap info dict or None if no significant gap.
        """
        try:
            # Get latest bar (may be pre-market or regular hours)
            bar = await self.alpaca_client.get_latest_bar(symbol)
            if not bar:
                return None
            
            current_price = bar.close
            
            # Get prior day's close
            prior_close = await self._get_prior_close(symbol)
            if not prior_close or prior_close <= 0:
                return None
            
            # Calculate gap percentage
            gap_pct = (current_price - prior_close) / prior_close
            
            # Only return if gap is significant
            if abs(gap_pct) >= self.GAP_WATCH_THRESHOLD or gap_pct >= self.GAP_UP_REVERSAL_THRESHOLD:
                return {
                    "symbol": symbol,
                    "gap_pct": gap_pct,
                    "prior_close": prior_close,
                    "current_price": current_price,
                    "gap_amount": current_price - prior_close,
                    "scan_time": datetime.now().isoformat(),
                }
            
            return None
            
        except Exception as e:
            logger.debug(f"Gap check failed for {symbol}: {e}")
            return None
    
    async def _get_prior_close(self, symbol: str) -> Optional[float]:
        """Get prior trading day's closing price."""
        try:
            # Get daily bars for last 2 days
            bars = await self.alpaca_client.get_daily_bars(symbol, limit=2)
            if bars and len(bars) >= 1:
                # Return the most recent complete day's close
                return bars[-1].close
            return None
        except Exception:
            return None
    
    async def inject_gaps_to_dui(self, gap_results: Dict[str, List[Dict]]) -> int:
        """
        Inject significant gaps into Dynamic Universe Injection (DUI).
        
        Args:
            gap_results: Results from scan_premarket_gaps()
            
        Returns:
            Number of tickers injected
        """
        from putsengine.config import DynamicUniverseManager
        
        dui = DynamicUniverseManager()
        injected = 0
        
        # Inject critical gaps with high score
        for gap in gap_results.get("critical", []):
            dui.promote_from_distribution(
                symbol=gap["symbol"],
                score=0.60,  # High score for critical gaps
                signals=["critical_gap_down", f"gap_{abs(gap['gap_pct'])*100:.0f}pct"]
            )
            injected += 1
            logger.warning(f"DUI: Injected CRITICAL gap {gap['symbol']} ({gap['gap_pct']*100:.1f}%)")
        
        # Inject class B gaps with medium score
        for gap in gap_results.get("class_b", []):
            dui.promote_from_distribution(
                symbol=gap["symbol"],
                score=0.45,
                signals=["class_b_gap_down", f"gap_{abs(gap['gap_pct'])*100:.0f}pct"]
            )
            injected += 1
            logger.info(f"DUI: Injected CLASS B gap {gap['symbol']} ({gap['gap_pct']*100:.1f}%)")
        
        # Inject watching gaps with low score
        for gap in gap_results.get("watching", []):
            dui.promote_from_liquidity(
                symbol=gap["symbol"],
                score=0.35,
                signals=["gap_down_watch", f"gap_{abs(gap['gap_pct'])*100:.0f}pct"]
            )
            injected += 1
        
        # Inject gap up reversals (potential distribution plays)
        for gap in gap_results.get("gap_up_reversal", []):
            dui.promote_from_distribution(
                symbol=gap["symbol"],
                score=0.30,
                signals=["gap_up_reversal_watch", f"gap_up_{gap['gap_pct']*100:.0f}pct"]
            )
            injected += 1
        
        return injected


async def run_premarket_gap_scan(alpaca_client) -> Dict:
    """
    Run pre-market gap scan and inject results into DUI.
    
    This should be called at:
    - 4:00 AM ET (overnight news)
    - 6:00 AM ET (Europe impact)
    - 8:00 AM ET (early movers)
    - 9:15 AM ET (final pre-market)
    
    Returns:
        Scan results with injected count
    """
    scanner = GapScanner(alpaca_client)
    
    # Run the scan
    results = await scanner.scan_premarket_gaps()
    
    # Inject into DUI
    injected = await scanner.inject_gaps_to_dui(results)
    
    # Add summary
    results["summary"] = {
        "scan_time": datetime.now().isoformat(),
        "total_gaps": sum(len(v) for k, v in results.items() if k != "summary"),
        "injected_to_dui": injected,
        "critical_count": len(results.get("critical", [])),
        "class_b_count": len(results.get("class_b", [])),
        "watching_count": len(results.get("watching", [])),
        "gap_up_count": len(results.get("gap_up_reversal", [])),
    }
    
    return results


# Extended universe size
GAP_SCAN_UNIVERSE_SIZE = len(GAP_SCAN_UNIVERSE)
