# 🏛️ PUTSENGINE DATA SOURCE & UPDATE ANALYSIS
**Generated:** February 3, 2026  
**Analysis Type:** Institutional Data Flow Audit

---

## 📊 EXECUTIVE SUMMARY

Your system is running, but **updates appear stale** because:
1. **Market is CLOSED** (Sunday/after-hours) - most scans only run during market hours
2. **Scheduler is UNRESPONSIVE** - Running but not executing scheduled jobs properly
3. **Last actual scan:** 11:19 PM on Feb 2 (dashboard refresh, not scheduled scan)

---

## 🗂️ TAB-BY-TAB DATA SOURCE ANALYSIS

### 1️⃣ GAMMA DRAIN ENGINE TAB

| Component | Data Source | Endpoint | Update Frequency |
|-----------|-------------|----------|------------------|
| **Price Data** | Alpaca | `get_latest_quote()` | Real-time when scanned |
| **Volume Analysis** | Polygon | `get_minute_bars()` | 15-min delayed (your plan) |
| **Options Flow** | Unusual Whales | `get_flow_recent()` | ~15 min delay |
| **GEX/DEX Data** | Unusual Whales | `get_market_tide()` | ~15 min delay |

**Decision Logic:**
```
Score = (Net GEX ≤ neutral × 0.20) + (Put OI > Call OI × 0.15) + 
        (VWAP Loss × 0.15) + (High RVOL × 0.15) + (Catalyst × 0.10)
```

**Data File:** `scheduled_scan_results.json` → `gamma_drain[]`

**Last Updated:** 2026-02-02 23:19:42 (dashboard refresh)

---

### 2️⃣ DISTRIBUTION ENGINE TAB

| Component | Data Source | Endpoint | Update Frequency |
|-----------|-------------|----------|------------------|
| **Price/Volume** | Polygon | `get_daily_bars()`, `get_minute_bars()` | 15-min delayed |
| **Dark Pool** | Unusual Whales | `get_dark_pool_flow()` | ~15 min delay |
| **Insider Trades** | FinViz | Scraping | ~1 hour delay |
| **Options Activity** | Unusual Whales | `get_flow_recent()` | ~15 min delay |
| **Congress Trades** | Unusual Whales | `get_congress_trades()` | Daily |

**Decision Logic:**
```
Score = (PRE_BREAKDOWN signals × 1.5) + (POST_BREAKDOWN signals × 1.0)

PRE_BREAKDOWN (predictive): dark_pool_surge, put_oi_accumulation, multi_day_distribution
POST_BREAKDOWN (reactive): high_rvol_red_day, pump_reversal, exhaustion
```

**Data File:** `scheduled_scan_results.json` → `distribution[]`

**Last Updated:** 2026-02-02 23:19:42

---

### 3️⃣ LIQUIDITY ENGINE TAB

| Component | Data Source | Endpoint | Update Frequency |
|-----------|-------------|----------|------------------|
| **Quote Data** | Alpaca | `get_latest_quote()` | Real-time |
| **Bid/Ask Spread** | Alpaca | `get_latest_quote()` → bid_price, ask_price | Real-time |
| **Volume Bars** | Polygon | `get_minute_bars()` | 15-min delayed |
| **Snapshot** | Polygon | `get_snapshot()` | 15-min delayed |

**Decision Logic:**
```
Bid Collapse Detection:
- Spread widening > 2× normal
- Bid size < 50% of ask size
- Volume spike + price weakness

Score = (Bid Collapse × 0.25) + (Spread Widening × 0.20) + (Quote Degradation × 0.15)
```

**Data File:** `scheduled_scan_results.json` → `liquidity[]`

**Last Updated:** 2026-02-02 23:19:42

---

### 4️⃣ EARLY WARNING TAB

| Component | Data Source | Endpoint | Update Frequency |
|-----------|-------------|----------|------------------|
| **Dark Pool Sequence** | Unusual Whales | `get_dark_pool_flow()` | ~15 min |
| **Put OI Accumulation** | Unusual Whales | `get_oi_change()` | ~15 min |
| **IV Term Inversion** | Unusual Whales | `get_iv_term_structure()` | ~15 min |
| **Quote Degradation** | Alpaca | `get_latest_quote()` | Real-time |
| **Flow Divergence** | Unusual Whales | `get_flow_recent()` | ~15 min |
| **Multi-Day Distribution** | Polygon | `get_daily_bars()` | Daily close |
| **Cross-Asset Divergence** | Polygon | `get_daily_bars()` | Daily close |

**Decision Logic:**
```
IPI = Σ(footprint_weight × strength × time_decay)

Time Decay: exp(-0.04 × hours_old)  [half-life ~17 hours]
Engine Diversity: +0.10 × (num_engines - 1)

Levels:
- ACT (IPI ≥ 0.70): Execute position
- PREPARE (0.50-0.70): Add to watchlist
- WATCH (0.30-0.50): Monitor
```

**Data File:** `early_warning_alerts.json`

**Last Updated:** 2026-02-02 08:34:00 ⚠️ **VERY STALE (15+ hours)**

---

### 5️⃣ 48-HOUR ANALYSIS TAB

| Component | Data Source | Update Frequency |
|-----------|-------------|------------------|
| **Aggregated History** | `scan_history.json` | After each scan |
| **Engine Convergence** | Calculated from history | On-demand |

**Decision Logic:**
```
Conviction Score = Σ(appearances × time_decay × engine_diversity_bonus)

Time Decay: exp(-0.04 × hours_old)
Diversity Bonus: 0.10 × (num_unique_engines - 1)

Multi-Engine (2+): → Full size position
Trifecta (3): → Maximum conviction
```

**Data File:** `scan_history.json`

**Last Updated:** 2026-02-02 23:19:42

---

### 6️⃣ BIG MOVERS ANALYSIS TAB

| Component | Data Source | Endpoint | Update Frequency |
|-----------|-------------|----------|------------------|
| **Pump Reversal** | Alpaca | `get_bars()` 10-day history | Scheduled |
| **Two-Day Rally** | Alpaca | `get_bars()` 10-day history | Scheduled |
| **High Vol Run** | Alpaca | `get_bars()` 10-day history | Scheduled |
| **Engine Confirmation** | Cross-reference with scheduled_scan_results | On-demand |

**Decision Logic:**
```
Pump Reversal: Price up +5%+ in 1 day, then shows weakness
Two-Day Rally: 2 consecutive up days → exhaustion setup
High Vol Run: Volume > 2× average + price gain > 3%

Badge System:
⭐⭐⭐ = Confirmed by 2+ engines → FULL SIZE
✅ = Confirmed by 1 engine → Standard size
⚠️ = Stale thesis (3+ sessions unconfirmed)
```

**Data File:** `pattern_scan_results.json`

**Last Updated:** 2026-02-02 23:19:42

---

## ⏰ COMPLETE SCAN SCHEDULE (57 Jobs)

### Pre-Market (4:00 AM - 9:30 AM ET)
| Time | Scan Type | What It Does |
|------|-----------|--------------|
| 4:00 AM | Gap Scan | Pre-market gaps detection |
| 4:15 AM | Pre-Market #1 | All 3 engines |
| 6:00 AM | Gap Scan | Pre-market gaps detection |
| 6:15 AM | Pre-Market #2 | All 3 engines |
| 7:00 AM | Earnings Check | BMO earnings upcoming |
| 7:30 AM | Multi-Day Weakness | 8 weakness patterns |
| 8:00 AM | Gap Scan | Pre-market gaps detection |
| 8:15 AM | Pre-Market #3 | All 3 engines |
| 9:15 AM | Pre-Market #4 | Final pre-market scan |

### Market Hours (9:30 AM - 4:00 PM ET)
| Time | Scan Type | What It Does |
|------|-----------|--------------|
| 10:00 AM | Pre-Earnings Flow | Smart money pre-earnings |
| 10:00 AM | Intraday Big Mover | Real-time price drops |
| 10:15 AM | Regular Scan | All 3 engines |
| 10:30 AM | Pump-Dump Reversal | Reversal detection |
| 11:00 AM | Sector Correlation | Sector-wide weakness |
| 11:00 AM | Intraday Big Mover | Real-time price drops |
| 11:15 AM | Regular Scan | All 3 engines |
| 11:30 AM | Vol-Price Divergence | Distribution patterns |
| 12:00 PM | Intraday Big Mover | Real-time price drops |
| 12:45 PM | Regular Scan | All 3 engines |
| 1:00 PM | Intraday Big Mover | Real-time price drops |
| 1:45 PM | Regular Scan | All 3 engines |
| 2:00 PM | Pre-Earnings Flow | Smart money pre-earnings |
| 2:00 PM | Sector Correlation | Sector-wide weakness |
| 2:00 PM | Intraday Big Mover | Real-time price drops |
| 2:30 PM | Pump-Dump Reversal | Reversal detection |
| 2:45 PM | Regular Scan | All 3 engines |
| 3:00 PM | Earnings Alert | AMC earnings upcoming |
| 3:00 PM | Daily Report | Email with top picks |
| 3:00 PM | Intraday Big Mover | Real-time price drops |
| 3:15 PM | Regular Scan | All 3 engines |
| 3:30 PM | Vol-Price Divergence | Distribution patterns |

### After-Hours (4:00 PM - 8:00 PM ET)
| Time | Scan Type | What It Does |
|------|-----------|--------------|
| 4:00 PM | Market Close | Final market scan |
| 4:30 PM | After-Hours #1 | AH price moves |
| 5:00 PM | End of Day | EOD summary scan |
| 5:00 PM | Multi-Day Weakness | Pattern detection |
| 6:00 PM | After-Hours #2 | AH price moves |
| 6:00 PM | Pre-Catalyst | Smart money positioning |
| 8:00 PM | After-Hours #3 | Final AH scan |

---

## 🚨 WHY DATA IS NOT UPDATING

### Issue 1: Scheduler Status = UNRESPONSIVE
```
Health Status: UNRESPONSIVE
Memory: 12.3 MB
Last Check: 2026-02-02T21:06:44
```

The scheduler daemon is running (PID 69557) but only showing heartbeats - **NO ACTUAL SCANS ARE EXECUTING**.

### Issue 2: Market Closed
- Today is **Sunday February 2** (now Feb 3 after midnight)
- Most scans only run during market hours
- Pre-market scans start at 4:00 AM ET Monday

### Issue 3: Early Warning Not Updated
- Last EWS update: **8:34 AM on Feb 2** (over 15 hours ago)
- Should have updated with the 5:00 PM EOD scan

---

## 💡 RECOMMENDATIONS

### Immediate (Fix Now)
1. **Restart Scheduler Daemon:**
   ```bash
   python start_scheduler_daemon.py restart
   ```

2. **Start Watchdog:**
   ```bash
   python start_scheduler_daemon.py start  # Includes watchdog
   ```

### Short-Term (This Week)
1. **Add Scheduler Health Check to Dashboard**
   - Show last scan time prominently
   - Alert if no scan in 2+ hours during market hours

2. **Implement Scheduled EWS Scans**
   - EWS should run at 4:00 AM, 9:00 AM, 12:00 PM, 4:00 PM, 8:00 PM
   - Currently only runs on dashboard refresh

3. **Add "Force Scan" Button**
   - Allow manual triggering of full scan from dashboard

### Long-Term (This Month)
1. **API Health Dashboard Tab**
   - Show real-time status of all 5 data sources
   - API call counts vs limits
   - Last successful call per endpoint

2. **Scan Execution Log**
   - Record actual start/end time of each scan
   - Track failures and retry attempts

---

## 📊 DATA FRESHNESS SUMMARY

| Tab | Data File | Last Updated | Status |
|-----|-----------|--------------|--------|
| Gamma Drain | scheduled_scan_results.json | Feb 2, 11:19 PM | 🟡 Dashboard Refresh Only |
| Distribution | scheduled_scan_results.json | Feb 2, 11:19 PM | 🟡 Dashboard Refresh Only |
| Liquidity | scheduled_scan_results.json | Feb 2, 11:19 PM | 🟡 Dashboard Refresh Only |
| Early Warning | early_warning_alerts.json | Feb 2, 8:34 AM | 🔴 STALE (15+ hours) |
| 48-Hour | scan_history.json | Feb 2, 11:19 PM | 🟡 Dashboard Refresh Only |
| Big Movers | pattern_scan_results.json | Feb 2, 11:19 PM | 🟢 Current |

---

## 🔄 DATA FLOW DIAGRAM

```
                    ┌─────────────────────────────────────────────┐
                    │              DATA SOURCES                    │
                    ├─────────┬──────────┬──────────┬─────────────┤
                    │ Alpaca  │ Polygon  │ Unusual  │  FinViz     │
                    │(Quotes) │ (OHLCV)  │ Whales   │ (Screener)  │
                    └────┬────┴────┬─────┴────┬─────┴──────┬──────┘
                         │         │          │            │
                         ▼         ▼          ▼            ▼
                    ┌─────────────────────────────────────────────┐
                    │           SCHEDULER DAEMON                   │
                    │  (57 jobs, runs 4 AM - 8 PM ET)              │
                    └──────────────────┬──────────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
           ▼                           ▼                           ▼
    ┌─────────────┐           ┌─────────────┐            ┌─────────────┐
    │   GAMMA     │           │DISTRIBUTION │            │  LIQUIDITY  │
    │   DRAIN     │           │    ENGINE   │            │   ENGINE    │
    │   ENGINE    │           │             │            │             │
    └──────┬──────┘           └──────┬──────┘            └──────┬──────┘
           │                         │                          │
           └─────────────────────────┼──────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────────────────┐
                    │         scheduled_scan_results.json          │
                    │  (gamma_drain[], distribution[], liquidity[])│
                    └──────────────────┬──────────────────────────┘
                                       │
                                       ▼
                    ┌─────────────────────────────────────────────┐
                    │          scan_history.json                   │
                    │     (48-hour rolling history)                │
                    └──────────────────┬──────────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
           ▼                           ▼                           ▼
    ┌─────────────┐           ┌─────────────┐            ┌─────────────┐
    │  48-HOUR    │           │    EARLY    │            │ BIG MOVERS  │
    │  ANALYSIS   │           │   WARNING   │            │  ANALYSIS   │
    └─────────────┘           └─────────────┘            └─────────────┘
```

---

## ✅ CONCLUSION

Your system architecture is **sound** but the scheduler is not executing jobs properly.

**Action Required:**
1. Restart scheduler daemon
2. Verify scans run on Monday pre-market (4:00 AM ET)
3. Check logs for any errors

The data sources (Alpaca, Polygon, UW, FinViz) are all correctly configured and working when called - the issue is the scheduler not triggering the scans.
