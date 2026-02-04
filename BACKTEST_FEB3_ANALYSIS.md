# Backtest Analysis: Feb 3, 2026 Crash

Generated: 2026-02-03T22:39:06.606028

## Summary
- total_crashes: 15
- in_universe_but_missed: 6
- not_in_universe: 9
- earnings_related: 14
- average_crash_pct: -12.43
- total_opportunity_lost: 186.45

## Recommendations
### [CRITICAL] UW API Budget Exhaustion
Implement smarter budget allocation - prioritize earnings stocks

3,984 API calls skipped in 24 hours. Need to batch requests and prioritize tickers with upcoming earnings or high-beta names.

### [CRITICAL] Missing Major Tickers in Universe
Add 9 missing tickers immediately

EXPE, CSGP, NVO, TRU, INTU, FIG (if tradeable), SHOP, ACN, KKR must be added to static universe

### [HIGH] AlpacaClient.get_daily_bars() Missing
Method was added on Feb 2 but still failing

Logs show 'AlpacaClient object has no attribute get_daily_bars' - verify fix is deployed

### [HIGH] No Earnings Calendar Integration
Add earnings date lookup from UW API or third party

12 of 15 crashes were earnings-related. System should auto-add earnings stocks to priority scan 3 days before event.

### [MEDIUM] Pre-Catalyst Scanner Not Running
Ensure precatalyst_scanner runs daily at 6 PM ET

The scanner exists but logs show no evidence it ran on Feb 1-2

### [MEDIUM] Sector Expansion Needed
Add consulting (ACN), private equity (KKR), travel (EXPE), credit bureaus (TRU), pharma ADRs (NVO)

Missing entire sectors that had 10%+ crashes

