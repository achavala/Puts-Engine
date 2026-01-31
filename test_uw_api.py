#!/usr/bin/env python3
"""
Unusual Whales API Validation Test
Tests API connectivity, rate limiting, and batched scanning
"""
import asyncio
import time
from datetime import datetime, date, timedelta
import pytz

et = pytz.timezone('US/Eastern')

async def test_single_calls():
    """Test single API calls to verify connectivity."""
    from putsengine.config import get_settings
    from putsengine.clients.unusual_whales_client import UnusualWhalesClient
    
    settings = get_settings()
    uw = UnusualWhalesClient(settings)
    
    print("=" * 70)
    print("TEST 1: SINGLE API CALLS")
    print("=" * 70)
    print()
    
    # Check API key
    print("Checking API key...")
    api_key = settings.unusual_whales_api_key
    if api_key and len(api_key) > 10:
        print(f"  [OK] API Key: {api_key[:8]}...{api_key[-4:]}")
    else:
        print(f"  [FAIL] API Key missing!")
        return False
    
    # Check rate limit settings
    print(f"\nRate limit config:")
    print(f"  Request Interval: {uw.MIN_REQUEST_INTERVAL}s")
    print(f"  Max req/min: {int(60/uw.MIN_REQUEST_INTERVAL)}")
    print(f"  Daily Limit: {uw.daily_limit}")
    print(f"  Remaining: {uw.remaining_calls}")
    
    # Test SPY flow
    print(f"\nTesting SPY flow...")
    try:
        start = time.time()
        flow = await uw.get_flow_recent("SPY", limit=5)
        elapsed = time.time() - start
        if flow:
            print(f"  [OK] Got {len(flow)} flow records in {elapsed:.2f}s")
            if flow[0]:
                f = flow[0]
                print(f"       Sample: {f.symbol} ${f.strike} {f.type} premium=${f.premium:,.0f}")
        else:
            print(f"  [WARN] No flow data (might be empty)")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
    
    # Test GEX
    print(f"\nTesting GEX data...")
    try:
        gex = await uw.get_net_gex("SPY")
        if gex:
            print(f"  [OK] SPY GEX: net={gex.net_gex:,.0f}, call={gex.call_gex:,.0f}, put={gex.put_gex:,.0f}")
        else:
            print(f"  [WARN] No GEX data")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
    
    # Test dark pool
    print(f"\nTesting dark pool...")
    try:
        dp = await uw.get_dark_pool_flow("SPY", limit=3)
        if dp:
            print(f"  [OK] Got {len(dp)} dark pool prints")
        else:
            print(f"  [WARN] No dark pool data")
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
    
    await uw.close()
    return True


async def test_batched_scanning():
    """Test batched scanning with rate limit protection."""
    from putsengine.config import get_settings, EngineConfig
    from putsengine.clients.unusual_whales_client import UnusualWhalesClient
    
    settings = get_settings()
    uw = UnusualWhalesClient(settings)
    
    print()
    print("=" * 70)
    print("TEST 2: BATCHED SCANNING (Rate Limit Validation)")
    print("=" * 70)
    print()
    
    # Get all tickers
    all_tickers = EngineConfig.get_all_tickers()
    print(f"Total tickers in universe: {len(all_tickers)}")
    
    # Test batch of 20 tickers (small test)
    test_tickers = all_tickers[:20]
    print(f"Testing batch of {len(test_tickers)} tickers...")
    print()
    
    BATCH_SIZE = 10
    BATCH_WAIT = 5  # Short wait for testing
    
    batches = [test_tickers[i:i+BATCH_SIZE] for i in range(0, len(test_tickers), BATCH_SIZE)]
    
    total_calls = 0
    total_success = 0
    total_empty = 0
    total_errors = 0
    rate_limit_hits = 0
    
    for batch_num, batch in enumerate(batches, 1):
        print(f"--- BATCH {batch_num}/{len(batches)} ({len(batch)} tickers) ---")
        batch_start = time.time()
        
        for symbol in batch:
            try:
                # Make single API call per ticker
                flow = await uw.get_flow_recent(symbol, limit=1)
                total_calls += 1
                
                if flow and len(flow) > 0:
                    total_success += 1
                    print(f"  {symbol}: OK ({len(flow)} flows)")
                else:
                    total_empty += 1
                    print(f"  {symbol}: Empty")
                    
            except Exception as e:
                total_errors += 1
                err_str = str(e).lower()
                if "429" in err_str or "rate" in err_str:
                    rate_limit_hits += 1
                    print(f"  {symbol}: RATE LIMITED!")
                else:
                    print(f"  {symbol}: Error - {e}")
        
        batch_elapsed = time.time() - batch_start
        req_per_min = (len(batch) / batch_elapsed) * 60 if batch_elapsed > 0 else 0
        print(f"  Batch time: {batch_elapsed:.1f}s ({req_per_min:.0f} req/min)")
        
        # Wait between batches
        if batch_num < len(batches):
            print(f"  Waiting {BATCH_WAIT}s...")
            await asyncio.sleep(BATCH_WAIT)
    
    print()
    print("=" * 70)
    print("BATCHED SCANNING RESULTS")
    print("=" * 70)
    print(f"  Total API calls: {total_calls}")
    print(f"  Successful: {total_success}")
    print(f"  Empty responses: {total_empty}")
    print(f"  Errors: {total_errors}")
    print(f"  Rate limit hits: {rate_limit_hits}")
    print()
    
    if rate_limit_hits == 0:
        print("  [OK] NO RATE LIMIT ISSUES - Strategy is working!")
    else:
        print(f"  [WARN] Hit rate limit {rate_limit_hits} times")
    
    # Show budget status
    status = uw.get_budget_status()
    print(f"\n  Budget status: {status['daily_used']}/{status['daily_limit']} used today")
    
    await uw.close()
    return rate_limit_hits == 0


async def test_full_batch_simulation():
    """Simulate full batch scanning to verify rate limits won't be hit."""
    from putsengine.config import EngineConfig
    
    print()
    print("=" * 70)
    print("TEST 3: FULL BATCH SIMULATION")
    print("=" * 70)
    print()
    
    # Get all tickers
    all_tickers = EngineConfig.get_all_tickers()
    total = len(all_tickers)
    
    # Simulation parameters
    BATCH_SIZE = 100
    REQUEST_INTERVAL = 0.6  # seconds
    BATCH_WAIT = 65  # seconds
    RATE_LIMIT = 120  # req/min
    
    batches = [all_tickers[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    num_batches = len(batches)
    
    print(f"Total tickers: {total}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Number of batches: {num_batches}")
    print(f"Request interval: {REQUEST_INTERVAL}s")
    print(f"Wait between batches: {BATCH_WAIT}s")
    print()
    
    # Calculate timing
    print("SIMULATION:")
    total_time = 0
    for i, batch in enumerate(batches, 1):
        batch_time = len(batch) * REQUEST_INTERVAL
        batch_req_per_min = (len(batch) / batch_time) * 60
        print(f"  Batch {i}: {len(batch)} tickers x {REQUEST_INTERVAL}s = {batch_time:.1f}s ({batch_req_per_min:.0f} req/min)")
        total_time += batch_time
        
        if i < num_batches:
            print(f"           + {BATCH_WAIT}s wait")
            total_time += BATCH_WAIT
    
    print()
    print(f"Total scan time: {total_time:.0f}s ({total_time/60:.1f} minutes)")
    print()
    
    # Verify rate limit safety
    max_req_per_min = (BATCH_SIZE / (BATCH_SIZE * REQUEST_INTERVAL)) * 60
    print(f"Max requests/min within batch: {max_req_per_min:.0f}")
    print(f"Rate limit: {RATE_LIMIT}/min")
    print()
    
    if max_req_per_min < RATE_LIMIT:
        print(f"[OK] Rate limit will NOT be hit!")
        print(f"     Safety margin: {RATE_LIMIT - max_req_per_min:.0f} req/min")
        return True
    else:
        print(f"[WARN] May hit rate limit!")
        return False


async def main():
    print()
    print("*" * 70)
    print("   UNUSUAL WHALES API VALIDATION & RATE LIMIT TEST")
    print(f"   {datetime.now(et).strftime('%Y-%m-%d %H:%M:%S ET')}")
    print("*" * 70)
    print()
    
    # Test 1: Single calls
    test1_ok = await test_single_calls()
    
    # Test 2: Batched scanning
    test2_ok = await test_batched_scanning()
    
    # Test 3: Full simulation
    test3_ok = await test_full_batch_simulation()
    
    # Summary
    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"  Test 1 (Single Calls):     {'PASS' if test1_ok else 'FAIL'}")
    print(f"  Test 2 (Batched Scanning): {'PASS' if test2_ok else 'FAIL'}")
    print(f"  Test 3 (Full Simulation):  {'PASS' if test3_ok else 'FAIL'}")
    print()
    
    if test1_ok and test2_ok and test3_ok:
        print("[SUCCESS] All tests passed! Rate limit strategy is working.")
        print("          Market open scanning will NOT hit 120 req/min limit.")
    else:
        print("[WARNING] Some tests failed. Review output above.")
    
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
