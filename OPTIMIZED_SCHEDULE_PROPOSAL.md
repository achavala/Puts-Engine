# OPTIMIZED SCAN SCHEDULE - February 4, 2026

## Current vs Proposed UW API Usage

### CURRENT: 30 scans using UW (4,000+ API calls/day)
### PROPOSED: 11 scans using UW (~1,500 API calls/day)

---

## PROPOSED SCHEDULE (KEEPING UW CALLS)

| # | Time | Scan Name | Tickers | UW Calls/Scan | Purpose |
|---|------|-----------|---------|---------------|---------|
| 1 | 7:00 AM | Earnings Calendar Check | N/A | ~50 | Check earnings dates |
| 2 | 7:00 AM | Earnings Priority Scan #1 | 361 | ~400 | Pre-market put flow |
| 3 | 8:00 AM | **Pre-Market Full Scan** | 361 | ~1,000 | Dark pool, options flow, IV |
| 4 | 10:30 AM | Pump-Dump Reversal #1 | 129 | ~150 | High-beta options flow |
| 5 | 12:00 PM | Earnings Priority Scan #2 | 361 | ~400 | Midday put flow |
| 6 | 2:00 PM | Pre-Earnings Flow #1 | 361 | ~400 | Afternoon flow |
| 7 | 2:30 PM | Pump-Dump Reversal #2 | 129 | ~150 | High-beta options flow |
| 8 | 4:30 PM | Earnings Priority Scan #3 | 361 | ~400 | Post-market put flow |
| 9 | 6:00 PM | Pre-Catalyst Distribution | 361 | ~400 | Distribution detection |
| 10 | 10:00 PM | Pre-Earnings Flow #2 | 361 | ~400 | Evening flow check |
| 11 | 10:00 PM | **🚨 EWS Full Scan** | 361 | ~1,200 | All 7 institutional footprints |

**TOTAL UW API CALLS: ~4,950/day** (within 7,500 limit)

---

## SCANS TO KEEP (NO UW - Use Alpaca/Polygon Only)

| Time | Scan Name | Tickers | Data Source |
|------|-----------|---------|-------------|
| 4:00 AM | Pre-Market Gap Scan | 361 | Alpaca |
| 6:00 AM | Pre-Market Gap Scan | 361 | Alpaca |
| 7:00 AM | Pre-Market Gap Scan | 361 | Alpaca |
| 7:30 AM | Multi-Day Weakness | 361 | Alpaca |
| 8:00 AM | Pre-Market Gap Scan | 361 | Alpaca |
| 9:15 AM | Zero-Hour Scanner | 361 | Alpaca |
| 10:00 AM | Intraday Big Mover | 361 | Alpaca |
| 11:00 AM | Sector Correlation | 361 | Alpaca |
| 11:00 AM | Intraday Big Mover | 361 | Alpaca |
| 11:30 AM | Volume-Price Divergence | 361 | Alpaca |
| 12:00 PM | Intraday Big Mover | 361 | Alpaca |
| 1:00 PM | Intraday Big Mover | 361 | Alpaca |
| 2:00 PM | Sector Correlation | 361 | Alpaca |
| 2:00 PM | Intraday Big Mover | 361 | Alpaca |
| 3:00 PM | Intraday Big Mover | 361 | Alpaca |
| 3:00 PM | Daily Report (Email) | N/A | Cached data |
| 3:30 PM | Volume-Price Divergence | 361 | Alpaca |
| 4:30 PM | After-Hours Scan #1 | 361 | Alpaca |
| 5:00 PM | Multi-Day Weakness | 361 | Alpaca |
| 6:00 PM | After-Hours Scan #2 | 361 | Alpaca |
| 8:00 PM | After-Hours Scan #3 | 361 | Alpaca |

---

## SCANS TO REMOVE (Redundant/Heavy UW Usage)

| Time | Scan Name | Reason to Remove |
|------|-----------|------------------|
| 4:15 AM | Pre-Market Scan #1 | Replaced by 8:00 AM scan |
| 6:15 AM | Pre-Market Scan #2 | Redundant |
| 8:15 AM | Pre-Market Scan #3 | Redundant |
| 9:15 AM | Pre-Market Scan #4 | Redundant |
| 10:15 AM | Regular Scan | Heavy UW, use Big Mover instead |
| 11:15 AM | Regular Scan | Heavy UW, use Big Mover instead |
| 12:45 PM | Regular Scan | Heavy UW, use Earnings Priority instead |
| 1:45 PM | Regular Scan | Heavy UW, use Big Mover instead |
| 2:45 PM | Regular Scan | Heavy UW, use Big Mover instead |
| 3:15 PM | Regular Scan | Heavy UW, use Big Mover instead |
| 4:00 PM | Market Close Scan | Heavy UW, redundant |
| 5:00 PM | End of Day Scan | Heavy UW, redundant |
| 10:00 PM | Overnight Full Scan | Heavy UW, EWS covers this |
| ALL | Pattern Scans (14) | Just technical patterns, no need for 30-min intervals |

---

## FINAL OPTIMIZED SCHEDULE

### UW-USING SCANS: 11 scans

| Time | Scan | Tickers | Est. UW Calls |
|------|------|---------|---------------|
| 7:00 AM | Earnings Calendar | - | 50 |
| 7:00 AM | Earnings Priority #1 | 361 | 400 |
| 8:00 AM | Pre-Market Full Scan | 361 | 1,000 |
| 10:30 AM | Pump-Dump Reversal | 129 | 150 |
| 12:00 PM | Earnings Priority #2 | 361 | 400 |
| 2:00 PM | Pre-Earnings Flow | 361 | 400 |
| 2:30 PM | Pump-Dump Reversal | 129 | 150 |
| 4:30 PM | Earnings Priority #3 | 361 | 400 |
| 6:00 PM | Pre-Catalyst Dist | 361 | 400 |
| 10:00 PM | Pre-Earnings Flow | 361 | 400 |
| 10:00 PM | 🚨 EWS Full Scan | 361 | 1,200 |

**TOTAL: ~4,950 UW calls/day**

### NON-UW SCANS: 21 scans (Alpaca/Polygon only)

**GRAND TOTAL: 32 scans** (down from 64)

---

## BENEFITS

1. **UW API Budget**: Reduced from ~7,000 to ~4,950 calls/day (30% savings)
2. **Focus on Key Scans**: EWS at 10 PM, Pre-Market at 8 AM
3. **Remove Redundancy**: No need for 14 pattern scans when Big Mover works
4. **Better Coverage**: Still scan 361 tickers at critical times
