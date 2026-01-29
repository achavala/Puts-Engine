#!/usr/bin/env python3
"""Populate all 3 engines with sample data for dashboard display."""

import json
from datetime import datetime, date, timedelta
from pathlib import Path

# Load current results
results_file = Path("scheduled_scan_results.json")
with open(results_file, "r") as f:
    data = json.load(f)

# Add distribution candidates
distribution = [
    {
        "symbol": "CRM",
        "score": 0.35,
        "tier": "💪 STRONG",
        "engine_type": "distribution",
        "current_price": 250.0,
        "close": 250.0,
        "change_pct": -5.5,
        "volume": 5000000,
        "rvol": 1.6,
        "signals": ["high_rvol_red_day", "vwap_loss"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "ZS",
        "score": 0.32,
        "tier": "🟡 CLASS B",
        "engine_type": "distribution",
        "current_price": 180.0,
        "close": 180.0,
        "change_pct": -4.8,
        "volume": 3000000,
        "rvol": 1.5,
        "signals": ["high_rvol_red_day", "vwap_loss"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "FSLR",
        "score": 0.30,
        "tier": "🟡 CLASS B",
        "engine_type": "distribution",
        "current_price": 120.0,
        "close": 120.0,
        "change_pct": -4.2,
        "volume": 2000000,
        "rvol": 1.4,
        "signals": ["high_rvol_red_day", "vwap_loss"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    }
]

# Add liquidity candidates
liquidity = [
    {
        "symbol": "BIDU",
        "score": 0.28,
        "tier": "🟡 CLASS B",
        "engine_type": "liquidity",
        "current_price": 95.0,
        "close": 95.0,
        "change_pct": -3.5,
        "volume": 1500000,
        "rvol": 1.3,
        "signals": ["vwap_loss", "liquidity_vacuum"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "ARKK",
        "score": 0.26,
        "tier": "📊 WATCHING",
        "engine_type": "liquidity",
        "current_price": 45.0,
        "close": 45.0,
        "change_pct": -3.2,
        "volume": 800000,
        "rvol": 1.3,
        "signals": ["vwap_loss", "liquidity_vacuum"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "CRSP",
        "score": 0.25,
        "tier": "📊 WATCHING",
        "engine_type": "liquidity",
        "current_price": 35.0,
        "close": 35.0,
        "change_pct": -3.0,
        "volume": 600000,
        "rvol": 1.2,
        "signals": ["vwap_loss"],
        "signal_count": 1,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    }
]

# Add Gamma Drain candidates (real Alpaca data)
import os
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

env_path = Path(".env")
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                os.environ[key] = val

api_key = os.environ.get("ALPACA_API_KEY")
secret_key = os.environ.get("ALPACA_SECRET_KEY")

if api_key and secret_key:
    try:
        client = StockHistoricalDataClient(api_key, secret_key)
        tickers = ["MSFT", "NOW", "TEAM", "TWLO", "WDAY", "CLS"]
        
        end_date = datetime(2026, 1, 30)
        start_date = datetime(2026, 1, 27)
        
        request = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=end_date
        )
        
        bars = client.get_stock_bars(request)
        gamma_drain = []
        
        for ticker in tickers:
            ticker_bars = list(bars.data.get(ticker, []))
            if len(ticker_bars) < 2:
                continue
            
            latest = ticker_bars[-1]
            prev = ticker_bars[-2] if len(ticker_bars) > 1 else ticker_bars[-1]
            
            change_pct = (latest.close - prev.close) / prev.close
            avg_vol = sum(b.volume for b in ticker_bars) / len(ticker_bars) if ticker_bars else 1
            rvol = latest.volume / avg_vol if avg_vol > 0 else 1
            
            signals = []
            score = 0.0
            
            if change_pct < -0.03 and rvol > 1.3:
                signals.append("high_rvol_red_day")
                score += 0.20
            
            if change_pct < -0.05:
                signals.append("gap_down")
                score += 0.15
            
            if len(ticker_bars) >= 3:
                closes = [b.close for b in ticker_bars[-3:]]
                if all(closes[i] > closes[i+1] for i in range(len(closes)-1)):
                    signals.append("multi_day_weakness")
                    score += 0.10
            
            if ticker in ["MSFT", "NOW", "TEAM", "TWLO", "WDAY", "CLS"]:
                if change_pct < -0.05:
                    signals.append("earnings_contagion")
                    score += 0.10
            
            if latest.close < latest.open:
                signals.append("vwap_loss")
                score += 0.10
            
            if score < 0.25:
                continue
            
            today = date.today()
            days_until_friday = (4 - today.weekday() + 7) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            expiry_date = today + timedelta(days=days_until_friday)
            
            candidate = {
                "symbol": ticker,
                "score": round(score, 4),
                "tier": "💪 STRONG" if score >= 0.45 else "🟡 CLASS B" if score >= 0.35 else "📊 WATCHING",
                "engine_type": "gamma_drain",
                "current_price": round(latest.close, 2),
                "close": round(latest.close, 2),
                "change_pct": round(change_pct * 100, 2),
                "volume": latest.volume,
                "rvol": round(rvol, 2),
                "signals": signals,
                "signal_count": len(signals),
                "expiry": expiry_date.strftime("%b %d"),
                "dte": days_until_friday,
                "scan_time": datetime.now().strftime("%H:%M ET"),
                "scan_type": "real_time",
                "timestamp": datetime.now().isoformat()
            }
            
            gamma_drain.append(candidate)
        
        gamma_drain.sort(key=lambda x: x["score"], reverse=True)
        data["gamma_drain"] = gamma_drain[:15]
    except Exception as e:
        print(f"Warning: Could not fetch Gamma Drain candidates: {e}")
        data["gamma_drain"] = []

# Update data
data["distribution"] = distribution
data["liquidity"] = liquidity
data["total_candidates"] = len(data.get("gamma_drain", [])) + len(distribution) + len(liquidity)

# Save
with open(results_file, "w") as f:
    json.dump(data, f, indent=2)

print(f"✅ Updated: Gamma={len(data['gamma_drain'])}, Dist={len(distribution)}, Liq={len(liquidity)}")
print(f"   Total candidates: {data['total_candidates']}")
