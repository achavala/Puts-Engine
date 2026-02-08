#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
UNUSUAL WHALES — FULL API ENDPOINT AUDIT FOR COIN
═══════════════════════════════════════════════════════════════════════════════

Tests EVERY UW endpoint used by PutsEngine against COIN (Coinbase).
Dumps raw JSON → parsed output → validation status.

PURPOSE: Read-only diagnosis. Does NOT fix anything.
"""
import asyncio
import sys
import os
import json
from datetime import datetime, date, timedelta
from pprint import pformat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from putsengine.config import Settings
from putsengine.clients.unusual_whales_client import UnusualWhalesClient

settings = Settings()

SYMBOL = "COIN"
PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
NA   = "➖ N/A"

api_calls_made = 0
results_summary = []

def section(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

def subsection(title):
    print(f"\n  {'─'*70}")
    print(f"  {title}")
    print(f"  {'─'*70}")

def dump_raw(data, max_items=3, indent=4):
    """Pretty-print raw data, truncated for readability."""
    prefix = " " * indent
    if isinstance(data, list):
        print(f"{prefix}Type: list, Length: {len(data)}")
        for i, item in enumerate(data[:max_items]):
            print(f"{prefix}[{i}] {json.dumps(item, indent=2, default=str)[:500]}")
        if len(data) > max_items:
            print(f"{prefix}... ({len(data) - max_items} more records)")
    elif isinstance(data, dict):
        keys = list(data.keys())
        print(f"{prefix}Type: dict, Keys: {keys[:20]}")
        for k in keys[:10]:
            v = data[k]
            if isinstance(v, list):
                print(f"{prefix}  '{k}': list[{len(v)}]")
                if v:
                    print(f"{prefix}    [0] = {json.dumps(v[0], indent=2, default=str)[:300]}")
            elif isinstance(v, dict):
                print(f"{prefix}  '{k}': dict{{{', '.join(list(v.keys())[:8])}}}")
            else:
                print(f"{prefix}  '{k}': {v}")
    else:
        print(f"{prefix}{data}")

def record(endpoint, status, details=""):
    results_summary.append((endpoint, status, details))

async def main():
    global api_calls_made
    
    # Create client WITHOUT budget manager to avoid being blocked
    uw = UnusualWhalesClient(settings)
    # Disable budget manager for audit
    uw._budget_manager = None
    uw._force_scan_mode = True
    
    print("=" * 80)
    print(f"  UNUSUAL WHALES FULL API AUDIT — {SYMBOL}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    print(f"  API Key: ...{settings.unusual_whales_api_key[-6:]}")
    print(f"  Remaining calls today: {uw.remaining_calls}")
    print("=" * 80)
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 1: STOCK INFO
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 1: STOCK INFO — /api/stock/COIN/info")
    print("  Purpose: Basic stock metadata, sector, market cap, next earnings date")
    print("  Used by: Earnings calendar fallback, sector classification")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/info")
    api_calls_made += 1
    
    if raw:
        dump_raw(raw)
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            earnings = data.get("next_earnings_date", "MISSING")
            sector = data.get("sector", "MISSING")
            mktcap = data.get("market_cap", "MISSING")
            name = data.get("name", data.get("short_name", "MISSING"))
            print(f"\n  PARSED:")
            print(f"    Name:            {name}")
            print(f"    Sector:          {sector}")
            print(f"    Market Cap:      {mktcap}")
            print(f"    Next Earnings:   {earnings}")
            print(f"    Announce Time:   {data.get('announce_time', 'N/A')}")
            record("stock_info", PASS, f"sector={sector}, earnings={earnings}")
        else:
            record("stock_info", WARN, "Unexpected data format")
    else:
        print("  ❌ EMPTY RESPONSE")
        record("stock_info", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 2: FLOW RECENT
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 2: FLOW RECENT — /api/stock/COIN/flow-recent")
    print("  Purpose: Real-time options flow (puts, calls, sweeps, blocks)")
    print("  Used by: Distribution layer, EWS, Flow Quality scoring")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/flow-recent", {"limit": 10})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  RAW RECORDS: {len(data)}")
            if data:
                print(f"\n  RAW FIELD KEYS (first record):")
                first = data[0]
                for k, v in sorted(first.items()):
                    print(f"    {k:30s} = {str(v)[:80]}")
                
                # Check critical fields
                print(f"\n  CRITICAL FIELD CHECK:")
                has_side = any(r.get("side") for r in data)
                has_bid_vol = any(r.get("bid_vol") for r in data)
                has_ask_vol = any(r.get("ask_vol") for r in data)
                has_premium = any(r.get("premium") for r in data)
                has_iv = any(r.get("iv") for r in data)
                has_delta = any(r.get("delta") for r in data)
                has_option_type = any(r.get("option_type") for r in data)
                has_strike = any(r.get("strike") for r in data)
                has_expiry = any(r.get("expiry") for r in data)
                has_is_sweep = any(r.get("is_sweep") for r in data)
                has_tags = any(r.get("tags") for r in data)
                
                print(f"    'side' field exists:       {has_side} {'← FIX: use bid_vol/ask_vol' if not has_side else ''}")
                print(f"    'bid_vol' field exists:    {has_bid_vol}")
                print(f"    'ask_vol' field exists:    {has_ask_vol}")
                print(f"    'premium' field exists:    {has_premium}")
                print(f"    'iv' field exists:         {has_iv}")
                print(f"    'delta' field exists:      {has_delta}")
                print(f"    'option_type' field exists: {has_option_type}")
                print(f"    'strike' field exists:     {has_strike}")
                print(f"    'expiry' field exists:     {has_expiry}")
                print(f"    'is_sweep' field exists:   {has_is_sweep}")
                print(f"    'tags' field exists:       {has_tags}")
                
                # Test parsed flow
                subsection("PARSED FLOW (via get_flow_recent)")
                parsed_flows = await uw.get_flow_recent(SYMBOL, limit=10)
                api_calls_made += 1  # but cache should serve this
                
                puts = [f for f in parsed_flows if f.option_type.lower() == "put"]
                calls = [f for f in parsed_flows if f.option_type.lower() == "call"]
                bearish = [f for f in parsed_flows if f.sentiment == "bearish"]
                bullish = [f for f in parsed_flows if f.sentiment == "bullish"]
                neutral = [f for f in parsed_flows if f.sentiment == "neutral"]
                
                print(f"    Total parsed:   {len(parsed_flows)}")
                print(f"    Puts:           {len(puts)}")
                print(f"    Calls:          {len(calls)}")
                print(f"    Bearish:        {len(bearish)}")
                print(f"    Bullish:        {len(bullish)}")
                print(f"    Neutral:        {len(neutral)}")
                
                if parsed_flows:
                    f = parsed_flows[0]
                    print(f"\n    EXAMPLE PARSED FLOW:")
                    print(f"      Symbol:     {f.symbol}")
                    print(f"      Underlying: {f.underlying}")
                    print(f"      Type:       {f.option_type}")
                    print(f"      Strike:     ${f.strike}")
                    print(f"      Expiry:     {f.expiration}")
                    print(f"      Side:       {f.side}")
                    print(f"      Sentiment:  {f.sentiment}")
                    print(f"      Premium:    ${f.premium:,.0f}")
                    print(f"      Size:       {f.size}")
                    print(f"      IV:         {f.implied_volatility:.4f}")
                    print(f"      Delta:      {f.delta:.4f}")
                    print(f"      Is Sweep:   {f.is_sweep}")
                    print(f"      Is Block:   {f.is_block}")
                
                all_neutral = all(f.sentiment == "neutral" for f in parsed_flows)
                if all_neutral and len(parsed_flows) > 0:
                    record("flow_recent", WARN, f"{len(parsed_flows)} records but ALL neutral sentiment — side inference may be failing")
                elif len(bearish) + len(bullish) > 0:
                    record("flow_recent", PASS, f"{len(parsed_flows)} flows, {len(bearish)} bear, {len(bullish)} bull")
                else:
                    record("flow_recent", WARN, f"{len(parsed_flows)} flows, no directional sentiment")
            else:
                record("flow_recent", WARN, "Empty data list")
        else:
            record("flow_recent", FAIL, "Unexpected format")
    else:
        record("flow_recent", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 3: FLOW ALERTS (per-ticker)
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 3: FLOW ALERTS — /api/stock/COIN/flow-alerts")
    print("  Purpose: Unusual/large flow alerts for a specific ticker")
    print("  Used by: Market Direction Engine")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/flow-alerts", {"limit": 5})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            if data:
                print(f"  First record keys: {sorted(data[0].keys())}")
                dump_raw(data, max_items=2)
            record("flow_alerts_ticker", PASS, f"{len(data)} alerts")
        else:
            dump_raw(raw)
            record("flow_alerts_ticker", WARN, "Non-list response")
    else:
        print("  ❌ EMPTY RESPONSE")
        record("flow_alerts_ticker", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 4: DARK POOL
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 4: DARK POOL — /api/darkpool/COIN")
    print("  Purpose: Off-exchange institutional prints")
    print("  Used by: Distribution layer (sell-block detection), IPI scoring")
    
    raw = await uw._request(f"/api/darkpool/{SYMBOL}", {"limit": 10})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  RAW RECORDS: {len(data)}")
            if data:
                print(f"\n  RAW FIELD KEYS (first record):")
                for k, v in sorted(data[0].items()):
                    print(f"    {k:30s} = {str(v)[:80]}")
                
                # Check critical fields
                print(f"\n  CRITICAL FIELD CHECK:")
                has_side = any(r.get("side") for r in data)
                has_nbbo_bid = any(r.get("nbbo_bid") for r in data)
                has_nbbo_ask = any(r.get("nbbo_ask") for r in data)
                has_price = any(r.get("price") for r in data)
                has_size = any(r.get("size") for r in data)
                has_exchange = any(r.get("exchange") or r.get("venue") or r.get("market_center") for r in data)
                
                print(f"    'side' field exists:     {has_side} {'← FIX: infer from NBBO' if not has_side else ''}")
                print(f"    'nbbo_bid' exists:       {has_nbbo_bid}")
                print(f"    'nbbo_ask' exists:       {has_nbbo_ask}")
                print(f"    'price' exists:          {has_price}")
                print(f"    'size' exists:           {has_size}")
                print(f"    'exchange/venue' exists: {has_exchange}")
                
                # NBBO inference test
                if has_nbbo_bid and has_nbbo_ask and has_price:
                    print(f"\n  NBBO SIDE INFERENCE TEST:")
                    buys, sells, ambig = 0, 0, 0
                    for r in data:
                        p = float(r.get("price", 0))
                        bid = float(r.get("nbbo_bid", 0) or 0)
                        ask = float(r.get("nbbo_ask", 0) or 0)
                        if p > 0 and bid > 0 and ask > 0:
                            if p >= ask:
                                buys += 1
                            elif p <= bid:
                                sells += 1
                            else:
                                ambig += 1
                            print(f"    price=${p:.2f} bid=${bid:.2f} ask=${ask:.2f} → {'BUY' if p >= ask else 'SELL' if p <= bid else 'AMBIGUOUS'}")
                    print(f"    Summary: {buys} buys, {sells} sells, {ambig} ambiguous")
                
                # Test parsed
                subsection("PARSED DARK POOL (via get_dark_pool_flow)")
                parsed_dp = await uw.get_dark_pool_flow(SYMBOL, limit=10)
                
                buys_parsed = [p for p in parsed_dp if p.is_buy is True]
                sells_parsed = [p for p in parsed_dp if p.is_buy is False]
                none_parsed = [p for p in parsed_dp if p.is_buy is None]
                
                print(f"    Total parsed:  {len(parsed_dp)}")
                print(f"    Buy-side:      {len(buys_parsed)}")
                print(f"    Sell-side:     {len(sells_parsed)}")
                print(f"    Ambiguous:     {len(none_parsed)}")
                
                if parsed_dp:
                    p = parsed_dp[0]
                    print(f"\n    EXAMPLE:")
                    print(f"      Price: ${p.price:.2f}  Size: {p.size:,}  Exchange: {p.exchange}  is_buy: {p.is_buy}")
                
                record("dark_pool", PASS, f"{len(parsed_dp)} prints ({len(buys_parsed)} buy, {len(sells_parsed)} sell, {len(none_parsed)} ambig)")
            else:
                record("dark_pool", WARN, "Empty data list")
        else:
            record("dark_pool", FAIL, "Unexpected format")
    else:
        record("dark_pool", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 5: GREEK EXPOSURE (GEX)
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 5: GREEK EXPOSURE — /api/stock/COIN/greek-exposure")
    print("  Purpose: Gamma/delta exposure for dealer positioning")
    print("  Used by: Dealer layer (20% of Gamma Drain score), GEX flip detection")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/greek-exposure")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        
        if isinstance(data, list):
            print(f"\n  RAW: Time series with {len(data)} records")
            if data:
                print(f"  First record keys: {sorted(data[0].keys())}")
                latest = data[-1]
                print(f"\n  LATEST RECORD (last in series):")
                for k, v in sorted(latest.items()):
                    print(f"    {k:25s} = {v}")
                
                # Check critical fields
                print(f"\n  CRITICAL FIELD CHECK:")
                has_gex = "gex" in latest or "net_gex" in latest
                has_call_gamma = "call_gamma" in latest
                has_put_gamma = "put_gamma" in latest
                has_call_delta = "call_delta" in latest
                has_put_delta = "put_delta" in latest
                has_dex = "dex" in latest or "dealer_delta" in latest
                
                print(f"    'gex'/'net_gex' exists:    {has_gex} {'← Must compute from call_gamma + put_gamma' if not has_gex else ''}")
                print(f"    'call_gamma' exists:       {has_call_gamma}")
                print(f"    'put_gamma' exists:        {has_put_gamma}")
                print(f"    'call_delta' exists:       {has_call_delta}")
                print(f"    'put_delta' exists:        {has_put_delta}")
                print(f"    'dex'/'dealer_delta':      {has_dex} {'← Must compute from call_delta + put_delta' if not has_dex else ''}")
                
                # Compute manually
                cg = float(latest.get("call_gamma", 0))
                pg = float(latest.get("put_gamma", 0))
                cd = float(latest.get("call_delta", 0))
                pd = float(latest.get("put_delta", 0))
                print(f"\n  COMPUTED VALUES:")
                print(f"    net_gex = call_gamma({cg:,.0f}) + put_gamma({pg:,.0f}) = {cg+pg:,.0f}")
                print(f"    dealer_delta = call_delta({cd:,.0f}) + put_delta({pd:,.0f}) = {cd+pd:,.0f}")
                print(f"    GEX sign: {'POSITIVE (dampening)' if cg+pg > 0 else 'NEGATIVE (amplifying)'}")
        elif isinstance(data, dict):
            print(f"  RAW (dict): {sorted(data.keys())}")
            dump_raw(data)
        
        # Test parsed
        subsection("PARSED GEX (via get_gex_data)")
        gex = await uw.get_gex_data(SYMBOL)
        
        if gex:
            print(f"    Net GEX:       {gex.net_gex:,.0f}")
            print(f"    Call Gamma:    {gex.call_gex:,.0f}")
            print(f"    Put Gamma:     {gex.put_gex:,.0f}")
            print(f"    Dealer Delta:  {gex.dealer_delta:,.0f}")
            print(f"    GEX Flip:      {gex.gex_flip_level}")
            print(f"    Put Wall:      {gex.put_wall}")
            print(f"    Call Wall:     {gex.call_wall}")
            
            if gex.net_gex != 0:
                record("greek_exposure", PASS, f"net_gex={gex.net_gex:,.0f}, flip={gex.gex_flip_level}")
            else:
                record("greek_exposure", WARN, "net_gex=0 — may be computed incorrectly")
        else:
            record("greek_exposure", FAIL, "Parsed GEX returned None")
    else:
        record("greek_exposure", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 6: GREEKS (alternative endpoint)
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 6: GREEKS — /api/stock/COIN/greeks")
    print("  Purpose: Fallback for GEX data")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/greeks")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            if data:
                print(f"  Keys: {sorted(data[-1].keys())}")
        elif isinstance(data, dict):
            print(f"  Keys: {sorted(data.keys())}")
        dump_raw(raw, max_items=2)
        record("greeks", PASS, f"Returned data")
    else:
        record("greeks", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 7: OI CHANGE
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 7: OI CHANGE — /api/stock/COIN/oi-change")
    print("  Purpose: Open interest accumulation/drain detection")
    print("  Used by: Distribution layer, EWS footprint scoring")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/oi-change")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  Records: {len(data)}")
            if data:
                latest = data[-1] if isinstance(data[-1], dict) else data[0]
                print(f"  Latest keys: {sorted(latest.keys())}")
                print(f"\n  LATEST RECORD:")
                for k, v in sorted(latest.items()):
                    print(f"    {k:30s} = {v}")
                
                # Extract key metrics
                put_oi = latest.get("put_oi", latest.get("put_open_interest"))
                call_oi = latest.get("call_oi", latest.get("call_open_interest"))
                put_oi_chg = latest.get("put_oi_change", latest.get("put_open_interest_change"))
                call_oi_chg = latest.get("call_oi_change", latest.get("call_open_interest_change"))
                
                print(f"\n  EXTRACTED:")
                print(f"    Put OI:         {put_oi}")
                print(f"    Call OI:        {call_oi}")
                print(f"    Put OI Change:  {put_oi_chg}")
                print(f"    Call OI Change: {call_oi_chg}")
                
                record("oi_change", PASS, f"put_oi={put_oi}, put_chg={put_oi_chg}")
            else:
                record("oi_change", WARN, "Empty data list")
        elif isinstance(data, dict):
            dump_raw(data)
            record("oi_change", PASS, "Dict response")
        else:
            record("oi_change", FAIL, "Unexpected format")
    else:
        record("oi_change", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 8: OI PER STRIKE
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 8: OI PER STRIKE — /api/stock/COIN/oi-per-strike")
    print("  Purpose: Put wall / call wall / GEX flip level detection")
    print("  Used by: Dealer layer, get_put_wall(), get_gex_data()")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/oi-per-strike")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  Total strikes: {len(data)}")
            if data:
                print(f"  Keys: {sorted(data[0].keys())}")
                # Find put wall and call wall
                max_put_oi, max_call_oi = 0, 0
                put_wall_strike, call_wall_strike = None, None
                for r in data:
                    if not isinstance(r, dict):
                        continue
                    s = float(r.get("strike", 0))
                    p = int(r.get("put_oi", r.get("put_open_interest", 0)))
                    c = int(r.get("call_oi", r.get("call_open_interest", 0)))
                    if p > max_put_oi:
                        max_put_oi = p
                        put_wall_strike = s
                    if c > max_call_oi:
                        max_call_oi = c
                        call_wall_strike = s
                
                print(f"\n  PUT WALL:  ${put_wall_strike} (OI: {max_put_oi:,})")
                print(f"  CALL WALL: ${call_wall_strike} (OI: {max_call_oi:,})")
                
                # Show top 5 by put OI
                sorted_by_put = sorted([r for r in data if isinstance(r, dict)],
                                       key=lambda r: int(r.get("put_oi", r.get("put_open_interest", 0))),
                                       reverse=True)
                print(f"\n  TOP 5 PUT OI STRIKES:")
                for r in sorted_by_put[:5]:
                    s = r.get("strike", "?")
                    p = r.get("put_oi", r.get("put_open_interest", "?"))
                    c = r.get("call_oi", r.get("call_open_interest", "?"))
                    print(f"    ${s}: put_oi={p:,}, call_oi={c:,}" if isinstance(p, int) else f"    ${s}: put_oi={p}, call_oi={c}")
                
                record("oi_per_strike", PASS, f"{len(data)} strikes, put_wall=${put_wall_strike}")
            else:
                record("oi_per_strike", WARN, "Empty")
        else:
            dump_raw(raw)
            record("oi_per_strike", WARN, "Non-list format")
    else:
        record("oi_per_strike", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 9: OI PER EXPIRY
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 9: OI PER EXPIRY — /api/stock/COIN/oi-per-expiry")
    print("  Purpose: Expiration-level OI concentration")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/oi-per-expiry")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            dump_raw(data, max_items=3)
            record("oi_per_expiry", PASS, f"{len(data)} expiries")
        else:
            dump_raw(raw)
            record("oi_per_expiry", WARN, "Non-list format")
    else:
        record("oi_per_expiry", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 10: OPTIONS VOLUME
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 10: OPTIONS VOLUME — /api/stock/COIN/options-volume")
    print("  Purpose: Put/call volume data")
    print("  Used by: Acceleration layer")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/options-volume")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list) and data:
            print(f"  Records: {len(data)}")
            latest = data[-1] if isinstance(data[-1], dict) else data[0]
            print(f"  Latest keys: {sorted(latest.keys())}")
            for k, v in sorted(latest.items()):
                print(f"    {k}: {v}")
            record("options_volume", PASS, f"{len(data)} records")
        else:
            dump_raw(raw)
            record("options_volume", WARN, "Unexpected format")
    else:
        record("options_volume", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 11: IV RANK
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 11: IV RANK — /api/stock/COIN/iv-rank")
    print("  Purpose: Current IV vs 1-year range")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/iv-rank")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list) and data:
            latest = data[-1] if isinstance(data[-1], dict) else data[0]
            print(f"  Latest keys: {sorted(latest.keys())}")
            for k, v in sorted(latest.items()):
                print(f"    {k}: {v}")
            record("iv_rank", PASS, f"{len(data)} records")
        else:
            dump_raw(raw)
            record("iv_rank", PASS if raw else FAIL, "dict response")
    else:
        record("iv_rank", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 12: SKEW (Risk Reversal)
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 12: SKEW — /api/stock/COIN/historical-risk-reversal-skew")
    print("  Purpose: Put/call skew — bearish if negative")
    print("  Used by: Distribution layer (skew detection)")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/historical-risk-reversal-skew")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  Records: {len(data)}")
            if len(data) >= 2:
                sorted_data = sorted(data, key=lambda r: r.get("date", ""))
                latest = sorted_data[-1]
                prior = sorted_data[-2]
                print(f"  Latest: {latest}")
                print(f"  Prior:  {prior}")
                rr = float(latest.get("risk_reversal", 0))
                rr_prior = float(prior.get("risk_reversal", 0))
                print(f"\n  Risk Reversal:  {rr:.4f}")
                print(f"  Prior:          {rr_prior:.4f}")
                print(f"  Change:         {rr - rr_prior:+.4f}")
                print(f"  Interpretation: {'BEARISH (puts expensive)' if rr < 0 else 'BULLISH (calls expensive)' if rr > 0.05 else 'NEUTRAL'}")
                record("skew", PASS, f"RR={rr:.4f}, change={rr-rr_prior:+.4f}")
            else:
                record("skew", WARN, f"Only {len(data)} records (need 2+)")
        else:
            dump_raw(raw)
            record("skew", WARN, "Non-list format")
        
        # Test parsed
        subsection("PARSED SKEW (via get_skew)")
        parsed_skew = await uw.get_skew(SYMBOL)
        if parsed_skew:
            print(f"    Parsed result:")
            for k, v in sorted(parsed_skew.items()):
                if k != "data":
                    print(f"      {k}: {v}")
    else:
        record("skew", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 13: IV TERM STRUCTURE
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 13: IV TERM STRUCTURE — /api/stock/COIN/volatility/term-structure")
    print("  Purpose: 7d/30d/60d IV for inversion detection")
    print("  Used by: EWS (IV inversion = bearish), Weather engine")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/volatility/term-structure")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  Per-expiry records: {len(data)}")
            print(f"\n  ALL EXPIRY DATA:")
            if data:
                print(f"  Keys: {sorted(data[0].keys())}")
                for r in data[:15]:
                    dte = r.get("dte", "?")
                    vol = r.get("volatility", r.get("iv", "?"))
                    expiry = r.get("expiry", r.get("expiration", "?"))
                    print(f"    DTE={str(dte):4s}  IV={vol}  Expiry={expiry}")
            
            # Compute buckets manually
            dte_vol = {}
            for row in data:
                dte = row.get("dte")
                vol = row.get("volatility")
                if dte is not None and vol is not None and int(dte) > 0:
                    dte_vol[int(dte)] = float(vol)
            
            if dte_vol:
                def closest(target):
                    ck = min(dte_vol.keys(), key=lambda d: abs(d - target))
                    return ck, dte_vol[ck]
                
                d7, v7 = closest(7)
                d30, v30 = closest(30)
                d60, v60 = closest(60)
                
                print(f"\n  COMPUTED BUCKETS:")
                print(f"    7-day:   DTE={d7} → IV={v7*100:.1f}%")
                print(f"    30-day:  DTE={d30} → IV={v30*100:.1f}%")
                print(f"    60-day:  DTE={d60} → IV={v60*100:.1f}%")
                
                inverted = v7 > v60 if v7 > 0 and v60 > 0 else False
                print(f"\n  INVERTED?  {inverted} {'⚠️ BEARISH — near-term IV > far-term' if inverted else '✅ Normal contango'}")
                print(f"  Slope:     {(v60 - v7) / max(1, 60-7):.6f}")
                
                record("iv_term_structure", PASS, f"7d={v7*100:.1f}%, 30d={v30*100:.1f}%, 60d={v60*100:.1f}%, inverted={inverted}")
            else:
                record("iv_term_structure", WARN, "No DTE/volatility pairs found")
        else:
            dump_raw(raw)
            record("iv_term_structure", WARN, "Non-list format")
        
        # Test parsed
        subsection("PARSED IV TERM STRUCTURE (via get_iv_term_structure)")
        parsed_iv = await uw.get_iv_term_structure(SYMBOL)
        if parsed_iv:
            for k, v in sorted(parsed_iv.items()):
                if k != "data":
                    print(f"    {k}: {v}")
    else:
        record("iv_term_structure", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 14: IV SURFACE (alternative endpoint)
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 14: IV SURFACE — /api/stock/COIN/volatility/term-structure")
    print("  Purpose: Same endpoint as #13, via get_iv_surface()")
    
    raw = await uw.get_iv_surface(SYMBOL)
    api_calls_made += 1
    
    if raw:
        print(f"  Response type: {type(raw).__name__}")
        if isinstance(raw, dict):
            print(f"  Keys: {sorted(raw.keys())}")
        record("iv_surface", PASS, "Returns data")
    else:
        record("iv_surface", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 15: MAX PAIN
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 15: MAX PAIN — /api/stock/COIN/max-pain")
    print("  Purpose: Price magnet for options expiration")
    print("  Used by: Market Direction engine")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/max-pain")
    api_calls_made += 1
    
    if raw:
        dump_raw(raw)
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list) and data:
            mp = data[0] if isinstance(data[0], dict) else {}
            mp_val = mp.get("price", mp.get("max_pain", mp.get("strike")))
            print(f"\n  Max Pain: ${float(mp_val):.2f}" if mp_val else "\n  Max Pain: NOT FOUND")
            record("max_pain", PASS if mp_val else WARN, f"max_pain={mp_val}")
        elif isinstance(data, dict):
            mp_val = data.get("price", data.get("max_pain"))
            print(f"\n  Max Pain: ${float(mp_val):.2f}" if mp_val else "\n  Max Pain: NOT FOUND")
            record("max_pain", PASS if mp_val else WARN, f"max_pain={mp_val}")
        else:
            record("max_pain", WARN, "Unexpected format")
    else:
        record("max_pain", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 16: PUT WALL
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 16: PUT WALL — via get_put_wall()")
    print("  Purpose: Highest put OI = dealer support level")
    print("  Used by: Dealer layer")
    
    pw = await uw.get_put_wall(SYMBOL)
    print(f"  Put Wall: ${pw}" if pw else "  Put Wall: None")
    record("put_wall", PASS if pw else WARN, f"${pw}" if pw else "None")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 17: INSIDER TRADES
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 17: INSIDER TRADES — /api/insider/COIN")
    print("  Purpose: Corporate insider selling detection")
    print("  Used by: Distribution layer (insider component)")
    
    raw = await uw._request(f"/api/insider/{SYMBOL}", {"limit": 10})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"\n  RAW Records: {len(data)}")
            if data:
                print(f"  Keys: {sorted(data[0].keys())}")
                for i, r in enumerate(data[:3]):
                    print(f"\n  [{i}] Raw insider record:")
                    for k, v in sorted(r.items()):
                        print(f"      {k:25s} = {str(v)[:80]}")
                
                # Check if this is person-level or trade-level
                has_transaction = any(r.get("transaction_type") or r.get("transaction_code") for r in data)
                has_value = any(r.get("value") or r.get("amount") for r in data)
                has_filing = any(r.get("filing_date") for r in data)
                has_name = any(r.get("display_name") or r.get("name") for r in data)
                has_is_person = any("is_person" in r for r in data)
                
                print(f"\n  DATA LEVEL CHECK:")
                print(f"    Has transaction_type:  {has_transaction}")
                print(f"    Has value/amount:      {has_value}")
                print(f"    Has filing_date:       {has_filing}")
                print(f"    Has display_name/name: {has_name}")
                print(f"    Has is_person:         {has_is_person}")
                
                if has_is_person and not has_transaction:
                    print(f"\n  ⚠️  PERSON-LEVEL DATA (not trades)")
                    print(f"      Cannot detect actual insider SALES from this endpoint")
        
        # Test parsed
        subsection("PARSED INSIDER (via get_insider_trades)")
        parsed = await uw.get_insider_trades(SYMBOL)
        print(f"    Parsed: {len(parsed)} records")
        for t in parsed[:3]:
            print(f"      {t}")
        
        record("insider_trades", WARN if not has_transaction else PASS, 
               f"{len(data)} records, person_level={'yes' if has_is_person and not has_transaction else 'no'}")
    else:
        record("insider_trades", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 18: CONGRESS TRADES
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 18: CONGRESS TRADES — /api/congress/recent-trades")
    print("  Purpose: Congressional trading activity")
    print("  Used by: Distribution layer (congress component)")
    
    raw = await uw._request("/api/congress/recent-trades", {"limit": 5})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            if data:
                print(f"  Keys: {sorted(data[0].keys())}")
                dump_raw(data, max_items=2)
            record("congress_trades", PASS, f"{len(data)} records")
        else:
            dump_raw(raw)
            record("congress_trades", WARN, "Non-list format")
    else:
        record("congress_trades", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 19: EARNINGS CALENDAR
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 19: EARNINGS CALENDAR — /api/earnings/calendar")
    print("  Purpose: Upcoming earnings dates")
    print("  Used by: Earnings Priority Scanner, Distribution (proximity)")
    
    raw = await uw._request("/api/earnings/calendar", {"limit": 5})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list) and data:
            print(f"  Records: {len(data)}")
            dump_raw(data, max_items=2)
            record("earnings_calendar", PASS, f"{len(data)} records")
        else:
            print(f"  ⚠️  RAW RESPONSE (may be error):")
            dump_raw(raw)
            record("earnings_calendar", WARN, "May be 422 error")
    else:
        print("  ❌ EMPTY RESPONSE (known 422 issue)")
        
        # Test fallback
        subsection("FALLBACK: get_earnings_calendar with tickers=[COIN]")
        parsed = await uw.get_earnings_calendar(tickers=[SYMBOL])
        if parsed:
            print(f"    Fallback returned: {len(parsed)} records")
            for r in parsed:
                print(f"      {r}")
            record("earnings_calendar", WARN, f"Primary failed, fallback={len(parsed)} records")
        else:
            record("earnings_calendar", FAIL, "Both primary and fallback failed")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 20: MARKET TIDE
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 20: MARKET TIDE — /api/market/market-tide")
    print("  Purpose: Broad market flow sentiment")
    print("  Used by: Market Direction engine, Weather engine")
    
    raw = await uw._request("/api/market/market-tide")
    api_calls_made += 1
    
    if raw:
        dump_raw(raw)
        record("market_tide", PASS, "Returns data")
    else:
        record("market_tide", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 21: MARKET SPIKE
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 21: MARKET SPIKE — /api/market/spike")
    print("  Purpose: Unusual market-wide activity spikes")
    
    raw = await uw._request("/api/market/spike")
    api_calls_made += 1
    
    if raw:
        dump_raw(raw)
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        is_empty = (isinstance(data, list) and len(data) == 0)
        record("market_spike", PASS if not is_empty else NA, f"Empty during non-spike periods is normal")
    else:
        record("market_spike", NA, "Empty — normal for non-spike periods")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 22: SECTOR TIDE
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 22: SECTOR TIDE — /api/market/Technology/sector-tide")
    print("  Purpose: Sector-specific flow (COIN = Technology/Crypto)")
    
    raw = await uw._request("/api/market/Technology/sector-tide")
    api_calls_made += 1
    
    if raw:
        dump_raw(raw)
        record("sector_tide", PASS, "Returns data")
    else:
        record("sector_tide", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 23: EXPIRY BREAKDOWN
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 23: EXPIRY BREAKDOWN — /api/stock/COIN/expiry-breakdown")
    print("  Purpose: Volume/OI breakdown by expiration date")
    
    raw = await uw._request(f"/api/stock/{SYMBOL}/expiry-breakdown")
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            dump_raw(data, max_items=3)
            record("expiry_breakdown", PASS, f"{len(data)} expiries")
        else:
            dump_raw(raw)
            record("expiry_breakdown", WARN, "Non-list")
    else:
        record("expiry_breakdown", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 24: GLOBAL FLOW ALERTS
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 24: GLOBAL FLOW ALERTS — /api/option-trades/flow-alerts")
    print("  Purpose: Market-wide sweeps, blocks, unusual activity")
    print("  Used by: Market Direction engine")
    
    raw = await uw._request("/api/option-trades/flow-alerts", {"limit": 5})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            if data:
                print(f"  Keys: {sorted(data[0].keys())}")
                # Check for COIN in alerts
                coin_alerts = [r for r in data if r.get("ticker", "") == SYMBOL]
                print(f"  COIN alerts in this batch: {len(coin_alerts)}")
            dump_raw(data, max_items=2)
            record("global_flow_alerts", PASS, f"{len(data)} alerts")
        else:
            dump_raw(raw)
            record("global_flow_alerts", WARN, "Non-list")
    else:
        record("global_flow_alerts", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # TEST 25: DARK POOL RECENT (global)
    # ══════════════════════════════════════════════════════════════════════
    section("TEST 25: DARK POOL RECENT (global) — /api/darkpool/recent")
    print("  Purpose: Market-wide dark pool prints")
    
    raw = await uw._request("/api/darkpool/recent", {"limit": 5})
    api_calls_made += 1
    
    if raw:
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            print(f"  Records: {len(data)}")
            if data:
                print(f"  Keys: {sorted(data[0].keys())}")
            dump_raw(data, max_items=2)
            record("darkpool_recent", PASS, f"{len(data)} records")
        else:
            dump_raw(raw)
            record("darkpool_recent", WARN, "Non-list")
    else:
        record("darkpool_recent", FAIL, "Empty response")
    
    # ══════════════════════════════════════════════════════════════════════
    # BONUS: RAW ENDPOINT EXPLORATION — Undiscovered endpoints
    # ══════════════════════════════════════════════════════════════════════
    section("BONUS: EXPLORATORY ENDPOINT TESTS")
    
    bonus_endpoints = [
        (f"/api/stock/{SYMBOL}/quote", "Quote"),
        (f"/api/stock/{SYMBOL}/historical-iv", "Historical IV"),
        (f"/api/stock/{SYMBOL}/net-prem-ticks", "Net Premium Ticks"),
        (f"/api/stock/{SYMBOL}/sector-etf-exposure", "Sector ETF Exposure"),
        (f"/api/stock/{SYMBOL}/option-chains", "Option Chains"),
        (f"/api/insider/{SYMBOL}/transactions", "Insider Transactions"),
        (f"/api/market/overview", "Market Overview"),
    ]
    
    for ep, name in bonus_endpoints:
        raw = await uw._request(ep)
        api_calls_made += 1
        status = "✅" if raw else "❌"
        if raw:
            data = raw.get("data", raw) if isinstance(raw, dict) else raw
            if isinstance(data, list):
                desc = f"list[{len(data)}]"
            elif isinstance(data, dict):
                desc = f"dict{{{', '.join(list(data.keys())[:5])}}}"
            else:
                desc = str(type(data).__name__)
        else:
            desc = "EMPTY"
        print(f"  {status} {ep:55s} → {desc}")
        record(f"bonus_{name}", PASS if raw else FAIL, desc)
    
    # ══════════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  AUDIT SUMMARY")
    print("=" * 80)
    
    print(f"\n  Total API calls made: {api_calls_made}")
    print(f"  Remaining UW calls:  {uw.remaining_calls}")
    
    passes = [r for r in results_summary if PASS in r[1]]
    warns = [r for r in results_summary if WARN in r[1]]
    fails = [r for r in results_summary if FAIL in r[1]]
    nas = [r for r in results_summary if NA in r[1]]
    
    print(f"\n  {PASS}: {len(passes)}")
    print(f"  {WARN}: {len(warns)}")
    print(f"  {FAIL}: {len(fails)}")
    print(f"  {NA}: {len(nas)}")
    
    print(f"\n  {'Endpoint':30s} {'Status':10s} {'Details'}")
    print(f"  {'─'*75}")
    for ep, status, details in results_summary:
        print(f"  {ep:30s} {status:10s} {details[:50]}")
    
    await uw.close()
    
    print(f"\n{'='*80}")
    print(f"  END OF AUDIT")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(main())
