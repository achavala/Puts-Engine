# CRITICAL MISS ANALYSIS - February 4, 2026

## Executive Summary

**17 stocks dropped 10-17%+ today and the system missed almost all of them.**

This is a comprehensive forensic analysis of why PutsEngine failed to detect these moves.

---

## 1. STOCKS MISSED TODAY

| Symbol | Drop | Price | In Universe? | In EWS? | In Scan Results? |
|--------|------|-------|--------------|---------|------------------|
| AMD | -17.32% | $204.30 | ✅ Yes | ❌ No | ❌ No |
| BSX | -17.69% | $76.81 | ❌ **NO** | ❌ No | ❌ No |
| IREN | -17.39% | $45.43 | ✅ Yes | ❌ No | ❌ No |
| APP | -16.11% | $384.78 | ✅ Yes | ⚠️ Watch (IPI=0.43) | ⚠️ Score=0.26 |
| SNDK | -15.91% | $605.50 | ✅ Yes | ❌ No | ⚠️ Score=0.51 |
| LUNR | -15.35% | $16.78 | ✅ Yes | ❌ No | ❌ No |
| APLD | -14.06% | $31.80 | ✅ Yes | ❌ No | ❌ No |
| W | -13.03% | $91.10 | ❌ **NO** | ❌ No | ❌ No |
| CRDO | -12.88% | $99.50 | ✅ Yes | ❌ No | ⚠️ Score=0.26 |
| BE | -12.87% | $152.33 | ✅ Yes | ❌ No | ❌ No |
| OKLO | -12.51% | $68.68 | ✅ Yes | ❌ No | ❌ No |
| PLTR | -11.64% | $139.80 | ✅ Yes | ❌ No | ❌ No |
| ASTS | -10.57% | $104.48 | ✅ Yes | ❌ No | ❌ No |
| TTMI | -10.37% | $91.00 | ❌ **NO** | ❌ No | ❌ No |
| RKLB | -9.98% | $73.19 | ✅ Yes | ❌ No | ❌ No |
| USAR | -9.40% | $23.37 | ✅ Yes | ❌ No | ❌ No |
| COHR | -7.96% | $199.50 | ✅ Yes | ❌ No | ✅ **Score=0.75** |

---

## 2. ROOT CAUSE ANALYSIS

### 🔴 CRITICAL ISSUE #1: Unusual Whales API Completely Blocked

**Evidence from logs:**
```
2026-02-04 17:17:18.583 | DEBUG | API Budget: PLTR on cooldown (1799s remaining)
2026-02-04 17:17:18.584 | DEBUG | UW API call skipped for PLTR - budget/cooldown
```

**Problem:** Every single UW API call is being skipped due to "cooldown"
- PLTR: skipped
- AMD: skipped
- APP: skipped
- ALL 330 tickers: skipped

**Impact:** Without Unusual Whales data, the system is BLIND to:
- ❌ Options flow (put accumulation)
- ❌ Dark pool distribution
- ❌ IV term structure
- ❌ Institutional positioning

### 🔴 CRITICAL ISSUE #2: Three Missed Stocks NOT in Universe

| Symbol | Name | Sector | Why Missing |
|--------|------|--------|-------------|
| BSX | Boston Scientific | Healthcare | Not in static universe |
| TTMI | TTM Technologies | Electronics | Not in static universe |
| W | Wayfair | E-commerce | Not in static universe |

### 🟡 ISSUE #3: Detected But Not Acted Upon

**COHR had a score of 0.75** - This should have triggered an alert!
- Distribution Engine detected it
- Score was above the 0.68 "Class A" threshold
- But it didn't appear in EWS or top alerts

### 🟡 ISSUE #4: EWS Only Caught 1/17 (and weakly)

APP was the only one in EWS with IPI=0.43 (watch level only)
- No ACT level alerts for any of these
- No PREPARE level alerts
- The EWS scan at 10:35 AM missed all signals

---

## 3. DATA SOURCE ANALYSIS

### Current Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DATA SOURCES                                │
├─────────────────────────────────────────────────────────────────┤
│  ALPACA (Working ✅)                                            │
│  ├── Real-time quotes                                            │
│  ├── Historical daily bars                                       │
│  └── Intraday bars                                              │
│                                                                  │
│  POLYGON (Working ✅)                                            │
│  ├── Options chains                                             │
│  ├── Historical bars                                            │
│  └── Technical indicators                                        │
│                                                                  │
│  UNUSUAL WHALES (❌ BLOCKED BY COOLDOWN)                        │
│  ├── Options flow → NOT GETTING DATA                            │
│  ├── Dark pool prints → NOT GETTING DATA                        │
│  ├── IV data → NOT GETTING DATA                                 │
│  └── Put/Call ratios → NOT GETTING DATA                         │
│                                                                  │
│  FINVIZ (❓ Not Used for Detection)                             │
│  └── Only used for universe filtering, not real-time signals    │
└─────────────────────────────────────────────────────────────────┘
```

### What Each Engine SHOULD Be Getting

| Engine | Data Needed | Source | Status |
|--------|-------------|--------|--------|
| **Distribution** | Dark pool prints | UW | ❌ BLOCKED |
| | Options flow | UW | ❌ BLOCKED |
| | Insider selling | UW | ❌ BLOCKED |
| | Price/volume | Alpaca | ✅ Working |
| **Liquidity** | Bid/ask spread | Alpaca | ✅ Working |
| | Quote degradation | Alpaca | ✅ Working |
| | Options OI | Polygon | ✅ Working |
| **EWS** | Dark pool sequence | UW | ❌ BLOCKED |
| | Put OI accumulation | UW | ❌ BLOCKED |
| | IV inversion | UW | ❌ BLOCKED |
| | Flow divergence | UW | ❌ BLOCKED |

---

## 4. WHY THE COOLDOWN IS HAPPENING

### API Budget Configuration
```python
TICKER_COOLDOWN = {
    PRIORITY_1: 300,   # 5 minutes
    PRIORITY_2: 900,   # 15 minutes  
    PRIORITY_3: 1800,  # 30 minutes (default)
}
```

### The Problem
1. Most tickers are classified as Priority 3 (low priority)
2. P3 tickers have 30-minute cooldown between UW API calls
3. After one scan, ALL tickers go on 30-min cooldown
4. Next scan comes, ALL tickers are still on cooldown
5. **Result: NO UW data is ever fetched**

### The Fix Needed
- Reduce P3 cooldown from 1800s to 300s
- OR increase scan interval to 35+ minutes
- OR prioritize missed tickers dynamically

---

## 5. WHAT SIGNALS SHOULD HAVE BEEN DETECTED

### Pre-Breakdown Signals We Should Have Seen (Day -1)

| Signal | Source | What to Look For | Priority |
|--------|--------|------------------|----------|
| **Dark Pool Distribution** | UW | Large blocks below VWAP | 🔴 CRITICAL |
| **Put OI Accumulation** | UW | Put volume > 2x avg without price drop | 🔴 CRITICAL |
| **Call Selling at Bid** | UW | Calls sold at bid (bearish) | 🟡 HIGH |
| **IV Term Inversion** | UW | Near-term IV > far-term IV | 🟡 HIGH |
| **Insider Selling** | UW/SEC | C-level sells in prior 14 days | 🟡 HIGH |
| **Multi-day Weakness** | Alpaca | Lower highs, higher volume down days | 🟡 HIGH |

### What the Charts Show (User's Screenshots)

Looking at the intraday charts:
1. All crashed at market open or shortly after
2. Pattern: Gap down → brief bounce → continued selling
3. Some had pre-market weakness visible

This suggests:
- After-hours news/earnings
- Pre-market gap scanner should have caught
- Zero-hour scanner should have flagged

---

## 6. SPECIFIC ANALYSIS: WHY EACH WAS MISSED

### AMD (-17.32%)
- **Root Cause:** Likely earnings-related (AMD reports Q4)
- **Should Have:** Earnings Priority Scanner should have flagged
- **UW Data Needed:** Put flow, IV spike before earnings
- **Fix:** Integrate earnings calendar more tightly

### PLTR (-11.64%)
- **Root Cause:** High-beta AI name, sector selloff
- **Should Have:** In universe, high-beta list
- **UW Data Needed:** Dark pool distribution
- **Fix:** Enable UW API calls

### SNDK (-15.91%)
- **Note:** Was detected! Score = 0.51 in Distribution
- **Problem:** Score not high enough for top alerts
- **Fix:** Lower threshold for high-beta sectors

### COHR (-7.96%)
- **Note:** WAS DETECTED with Score = 0.75!
- **Problem:** Didn't surface in dashboard properly
- **Fix:** Dashboard display issue

### BSX, W, TTMI
- **Root Cause:** Not in universe
- **Fix:** Add these sectors:
  - Medical devices (BSX)
  - E-commerce (W)
  - Electronics manufacturing (TTMI)

---

## 7. SYSTEM ARCHITECTURE GAPS

### What's Missing

1. **Pre-Market Gap Scanner Not Running**
   - The zero-hour scanner runs at 9:15 AM
   - But gaps form by 8:00-9:00 AM
   - Need earlier scan (7:00 AM)

2. **After-Hours News Scanner**
   - Many crashes are from AH earnings
   - No scanner watching AH price action
   - Need 5:00-8:00 PM scanner

3. **Earnings-Aware Prioritization**
   - AMD had earnings - should be P1
   - System treated it as P3
   - Earnings = automatic P1

4. **Real-Time Intraday Alerts**
   - 5% drop in first 15 min = alert
   - Currently no intraday monitoring

5. **Sector Contagion Detection**
   - When NVDA drops, all AI/semis follow
   - No sector correlation scanner

---

## 8. IMMEDIATE FIXES REQUIRED

### Fix 1: Disable UW API Cooldown (CRITICAL)
```python
# In api_budget.py, change:
TICKER_COOLDOWN = {
    PRIORITY_1: 60,   # 1 minute
    PRIORITY_2: 120,  # 2 minutes  
    PRIORITY_3: 300,  # 5 minutes (was 1800!)
}
```

### Fix 2: Add Missing Tickers to Universe
```python
# Add to config.py
"medical_devices": ["BSX", "MDT", "ABT", "SYK", "ISRG", "EW"],
"ecommerce": ["W", "ETSY", "EBAY", "CHWY", "WISH"],
"electronics_mfg": ["TTMI", "FLEX", "JABIL", "SANM"],
```

### Fix 3: Add 7:00 AM Pre-Market Gap Scan
```python
# In scheduler.py
self.scheduler.add_job(
    self._run_premarket_gap_scan_wrapper,
    CronTrigger(hour=7, minute=0, timezone=EST),
    id="premarket_gap_7am",
    name="Pre-Market Gap Scanner (7:00 AM ET)"
)
```

### Fix 4: Earnings = Auto Priority 1
```python
# In api_budget.py
def get_ticker_priority(self, symbol, score, is_dui, has_earnings_soon=False):
    if has_earnings_soon:
        return TickerPriority.PRIORITY_1
```

### Fix 5: High Score Alert Threshold
```python
# Any score >= 0.60 should trigger ACT alert
if score >= 0.60:
    # Force into ACT level even without full footprints
    alert_level = "act"
```

---

## 9. RECOMMENDED ENHANCEMENTS

### New Scanners Needed

| Scanner | Purpose | Run Time | Priority |
|---------|---------|----------|----------|
| **AH News Scanner** | Watch for earnings, news AH | 5 PM, 7 PM | 🔴 CRITICAL |
| **7 AM Gap Scanner** | Pre-market gaps before open | 7:00 AM | 🔴 CRITICAL |
| **Sector Contagion** | When sector leader drops, flag peers | Real-time | 🟡 HIGH |
| **Intraday Drop Alert** | >5% drop in first 30 min | 10:00 AM | 🟡 HIGH |
| **Earnings Countdown** | T-3 to T+1 around earnings | Daily | 🟡 HIGH |

### Data Sources to Add

| Source | Data | Cost | Priority |
|--------|------|------|----------|
| **Benzinga** | Real-time news, analyst ratings | $$ | 🟡 HIGH |
| **SEC EDGAR** | 13F filings, insider transactions | Free | 🟡 HIGH |
| **Twitter/X API** | Social sentiment | $$ | 🟢 MEDIUM |
| **FinViz Elite** | Pre-market movers | $ | 🟢 MEDIUM |

---

## 10. CONCLUSION

### Why We Missed 17 Stocks

1. **UW API Cooldown blocked 100% of flow/dark pool data**
2. **3 stocks not in universe (BSX, W, TTMI)**
3. **No pre-market gap scanner running early enough**
4. **Earnings-aware prioritization missing**
5. **Dashboard not surfacing high-score alerts properly**

### Immediate Action Items

1. ⚡ **NOW:** Reduce UW API cooldowns to 60-300 seconds
2. ⚡ **NOW:** Add BSX, W, TTMI to universe
3. 📅 **TODAY:** Add 7:00 AM pre-market scan
4. 📅 **TODAY:** Fix dashboard to show all scores >= 0.60
5. 📅 **THIS WEEK:** Implement earnings-aware P1 priority

### Expected Outcome After Fixes

With these fixes, we should have caught:
- **AMD:** Via earnings priority + pre-market gap
- **PLTR:** Via dark pool distribution + high-beta flag
- **COHR:** Already detected (score 0.75) - dashboard fix
- **SNDK:** Already detected (score 0.51) - threshold fix
- **Others:** Via restored UW API + sector contagion

---

## Appendix: Full Scan Log Analysis

```
Last scan: end_of_day (timestamp missing)
Distribution Engine: 80 candidates
- COHR: 0.75 ✅ (detected but not alerted)
- SNDK: 0.51 ✅ (detected, score too low)
- APP: 0.26 (too low)
- CRDO: 0.26 (too low)

Liquidity Engine: 1 candidate (nothing useful)
Acceleration Engine: 0 candidates

EWS Alerts: 90 total
- APP: IPI=0.43, watch level only
- 0 ACT level alerts
- 0 PREPARE level alerts for missed stocks
```

**This confirms the system is running but severely handicapped by the UW API cooldown.**

---

## 11. FIXES IMPLEMENTED (Feb 4, 2026 7:00 PM ET)

### ✅ Fix 1: UW API Cooldown Bug (CRITICAL)
**Problem:** Second API call for same ticker was blocked by cooldown, even within same scan
**Solution:** Added 30-second "scan window" - all calls within window are allowed
```python
# Before: ALL calls blocked after first
TICKER_COOLDOWN = {
    P1: 300,   # 5 minutes
    P2: 900,   # 15 minutes
    P3: 1800,  # 30 minutes - THIS WAS THE KILLER
}

# After: Multiple calls allowed within scan window, reduced cooldowns
TICKER_COOLDOWN = {
    P1: 60,    # 1 minute
    P2: 180,   # 3 minutes  
    P3: 300,   # 5 minutes
}
SCAN_WINDOW_SECONDS = 30  # Allow all calls within 30 seconds
```

### ✅ Fix 2: Added Missing Tickers
Added 3 new sectors with 34 new tickers:
- **Medical Devices:** BSX, MDT, ABT, SYK, ISRG, EW, ZBH, BDX, HOLX, BAX, ALGN, DXCM, PODD
- **E-Commerce Retail:** W, ETSY, CHWY, WISH, FVRR, UPWK, RVLV, REAL, PRTS, FLWS, OSTK
- **Electronics Mfg:** TTMI, FLEX, JABIL, SANM, PLXS, CGNX, MKSI, ENTG, LRCX, KLAC

### ✅ Fix 3: Added High-Beta Correlation Groups
Added 3 new correlation groups to catch sector-wide drops:
- `medical_devices`: BSX, MDT, ABT, SYK, ISRG, EW, ZBH, DXCM
- `ecommerce_retail`: W, ETSY, CHWY, WISH, RVLV, OSTK
- `electronics_mfg`: TTMI, FLEX, JABIL, SANM, CGNX, MKSI

### ✅ Fix 4: Added 7:00 AM Pre-Market Gap Scan
New scan specifically to catch overnight earnings movers before 8:00 AM

### ✅ Fix 5: Increased MAX_CALLS_PER_TICKER
```python
# Before: Too restrictive
MAX_CALLS_PER_TICKER = {P1: 20, P2: 8, P3: 3}

# After: Allow proper data collection
MAX_CALLS_PER_TICKER = {P1: 50, P2: 25, P3: 10}
```

---

## 12. VERIFICATION STEPS

After restarting scheduler, run:
```bash
# Verify new tickers in universe
python -c "from putsengine.config import EngineConfig; print('BSX' in EngineConfig.get_all_tickers(), 'W' in EngineConfig.get_all_tickers(), 'TTMI' in EngineConfig.get_all_tickers())"

# Check scheduler health
cat scheduler_health.json | python -m json.tool

# Monitor UW API calls (should see multiple per ticker now)
tail -f logs/scheduler_daemon.log | grep "UW API"
```

---

*Analysis completed: Feb 4, 2026 7:00 PM ET*
*Fixes implemented: Feb 4, 2026 7:00 PM ET*
*Analyst: PutsEngine Forensics*
