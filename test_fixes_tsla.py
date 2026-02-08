#!/usr/bin/env python3
"""
Validation script for 5 UW parser fixes (Feb 8, 2026).
Tests using TSLA as reference ticker.

1. GEX flip level — ±30% filter
2. Put/Call wall — ±30% filter  
3. Net-prem-ticks → opening/closing flow
4. UW tags preferred for sentiment
5. Options-volume aggression scoring
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from putsengine.config import Settings
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.api_budget import APIBudgetManager

settings = Settings()

async def main():
    uw = UnusualWhalesClient(settings)
    symbol = "TSLA"
    
    print("=" * 70)
    print(f"🔧 TESTING 5 UW PARSER FIXES — {symbol}")
    print("=" * 70)
    
    results = {"pass": 0, "fail": 0, "warn": 0}
    
    # ── TEST 1: GEX flip level + wall computation ──
    print("\n📊 TEST 1: GEX Data (flip level + walls with ±30% filter)")
    try:
        gex = await uw.get_gex_data(symbol)
        if gex:
            print(f"  net_gex:       {gex.net_gex:,.0f}")
            print(f"  call_gex:      {gex.call_gex:,.0f}")
            print(f"  put_gex:       {gex.put_gex:,.0f}")
            print(f"  dealer_delta:  {gex.dealer_delta:,.0f}")
            print(f"  gex_flip:      ${gex.gex_flip_level}" if gex.gex_flip_level else "  gex_flip:      None")
            print(f"  put_wall:      ${gex.put_wall}" if gex.put_wall else "  put_wall:      None")
            print(f"  call_wall:     ${gex.call_wall}" if gex.call_wall else "  call_wall:     None")
            
            # Validation: flip and walls should be within ±30% of ~$400ish range
            if gex.gex_flip_level:
                if 250 < gex.gex_flip_level < 600:
                    print(f"  ✅ PASS: GEX flip ${gex.gex_flip_level:.2f} is in realistic range")
                    results["pass"] += 1
                else:
                    print(f"  ❌ FAIL: GEX flip ${gex.gex_flip_level:.2f} outside $250-$600 range")
                    results["fail"] += 1
            else:
                print(f"  ⚠️ WARN: GEX flip not computed")
                results["warn"] += 1
            
            if gex.put_wall:
                cw = f"${gex.call_wall:.0f}" if gex.call_wall else "N/A"
                if gex.put_wall != gex.call_wall:
                    print(f"  ✅ PASS: Put wall (${gex.put_wall:.0f}) ≠ Call wall ({cw})")
                    results["pass"] += 1
                else:
                    print(f"  ⚠️ WARN: Put wall = Call wall = ${gex.put_wall:.0f}")
                    results["warn"] += 1
            else:
                print(f"  ⚠️ WARN: Put wall not computed")
                results["warn"] += 1
        else:
            print("  ❌ FAIL: get_gex_data returned None")
            results["fail"] += 1
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        results["fail"] += 1
    
    # ── TEST 2: Standalone put wall ──
    print("\n📊 TEST 2: Standalone get_put_wall (±30% filter)")
    try:
        put_wall = await uw.get_put_wall(symbol)
        if put_wall:
            if 250 < put_wall < 600:
                print(f"  ✅ PASS: Put wall ${put_wall:.0f} in realistic range")
                results["pass"] += 1
            else:
                print(f"  ❌ FAIL: Put wall ${put_wall:.0f} outside $250-$600")
                results["fail"] += 1
        else:
            print(f"  ⚠️ WARN: get_put_wall returned None")
            results["warn"] += 1
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        results["fail"] += 1
    
    # ── TEST 3: Net Premium Ticks + Opening/Closing Flow ──
    print("\n📊 TEST 3: Net Premium Ticks + Opening/Closing Flow")
    try:
        raw = await uw.get_net_premium_ticks(symbol)
        if raw:
            data = raw.get("data", raw) if isinstance(raw, dict) else raw
            tick_count = len(data) if isinstance(data, list) else 0
            print(f"  Raw ticks: {tick_count}")
            if tick_count > 0 and isinstance(data, list) and isinstance(data[0], dict):
                sample = data[0]
                keys = list(sample.keys())[:10]
                print(f"  Sample keys: {keys}")
                print(f"  Sample: net_call_premium={sample.get('net_call_premium')}, "
                      f"net_put_premium={sample.get('net_put_premium')}, "
                      f"net_delta={sample.get('net_delta')}")
            
            flow = await uw.get_opening_closing_flow(symbol)
            if flow:
                print(f"  Opening bias:    {flow.get('opening_bias')}")
                print(f"  Closing bias:    {flow.get('closing_bias')}")
                print(f"  Flow reversal:   {flow.get('flow_reversal')}")
                print(f"  Delta trend:     {flow.get('intraday_delta_trend')}")
                print(f"  Opening net $:   ${flow.get('opening_net_premium', 0):,.0f}")
                print(f"  Closing net $:   ${flow.get('closing_net_premium', 0):,.0f}")
                print(f"  Total net $:     ${flow.get('total_net_premium', 0):,.0f}")
                print(f"  ✅ PASS: Opening/closing flow analysis working")
                results["pass"] += 1
            else:
                print(f"  ⚠️ WARN: get_opening_closing_flow returned empty (market might be closed)")
                results["warn"] += 1
        else:
            print(f"  ⚠️ WARN: net-prem-ticks returned empty (market might be closed)")
            results["warn"] += 1
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        results["fail"] += 1
    
    # ── TEST 4: Flow Sentiment with UW Tags ──
    print("\n📊 TEST 4: Flow Sentiment (UW tags preferred over bid/ask inference)")
    try:
        flows = await uw.get_flow_recent(symbol, limit=20)
        if flows:
            tag_based = 0
            inference_based = 0
            for f in flows:
                # Check if tags would have caught this
                # We can't easily tell which method was used, but we can check
                # that sentiments are set
                if f.sentiment in ["bearish", "bullish"]:
                    tag_based += 1
                else:
                    inference_based += 1
            
            print(f"  Total flows: {len(flows)}")
            print(f"  With sentiment (bearish/bullish): {tag_based}")
            print(f"  Neutral/unknown: {inference_based}")
            
            # Show samples
            for f in flows[:3]:
                print(f"    {f.underlying:5s} {f.option_type:4s} ${f.strike:7.0f} "
                      f"side={f.side:4s} sentiment={f.sentiment:8s} "
                      f"prem=${f.premium:,.0f}")
            
            if tag_based > 0:
                print(f"  ✅ PASS: {tag_based}/{len(flows)} flows have sentiment classification")
                results["pass"] += 1
            else:
                print(f"  ⚠️ WARN: No flows with bearish/bullish sentiment")
                results["warn"] += 1
        else:
            print(f"  ⚠️ WARN: No recent flows")
            results["warn"] += 1
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        results["fail"] += 1
    
    # ── TEST 5: Options Volume Aggression ──
    print("\n📊 TEST 5: Options Volume Ask/Bid Side Aggression")
    try:
        vol_data = await uw.get_options_volume(symbol)
        if vol_data:
            data = vol_data.get("data", vol_data) if isinstance(vol_data, dict) else vol_data
            if isinstance(data, list) and data:
                latest = data[-1] if isinstance(data[-1], dict) else data[0]
                if isinstance(latest, dict):
                    pv = int(latest.get("put_volume", 0))
                    pa = int(latest.get("put_volume_ask_side", 0))
                    pb = int(latest.get("put_volume_bid_side", 0))
                    bp = float(latest.get("bearish_premium", 0))
                    blp = float(latest.get("bullish_premium", 0))
                    avg30 = float(latest.get("avg_30_day_put_volume", 0))
                    
                    print(f"  Put volume:        {pv:,}")
                    print(f"  Put vol ask side:  {pa:,}")
                    print(f"  Put vol bid side:  {pb:,}")
                    print(f"  30d avg put vol:   {avg30:,.0f}")
                    print(f"  Bearish premium:   ${bp:,.0f}")
                    print(f"  Bullish premium:   ${blp:,.0f}")
                    
                    if pb > 0:
                        aggression = pa / pb
                        print(f"  Aggression ratio:  {aggression:.2f}x")
                    else:
                        aggression = 0
                        print(f"  Aggression ratio:  N/A (no bid-side)")
                    
                    if pa > 0 or pb > 0:
                        print(f"  ✅ PASS: Ask/bid side data available for aggression scoring")
                        results["pass"] += 1
                    else:
                        print(f"  ⚠️ WARN: No ask/bid side data (field may not be present)")
                        results["warn"] += 1
                else:
                    print(f"  ⚠️ WARN: Unexpected data format")
                    results["warn"] += 1
            else:
                print(f"  ⚠️ WARN: No volume data records")
                results["warn"] += 1
        else:
            print(f"  ⚠️ WARN: get_options_volume returned empty")
            results["warn"] += 1
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        results["fail"] += 1
    
    # ── SUMMARY ──
    print("\n" + "=" * 70)
    print(f"📋 RESULTS: ✅ {results['pass']} PASS | ⚠️ {results['warn']} WARN | ❌ {results['fail']} FAIL")
    print("=" * 70)
    
    # Remaining API calls
    print(f"\n📊 UW API calls used: {uw._calls_today}")
    print(f"📊 UW API calls remaining: {uw.remaining_calls}")
    
    cache_stats = uw.get_cache_stats()
    print(f"📊 Cache: hits={cache_stats['cache_hits']}, "
          f"misses={cache_stats['cache_misses']}, "
          f"saved={cache_stats['api_calls_saved']}")
    
    await uw.close()

if __name__ == "__main__":
    asyncio.run(main())
