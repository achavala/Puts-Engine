# 🏛️ COMPLETE DATA SOURCE ANALYSIS
## PutsEngine Tab-by-Tab Breakdown
### 30+ Years Trading + PhD Quant + Institutional Microstructure Lens

---

## EXECUTIVE SUMMARY

Your system uses **4 primary data sources**:

| Source | Type | Cost | Primary Use |
|--------|------|------|-------------|
| **Unusual Whales (UW)** | Options Flow | Paid | Dark pool, GEX, OI, IV, flow alerts |
| **Polygon (Massive)** | Market Data | Paid ($199/mo) | Price bars, quotes, snapshots, news |
| **Alpaca** | Market Data | Free tier | Backup quotes, real-time prices |
| **Finviz** | Technical/News | Paid Elite | Technical screening, news sentiment |

---

## 1️⃣ EARLY WARNING SYSTEM (EWS) TAB

### Philosophy
> "You can't predict the catalyst, but you CAN detect the footprints of those who KNOW."

### Example Pick: IBM (IPI = 1.00)

**Data collected for IBM:**

| Footprint | Data Source | API Call | What It Detects |
|-----------|-------------|----------|-----------------|
| **Dark Pool Sequence** | UW | `get_dark_pool_flow("IBM")` | 50 prints, 505K shares, staircase selling |
| **Put OI Accumulation** | UW + Polygon | `get_oi_change("IBM")` + `get_daily_bars()` | 30%+ put OI increase without price drop |
| **IV Term Inversion** | UW | `get_iv_term_structure("IBM")` | 7-day IV > 30-day IV = near-term protection |
| **Quote Degradation** | Polygon | `get_latest_quote("IBM")` | Bid=80, Ask=40, spread widening |
| **Flow Divergence** | UW | `get_flow_alerts("IBM")` | Put premium increasing while price flat |
| **Multi-Day Distribution** | Polygon | `get_daily_bars("IBM", 5 days)` | Lower highs, volume on down days |
| **Cross-Asset Divergence** | Polygon | Compare IBM to XLK sector | Stock flat while sector drops |

### IPI Calculation Formula
```
IPI = Σ(weight × strength × time_decay) × diversity_bonus

Weights:
- Dark Pool Sequence: 0.20 (highest - direct evidence)
- Put OI Accumulation: 0.18
- IV Term Inversion: 0.15
- Quote Degradation: 0.15
- Flow Divergence: 0.12
- Multi-Day Distribution: 0.12
- Cross-Asset Divergence: 0.08

Time decay: exp(-0.03 × hours_since_detection)
Half-life: ~23 hours

Diversity bonus: 1.0 + 0.1 × (unique_footprint_types - 1)
```

### IBM Breakdown:
- Dark Pool: strength=1.0, weight=0.20 → 0.20
- Multi-Day Distribution: strength=0.6, weight=0.12 → 0.072
- Quote Degradation: strength=0.5, weight=0.15 → 0.075
- **Sum**: 0.347 × diversity_bonus(1.2 for 3 types) = **0.42 base**
- With multiple detections over time → **IPI = 1.00**

---

## 2️⃣ 48-HOUR FREQUENCY TAB

### Philosophy
> "Symbols appearing across multiple engines in a 48-hour window have highest conviction."

### Data Sources per Engine

| Engine | Primary Data | UW Data | Key Indicators |
|--------|--------------|---------|----------------|
| **Gamma Drain** | Polygon bars | GEX, dealer positioning | Gamma exposure flip, delta hedging |
| **Distribution** | Polygon volume | Dark pool, block trades | Wyckoff distribution, selling pressure |
| **Liquidity Vacuum** | Polygon quotes | Options volume | Bid depletion, spread widening |

### Example Pick: TRIFECTA Symbol

When a symbol appears in ALL 3 engines:
```
Conviction Score = (weighted_appearances × avg_score × diversity_bonus)

where:
- weighted_appearances = Σ(decay(hours_since) × count)
- diversity_bonus = 1.5 (for 3 engines)
- decay = exp(-0.04 × hours)
```

### What makes a TRIFECTA actionable:
1. **Gamma Drain**: Dealers forced to sell into down moves
2. **Distribution**: Smart money exiting over multiple days
3. **Liquidity**: Market makers pulling bids

**ALL THREE = Mechanical selling pressure + smart money exit + liquidity vacuum**

---

## 3️⃣ BIG MOVERS TAB

### Philosophy
> "Detect patterns that precede -5% to -20% moves based on historical analysis."

### Data Source: **Polygon ONLY** (No UW calls)

| Pattern Type | Detection Logic | Data Required |
|--------------|-----------------|---------------|
| **Pump-and-Dump** | +3%+ gain over 1-3 days → watch for crash | 10-day price bars |
| **Reversal After Pump** | 2 consecutive up days with +3%+ total | 10-day price bars |
| **Sudden Crash** | Flat (<3% move) then big drop | 10-day price bars |
| **Sector Contagion** | 2+ sector peers moving together | Multi-ticker comparison |

### Example: NET (Cloudflare) Pattern Detection

```python
Day -3: +2.1%
Day -2: +1.8%  
Day -1: +3.2% (total +7.1% in 3 days)
Day 0:  -10.2% CRASH

Pattern: PUMP_AND_DUMP
Confidence: 0.75
Expected Move: -10% to -15%
Sector: cloud_saas
Peers: CRWD, ZS, OKTA, DDOG (watching for contagion)
```

### API Calls for Big Movers:
```
Polygon.get_daily_bars(symbol, from_date=today-10days)
```
**No UW API calls** - purely price-action based detection.

---

## 4️⃣ MARKET DIRECTION TAB (MarketPulse)

### Philosophy
> "Regime awareness, not prediction. 52-58% edge for risk gating."

### Data Sources by Component

| Component | Weight | Data Source | API Call |
|-----------|--------|-------------|----------|
| **Futures/Indexes** | 30% | Polygon | `get_snapshot("SPY")`, `get_snapshot("QQQ")` |
| **VIX** | 25% | Polygon | `get_snapshot("VIX")` |
| **Gamma (GEX)** | 20% | UW | `get_gex_data("SPY")` |
| **Breadth** | 15% | Polygon | `get_snapshot(sector_etfs)` |
| **Sentiment** | 10% | UW | `get_market_tide()` (put/call ratio) |

### Architect-4 Additions (Read-Only Context)

| Metric | Data Source | Purpose |
|--------|-------------|---------|
| Gamma Flip Distance | UW GEX | Fragility indicator |
| Flow Quality | UW flow | Opening vs closing transactions |
| Spread Expansion | Polygon quotes | Violence indicator |
| Expected Move | Polygon + UW IV | Dealer re-hedge risk |

---

## 📊 COMPLETE DATA FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PUTSENGINE DATA FLOW                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ UNUSUAL      │  │ POLYGON      │  │ FINVIZ       │              │
│  │ WHALES       │  │ (MASSIVE)    │  │ ELITE        │              │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤              │
│  │ Dark Pool    │  │ Price Bars   │  │ News         │              │
│  │ GEX/Gamma    │  │ Quotes       │  │ Sentiment    │              │
│  │ OI Change    │  │ Snapshots    │  │ Technical    │              │
│  │ IV Data      │  │ Top Movers   │  │ Insider      │              │
│  │ Flow Alerts  │  │ News         │  │              │              │
│  │ Market Tide  │  │              │  │              │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                 │                       │
│         └────────────┬────┴────────────┬────┘                       │
│                      │                 │                            │
│         ┌────────────▼─────────────────▼────────────┐               │
│         │           EARLY WARNING SYSTEM            │               │
│         │    (7 Footprints → IPI 0-1.0)            │               │
│         │    ACT ≥0.70 | PREPARE 0.50-0.70         │               │
│         └────────────────────┬──────────────────────┘               │
│                              │                                      │
│  ┌───────────────────────────┼───────────────────────────┐         │
│  │                           │                           │         │
│  ▼                           ▼                           ▼         │
│ ┌─────────────┐  ┌─────────────────────┐  ┌─────────────────┐      │
│ │ GAMMA DRAIN │  │ DISTRIBUTION LAYER  │  │ LIQUIDITY       │      │
│ │   ENGINE    │  │                     │  │ VACUUM ENGINE   │      │
│ └──────┬──────┘  └──────────┬──────────┘  └────────┬────────┘      │
│        │                    │                      │               │
│        └────────────────────┼──────────────────────┘               │
│                             │                                      │
│                  ┌──────────▼──────────┐                           │
│                  │   48-HOUR FREQUENCY  │                           │
│                  │   (Multi-Engine)     │                           │
│                  │   TRIFECTA = ALL 3   │                           │
│                  └──────────┬──────────┘                           │
│                             │                                      │
│  ┌──────────────────────────┼──────────────────────────┐           │
│  │                          │                          │           │
│  ▼                          ▼                          ▼           │
│ ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐        │
│ │ BIG MOVERS   │  │  MARKETPULSE    │  │ VEGA GATE        │        │
│ │ (Price Only) │  │  (Regime)       │  │ (IV Structure)   │        │
│ └──────────────┘  └─────────────────┘  └──────────────────┘        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 CONSOLIDATED TOP 8 PICKS LOGIC

The **Market Direction** tab should consolidate the best picks from ALL sources:

### Ranking Algorithm

```python
FINAL_SCORE = (
    EWS_IPI × 0.35 +           # Institutional footprints (highest weight)
    FREQUENCY_CONV × 0.25 +    # Multi-engine convergence
    MARKETPULSE_REGIME × 0.20 + # Regime alignment
    BIG_MOVER_CONF × 0.15 +    # Pattern detection
    SECTOR_STRESS × 0.05       # Sector contagion
)
```

### Selection Criteria

| Rank | Source | Required Score | Condition |
|------|--------|----------------|-----------|
| 1 | EWS ACT | IPI ≥ 0.70 | + MarketPulse RISK_OFF |
| 2 | TRIFECTA | Conv ≥ 0.30 | All 3 engines |
| 3 | EWS PREPARE | IPI ≥ 0.50 | + Big Mover pattern |
| 4 | Multi-Engine | Conv ≥ 0.20 | 2+ engines |
| 5 | Big Mover | Conf ≥ 0.70 | PUMP_DUMP or REVERSAL |
| 6-8 | Best remaining | Any source | Sorted by composite score |

---

## ⚠️ DATA VALIDATION CHECKLIST

Before taking a trade, verify:

| Check | Source | What to Verify |
|-------|--------|----------------|
| ✅ Price is REAL | Polygon snapshot | Matches your broker |
| ✅ Dark pool is FRESH | UW timestamp | < 2 hours old |
| ✅ IV is CURRENT | UW IV data | Not stale |
| ✅ Volume is LIVE | Polygon bars | Today's volume |
| ✅ Spreads are TIGHT | Polygon quote | Bid-ask < 5% |

---

## 📅 RECOMMENDED WORKFLOW

### Pre-Market (8-9 AM ET)
1. Run MarketPulse → Get regime (RISK_OFF favorable)
2. Check EWS ACT alerts → Highest conviction
3. Check TRIFECTA symbols → 48-hour convergence

### Market Open (9:30 AM)
1. Verify prices are moving as expected
2. Check if ACT symbols are below VWAP
3. Look for entry on bounces

### Power Hour (3-4 PM ET)
1. Re-run MarketPulse for next-day setup
2. Check Big Movers for new patterns
3. Set alerts for tomorrow's opens

---

*Document generated: Feb 5, 2026*
*System version: MarketPulse + Architect-4 Enhancements*
