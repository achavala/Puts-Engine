#!/usr/bin/env python3
"""
PATTERN INTEGRATION SCRIPT

Purpose: Integrate pattern scan results into the existing scheduled scan results.
This boosts scores for candidates that match pump-reversal or exhaustion patterns.

Runs AFTER the regular scan to enhance results with pattern detection.

STRIKE/EXPIRY CALCULATION (Institutional-Grade):
- Uses price tiers for optimal OTM distance
- Calculates ATR-based expected moves
- Selects nearest Friday with appropriate DTE
- Delta targeting: -0.20 to -0.40 based on price tier
"""
import asyncio
import json
from datetime import datetime, timedelta, date
from pathlib import Path
import pytz
import math

from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.config import EngineConfig, get_settings

ET = pytz.timezone('US/Eastern')
SCHEDULED_RESULTS_FILE = Path("scheduled_scan_results.json")
PATTERN_RESULTS_FILE = Path("pattern_scan_results.json")


# ============================================================================
# INSTITUTIONAL STRIKE PRICE CALCULATION
# ============================================================================

# Price tier definitions for strike selection
PRICE_TIERS = {
    "gamma_sweet": {"range": (0, 30), "pct_otm": (0.10, 0.16), "delta": (-0.30, -0.20), "mult": "4x-8x"},
    "low_mid":     {"range": (30, 100), "pct_otm": (0.07, 0.12), "delta": (-0.32, -0.22), "mult": "3x-6x"},
    "mid":         {"range": (100, 300), "pct_otm": (0.04, 0.08), "delta": (-0.35, -0.25), "mult": "2.5x-5x"},
    "high":        {"range": (300, 500), "dollar_otm": (15, 35), "delta": (-0.40, -0.25), "mult": "2x-4x"},
    "premium":     {"range": (500, 800), "dollar_otm": (20, 50), "delta": (-0.35, -0.22), "mult": "2x-3x"},
    "ultra":       {"range": (800, 1200), "dollar_otm": (30, 70), "delta": (-0.30, -0.20), "mult": "1.5x-3x"},
    "mega":        {"range": (1200, 99999), "dollar_otm": (40, 90), "delta": (-0.25, -0.15), "mult": "1.5x-2.5x"},
}

# ATR multipliers by tier (institutional approach)
ATR_MULTIPLIERS = {
    "gamma_sweet": 1.8,
    "low_mid": 1.5,
    "mid": 1.3,
    "high": 1.2,
    "premium": 1.1,
    "ultra": 1.0,
    "mega": 0.9,
}


def get_price_tier(price: float) -> str:
    """Get price tier for strike calculation."""
    for tier, config in PRICE_TIERS.items():
        low, high = config["range"]
        if low <= price < high:
            return tier
    return "mega"


def calculate_optimal_strike(price: float, atr: float = None, gain_pct: float = 0) -> dict:
    """
    Calculate optimal PUT strike price using institutional methodology.
    
    Args:
        price: Current stock price
        atr: 14-day Average True Range (optional)
        gain_pct: Recent % gain (for aggressive strikes on pumped stocks)
    
    Returns:
        dict with strike, reasoning, delta_target, potential_multiple
    """
    tier = get_price_tier(price)
    config = PRICE_TIERS[tier]
    
    # Calculate strike range
    if "pct_otm" in config:
        # Percentage-based for cheaper stocks
        pct_min, pct_max = config["pct_otm"]
        
        # More aggressive strike if stock has pumped
        if gain_pct > 10:
            pct_min *= 0.7  # Closer to ATM
            pct_max *= 0.8
        elif gain_pct > 5:
            pct_min *= 0.85
            pct_max *= 0.9
        
        strike_low = price * (1 - pct_max)
        strike_high = price * (1 - pct_min)
        strike_mid = (strike_low + strike_high) / 2
        
        # Round to standard strikes
        if price < 50:
            strike = round(strike_mid * 2) / 2  # $0.50 increments
        else:
            strike = round(strike_mid)  # $1.00 increments
        
        otm_pct = (price - strike) / price * 100
        reasoning = f"{otm_pct:.1f}% OTM ({tier} tier)"
        
    else:
        # Dollar-based for expensive stocks
        dollar_min, dollar_max = config["dollar_otm"]
        
        # More aggressive if pumped
        if gain_pct > 10:
            dollar_min *= 0.6
            dollar_max *= 0.7
        elif gain_pct > 5:
            dollar_min *= 0.8
            dollar_max *= 0.85
        
        # Use ATR if available for institutional approach
        if atr and atr > 0:
            k = ATR_MULTIPLIERS.get(tier, 1.2)
            expected_move = k * atr
            strike = round(price - expected_move)
            reasoning = f"${expected_move:.0f} OTM ({k}x ATR)"
        else:
            dollar_mid = (dollar_min + dollar_max) / 2
            strike = round(price - dollar_mid)
            reasoning = f"${dollar_mid:.0f} OTM ({tier} tier)"
    
    # Ensure strike is below current price
    strike = min(strike, price * 0.98)
    
    # Round to standard strike increments
    if strike < 50:
        strike = math.floor(strike * 2) / 2  # $0.50
    elif strike < 200:
        strike = math.floor(strike)  # $1.00
    else:
        strike = math.floor(strike / 5) * 5  # $5.00
    
    delta_min, delta_max = config["delta"]
    
    return {
        "strike": strike,
        "otm_pct": round((price - strike) / price * 100, 1),
        "reasoning": reasoning,
        "delta_target": f"{delta_min:.2f} to {delta_max:.2f}",
        "potential_mult": config["mult"],
        "tier": tier
    }


def calculate_optimal_expiry(score: float, price: float, gain_pct: float = 0) -> dict:
    """
    Calculate optimal expiry date using institutional DTE rules.
    
    Args:
        score: Candidate score (0-1)
        price: Current stock price
        gain_pct: Recent % gain
    
    Returns:
        dict with expiry date, DTE, and reasoning
    """
    today = date.today()
    
    # Find next Fridays
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    
    friday_1 = today + timedelta(days=days_until_friday)
    friday_2 = friday_1 + timedelta(days=7)
    friday_3 = friday_2 + timedelta(days=7)
    
    dte_1 = (friday_1 - today).days
    dte_2 = (friday_2 - today).days
    dte_3 = (friday_3 - today).days
    
    # DTE selection based on score and conviction
    if score >= 0.70:
        # High conviction: nearest Friday (7-12 DTE)
        if dte_1 >= 7:
            expiry = friday_1
            dte = dte_1
            reasoning = "High conviction (≥0.70): Nearest Friday for max gamma"
        else:
            expiry = friday_2
            dte = dte_2
            reasoning = "High conviction (≥0.70): Next Friday (min 7 DTE)"
    elif score >= 0.50:
        # Medium conviction: 2nd Friday (12-18 DTE)
        if dte_1 >= 10:
            expiry = friday_1
            dte = dte_1
            reasoning = "Medium conviction: This Friday (enough time)"
        else:
            expiry = friday_2
            dte = dte_2
            reasoning = "Medium conviction: 2nd Friday for theta buffer"
    else:
        # Lower conviction: 3rd Friday (18-25 DTE)
        expiry = friday_3
        dte = dte_3
        reasoning = "Watch-tier: 3rd Friday for max time value"
    
    # Aggressive adjustment for pumped stocks
    if gain_pct > 15:
        # Very pumped = could crash fast, use nearer expiry
        if dte > 14:
            expiry = friday_2 if dte_2 >= 7 else friday_1
            dte = (expiry - today).days
            reasoning += " | Adjusted closer for 15%+ pump"
    
    return {
        "expiry": expiry.strftime("%Y-%m-%d"),
        "expiry_display": expiry.strftime("%b %d"),
        "dte": dte,
        "reasoning": reasoning
    }


def calculate_contract_recommendation(
    symbol: str,
    price: float,
    score: float,
    gain_pct: float = 0,
    atr: float = None
) -> dict:
    """
    Generate full contract recommendation for a PUT candidate.
    
    Returns institutional-grade strike + expiry with reasoning.
    """
    strike_info = calculate_optimal_strike(price, atr, gain_pct)
    expiry_info = calculate_optimal_expiry(score, price, gain_pct)
    
    strike = strike_info["strike"]
    expiry = expiry_info["expiry"]
    
    # Generate contract symbol (OCC format approximation)
    exp_fmt = datetime.strptime(expiry, "%Y-%m-%d").strftime("%y%m%d")
    strike_fmt = f"{int(strike * 1000):08d}"
    contract = f"{symbol}{exp_fmt}P{strike_fmt}"
    
    return {
        "contract_symbol": contract,
        "strike": strike,
        "strike_display": f"${strike:.0f}P" if strike >= 10 else f"${strike:.1f}P",
        "expiry": expiry,
        "expiry_display": expiry_info["expiry_display"],
        "dte": expiry_info["dte"],
        "otm_pct": strike_info["otm_pct"],
        "delta_target": strike_info["delta_target"],
        "potential_mult": strike_info["potential_mult"],
        "reasoning": f"{strike_info['reasoning']} | {expiry_info['reasoning']}",
        "tier": strike_info["tier"]
    }


async def scan_patterns():
    """Scan for pump-reversal and exhaustion patterns."""
    now = datetime.now(ET)
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    all_tickers = EngineConfig.get_all_tickers()
    
    print("="*70)
    print(f"PATTERN SCANNER - {now.strftime('%Y-%m-%d %H:%M:%S')} EST")
    print("="*70)
    
    # Priority sectors from Jan 26-29 analysis
    priority_sectors = {
        "crypto": ["MSTR", "COIN", "RIOT", "MARA", "HUT", "CLSK", "CIFR", "WULF"],
        "uranium": ["UUUU", "LEU", "OKLO", "SMR", "CCJ", "NNE", "UEC"],
        "evtol": ["JOBY", "RKLB", "LUNR", "ASTS", "RDW", "RCAT", "PL", "ACHR"],
        "quantum": ["RGTI", "QUBT", "IONQ", "QBTS"],
        "cloud": ["NET", "CRWD", "ZS", "OKTA", "DDOG", "TEAM", "WDAY", "SNOW", "NOW"],
        "solar": ["FSLR", "ENPH", "BE", "PLUG", "FCEL", "EOSE"],
        "rare_earth": ["MP", "USAR", "LAC", "ALB"],
        "semis": ["CLS", "SWKS", "INTC", "AMD", "NVDA", "MU"],
        "mega": ["MSFT", "AAPL", "GOOGL", "META", "AMZN", "TSLA"],
    }
    
    # Flatten priority list
    priority_tickers = set()
    for tickers in priority_sectors.values():
        priority_tickers.update(tickers)
    
    scan_order = list(priority_tickers) + [t for t in all_tickers if t not in priority_tickers]
    
    results = {
        "pump_reversal": [],
        "two_day_rally": [],
        "high_vol_run": [],
        "scan_time": now.isoformat()
    }
    
    scanned = 0
    for symbol in scan_order[:150]:
        try:
            start_date = datetime.now() - timedelta(days=15)
            bars = await alpaca.get_bars(symbol, timeframe="1Day", start=start_date, limit=10)
            if not bars or len(bars) < 5:
                continue
            
            scanned += 1
            
            # Calculate returns
            returns = []
            for i in range(1, min(5, len(bars))):
                pct = ((bars[-i].close - bars[-(i+1)].close) / bars[-(i+1)].close) * 100
                returns.append(pct)
            
            if not returns:
                continue
            
            current_price = bars[-1].close
            day1 = returns[0] if len(returns) > 0 else 0
            day2 = returns[1] if len(returns) > 1 else 0
            day3 = returns[2] if len(returns) > 2 else 0
            
            # Volume ratio
            if len(bars) >= 6:
                avg_vol = sum(b.volume for b in bars[-6:-1]) / 5
                curr_vol = bars[-1].volume
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
            else:
                vol_ratio = 1.0
            
            # Get sector
            sector = "other"
            for sec, tickers in priority_sectors.items():
                if symbol in tickers:
                    sector = sec
                    break
            
            # PATTERN 1: Pump Reversal Watch
            total_gain = day1 + day2 + day3
            max_gain = max(day1, day2, day3) if returns else 0
            
            if max_gain >= 3.0 or total_gain >= 5.0:
                reversal_signals = []
                curr_bar = bars[-1]
                prev_bar = bars[-2] if len(bars) >= 2 else None
                
                if curr_bar.close < curr_bar.high * 0.97:
                    reversal_signals.append("exhaustion")
                
                body = abs(curr_bar.close - curr_bar.open)
                upper_wick = curr_bar.high - max(curr_bar.close, curr_bar.open)
                if body > 0 and upper_wick > body * 1.5:
                    reversal_signals.append("topping_tail")
                
                if curr_bar.close < curr_bar.open and vol_ratio > 1.3:
                    reversal_signals.append("high_vol_red")
                
                if prev_bar and curr_bar.close < prev_bar.low:
                    reversal_signals.append("below_prior_low")
                
                # Calculate ATR for institutional strike selection
                atr = None
                if len(bars) >= 5:
                    tr_list = []
                    for i in range(1, min(6, len(bars))):
                        b = bars[-i]
                        prev_b = bars[-(i+1)] if i+1 <= len(bars) else b
                        tr = max(b.high - b.low, abs(b.high - prev_b.close), abs(b.low - prev_b.close))
                        tr_list.append(tr)
                    atr = sum(tr_list) / len(tr_list) if tr_list else None
                
                # Calculate score for DTE selection
                score_boost = min(0.20, 0.05 + len(reversal_signals) * 0.04 + max_gain * 0.01)
                base_score = 0.45 + score_boost
                
                # Get institutional contract recommendation
                contract_rec = calculate_contract_recommendation(
                    symbol=symbol,
                    price=current_price,
                    score=base_score,
                    gain_pct=total_gain,
                    atr=atr
                )
                
                results["pump_reversal"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "price": round(current_price, 2),
                    "gain_1d": round(day1, 1),
                    "gain_2d": round(day2, 1),
                    "gain_3d": round(day3, 1),
                    "total_gain": round(total_gain, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "signals": reversal_signals,
                    "score_boost": score_boost,
                    # Contract recommendation
                    "strike": contract_rec["strike"],
                    "strike_display": contract_rec["strike_display"],
                    "expiry": contract_rec["expiry"],
                    "expiry_display": contract_rec["expiry_display"],
                    "dte": contract_rec["dte"],
                    "otm_pct": contract_rec["otm_pct"],
                    "delta_target": contract_rec["delta_target"],
                    "potential_mult": contract_rec["potential_mult"],
                    "contract_symbol": contract_rec["contract_symbol"],
                    "atr": round(atr, 2) if atr else None
                })
            
            # PATTERN 2: Two-Day Rally
            if day1 > 1.0 and day2 > 1.0:
                total = day1 + day2
                score_boost_2 = min(0.15, 0.05 + total * 0.02)
                base_score_2 = 0.40 + score_boost_2
                
                # Contract recommendation for two-day rally
                contract_rec_2 = calculate_contract_recommendation(
                    symbol=symbol,
                    price=current_price,
                    score=base_score_2,
                    gain_pct=total,
                    atr=atr if 'atr' in dir() else None
                )
                
                results["two_day_rally"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "price": round(current_price, 2),
                    "day1": round(day1, 1),
                    "day2": round(day2, 1),
                    "total": round(total, 1),
                    "score_boost": score_boost_2,
                    # Contract recommendation
                    "strike": contract_rec_2["strike"],
                    "strike_display": contract_rec_2["strike_display"],
                    "expiry": contract_rec_2["expiry"],
                    "expiry_display": contract_rec_2["expiry_display"],
                    "dte": contract_rec_2["dte"],
                    "otm_pct": contract_rec_2["otm_pct"],
                    "delta_target": contract_rec_2["delta_target"],
                    "potential_mult": contract_rec_2["potential_mult"]
                })
            
            # PATTERN 3: High Volume Run
            if max_gain >= 5.0 and vol_ratio >= 1.5:
                score_boost_3 = min(0.15, 0.05 + vol_ratio * 0.03)
                base_score_3 = 0.42 + score_boost_3
                
                # Contract recommendation for high volume run
                contract_rec_3 = calculate_contract_recommendation(
                    symbol=symbol,
                    price=current_price,
                    score=base_score_3,
                    gain_pct=max_gain,
                    atr=atr if 'atr' in dir() else None
                )
                
                results["high_vol_run"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "price": round(current_price, 2),
                    "gain": round(max_gain, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "score_boost": score_boost_3,
                    # Contract recommendation
                    "strike": contract_rec_3["strike"],
                    "strike_display": contract_rec_3["strike_display"],
                    "expiry": contract_rec_3["expiry"],
                    "expiry_display": contract_rec_3["expiry_display"],
                    "dte": contract_rec_3["dte"],
                    "otm_pct": contract_rec_3["otm_pct"],
                    "delta_target": contract_rec_3["delta_target"],
                    "potential_mult": contract_rec_3["potential_mult"]
                })
                
        except Exception as e:
            continue
    
    print(f"Scanned {scanned} tickers")
    
    # Sort by score boost
    for key in results:
        if isinstance(results[key], list):
            results[key].sort(key=lambda x: x.get("score_boost", 0), reverse=True)
    
    return results


def _populate_from_patterns(pattern_results):
    """Create scheduled results from pattern data when engines are empty."""
    gamma_candidates = []
    distribution_candidates = []
    liquidity_candidates = []
    
    # Pump reversal -> Distribution or Gamma based on signals
    for pr in pattern_results.get("pump_reversal", []):
        candidate = {
            "symbol": pr["symbol"],
            "score": round(0.45 + pr.get("score_boost", 0.1), 4),
            "tier": "🟡 CLASS B" if pr.get("score_boost", 0) >= 0.15 else "⚪ WATCH",
            "engine_type": "gamma_drain" if "exhaustion" in pr.get("signals", []) else "distribution_trap",
            "current_price": pr.get("price", 0),
            "close": pr.get("price", 0),
            "signals": pr.get("signals", []) + [f"pump_{pr.get('total_gain', 0):+.0f}%"],
            "pattern_enhanced": True,
            "pattern_boost": pr.get("score_boost", 0.1),
            "pattern_source": "pump_reversal",
            "sector": pr.get("sector", "other"),
            "total_gain": pr.get("total_gain", 0),
            "gain_1d": pr.get("gain_1d", 0),
            "gain_2d": pr.get("gain_2d", 0),
            "gain_3d": pr.get("gain_3d", 0),
            "vol_ratio": pr.get("vol_ratio", 1.0)
        }
        
        if "exhaustion" in pr.get("signals", []) or "high_vol_red" in pr.get("signals", []):
            gamma_candidates.append(candidate)
        else:
            distribution_candidates.append(candidate)
    
    # Two day rally -> Liquidity
    for pr in pattern_results.get("two_day_rally", []):
        candidate = {
            "symbol": pr["symbol"],
            "score": round(0.40 + pr.get("score_boost", 0.1), 4),
            "tier": "⚪ WATCH",
            "engine_type": "liquidity_vacuum",
            "current_price": pr.get("price", 0),
            "close": pr.get("price", 0),
            "signals": ["two_day_rally", "exhaustion_setup"],
            "pattern_enhanced": True,
            "pattern_boost": pr.get("score_boost", 0.1),
            "pattern_source": "two_day_rally",
            "sector": pr.get("sector", "other"),
            "day1": pr.get("day1", 0),
            "day2": pr.get("day2", 0),
            "total": pr.get("total", 0)
        }
        liquidity_candidates.append(candidate)
    
    # High vol run -> Gamma Drain
    for pr in pattern_results.get("high_vol_run", []):
        candidate = {
            "symbol": pr["symbol"],
            "score": round(0.42 + pr.get("score_boost", 0.1), 4),
            "tier": "⚪ WATCH",
            "engine_type": "gamma_drain",
            "current_price": pr.get("price", 0),
            "close": pr.get("price", 0),
            "signals": ["high_vol_run", f"vol_{pr.get('vol_ratio', 1):.1f}x"],
            "pattern_enhanced": True,
            "pattern_boost": pr.get("score_boost", 0.1),
            "pattern_source": "high_vol_run",
            "sector": pr.get("sector", "other"),
            "gain": pr.get("gain", 0),
            "vol_ratio": pr.get("vol_ratio", 1.0)
        }
        gamma_candidates.append(candidate)
    
    # Sort and limit
    gamma_candidates.sort(key=lambda x: x["score"], reverse=True)
    distribution_candidates.sort(key=lambda x: x["score"], reverse=True)
    liquidity_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "gamma_drain": gamma_candidates[:20],
        "distribution": distribution_candidates[:20],
        "liquidity": liquidity_candidates[:15],
        "last_scan": datetime.now(ET).isoformat(),
        "scan_type": "pattern_populated",
        "market_regime": {"is_tradeable": True, "regime": "pattern_based"},
        "tickers_scanned": len(pattern_results.get("pump_reversal", [])) + 
                          len(pattern_results.get("two_day_rally", [])) +
                          len(pattern_results.get("high_vol_run", [])),
        "errors": [],
        "total_candidates": len(gamma_candidates) + len(distribution_candidates) + len(liquidity_candidates)
    }


def _update_scan_history(scheduled):
    """Update scan history for 48-hour analysis."""
    history_file = Path("scan_history.json")
    
    if history_file.exists():
        with open(history_file) as f:
            history = json.load(f)
    else:
        history = {"scans": []}
    
    # Create history entry
    entry = {
        "timestamp": datetime.now(ET).isoformat(),
        "scan_type": scheduled.get("scan_type", "pattern"),
        "gamma_drain": [{"symbol": c["symbol"], "score": c["score"]} for c in scheduled.get("gamma_drain", [])],
        "distribution": [{"symbol": c["symbol"], "score": c["score"]} for c in scheduled.get("distribution", [])],
        "liquidity": [{"symbol": c["symbol"], "score": c["score"]} for c in scheduled.get("liquidity", [])]
    }
    
    history["scans"].append(entry)
    history["scans"] = history["scans"][-100:]  # Keep last 100
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2, default=str)


def integrate_with_scheduled_results(pattern_results):
    """Integrate pattern results with scheduled scan results.
    
    If scheduled results are empty, POPULATES from patterns.
    """
    
    # Load existing scheduled results or create empty structure
    if SCHEDULED_RESULTS_FILE.exists():
        with open(SCHEDULED_RESULTS_FILE, 'r') as f:
            scheduled = json.load(f)
    else:
        scheduled = {"gamma_drain": [], "distribution": [], "liquidity": []}
    
    # Check if ALL engines are empty - if so, POPULATE from patterns
    total_existing = sum(len(scheduled.get(e, [])) for e in ["gamma_drain", "distribution", "liquidity"])
    
    if total_existing == 0:
        print("  [INFO] Scheduled results empty - POPULATING from patterns...")
        scheduled = _populate_from_patterns(pattern_results)
        
        # Save and return early
        with open(SCHEDULED_RESULTS_FILE, 'w') as f:
            json.dump(scheduled, f, indent=2, default=str)
        
        print(f"  Populated: Gamma={len(scheduled.get('gamma_drain', []))}, " +
              f"Dist={len(scheduled.get('distribution', []))}, " +
              f"Liq={len(scheduled.get('liquidity', []))}")
        
        # Also update scan history
        _update_scan_history(scheduled)
        return scheduled
    
    # Create lookup of pattern symbols and their boosts
    pattern_boosts = {}
    pattern_signals = {}
    
    for pr in pattern_results.get("pump_reversal", []):
        symbol = pr["symbol"]
        pattern_boosts[symbol] = pattern_boosts.get(symbol, 0) + pr["score_boost"]
        pattern_signals.setdefault(symbol, []).append(f"pump_reversal_{pr['total_gain']:+.0f}%")
        if pr.get("signals"):
            pattern_signals[symbol].extend(pr["signals"])
    
    for pr in pattern_results.get("two_day_rally", []):
        symbol = pr["symbol"]
        pattern_boosts[symbol] = pattern_boosts.get(symbol, 0) + pr["score_boost"]
        pattern_signals.setdefault(symbol, []).append(f"two_day_rally_{pr['total']:+.0f}%")
    
    for pr in pattern_results.get("high_vol_run", []):
        symbol = pr["symbol"]
        pattern_boosts[symbol] = pattern_boosts.get(symbol, 0) + pr["score_boost"]
        pattern_signals.setdefault(symbol, []).append(f"high_vol_{pr['vol_ratio']:.1f}x")
    
    # Update scheduled results with pattern boosts
    updated_count = 0
    added_count = 0
    
    for engine in ["gamma_drain", "distribution", "liquidity"]:
        candidates = scheduled.get(engine, [])
        
        for candidate in candidates:
            symbol = candidate.get("symbol")
            if symbol in pattern_boosts:
                # Boost existing score
                old_score = candidate.get("score", 0)
                boost = min(pattern_boosts[symbol], 0.25)  # Cap boost at 0.25
                new_score = min(old_score + boost, 0.95)
                candidate["score"] = round(new_score, 4)
                
                # Add pattern signals
                existing_signals = candidate.get("signals", [])
                candidate["signals"] = existing_signals + pattern_signals.get(symbol, [])
                
                # Mark as pattern-enhanced
                candidate["pattern_enhanced"] = True
                candidate["pattern_boost"] = round(boost, 3)
                
                updated_count += 1
    
    # Add NEW candidates from patterns that aren't in scheduled results
    existing_symbols = set()
    for engine in ["gamma_drain", "distribution", "liquidity"]:
        for c in scheduled.get(engine, []):
            existing_symbols.add(c.get("symbol"))
    
    # Add top pump reversal candidates not in existing results
    for pr in pattern_results.get("pump_reversal", [])[:10]:
        symbol = pr["symbol"]
        if symbol not in existing_symbols and len(pr.get("signals", [])) >= 2:
            # This is a high-confidence pattern not in existing scan
            new_candidate = {
                "symbol": symbol,
                "score": round(0.35 + pr["score_boost"], 4),  # Base 0.35 + boost
                "tier": "🟡 CLASS B",
                "engine_type": "distribution_trap",
                "current_price": pr["price"],
                "expiry": "TBD",
                "dte": 7,
                "signals": pr["signals"] + [f"pump_{pr['total_gain']:+.0f}%"],
                "pattern_enhanced": True,
                "pattern_source": "pump_reversal"
            }
            scheduled.setdefault("distribution", []).append(new_candidate)
            added_count += 1
            existing_symbols.add(symbol)
    
    # Re-sort by score
    for engine in ["gamma_drain", "distribution", "liquidity"]:
        if engine in scheduled:
            scheduled[engine].sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Update metadata
    scheduled["pattern_integration_time"] = datetime.now(ET).isoformat()
    scheduled["pattern_updated_count"] = updated_count
    scheduled["pattern_added_count"] = added_count
    
    # Save updated results
    with open(SCHEDULED_RESULTS_FILE, 'w') as f:
        json.dump(scheduled, f, indent=2, default=str)
    
    # Update scan history for 48-hour analysis
    _update_scan_history(scheduled)
    
    print(f"\nIntegration complete:")
    print(f"  Updated {updated_count} existing candidates with pattern boosts")
    print(f"  Added {added_count} new pattern-based candidates")
    
    return scheduled


async def main():
    # Run pattern scan
    pattern_results = await scan_patterns()
    
    # Display results
    print("\n" + "="*70)
    print("🎯 PUMP REVERSAL WATCH (watch for crash)")
    print("="*70)
    for r in pattern_results.get("pump_reversal", [])[:15]:
        signals = ", ".join(r["signals"][:2]) if r["signals"] else "-"
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} | {r['total_gain']:>+6.1f}% gain | boost: +{r['score_boost']:.2f} | {signals}")
    
    print("\n" + "="*70)
    print("↩️ TWO-DAY RALLY (exhaustion setup)")
    print("="*70)
    for r in pattern_results.get("two_day_rally", [])[:10]:
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} | {r['day1']:>+.1f}% + {r['day2']:>+.1f}% = {r['total']:>+.1f}% | boost: +{r['score_boost']:.2f}")
    
    print("\n" + "="*70)
    print("📈 HIGH VOLUME RUN")
    print("="*70)
    for r in pattern_results.get("high_vol_run", [])[:10]:
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} | {r['gain']:>+.1f}% on {r['vol_ratio']:.1f}x vol | boost: +{r['score_boost']:.2f}")
    
    # Save pattern results
    with open(PATTERN_RESULTS_FILE, 'w') as f:
        json.dump(pattern_results, f, indent=2)
    print(f"\nPattern results saved to {PATTERN_RESULTS_FILE}")
    
    # Integrate with scheduled results
    print("\n" + "="*70)
    print("INTEGRATING WITH SCHEDULED SCAN RESULTS")
    print("="*70)
    integrate_with_scheduled_results(pattern_results)


if __name__ == "__main__":
    asyncio.run(main())
