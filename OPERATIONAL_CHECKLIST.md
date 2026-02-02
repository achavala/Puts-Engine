# 🏛️ PUTSENGINE — OPERATIONAL CHECKLIST

**Status:** ✅ SIGNED OFF — LIVE DEPLOYMENT APPROVED (CONTROLLED)  
**Date:** February 1, 2026  
**Audit:** Architect-4 (Conclusive)

---

## DAILY OPERATIONAL FLOW

### Pre-Market (Before 9:30 AM ET)

```
□ 8:00 AM  - EWS scan runs automatically (check logs)
□ 9:15 AM  - Zero-Hour scan confirms/rejects EWS signals
□ 9:15 AM  - Review VACUUM_OPEN alerts (if any)
□ 9:25 AM  - Decision: Enter or wait
```

### Intraday

```
□ Monitor dashboard for engine confirmations
□ Do NOT override Vega Gate structure recommendations
□ Do NOT chase signals that weren't pre-identified by EWS
```

### Post-Market

```
□ 4:30 PM  - EWS scan captures end-of-day footprints
□ Review attribution log for any open positions
□ Update trade exits when applicable
```

---

## SCALING GATE — DO NOT DEPLOY FULL CAPITAL UNTIL:

| Metric | Requirement | Current |
|--------|-------------|---------|
| ACT events logged | ≥ 20 | ___ |
| Win rate | ≥ 50% | ___ |
| ACT → VACUUM_OPEN | ≥ 60% | ___ |

**Check progress:** `python -m putsengine.ews_attribution`

---

## WHAT IS FROZEN (DO NOT CHANGE)

- [ ] Footprint taxonomy (7 types)
- [ ] IPI thresholds (0.30 / 0.50 / 0.70)
- [ ] Causal ordering (Pressure → Permission → Structure)
- [ ] EWS as radar (NOT trigger)
- [ ] Zero-Hour as confirmation (NOT signal)
- [ ] Vega Gate coupling logic

---

## SCHEDULER STATUS

**Check:** `python start_scheduler_daemon.py status`

**Restart:** `python start_scheduler_daemon.py restart`

**Logs:** `tail -f logs/scheduler_daemon.log`

---

## KEY FILES

| File | Purpose |
|------|---------|
| `scheduled_scan_results.json` | Latest engine results |
| `early_warning_alerts.json` | Current EWS pressure |
| `zero_hour_alerts.json` | Day 0 confirmations |
| `flash_alerts.json` | Rapid IPI surges |
| `ews_attribution.json` | Trade attribution log |
| `footprint_history.json` | Multi-day footprint data |

---

## DECISION TREE

```
EWS Level?
├─ NONE (IPI < 0.30)
│   └─ No action
│
├─ WATCH (IPI 0.30-0.50)
│   └─ Add to watchlist only
│
├─ PREPARE (IPI 0.50-0.70)
│   └─ Prepare strike selection, wait for confirmation
│
└─ ACT (IPI ≥ 0.70)
    │
    └─ Zero-Hour (9:15 AM)?
        ├─ VACUUM_OPEN
        │   └─ ✅ Permission granted → Check engine convergence
        │       │
        │       └─ Vega Gate?
        │           ├─ IV < 60 → Long Put
        │           ├─ IV 60-80 → Long Put (reduced)
        │           └─ IV > 85 + ACT → Bear Call Spread
        │
        ├─ SPREAD_COLLAPSE
        │   └─ ✅ Urgent → Same as VACUUM_OPEN
        │
        ├─ PRESSURE_ABSORBED
        │   └─ ❌ Wait → Re-evaluate next day
        │
        └─ NO_CONFIRMATION
            └─ ❌ Stand down → Do not trade
```

---

## WHAT NOT TO DO

❌ Lower IPI thresholds to "get more signals"  
❌ Trade before Zero-Hour confirmation  
❌ Override Vega Gate structure  
❌ Auto-trade from Flash Alerts  
❌ Add ML or new footprints  
❌ Chase missed moves  

---

## ATTRIBUTION LOGGING

**Automatic:** ACT-level events are auto-logged when detected

**Manual updates needed:**
```python
from putsengine.ews_attribution import update_trade_entry, update_trade_exit

# When entering trade
update_trade_entry(event_id, entry_price=1.50, lead_time_hours=18)

# When exiting trade
update_trade_exit(event_id, exit_price=4.20, max_return=3.4, outcome="win")
```

---

## CONTACT PROTOCOL (IF SYSTEM FAILS)

1. Check scheduler status
2. Review logs for errors
3. Verify API connectivity
4. DO NOT modify signal logic
5. Reduce position size, not detection sensitivity

---

## FINAL REMINDER

> **Silence is discipline, not failure.**
>
> If EWS finds nothing actionable, that IS the correct output.
> The system protects capital by staying out of bad setups.

---

*Document created: February 1, 2026*  
*Version: architect4-final-signoff-020126*
