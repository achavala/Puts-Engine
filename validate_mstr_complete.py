#!/usr/bin/env python3
"""
COMPREHENSIVE DATA VALIDATION FOR MSTR
======================================
This script traces EVERY data point used for a specific ticker
through ALL data sources to validate freshness and accuracy.

PhD-Level Analysis: Validate each API call, timestamp, and decision logic.
"""

import asyncio
import json
from datetime import datetime, date, timedelta
import pytz

# Import all clients
from putsengine.config import get_settings, EngineConfig
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.engine import PutsEngine


async def validate_ticker(symbol: str = "MSTR"):
    """
    Complete data source validation for a single ticker.
    """
    settings = get_settings()
    
    # Initialize clients
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    print("="*80)
    print(f"📊 COMPREHENSIVE DATA VALIDATION FOR {symbol}")
    print(f"⏰ Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    results = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "data_sources": {},
        "decision_factors": {},
        "issues_found": [],
        "recommendations": []
    }
    
    # =======================================================================
    # 1. ALPACA DATA (Real-time Stock Data)
    # =======================================================================
    print("\n" + "="*60)
    print("📈 1. ALPACA DATA (Real-Time Stock Prices & Quotes)")
    print("="*60)
    
    try:
        # Latest Quote (MOST IMPORTANT FOR CURRENT PRICE)
        quote = await alpaca.get_latest_quote(symbol)
        if quote and "quote" in quote:
            q = quote["quote"]
            bid = float(q.get("bp", 0))
            ask = float(q.get("ap", 0))
            bid_size = int(q.get("bs", 0))
            ask_size = int(q.get("as", 0))
            timestamp = q.get("t", "")
            
            current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
            
            results["data_sources"]["alpaca_quote"] = {
                "bid": bid,
                "ask": ask,
                "mid_price": current_price,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "timestamp": timestamp,
                "source": "Alpaca get_latest_quote",
                "endpoint": f"/v2/stocks/{symbol}/quotes/latest"
            }
            
            print(f"  ✅ Quote Data:")
            print(f"     Bid: ${bid:.2f} x {bid_size}")
            print(f"     Ask: ${ask:.2f} x {ask_size}")
            print(f"     Mid Price: ${current_price:.2f}")
            print(f"     Timestamp: {timestamp}")
        else:
            print(f"  ❌ No quote data available")
            results["issues_found"].append("No Alpaca quote data")
    except Exception as e:
        print(f"  ❌ Alpaca quote error: {e}")
        results["issues_found"].append(f"Alpaca quote error: {e}")
    
    try:
        # Daily Bars (Historical)
        daily_bars = await alpaca.get_daily_bars(symbol, limit=5)
        if daily_bars:
            last_bar = daily_bars[-1]
            results["data_sources"]["alpaca_daily_bars"] = {
                "last_bar_date": last_bar.timestamp.strftime("%Y-%m-%d"),
                "open": last_bar.open,
                "high": last_bar.high,
                "low": last_bar.low,
                "close": last_bar.close,
                "volume": last_bar.volume,
                "bars_returned": len(daily_bars),
                "source": "Alpaca get_daily_bars",
                "endpoint": f"/v2/stocks/{symbol}/bars (1Day)"
            }
            
            print(f"\n  ✅ Daily Bars (Last 5):")
            for bar in daily_bars:
                print(f"     {bar.timestamp.strftime('%Y-%m-%d')}: O=${bar.open:.2f} H=${bar.high:.2f} L=${bar.low:.2f} C=${bar.close:.2f} V={bar.volume:,}")
        else:
            print(f"  ❌ No daily bars available")
            results["issues_found"].append("No Alpaca daily bars")
    except Exception as e:
        print(f"  ❌ Alpaca bars error: {e}")
        results["issues_found"].append(f"Alpaca bars error: {e}")
    
    try:
        # Intraday Change (Real-time)
        change = await alpaca.get_intraday_change(symbol)
        if change:
            results["data_sources"]["alpaca_intraday_change"] = {
                "current_price": change["current_price"],
                "prev_close": change["prev_close"],
                "change_pct": change["change_pct"],
                "is_bearish": change["is_bearish"],
                "source": "Alpaca get_intraday_change (real-time)",
                "endpoint": "Combined: quotes + daily bars"
            }
            
            print(f"\n  ✅ Intraday Change:")
            print(f"     Current: ${change['current_price']:.2f}")
            print(f"     Prev Close: ${change['prev_close']:.2f}")
            print(f"     Change: {change['change_pct']:.2f}%")
            print(f"     Bearish (>3% drop): {change['is_bearish']}")
        else:
            print(f"  ⚠️ No intraday change data")
    except Exception as e:
        print(f"  ⚠️ Intraday change error: {e}")
    
    try:
        # Borrow Status
        borrow = await alpaca.check_borrow_status(symbol)
        results["data_sources"]["alpaca_borrow_status"] = borrow
        print(f"\n  ✅ Borrow Status:")
        print(f"     Easy to Borrow: {borrow['easy_to_borrow']}")
        print(f"     Squeeze Risk: {borrow['squeeze_risk']}")
    except Exception as e:
        print(f"  ⚠️ Borrow status error: {e}")
    
    # =======================================================================
    # 2. POLYGON DATA (Historical + Options)
    # =======================================================================
    print("\n" + "="*60)
    print("📊 2. POLYGON DATA (Historical Bars, Options, Technicals)")
    print("="*60)
    
    try:
        # Daily Bars
        poly_daily = await polygon.get_daily_bars(
            symbol,
            from_date=date.today() - timedelta(days=30)
        )
        if poly_daily:
            last_bar = poly_daily[-1]
            results["data_sources"]["polygon_daily_bars"] = {
                "last_bar_date": last_bar.timestamp.strftime("%Y-%m-%d"),
                "open": last_bar.open,
                "high": last_bar.high,
                "low": last_bar.low,
                "close": last_bar.close,
                "volume": last_bar.volume,
                "vwap": last_bar.vwap,
                "bars_returned": len(poly_daily),
                "source": "Polygon get_daily_bars",
                "endpoint": f"/v2/aggs/ticker/{symbol}/range/1/day/..."
            }
            
            print(f"  ✅ Daily Bars (Last 5):")
            for bar in poly_daily[-5:]:
                print(f"     {bar.timestamp.strftime('%Y-%m-%d')}: O=${bar.open:.2f} H=${bar.high:.2f} L=${bar.low:.2f} C=${bar.close:.2f} VWAP=${bar.vwap:.2f}")
        else:
            print(f"  ❌ No Polygon daily bars")
            results["issues_found"].append("No Polygon daily bars")
    except Exception as e:
        print(f"  ❌ Polygon bars error: {e}")
        results["issues_found"].append(f"Polygon bars error: {e}")
    
    try:
        # Minute Bars (today + yesterday)
        poly_minute = await polygon.get_minute_bars(
            symbol,
            from_date=date.today() - timedelta(days=2),
            limit=500
        )
        if poly_minute:
            results["data_sources"]["polygon_minute_bars"] = {
                "bars_returned": len(poly_minute),
                "first_bar": poly_minute[0].timestamp.isoformat(),
                "last_bar": poly_minute[-1].timestamp.isoformat(),
                "source": "Polygon get_minute_bars",
                "endpoint": f"/v2/aggs/ticker/{symbol}/range/1/minute/..."
            }
            print(f"\n  ✅ Minute Bars: {len(poly_minute)} bars from {poly_minute[0].timestamp.strftime('%Y-%m-%d %H:%M')} to {poly_minute[-1].timestamp.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"  ⚠️ No minute bars")
    except Exception as e:
        print(f"  ⚠️ Minute bars error: {e}")
    
    try:
        # Snapshot
        snapshot = await polygon.get_snapshot(symbol)
        if snapshot and "ticker" in snapshot:
            ticker = snapshot["ticker"]
            results["data_sources"]["polygon_snapshot"] = {
                "prev_day_close": ticker.get("prevDay", {}).get("c"),
                "today_open": ticker.get("day", {}).get("o"),
                "today_vwap": ticker.get("day", {}).get("vw"),
                "today_volume": ticker.get("day", {}).get("v"),
                "last_trade_price": ticker.get("lastTrade", {}).get("p"),
                "source": "Polygon snapshot",
                "endpoint": f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}"
            }
            print(f"\n  ✅ Snapshot:")
            print(f"     Prev Close: ${ticker.get('prevDay', {}).get('c', 0):.2f}")
            print(f"     Today Open: ${ticker.get('day', {}).get('o', 0):.2f}")
            print(f"     Today VWAP: ${ticker.get('day', {}).get('vw', 0):.2f}")
            print(f"     Today Volume: {ticker.get('day', {}).get('v', 0):,}")
        else:
            print(f"  ⚠️ No snapshot data")
    except Exception as e:
        print(f"  ⚠️ Snapshot error: {e}")
    
    try:
        # Technical Indicators (RSI)
        rsi_data = await polygon.get_rsi(symbol, window=14)
        if rsi_data:
            latest_rsi = rsi_data[-1] if rsi_data else None
            results["data_sources"]["polygon_rsi"] = {
                "latest_value": latest_rsi.get("value") if latest_rsi else None,
                "timestamp": latest_rsi.get("timestamp") if latest_rsi else None,
                "source": "Polygon RSI indicator",
                "endpoint": f"/v1/indicators/rsi/{symbol}"
            }
            print(f"\n  ✅ RSI (14): {latest_rsi.get('value', 'N/A'):.2f}" if latest_rsi and latest_rsi.get("value") else "  ⚠️ No RSI data")
        else:
            print(f"  ⚠️ No RSI data available")
    except Exception as e:
        print(f"  ⚠️ RSI error: {e}")
    
    try:
        # News/Earnings
        earnings = await polygon.check_earnings_proximity(symbol)
        results["data_sources"]["polygon_earnings"] = earnings
        print(f"\n  ✅ Earnings Proximity:")
        print(f"     Has Recent Earnings: {earnings['has_recent_earnings']}")
        print(f"     Pre-Earnings: {earnings['is_pre_earnings']}")
        print(f"     Post-Earnings: {earnings['is_post_earnings']}")
        print(f"     Guidance Sentiment: {earnings['guidance_sentiment']}")
    except Exception as e:
        print(f"  ⚠️ Earnings check error: {e}")
    
    # =======================================================================
    # 3. UNUSUAL WHALES DATA (Options Flow + Institutional)
    # =======================================================================
    print("\n" + "="*60)
    print("🐋 3. UNUSUAL WHALES DATA (Options Flow, Dark Pool, GEX)")
    print("="*60)
    
    try:
        # Options Flow Recent
        flow = await uw.get_flow_recent(symbol, limit=10)
        if flow:
            results["data_sources"]["uw_options_flow"] = {
                "flow_count": len(flow),
                "total_premium": sum(f.premium for f in flow),
                "put_count": sum(1 for f in flow if f.option_type.lower() == "put"),
                "call_count": sum(1 for f in flow if f.option_type.lower() == "call"),
                "recent_timestamps": [f.timestamp.isoformat() for f in flow[:3]],
                "source": "Unusual Whales flow-recent",
                "endpoint": f"/api/stock/{symbol}/flow-recent"
            }
            print(f"  ✅ Options Flow (Last 10):")
            print(f"     Total Premium: ${sum(f.premium for f in flow):,.0f}")
            print(f"     Put Trades: {sum(1 for f in flow if f.option_type.lower() == 'put')}")
            print(f"     Call Trades: {sum(1 for f in flow if f.option_type.lower() == 'call')}")
            
            # Show last 3 trades
            print(f"     Recent Trades:")
            for f in flow[:3]:
                print(f"       {f.timestamp.strftime('%H:%M')} | {f.option_type} ${f.strike} {f.expiration} | ${f.premium:,.0f} | {f.side}")
        else:
            print(f"  ⚠️ No options flow data")
    except Exception as e:
        print(f"  ❌ Options flow error: {e}")
        results["issues_found"].append(f"UW flow error: {e}")
    
    try:
        # Dark Pool Flow
        dp = await uw.get_dark_pool_flow(symbol, limit=10)
        if dp:
            results["data_sources"]["uw_dark_pool"] = {
                "print_count": len(dp),
                "total_shares": sum(p.size for p in dp),
                "avg_price": sum(p.price for p in dp) / len(dp) if dp else 0,
                "timestamps": [p.timestamp.isoformat() for p in dp[:3]],
                "source": "Unusual Whales dark pool",
                "endpoint": f"/api/darkpool/{symbol}"
            }
            print(f"\n  ✅ Dark Pool Flow (Last 10):")
            print(f"     Total Shares: {sum(p.size for p in dp):,}")
            print(f"     Avg Price: ${sum(p.price for p in dp) / len(dp):.2f}" if dp else "N/A")
            
            for p in dp[:3]:
                print(f"       {p.timestamp.strftime('%H:%M')} | {p.size:,} shares @ ${p.price:.2f}")
        else:
            print(f"  ⚠️ No dark pool data")
    except Exception as e:
        print(f"  ⚠️ Dark pool error: {e}")
    
    try:
        # GEX Data
        gex = await uw.get_gex_data(symbol)
        if gex:
            results["data_sources"]["uw_gex"] = {
                "net_gex": gex.net_gex,
                "call_gex": gex.call_gex,
                "put_gex": gex.put_gex,
                "dealer_delta": gex.dealer_delta,
                "put_wall": gex.put_wall,
                "call_wall": gex.call_wall,
                "gex_flip_level": gex.gex_flip_level,
                "source": "Unusual Whales GEX",
                "endpoint": f"/api/stock/{symbol}/greek-exposure"
            }
            print(f"\n  ✅ GEX (Gamma Exposure):")
            print(f"     Net GEX: {gex.net_gex:,.0f}")
            print(f"     Dealer Delta: {gex.dealer_delta:,.0f}")
            print(f"     Put Wall: ${gex.put_wall:.2f}" if gex.put_wall else "     Put Wall: N/A")
            print(f"     Call Wall: ${gex.call_wall:.2f}" if gex.call_wall else "     Call Wall: N/A")
            print(f"     GEX Flip Level: ${gex.gex_flip_level:.2f}" if gex.gex_flip_level else "     GEX Flip: N/A")
        else:
            print(f"  ⚠️ No GEX data")
    except Exception as e:
        print(f"  ⚠️ GEX error: {e}")
    
    try:
        # IV Rank
        iv_data = await uw.get_iv_rank(symbol)
        if iv_data:
            data = iv_data.get("data", iv_data)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            results["data_sources"]["uw_iv_rank"] = {
                "iv_rank": data.get("iv_rank") if isinstance(data, dict) else None,
                "iv_percentile": data.get("iv_percentile") if isinstance(data, dict) else None,
                "source": "Unusual Whales IV rank",
                "endpoint": f"/api/stock/{symbol}/iv-rank"
            }
            iv_rank = data.get("iv_rank") if isinstance(data, dict) else None
            print(f"\n  ✅ IV Rank: {iv_rank}%" if iv_rank else "  ⚠️ No IV rank")
        else:
            print(f"  ⚠️ No IV data")
    except Exception as e:
        print(f"  ⚠️ IV rank error: {e}")
    
    try:
        # OI Change
        oi = await uw.get_oi_change(symbol)
        if oi:
            data = oi.get("data", oi)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            results["data_sources"]["uw_oi_change"] = {
                "data": data if isinstance(data, dict) else oi,
                "source": "Unusual Whales OI change",
                "endpoint": f"/api/stock/{symbol}/oi-change"
            }
            print(f"\n  ✅ OI Change: Data available")
        else:
            print(f"  ⚠️ No OI change data")
    except Exception as e:
        print(f"  ⚠️ OI change error: {e}")
    
    # =======================================================================
    # 4. RUN FULL ENGINE ANALYSIS
    # =======================================================================
    print("\n" + "="*60)
    print("🔥 4. FULL ENGINE ANALYSIS (Gamma Drain + Distribution + Liquidity)")
    print("="*60)
    
    try:
        engine = PutsEngine(settings)
        
        # Run individual analyses
        print("\n  Running Distribution Analysis...")
        dist_signal = await engine.distribution.analyze(symbol)
        results["decision_factors"]["distribution"] = {
            "score": dist_signal.score,
            "signals": dist_signal.signals,
            "flat_price_rising_volume": dist_signal.flat_price_rising_volume,
            "failed_breakout": dist_signal.failed_breakout,
            "vwap_loss": dist_signal.vwap_loss,
            "call_selling_at_bid": dist_signal.call_selling_at_bid,
            "put_buying_at_ask": dist_signal.put_buying_at_ask,
            "repeated_sell_blocks": dist_signal.repeated_sell_blocks,
        }
        print(f"  ✅ Distribution Score: {dist_signal.score:.2f}")
        print(f"     Active Signals: {sum(1 for v in dist_signal.signals.values() if v and v != 'UNKNOWN')}")
        
        print("\n  Running Liquidity Vacuum Analysis...")
        liq_signal = await engine.liquidity.analyze(symbol)
        results["decision_factors"]["liquidity"] = {
            "score": liq_signal.score,
            "bid_collapsing": liq_signal.bid_collapsing,
            "spread_widening": liq_signal.spread_widening,
            "volume_no_progress": liq_signal.volume_no_progress,
            "vwap_retest_failed": liq_signal.vwap_retest_failed,
        }
        print(f"  ✅ Liquidity Score: {liq_signal.score:.2f}")
        
        print("\n  Running Acceleration Window Analysis...")
        accel_signal = await engine.acceleration.analyze(symbol)
        results["decision_factors"]["acceleration"] = {
            "is_valid": accel_signal.is_valid,
            "is_late_entry": accel_signal.is_late_entry,
            "price_below_vwap": accel_signal.price_below_vwap,
            "price_below_ema20": accel_signal.price_below_ema20,
            "net_delta_negative": accel_signal.net_delta_negative,
            "gamma_flipping_short": accel_signal.gamma_flipping_short,
            "iv_reasonable": accel_signal.iv_reasonable,
            "engine_type": accel_signal.engine_type.value,
        }
        print(f"  ✅ Acceleration Valid: {accel_signal.is_valid}")
        print(f"     Engine Type: {accel_signal.engine_type.value}")
        print(f"     Late Entry Block: {accel_signal.is_late_entry}")
        
    except Exception as e:
        print(f"  ❌ Engine analysis error: {e}")
        results["issues_found"].append(f"Engine error: {e}")
    
    # =======================================================================
    # 5. SUMMARY & RECOMMENDATIONS
    # =======================================================================
    print("\n" + "="*60)
    print("📋 5. VALIDATION SUMMARY")
    print("="*60)
    
    # Count data sources
    total_sources = len(results["data_sources"])
    working_sources = sum(1 for k, v in results["data_sources"].items() if v)
    
    print(f"\n  Data Sources Validated: {working_sources}/{total_sources}")
    print(f"  Issues Found: {len(results['issues_found'])}")
    
    if results["issues_found"]:
        print("\n  ❌ ISSUES:")
        for issue in results["issues_found"]:
            print(f"     - {issue}")
    
    # Data freshness check
    print("\n  📅 DATA FRESHNESS:")
    
    alpaca_quote = results["data_sources"].get("alpaca_quote", {})
    if alpaca_quote:
        ts = alpaca_quote.get("timestamp", "")
        print(f"     Alpaca Quote: {ts}")
    
    poly_bars = results["data_sources"].get("polygon_daily_bars", {})
    if poly_bars:
        print(f"     Polygon Bars: {poly_bars.get('last_bar_date', 'N/A')}")
    
    uw_flow = results["data_sources"].get("uw_options_flow", {})
    if uw_flow:
        print(f"     UW Flow: {uw_flow.get('flow_count', 0)} trades")
    
    # Decision summary
    print("\n  🎯 DECISION FACTORS FOR {symbol}:")
    dist = results["decision_factors"].get("distribution", {})
    liq = results["decision_factors"].get("liquidity", {})
    accel = results["decision_factors"].get("acceleration", {})
    
    print(f"     Distribution Score: {dist.get('score', 0):.2f}")
    print(f"     Liquidity Score: {liq.get('score', 0):.2f}")
    print(f"     Acceleration Valid: {accel.get('is_valid', False)}")
    print(f"     Engine Type: {accel.get('engine_type', 'N/A')}")
    
    # Final verdict
    total_score = dist.get('score', 0) + liq.get('score', 0)
    is_valid = accel.get('is_valid', False)
    
    print("\n  📊 FINAL VERDICT:")
    if total_score >= 0.6 and is_valid:
        print(f"     ✅ {symbol} is a VALID PUT CANDIDATE (Score: {total_score:.2f})")
    elif total_score >= 0.4:
        print(f"     🟡 {symbol} is on WATCH (Score: {total_score:.2f}, Timing: {is_valid})")
    else:
        print(f"     ❌ {symbol} does NOT meet PUT criteria (Score: {total_score:.2f})")
    
    # Close clients
    await alpaca.close()
    await polygon.close()
    await uw.close()
    
    # Save results
    output_file = f"validation_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  💾 Full results saved to: {output_file}")
    
    return results


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "MSTR"
    asyncio.run(validate_ticker(symbol))
