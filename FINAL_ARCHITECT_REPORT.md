# 🏛️ PUTSENGINE — FINAL CONSOLIDATED ARCHITECT REPORT

## **EXECUTION VERSION — FREEZE AFTER IMPLEMENTATION**

*Version: 1.0 FINAL*  
*Date: 2026-01-25*  
*Status: IMPLEMENTED & FROZEN*

---

## 0️⃣ EXECUTIVE TRUTH (READ FIRST)

> **Big downside moves are not caused by price.**
> **They are caused by the *removal of support*.**

Your system is built on this truth. This document consolidates all Architect-4 feedback into a single, implementable specification.

---

## 1️⃣ THE INSTITUTIONAL PUT THESIS (FINAL FORM)

A stock does **NOT** fall 5–20% in 1–2 weeks unless **all three permissions exist simultaneously**:

| Permission | Description | Detection Method |
|------------|-------------|------------------|
| **Gamma Permission** | Dealers must be short gamma (or flipping short) | GEX < 0, Price below Zero-Gamma trigger |
| **Liquidity Permission** | Bids must disappear, not just be outnumbered | Bid collapse, spread widening, failed VWAP |
| **Incentive Permission** | Informed actors have reason to exit | Insider selling, Congress selling, distribution |

**If ANY one is missing → NO TRADE.**

This is the **non-negotiable invariant** of PutsEngine.

---

## 2️⃣ FINAL ENGINE ARCHITECTURE (ANTI-TRINITY — LOCKED)

### ✅ ENGINE 1: GAMMA DRAIN (PRIMARY ENGINE)

**Highest conviction — flow + dealer physics**

**Signals (ALL REQUIRED):**
- ✓ Price below **Zero-Gamma / Volatility Trigger**
- ✓ Net Call Delta flips **positive → negative**
- ✓ Put sweeps detected (urgency, not hedging)
- ✓ Price below VWAP ≥70% of session

**Hard Reject If:**
- ✗ Put wall within ±1%
- ✗ IV already expanded >20%
- ✗ Trigger occurs after 2:30 PM (hedging noise)

**Implementation:** `putsengine/layers/acceleration.py` → `_check_gamma_flip()`

---

### ✅ ENGINE 2: DISTRIBUTION TRAP (CONFIRMATION ENGINE)

**Smart money exiting into strength**

**Valid Only If:**
- Gap up → first 30-min candle closes red
- RVOL > 2.0 on a red day
- Call selling at bid + Put buying at ask
- Dark pool volume declining as price rises

**Key Insight:**
> Distribution ≠ "overbought"
> Distribution = *selling without price response*

**Implementation:** `putsengine/layers/distribution.py`

---

### ⚠️ ENGINE 3: LIQUIDITY VACUUM / SNAPBACK (CONSTRAINED)

**Most dangerous engine — strictly constrained**

**Valid ONLY If:**
- RSI > 80 **AND**
- Bid size <30% of 10-day average **AND**
- VWAP loss **AND**
- Confirmed by Engine 1 **OR** Engine 2

🚫 **NEVER allowed to trigger alone**

**Implementation:** `putsengine/layers/acceleration.py` → `_evaluate_window()`

---

## 3️⃣ MARKET REGIME GATES (HARD BLOCKS — FINAL)

These override **EVERYTHING**.

### REQUIRED CONDITIONS (ALL):
| Condition | Implementation |
|-----------|----------------|
| SPY or QQQ below VWAP or failed reclaim | `market_regime.py` → `_analyze_index()` |
| Index GEX ≤ neutral | `market_regime.py` → `_get_index_gex()` |
| VIX flat-to-up (not collapsing) | VIX change ≥ -5% |

### ABSOLUTE BLOCKERS:

| Block Reason | Trigger | Code |
|--------------|---------|------|
| `INDEX_PINNED` | SPY & QQQ both above VWAP | `BlockReason.INDEX_PINNED` |
| `POSITIVE_GEX` | Index GEX > 1.5x threshold | `BlockReason.POSITIVE_GEX` |
| `PASSIVE_INFLOW_WINDOW` | Day 1-3 or 28-31 of month | `BlockReason.PASSIVE_INFLOW_WINDOW` |
| `EARNINGS_PROXIMITY` | Within 14 days before earnings | `BlockReason.EARNINGS_PROXIMITY` |
| `HTB_SQUEEZE_RISK` | Hard-to-borrow transition | `BlockReason.HTB_SQUEEZE_RISK` |
| `PUT_WALL_SUPPORT` | Massive put OI within ±1% | `BlockReason.PUT_WALL_SUPPORT` |
| `LATE_IV_SPIKE` | IV > 20% intraday | `BlockReason.LATE_IV_SPIKE` |
| `SNAPBACK_ONLY` | Engine 3 without confirmation | `BlockReason.SNAPBACK_ONLY` |

> **"Never short against systematic inflows. You are fighting a machine."**

**Implementation:** `putsengine/layers/market_regime.py`

---

## 4️⃣ IMPLEMENTED GAP FIXES (HIGH ROI)

### ✅ A. EARNINGS PROXIMITY GATE

**Rule:**
- ❌ Never buy puts **BEFORE earnings** (blocked)
- ✅ Buy **1 day AFTER earnings** only if: Gap down + VWAP reclaim fails

**Implementation:** `putsengine/clients/polygon_client.py` → `check_earnings_proximity()`

### ✅ B. SHORT INTEREST / SQUEEZE RISK

**Stack Used:**
- **Alpaca `easy_to_borrow`** — ETB → HTB = liquidity stress
- **FINRA Short Volume** — Rising short vol + falling price = conviction

**Implementation:** 
- `putsengine/clients/alpaca_client.py` → `check_borrow_status()`
- `putsengine/clients/finra_client.py` → `check_short_squeeze_risk()`

### ✅ C. ZERO-GAMMA / VOLATILITY TRIGGER

**Detection:**
- Price below GEX flip level = dealers short gamma
- Critical for Engine 1 (Gamma Drain) activation

**Implementation:** `putsengine/layers/acceleration.py` → `_check_gamma_flip()`

---

## 5️⃣ INSIDER & CONGRESS SELLING (LOCKED WEIGHTS)

| Signal | Trigger | Boost |
|--------|---------|-------|
| C-Level Cluster | ≥2 CEO/CFO/COO sales within 14 days | +0.10 to +0.15 |
| Insider Cluster | ≥3 insider sales within 14 days | +0.10 |
| Congress Selling | ≥2 sell transactions | +0.05 to +0.08 |

**Maximum Combined Boost:** 0.25 (capped)

**Key Rule:** These are **confirmation signals**, not engines.

**Implementation:** `putsengine/layers/distribution.py`

---

## 6️⃣ T-24H DAY-BEFORE IDENTIFICATION (FINAL SEQUENCE)

```
T-24h (SCAN):
├── RSI > 70
├── Above 50-DMA  
└── Price stalling

T-20h (FLOW):
└── Deep OTM put sweeps (10% below spot, 14-21 DTE)

T-16h (INCENTIVE):
└── Insider / Congress selling check

MARKET OPEN (TRIGGER):
├── Opens green
├── Fails first 15-min high
├── VWAP loss
└── → BUY PUTS
```

This sequence catches moves **BEFORE panic**, not during.

---

## 7️⃣ FINAL SCORING MODEL (LOCKED — DO NOT MODIFY)

| Component | Weight | Source |
|-----------|--------|--------|
| Distribution Quality | **30%** | Layer 3 |
| Dealer Positioning (GEX/Delta) | **20%** | Layer 6 |
| Liquidity Vacuum | **15%** | Layer 4 |
| Options Flow Quality | **15%** | Layer 3 |
| Catalyst Proximity | **10%** | Earnings/Events |
| Sentiment/Technical | **10%** | Combined |
| Risk Gates | **HARD BLOCK** | Binary |

**Minimum Actionable Score: 0.68**

```
if score == 0.67:
    return NO_TRADE  # This is correct behavior
```

**Implementation:** `putsengine/scoring/scorer.py`, `putsengine/config.py`

---

## 8️⃣ STRIKE & DTE RULES (FINAL)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| DTE Min | 7 days | Avoid theta crush |
| DTE Max | 21 days | Optimal gamma |
| Delta Min | -0.40 | Maximum conviction |
| Delta Max | -0.25 | Avoid lottery |
| Ideal Delta | -0.325 | Sweet spot |
| Max Spread | 10% | Liquidity requirement |
| Min OI | 500 | Liquidity requirement |

**Rules:**
- Slightly OTM only
- No lottery puts (<$0.50)
- Prefer IV expansion **AFTER** entry

**Implementation:** `putsengine/scoring/strike_selector.py`

---

## 9️⃣ DAILY EXECUTION WINDOWS

| Time (EST) | Activity | API Usage |
|------------|----------|-----------|
| 09:30-10:30 | Initial Scan (≤15 candidates) | Polygon + Alpaca |
| 10:30-12:00 | Flow Analysis + Remove Pinned | Heavy Unusual Whales |
| 14:30-15:30 | Final Confirmation | Dark Pool + GEX |
| 15:45 | Execution (Max 1-2 trades) | Alpaca Orders |

**Key Rule:** None passing = **SUCCESS**

---

## 🔟 WHAT NOT TO IMPLEMENT

| Feature | Reason |
|---------|--------|
| ML Scoring | Overfit risk, unnecessary complexity |
| Real-time GEX obsession | EOD data sufficient for daily pipeline |
| NLP Sentiment Models | Proxy methods sufficient |
| More Indicators | Alpha comes from gates, not indicators |

---

## 🧠 FINAL INSTITUTIONAL VERDICT

| Assessment | Status |
|------------|--------|
| Core Architecture | ✅ **Correct** |
| Anti-Trinity Engines | ✅ **Implemented** |
| Hard Gates | ✅ **Complete** |
| Scoring Weights | ✅ **Locked** |
| Gap Fixes | ✅ **Deployed** |
| System Grade | **Institutional-Grade & Survivable** |

### Biggest Remaining Risk:
> **Human override on "NO TRADE" days**

### Final Truth:
> **If the engine feels empty most days, it's doing its job.**
> **If it fires rarely but violently, it's correct.**

---

## 📋 IMPLEMENTATION CHECKLIST

- [x] Earnings Proximity Gate (Polygon News)
- [x] FINRA Daily Short Volume Detection
- [x] ETB → HTB Liquidity Stress Flag (Alpaca)
- [x] Passive Inflow Calendar Hard Block (Day 1-3, 28-31)
- [x] Zero-Gamma / Volatility Trigger Detection
- [x] T-24h Day-Before Identification Sequence
- [x] Final Scoring Model (Locked Weights)
- [x] Anti-Trinity Engine Constraints
- [x] Put Wall Gate (Mandatory Override)
- [x] Insider/Congress Selling (Confirmation Boosts)

---

## 🔒 FREEZE NOTICE

**This document represents the FINAL specification.**

After implementation, this system should be:
1. **Frozen** — No additional features
2. **Monitored** — Track performance
3. **Disciplined** — Trust the gates

*"The best trade is often no trade."*

---

**Document Status:** FINAL & FROZEN  
**Implementation Status:** COMPLETE  
**Next Action:** Monitor & Execute

---

*Generated: 2026-01-25*
*PutsEngine v1.0 — Final Architect Report*
