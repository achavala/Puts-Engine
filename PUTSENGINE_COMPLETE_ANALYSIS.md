# 🔬 PutsEngine: Complete Institutional Analysis

## Executive Summary

**System Purpose**: PutsEngine is a sophisticated PUT options detection algorithm designed to identify stocks likely to move **-3% to -20% within 1-10 days** using dealer microstructure, options flow analysis, and institutional distribution patterns.

**Key Philosophy**:
- Calls = acceleration engines (front-run emotion)
- Puts = permission engines (front-run information)
- Flow is leading, price is lagging
- Empty days are a feature, not a bug

---

## 📊 Table of Contents

1. [System Architecture](#system-architecture)
2. [Data Sources - Complete API Analysis](#data-sources)
3. [Pipeline Flow - Step by Step](#pipeline-flow)
4. [Layer-by-Layer Deep Dive](#layer-analysis)
5. [Indicators & Signals Catalog](#indicators-catalog)
6. [Scoring Model Breakdown](#scoring-model)
7. [Data Freshness & Latency Analysis](#data-freshness)
8. [CRITICAL GAPS & Missing Data Sources](#critical-gaps)
9. [Recommendations for -3% to -10% Detection](#recommendations)
10. [API Call Inventory](#api-call-inventory)

---

## 1. System Architecture {#system-architecture}

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        PUTSENGINE PIPELINE ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────────┘

                                    DATA SOURCES
                    ┌──────────────────┬──────────────────┬──────────────────┐
                    │      ALPACA      │     POLYGON      │  UNUSUAL WHALES  │
                    │   (Execution)    │  (Market Data)   │   (Flow Data)    │
                    └────────┬─────────┴────────┬─────────┴────────┬─────────┘
                             │                  │                   │
                             ▼                  ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: MARKET REGIME (BINARY KILL-SWITCH)                                     │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ ✓ SPY/QQQ Below VWAP      ✓ Index GEX ≤ Neutral      ✓ VIX Rising/Stable  │ │
│ │ ✗ Index Pinned (+GEX)     ✗ Passive Inflows          ✗ Buyback Window     │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                            │
│                         IF BLOCKED → NO TRADE                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │ PASS
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: UNIVERSE SCAN → SHORTLIST (≤15 Names)                                  │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ • 160+ tickers across 16 sectors                                           │ │
│ │ • Top 30 daily losers (Polygon API)                                        │ │
│ │ • Filter: Down day, Volume > Avg, Below VWAP                               │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: DISTRIBUTION DETECTION (PRIMARY ALPHA - 30% Weight)                    │
│ ┌───────────────────────────────┬───────────────────────────────────────────┐  │
│ │ PRICE-VOLUME SIGNALS          │ OPTIONS-LED SIGNALS                       │  │
│ │ • Flat price + rising volume  │ • Call selling at bid                     │  │
│ │ • Failed breakout (high vol)  │ • Put buying at ask                       │  │
│ │ • Lower highs + flat RSI      │ • Rising put OI                           │  │
│ │ • VWAP loss + failed reclaim  │ • Skew steepening                         │  │
│ └───────────────────────────────┴───────────────────────────────────────────┘  │
│                            ┌────────────────────┐                               │
│                            │ DARK POOL SIGNALS  │                               │
│                            │ • Repeated sell    │                               │
│                            │   blocks at level  │                               │
│                            └────────────────────┘                               │
│                                                                                  │
│ REQUIREMENT: ≥2 Price-Volume signals for valid setup                            │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: LIQUIDITY VACUUM DETECTION (15% Weight)                                │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ • Bid size collapsing (< 30% of avg trade size)                            │ │
│ │ • Spread widening (> 1.5x normal)                                          │ │
│ │ • Volume up, price progress down                                           │ │
│ │ • VWAP retest failures (≥2 failed reclaims)                                │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│ KEY INSIGHT: Downside accelerates ONLY when buyers step away                    │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: ACCELERATION WINDOW (TIMING)                                           │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ ENTRY CONFIRMATION:                    │ HARD BLOCK (LATE ENTRY):          │ │
│ │ • Price < VWAP, 20-EMA, prior low     │ • IV spike >20% same session      │ │
│ │ • Failed reclaim attempts              │ • Put volume explosion late day   │ │
│ │ • Put volume rising + IV reasonable    │ • Price already down >5% today    │ │
│ │ • Net delta negative                   │                                   │ │
│ │ • Gamma flipping short                 │                                   │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│ CRITICAL: Late puts = negative expectancy (IV already expanded)                 │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 6: DEALER POSITIONING (MANDATORY GATE - 20% Weight)                       │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ GEX ANALYSIS:                          │ PUT WALL DETECTION:               │ │
│ │ • Net GEX (call_gex + put_gex)         │ • High put OI within ±1% of price│ │
│ │ • Dealer delta exposure                │ • Historical bounces from level  │ │
│ │ • GEX flip level vs current price      │ • >20% of total put OI at strike │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│ BLOCK CONDITIONS:                                                                │
│ • Positive GEX → dealers buy dips (mean reversion)                              │
│ • Price at put wall → dealers will defend (support)                             │
│ • Price above GEX flip → dealers long gamma                                     │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 7: FINAL SCORING (COMPOSITE ≥ 0.68 REQUIRED)                              │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ COMPONENT                    │ WEIGHT │ DESCRIPTION                        │ │
│ │──────────────────────────────┼────────┼────────────────────────────────────│ │
│ │ Distribution Quality         │  30%   │ Price-volume + options signals     │ │
│ │ Dealer Positioning           │  20%   │ GEX, delta, put wall analysis      │ │
│ │ Liquidity Vacuum             │  15%   │ Bid collapse, spread widening      │ │
│ │ Options Flow Quality         │  15%   │ Sweeps, blocks, aggressive buys    │ │
│ │ Catalyst Proximity           │  10%   │ Earnings, events (STUB)            │ │
│ │ Sentiment Divergence         │   5%   │ Price vs sentiment (STUB)          │ │
│ │ Technical Alignment          │   5%   │ VWAP, EMA, prior low              │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 8: STRIKE/DTE SELECTION                                                   │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ CONSTRAINTS:                           │ SELECTION CRITERIA:               │ │
│ │ • DTE: 7-21 days only                  │ • Ideal delta: -0.30 to -0.35    │ │
│ │ • Delta: -0.25 to -0.40                │ • Spread < 10%                   │ │
│ │ • Strike: 5-15% OTM                    │ • Min volume: 100                │ │
│ │ • NO lottery puts (<20% OTM)           │ • Min OI: 500                    │ │
│ │ • Premium: $1-$5 preferred             │ • DTE: 14-17 ideal               │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 9: TRADE EXECUTION                                                        │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ • Position sizing: 2% max risk per trade, 5% max position                  │ │
│ │ • Order type: Limit at mid-price                                           │ │
│ │ • Max daily trades: 2                                                       │ │
│ │ • Execution via Alpaca API                                                 │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Sources - Complete API Analysis {#data-sources}

### 2.1 Alpaca Trading API

**Base URLs**:
- Trading: `https://paper-api.alpaca.markets/v2`
- Market Data: `https://data.alpaca.markets/v2`
- Options Data: `https://data.alpaca.markets/v1beta1`

| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|------------|
| `/account` | GET | Account info, equity balance | Unlimited |
| `/positions` | GET | Open positions | Unlimited |
| `/orders` | POST | Submit trade orders | Unlimited |
| `/orders/{id}` | GET/DELETE | Order status/cancel | Unlimited |
| `/stocks/{symbol}/bars` | GET | Historical OHLCV bars | Unlimited |
| `/stocks/{symbol}/quotes/latest` | GET | Real-time bid/ask | Unlimited |
| `/stocks/{symbol}/trades/latest` | GET | Real-time last trade | Unlimited |
| `/stocks/{symbol}/snapshot` | GET | Comprehensive snapshot | Unlimited |
| `/stocks/bars` | GET | Multi-symbol bars | Unlimited |
| `/options/contracts` | GET | Options chain | Unlimited |
| `/options/quotes/latest` | GET | Options quotes (100 max) | Unlimited |
| `/options/trades` | GET | Options trades | Unlimited |
| `/options/snapshots/{underlying}` | GET | All options for symbol | Unlimited |
| `/assets` | GET | Tradeable assets | Unlimited |
| `/clock` | GET | Market open status | Unlimited |
| `/calendar` | GET | Market calendar | Unlimited |

**DATA FRESHNESS**: ⚡ **REAL-TIME** (Streaming available)

---

### 2.2 Polygon.io Market Data API

**Base URL**: `https://api.polygon.io`

| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|------------|
| `/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from}/{to}` | GET | Historical bars | 5/sec |
| `/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}` | GET | Single stock snapshot | 5/sec |
| `/v2/snapshot/locale/us/markets/stocks/tickers` | GET | All tickers snapshot | 5/sec |
| `/v2/snapshot/locale/us/markets/stocks/losers` | GET | Top losers | 5/sec |
| `/v2/snapshot/locale/us/markets/stocks/gainers` | GET | Top gainers | 5/sec |
| `/v3/reference/options/contracts/{symbol}` | GET | Option contract details | 5/sec |
| `/v3/reference/options/contracts` | GET | Options chain | 5/sec |
| `/v3/snapshot/options/{underlying}` | GET | Options snapshot | 5/sec |
| `/v3/quotes/{symbol}` | GET | Historical quotes | 5/sec |
| `/v1/indicators/sma/{symbol}` | GET | Simple Moving Average | 5/sec |
| `/v1/indicators/ema/{symbol}` | GET | Exponential Moving Average | 5/sec |
| `/v1/indicators/rsi/{symbol}` | GET | Relative Strength Index | 5/sec |
| `/v1/indicators/macd/{symbol}` | GET | MACD | 5/sec |
| `/v3/reference/tickers/{symbol}` | GET | Ticker details | 5/sec |
| `/v1/related-companies/{symbol}` | GET | Related companies | 5/sec |
| `/v1/marketstatus/upcoming` | GET | Market holidays | 5/sec |
| `/v1/marketstatus/now` | GET | Current market status | 5/sec |
| `/v2/reference/news` | GET | News articles | 5/sec |
| `/v3/trades/{symbol}` | GET | Historical trades | 5/sec |

**DATA FRESHNESS**: ⚡ **REAL-TIME** (15-min delay on free tier, real-time on paid)

---

### 2.3 Unusual Whales API

**Base URL**: `https://api.unusualwhales.com`

| Endpoint | Method | Purpose | Daily Limit |
|----------|--------|---------|-------------|
| `/api/stock/{ticker}/flow-recent` | GET | Recent options flow | 5,000/day |
| `/api/stock/{ticker}/flow-alerts` | GET | Flow alerts | 5,000/day |
| `/api/darkpool/{ticker}` | GET | Dark pool prints | 5,000/day |
| `/api/darkpool/recent` | GET | Global dark pool | 5,000/day |
| `/api/stock/{ticker}/greeks` | GET | Greeks data | 5,000/day |
| `/api/stock/{ticker}/greek-exposure` | GET | GEX/DEX | 5,000/day |
| `/api/stock/{ticker}/options-volume` | GET | Options volume | 5,000/day |
| `/api/stock/{ticker}/oi-change` | GET | OI changes | 5,000/day |
| `/api/stock/{ticker}/oi-per-strike` | GET | OI by strike | 5,000/day |
| `/api/stock/{ticker}/oi-per-expiry` | GET | OI by expiry | 5,000/day |
| `/api/stock/{ticker}/iv-rank` | GET | IV rank | 5,000/day |
| `/api/stock/{ticker}/historical-risk-reversal-skew` | GET | Skew data | 5,000/day |
| `/api/stock/{ticker}/volatility/term-structure` | GET | IV term structure | 5,000/day |
| `/api/stock/{ticker}/max-pain` | GET | Max pain level | 5,000/day |
| `/api/market/market-tide` | GET | Market-wide flow | 5,000/day |
| `/api/market/spike` | GET | Market spikes | 5,000/day |
| `/api/market/{sector}/sector-tide` | GET | Sector flow | 5,000/day |
| `/api/stock/{ticker}/info` | GET | Stock info | 5,000/day |
| `/api/stock/{ticker}/expiry-breakdown` | GET | Expiry breakdown | 5,000/day |
| `/api/option-trades/flow-alerts` | GET | Global flow alerts | 5,000/day |
| `/api/insider/{ticker}` | GET | **Insider trades** | 5,000/day |
| `/api/congress/recent-trades` | GET | **Congressional trades** | 5,000/day |

**DATA FRESHNESS**: ⚡ **NEAR REAL-TIME** (15-30 min delay typical for flow data)

---

## 3. Pipeline Flow - Step by Step {#pipeline-flow}

### Execution Windows

| Time (ET) | Phase | Activity |
|-----------|-------|----------|
| 09:30-10:30 | Initial Scan | Overextension check, VWAP analysis |
| 10:30-12:00 | Flow Analysis | Put flow, call selling detection |
| 14:30-15:30 | Final Confirmation | Dealer check, execution |

### Step-by-Step Flow

```
1. INITIALIZATION
   └─→ Load API clients (Alpaca, Polygon, Unusual Whales)
   └─→ Load configuration (thresholds, weights, constraints)
   └─→ Initialize all analysis layers

2. MARKET REGIME CHECK (GATE)
   └─→ Get SPY/QQQ minute bars (Polygon)
   └─→ Calculate VWAP for indices
   └─→ Check if indices below VWAP
   └─→ Get VIX data (Polygon - VIX or VIXY)
   └─→ Get index GEX (Unusual Whales - SPY, QQQ)
   └─→ Check for passive inflow window (calendar logic)
   └─→ DECISION: Trade or Block

3. UNIVERSE SCAN
   └─→ Get top 30 losers (Polygon gainers/losers API)
   └─→ Load sector universe (160+ tickers)
   └─→ For each ticker:
       └─→ Get snapshot (Polygon)
       └─→ Filter: Down today, Below VWAP, Volume > 0.8x previous
   └─→ Build shortlist (max 15 names)

4. DISTRIBUTION ANALYSIS (For each shortlist candidate)
   └─→ Get 30 days daily bars (Polygon)
   └─→ Get 2 days minute bars (Polygon)
   └─→ Calculate: RSI, VWAP, price patterns
   └─→ Get put flow (Unusual Whales)
   └─→ Get call selling flow (Unusual Whales)
   └─→ Get OI changes (Unusual Whales)
   └─→ Get skew data (Unusual Whales)
   └─→ Get dark pool prints (Unusual Whales)
   └─→ Score distribution (requires ≥2 price-volume signals)

5. LIQUIDITY VACUUM CHECK
   └─→ Get minute bars (Polygon)
   └─→ Get latest quote (Alpaca)
   └─→ Get snapshot (Polygon)
   └─→ Get trades for bid collapse calc (Polygon)
   └─→ Detect: Bid collapse, spread widening, VWAP failures

6. ACCELERATION WINDOW CHECK
   └─→ Get 5 days minute bars (Polygon)
   └─→ Get 30 days daily bars (Polygon)
   └─→ Calculate: VWAP, 20-EMA, prior low
   └─→ Check price weakness signals
   └─→ Get options volume/IV data (Unusual Whales)
   └─→ Get GEX data for delta/gamma (Unusual Whales)
   └─→ LATE ENTRY CHECK: IV spike, volume explosion, price drop

7. DEALER POSITIONING CHECK (GATE)
   └─→ Get latest quote (Alpaca)
   └─→ Get GEX data (Unusual Whales)
   └─→ Get OI by strike (Unusual Whales)
   └─→ Detect put wall
   └─→ Check GEX positivity
   └─→ DECISION: Block or Pass

8. FINAL SCORING
   └─→ Calculate component scores
   └─→ Apply weights
   └─→ Composite score ≥ 0.68 → Actionable

9. STRIKE/DTE SELECTION
   └─→ Get valid expirations (7-21 DTE, Fridays)
   └─→ Get options chain (Alpaca)
   └─→ Get options quotes (Alpaca)
   └─→ Filter by: DTE, delta, spread, liquidity
   └─→ Rank and select best contract

10. EXECUTION
    └─→ Calculate position size (2% risk, 5% max position)
    └─→ Submit limit order (Alpaca)
    └─→ Monitor fill
```

---

## 4. Layer-by-Layer Deep Dive {#layer-analysis}

### Layer 1: Market Regime

**Purpose**: Binary kill-switch that prevents trading in unfavorable conditions.

**Logic**:
```python
is_tradeable = (
    len(block_reasons) == 0 AND
    (SPY_below_VWAP OR QQQ_below_VWAP) AND
    VIX_change >= -0.05  # VIX not collapsing
)
```

**Block Conditions**:
| Condition | Threshold | Rationale |
|-----------|-----------|-----------|
| Positive GEX | > 0 × 1.5 | Dealers long gamma → buy dips |
| Index Pinned | SPY + QQQ both above VWAP | Strong support regime |
| Passive Inflows | Day 1-3 or 28-31 of month | Rebalancing flows |
| Quarter End | Last 5 days of Q | Window dressing |

**Data Sources Used**:
- Polygon: SPY/QQQ minute bars, VIX daily bars
- Unusual Whales: SPY/QQQ GEX data

---

### Layer 2: Distribution Detection

**Purpose**: Identify smart money selling before price breaks down.

**Signal Categories**:

| Category | Signal | Detection Logic |
|----------|--------|-----------------|
| **Price-Volume** | Flat Price + Rising Volume | Price range < 2% + volume up > 20% |
| **Price-Volume** | Failed Breakout | Touch resistance + close 2% below + high volume |
| **Price-Volume** | Lower Highs + Flat RSI | Highs declining but RSI stable |
| **Price-Volume** | VWAP Loss | Below VWAP + ≥2 failed reclaim attempts |
| **Options Flow** | Call Selling at Bid | $50K+ premium at bid side |
| **Options Flow** | Put Buying at Ask | $50K+ premium at ask side |
| **Options Flow** | Rising Put OI | >10% increase in put OI |
| **Options Flow** | Skew Steepening | Put IV - Call IV increasing > 5% |
| **Dark Pool** | Repeated Sell Blocks | 3+ blocks at same level, 50K+ shares |

**Scoring**:
- Requires ≥2 price-volume signals (HARD REQUIREMENT)
- Price-volume: 15% each (max 40%)
- Options signals: 15% each
- Dark pool: 15%

---

### Layer 3: Liquidity Vacuum

**Purpose**: Confirm that buyers have stepped away, enabling downside acceleration.

| Signal | Detection Logic | Threshold |
|--------|-----------------|-----------|
| Bid Collapse | Current bid size vs avg trade size | < 30% |
| Spread Widening | Current spread vs normal spread | > 1.5× |
| Volume No Progress | High volume + minimal price movement | Vol > 1.5× avg + price < 0.5% |
| VWAP Retest Failed | Touch VWAP + close below (count) | ≥ 2 failures |

**Key Insight**: "Selling alone doesn't crash stocks. The absence of buyers is what allows prices to fall rapidly."

---

### Layer 4: Acceleration Window

**Purpose**: Entry timing to avoid buying puts after the move has started.

**Entry Confirmation Requirements**:
| Signal | Condition |
|--------|-----------|
| Price Below VWAP | Current < VWAP |
| Price Below 20-EMA | Current < EMA(20, daily) |
| Price Below Prior Low | Current < Yesterday's low |
| Failed Reclaim | ≥2 VWAP reclaim failures |
| Put Volume Rising | Put volume > 1.2× average |
| IV Reasonable | IV rank < 70% + IV change < 20% |
| Net Delta Negative | Dealer delta < 0 |
| Gamma Flipping | Price < GEX flip level OR net GEX < 0 |

**HARD BLOCKS (Late Entry)**:
| Condition | Threshold | Rationale |
|-----------|-----------|-----------|
| IV Spike | > 20% same session | Already priced in |
| Volume Explosion | 2× avg in last hour + 3% drop | Late to party |
| Already Broken | > 5% down from day high | Move happened |

---

### Layer 5: Dealer Positioning

**Purpose**: Ensure dealer hedging flows don't work against the trade.

**GEX Analysis**:
```
Net GEX = Call GEX + Put GEX

If Net GEX > 0:
  → Dealers LONG gamma
  → They BUY dips (mean reversion)
  → BLOCKS puts

If Net GEX < 0:
  → Dealers SHORT gamma
  → They SELL dips (trend amplification)
  → FAVORABLE for puts
```

**Put Wall Detection**:
```
Put Wall = Strike with:
  - >20% of total put OI at that strike
  - Within ±1% of current price
  - Historical bounces from level

If Put Wall detected near price → BLOCK
```

---

## 5. Indicators & Signals Catalog {#indicators-catalog}

### Technical Indicators Currently Used

| Indicator | Calculation | Purpose | Source |
|-----------|-------------|---------|--------|
| **VWAP** | Σ(Typical Price × Volume) / Σ(Volume) | Institutional fair value | Calculated in-house |
| **RSI** | 100 - 100/(1 + RS) where RS = Avg Gain / Avg Loss | Momentum/Overbought | Calculated in-house |
| **EMA(20)** | Weighted average with decay factor | Trend direction | Calculated in-house |
| **Prior Day Low** | Previous session's low | Support level | Polygon bars |
| **Volume Ratio** | Current Vol / Avg Vol | Participation | Polygon bars |
| **Spread %** | (Ask - Bid) / Mid | Liquidity quality | Alpaca/Polygon quotes |

### Options Flow Indicators

| Indicator | Source | Purpose |
|-----------|--------|---------|
| **Net GEX** | Unusual Whales | Dealer gamma exposure |
| **Dealer Delta** | Unusual Whales | Dealer directional exposure |
| **GEX Flip Level** | Unusual Whales | Price where dealers flip |
| **Put Wall** | Unusual Whales | Max put OI strike |
| **Call Wall** | Unusual Whales | Max call OI strike |
| **IV Rank** | Unusual Whales | IV percentile |
| **IV Change** | Unusual Whales | Same-day IV movement |
| **Put/Call OI Ratio** | Unusual Whales | Sentiment |
| **Skew** | Unusual Whales | Put vs Call IV premium |
| **Flow Sentiment** | Unusual Whales | Aggressive buy/sell side |

---

## 6. Scoring Model Breakdown {#scoring-model}

```
COMPOSITE_SCORE = 
    0.30 × Distribution_Score +
    0.20 × Dealer_Score +
    0.15 × Liquidity_Score +
    0.15 × Flow_Score +
    0.10 × Catalyst_Score +      ← STUB (returns 0.5)
    0.05 × Sentiment_Score +     ← STUB (returns 0.5)
    0.05 × Technical_Score

ACTIONABLE THRESHOLD: ≥ 0.68
```

### Score Calculations

**Distribution Score** (max 1.0):
```python
if price_volume_signals < 2:
    return 0.0  # Hard requirement

score = min(price_volume_count × 0.15, 0.40)  # Cap at 40%
score += options_signal_count × 0.15
score += 0.15 if repeated_sell_blocks else 0
return min(score, 1.0)
```

**Dealer Score** (max 1.0):
```python
if is_blocked:
    return 0.0

score = 0.5  # Start neutral
if net_gex < 0:
    score += 0.25
    if net_gex < -1,000,000:
        score += 0.15
if dealer_delta < 0:
    score += 0.10
if price < gex_flip_level:
    score += 0.15
return min(max(score, 0.0), 1.0)
```

**Liquidity Score** (max 1.0):
```python
signals = [bid_collapsing, spread_widening, volume_no_progress, vwap_retest_failed]
return min(sum(signals) × 0.25, 1.0)
```

**Technical Score** (max 1.0):
```python
score = 0
if price_below_vwap: score += 0.25
if price_below_ema20: score += 0.25
if price_below_prior_low: score += 0.25
if failed_reclaim: score += 0.25
return min(score, 1.0)
```

---

## 7. Data Freshness & Latency Analysis {#data-freshness}

### Current Data Freshness

| Data Type | Source | Freshness | Latency | Assessment |
|-----------|--------|-----------|---------|------------|
| Stock Quotes | Alpaca | Real-time | <1s | ✅ EXCELLENT |
| Stock Bars | Polygon | Real-time* | 1-15min | ⚠️ DEPENDS ON PLAN |
| Options Quotes | Alpaca | Real-time | <1s | ✅ EXCELLENT |
| Options Chain | Alpaca | Real-time | <1s | ✅ EXCELLENT |
| Options Flow | Unusual Whales | Near real-time | 15-30min | ⚠️ ACCEPTABLE |
| Dark Pool | Unusual Whales | Delayed | 15-60min | ⚠️ ACCEPTABLE |
| GEX Data | Unusual Whales | End of day refresh | ~24h | ❌ STALE |
| OI Data | Unusual Whales | End of day | ~24h | ❌ STALE |
| Insider Trades | Unusual Whales | Delayed | Days-weeks | ❌ VERY STALE |
| News | Polygon | Near real-time | Minutes | ✅ GOOD |

### Critical Freshness Issues

1. **GEX/OI Data is STALE**: Updated daily, not intraday
   - Impact: Dealer positioning may have changed significantly
   - Mitigation: Weight more heavily on flow data

2. **Dark Pool Delay**: 15-60 minute delay
   - Impact: Large block prints may be outdated
   - Mitigation: Use for confirmation, not primary signal

3. **Insider Data is VERY STALE**: SEC filings have 2-day delay minimum
   - Impact: By the time you see it, market may have reacted
   - Mitigation: Use for pattern recognition, not timing

---

## 8. CRITICAL GAPS & Missing Data Sources {#critical-gaps}

### 🚨 HIGH-PRIORITY GAPS

#### 1. **Catalyst/Earnings Calendar - NOT IMPLEMENTED**
```
CURRENT: Returns hardcoded 0.5 (neutral)
IMPACT: Missing 10% of scoring weight
NEEDED: 
  - Earnings dates (whisper numbers, beat/miss history)
  - FDA decisions
  - Product launches
  - Conference schedules
  - Ex-dividend dates

RECOMMENDED DATA SOURCES:
  - Earnings Whispers API
  - FDA calendar API
  - Benzinga Calendar API
  - Alpha Vantage Earnings
```

#### 2. **Sentiment Analysis - NOT IMPLEMENTED**
```
CURRENT: Returns hardcoded 0.5 (neutral)
IMPACT: Missing 5% of scoring weight + major alpha source
NEEDED:
  - Social media sentiment (Twitter/X, Reddit, StockTwits)
  - News sentiment scoring
  - Analyst sentiment changes
  - Short interest data
  - Retail vs institutional positioning

RECOMMENDED DATA SOURCES:
  - Quiver Quantitative (Reddit/Congress)
  - Sentifi (social sentiment)
  - MarketBeat (analyst data)
  - FINRA (short interest)
  - Refinitiv (institutional)
```

#### 3. **Real-Time GEX - MISSING**
```
CURRENT: Using end-of-day GEX from Unusual Whales
IMPACT: Dealer positioning can flip intraday
NEEDED: Intraday GEX updates

RECOMMENDED:
  - SpotGamma subscription ($200-500/mo)
  - Calculate from options chain (complex)
  - Unusual Whales real-time (premium tier)
```

#### 4. **Insider Trading - USED BUT UNDERUTILIZED**
```
CURRENT: API endpoint exists but NOT used in analysis
IMPACT: Missing major predictive signal
NEEDED:
  - C-level selling clusters
  - 10b5-1 plan modifications
  - Form 4 filing patterns
  - Insider buying sprees

ALREADY AVAILABLE:
  - Unusual Whales: /api/insider/{ticker}
  - Unusual Whales: /api/congress/recent-trades
  
ACTION: Integrate into Distribution or Catalyst layer
```

#### 5. **Global Events/Macro - NOT IMPLEMENTED**
```
CURRENT: No macro integration
IMPACT: Missing systemic risk factors
NEEDED:
  - FOMC meeting dates
  - CPI/PPI release dates
  - Geopolitical risk indicators
  - Currency movements
  - Bond yield spikes
  - Sector rotation signals

RECOMMENDED DATA SOURCES:
  - FRED API (Federal Reserve)
  - Trading Economics
  - Quandl
```

#### 6. **Short Interest - NOT IMPLEMENTED**
```
CURRENT: No short interest analysis
IMPACT: Missing squeeze/cover dynamics
NEEDED:
  - Days to cover
  - Short interest % float
  - Short interest changes
  - Cost to borrow

RECOMMENDED DATA SOURCES:
  - FINRA short interest (bi-weekly, free)
  - Ortex (daily, paid)
  - S3 Partners (real-time, expensive)
```

#### 7. **Institutional Holdings (13F) - NOT IMPLEMENTED**
```
CURRENT: No institutional flow tracking
IMPACT: Missing "smart money" positioning
NEEDED:
  - 13F filing changes
  - Hedge fund positioning
  - Mutual fund flows

RECOMMENDED DATA SOURCES:
  - SEC EDGAR (free, delayed)
  - WhaleWisdom
  - Fintel
```

#### 8. **Order Flow Imbalance - NOT IMPLEMENTED**
```
CURRENT: Using aggregated flow, not imbalance
IMPACT: Missing micro-structure alpha
NEEDED:
  - Real-time order imbalance
  - Level 2 bid/ask depth changes
  - Trade classification (buy/sell side)

RECOMMENDED DATA SOURCES:
  - Alpaca Level 2 (subscription)
  - Polygon Level 2
  - IEX Exchange data
```

---

## 9. Recommendations for -3% to -10% Detection {#recommendations}

### Immediate Actions (High Impact, Low Effort)

#### 1. **Activate Insider Trading Analysis**
```python
# In distribution.py, add:
async def _analyze_insider_flow(self, symbol: str) -> Dict[str, bool]:
    insider_trades = await self.unusual_whales.get_insider_trades(symbol, limit=30)
    
    # Look for:
    # - C-level selling clusters (3+ execs selling in 7 days)
    # - Large sales relative to holding
    # - Sales before earnings
    
    c_level_selling = False
    large_sales = False
    
    for trade in insider_trades:
        if trade.get('title') in ['CEO', 'CFO', 'COO', 'CTO']:
            if trade.get('transaction_type') == 'Sale':
                c_level_selling = True
    
    return {
        'c_level_selling': c_level_selling,
        'insider_cluster': len([t for t in insider_trades if t.get('transaction_type') == 'Sale']) >= 3
    }
```

#### 2. **Implement Basic Earnings Detection**
```python
# Add to catalyst scoring:
async def _score_catalyst(self, symbol: str) -> float:
    # Use Polygon news to detect earnings proximity
    news = await self.polygon.get_ticker_news(symbol, limit=20)
    
    earnings_keywords = ['earnings', 'quarterly', 'Q1', 'Q2', 'Q3', 'Q4', 'guidance']
    
    for article in news:
        title = article.get('title', '').lower()
        if any(kw in title for kw in earnings_keywords):
            # Earnings proximity detected
            return 0.7  # Elevated risk
    
    return 0.5  # Neutral
```

#### 3. **Add News Sentiment Analysis**
```python
# Simple keyword-based sentiment:
async def _analyze_news_sentiment(self, symbol: str) -> float:
    news = await self.polygon.get_ticker_news(symbol, limit=10)
    
    bearish_keywords = ['downgrade', 'miss', 'cut', 'lower', 'warning', 'concern', 'weak', 'decline']
    bullish_keywords = ['upgrade', 'beat', 'raise', 'strong', 'growth', 'record']
    
    bearish_count = 0
    bullish_count = 0
    
    for article in news:
        text = (article.get('title', '') + ' ' + article.get('description', '')).lower()
        bearish_count += sum(1 for kw in bearish_keywords if kw in text)
        bullish_count += sum(1 for kw in bullish_keywords if kw in text)
    
    if bearish_count > bullish_count * 1.5:
        return 0.8  # Bearish sentiment
    elif bullish_count > bearish_count * 1.5:
        return 0.2  # Bullish sentiment
    return 0.5  # Neutral
```

### Medium-Term Actions (High Impact, Medium Effort)

#### 4. **Integrate Short Interest Data**
Add FINRA short interest (free, bi-weekly):
```python
# New file: putsengine/clients/finra_client.py
class FinraClient:
    """Client for FINRA short interest data."""
    
    async def get_short_interest(self, symbol: str) -> Dict:
        # Scrape or API call to FINRA
        # Return: short_interest_pct, days_to_cover, change_from_prior
        pass
```

#### 5. **Add Congressional Trading Alerts**
```python
# In distribution layer:
async def _check_congress_trades(self, symbol: str) -> bool:
    # Already available via Unusual Whales
    congress = await self.unusual_whales.get_congress_trades(limit=50)
    
    for trade in congress:
        if trade.get('ticker') == symbol:
            if trade.get('transaction_type') == 'Sale':
                return True  # Congress member selling
    return False
```

### Long-Term Actions (High Impact, High Effort)

#### 6. **Real-Time GEX Calculation**
Build intraday GEX from options chain:
```python
async def calculate_realtime_gex(self, symbol: str) -> float:
    """Calculate GEX from current options chain."""
    contracts = await self.alpaca.get_options_snapshots(symbol)
    
    net_gex = 0
    spot = await self.alpaca.get_latest_quote(symbol)
    spot_price = spot['quote']['ap']
    
    for contract in contracts:
        strike = contract['strike']
        oi = contract['open_interest']
        gamma = contract['greeks']['gamma']
        
        # GEX = OI × Gamma × 100 × Spot²
        contract_gex = oi * gamma * 100 * (spot_price ** 2)
        
        if contract['type'] == 'call':
            net_gex += contract_gex
        else:
            net_gex -= contract_gex  # Puts have opposite dealer exposure
    
    return net_gex
```

#### 7. **Social Sentiment Integration**
Add Reddit/Twitter monitoring:
```python
# Consider: Quiver Quantitative API for Reddit wallstreetbets mentions
# Or: Build custom scraper for StockTwits
```

---

## 10. API Call Inventory {#api-call-inventory}

### Per-Symbol API Calls (Deep Analysis)

| Layer | Endpoint | Source | Calls |
|-------|----------|--------|-------|
| Market Regime | Minute bars SPY | Polygon | 1 |
| Market Regime | Minute bars QQQ | Polygon | 1 |
| Market Regime | Daily bars VIX | Polygon | 1 |
| Market Regime | GEX SPY | UW | 1 |
| Market Regime | GEX QQQ | UW | 1 |
| **Subtotal** | | | **5** |
| Distribution | Daily bars | Polygon | 1 |
| Distribution | Minute bars | Polygon | 1 |
| Distribution | Put flow | UW | 1 |
| Distribution | Call selling flow | UW | 1 |
| Distribution | OI change | UW | 1 |
| Distribution | Skew | UW | 1 |
| Distribution | Dark pool | UW | 1 |
| **Subtotal** | | | **7** |
| Liquidity | Minute bars | Polygon | 1 |
| Liquidity | Latest quote | Alpaca | 1 |
| Liquidity | Snapshot | Polygon | 1 |
| Liquidity | Trades | Polygon | 1 |
| **Subtotal** | | | **4** |
| Acceleration | Minute bars | Polygon | 1 |
| Acceleration | Daily bars | Polygon | 1 |
| Acceleration | Options volume | UW | 1 |
| Acceleration | GEX | UW | 1 |
| Acceleration | Quote | Alpaca | 1 |
| **Subtotal** | | | **5** |
| Dealer | Quote | Alpaca | 1 |
| Dealer | GEX | UW | 1 |
| Dealer | OI by strike | UW | 1 |
| **Subtotal** | | | **3** |
| Strike Select | Options chain (5 exp) | Alpaca | 5 |
| Strike Select | Options quotes | Alpaca | 1 |
| **Subtotal** | | | **6** |
| **TOTAL PER SYMBOL** | | | **30** |

### Daily Budget Analysis

```
Unusual Whales Budget: 5,000 calls/day

Per Symbol Deep Analysis:
- UW Calls: 10 (flow, OI, GEX, skew, dark pool)

Universe Scan (shortlist building):
- Polygon snapshot per symbol: ~160 calls

Daily Pipeline:
- Market Regime: 5 UW calls
- Shortlist Build: ~15 symbols × 10 UW = 150 UW calls
- Total UW: ~155 calls

Remaining UW Budget: 5,000 - 155 = ~4,845 calls

PLENTY OF HEADROOM for additional data sources!
```

---

## 11. Summary & Action Items

### Current System Strengths ✅

1. **Solid Multi-Layer Architecture**: 6 sequential gates ensure quality over quantity
2. **Good Data Source Mix**: Real-time trading + flow data + options analytics
3. **Risk Management Built-In**: Late entry filters, put wall detection, GEX analysis
4. **Professional Scoring Model**: Weighted composite with clear thresholds
5. **Proper Position Sizing**: 2% risk per trade, 5% max position

### Current System Weaknesses ❌

1. **Catalyst Detection**: Hardcoded stub (10% weight)
2. **Sentiment Analysis**: Hardcoded stub (5% weight)
3. **Stale GEX Data**: End-of-day, not intraday
4. **No Insider Integration**: Endpoint exists but unused
5. **No Short Interest**: Missing squeeze dynamics
6. **No Macro Integration**: Blind to FOMC, CPI, etc.

### Priority Action Items

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| 🔴 HIGH | Integrate insider trading analysis | Low | High |
| 🔴 HIGH | Implement basic earnings detection | Low | High |
| 🔴 HIGH | Add news sentiment scoring | Low | Medium |
| 🟡 MEDIUM | Add short interest tracking | Medium | High |
| 🟡 MEDIUM | Implement congressional trade alerts | Low | Medium |
| 🟡 MEDIUM | Calculate real-time GEX | High | High |
| 🟢 LOW | Add macro event calendar | Medium | Medium |
| 🟢 LOW | Integrate social sentiment | High | Medium |

---

## 12. Patterns That Predict -3% to -10% Moves

Based on institutional research and the current system design, here are the patterns most predictive of significant downside moves:

### Tier 1: Highest Conviction (Multiple signals required)

| Pattern | Description | Current Detection |
|---------|-------------|-------------------|
| **Distribution + Flow Divergence** | Price flat/up + heavy put buying | ✅ Yes |
| **Liquidity Vacuum + VWAP Loss** | Buyers stepping away + failed reclaims | ✅ Yes |
| **C-Level Selling Cluster** | 3+ execs selling within 7 days | ❌ No (easy add) |
| **Earnings Miss Setup** | High expectations + distribution | ❌ No (easy add) |

### Tier 2: Strong Conviction

| Pattern | Description | Current Detection |
|---------|-------------|-------------------|
| **Negative GEX Flip** | Dealers go from buying dips to selling dips | ⚠️ Partial (stale data) |
| **Dark Pool Dump** | Repeated large blocks at same level | ✅ Yes |
| **IV Compression Pre-Move** | Calm before storm | ⚠️ Partial |
| **Short Interest Spike** | New shorts piling in | ❌ No |

### Tier 3: Supporting Evidence

| Pattern | Description | Current Detection |
|---------|-------------|-------------------|
| **Failed Breakout** | Rejection at resistance on volume | ✅ Yes |
| **Lower Highs + Flat RSI** | Divergence pattern | ✅ Yes |
| **Analyst Downgrade** | Fresh negative coverage | ❌ No |
| **Congress Selling** | Informed insiders exit | ❌ No (easy add) |

---

## 13. Live Validation Results (January 24, 2026)

### API Connectivity Test Results

```
======================================================================
  VALIDATION SUMMARY - 2026-01-24 17:48
======================================================================
  ✅ ALPACA: OK
     - Account Data: Equity $72,646.20
     - Market Clock: Working
     - Stock Quotes: AAPL Bid: $247.75 Ask: $247.79
     - Stock Bars: Last bar 2026-01-23 Close: $248.04
     - Options Chain: Working (404 on specific dates normal)
     
  ✅ POLYGON: OK
     - Snapshot: AAPL Last Trade $247.75
     - Daily Bars: Working
     - Losers: Top loser INVZW
     - RSI(14): 25.47 (correctly calculated)
     - News: 3 articles found
     
  ✅ UNUSUAL_WHALES: OK
     - Options Flow: 49 flow records found
     - Dark Pool: 10 prints found
     - GEX Data: Working
     - OI by Strike: Working
     - IV Rank: Working
     - Insider Trades: 68 trades found (UNDERUTILIZED!)
     - Congress Trades: 10 trades found (UNDERUTILIZED!)
     
  ✅ PIPELINE: OK
     - Full analysis completes successfully
     - All 6 layers execute properly
     - Scoring model calculates correctly
```

### Current Market Assessment (AAPL Example)

```
  Symbol: AAPL
  Current Price: $247.79
  RSI(14): 25.47 (OVERSOLD - potential bounce candidate)
  
  Market Regime: BULLISH_NEUTRAL
  - SPY Below VWAP: No
  - QQQ Below VWAP: No
  - Index GEX: Neutral
  - VIX: 25.68 (+1.82%)
  - Status: BLOCKED (indices above VWAP)
  
  Distribution Signals (1/9 active):
  ✅ Repeated Sell Blocks (dark pool)
  ⬜ Flat Price Rising Volume
  ⬜ Failed Breakout
  ⬜ Lower Highs Flat RSI
  ⬜ VWAP Loss
  ⬜ Call Selling at Bid
  ⬜ Put Buying at Ask
  ⬜ Rising Put OI
  ⬜ Skew Steepening
  
  RESULT: No distribution detected (needs ≥2 price-volume signals)
```

### Data Freshness Confirmed

| Data Type | Status | Sample Value | Freshness |
|-----------|--------|--------------|-----------|
| Stock Quote | ✅ Real | $247.79 | Real-time |
| Stock Bars | ✅ Real | 2026-01-23 | Same day |
| Options Flow | ✅ Real | 49 records | Near real-time |
| Dark Pool | ✅ Real | 10 prints | 15-60min delay |
| Insider Trades | ✅ Real | 68 trades | Days delay (normal) |
| Congress Trades | ✅ Real | 10 trades | Days delay (normal) |
| RSI | ✅ Real | 25.47 | Real-time calc |
| News | ✅ Real | 3 articles | Minutes delay |

---

## 14. Quick Win: Integrate Insider Trading (Code Ready)

Add this to `/putsengine/layers/distribution.py` after line 430:

```python
async def _analyze_insider_activity(self, symbol: str) -> Dict[str, bool]:
    """
    Analyze insider trading patterns.
    C-level selling clusters are highly predictive of downside.
    """
    signals = {
        "c_level_selling": False,
        "insider_cluster": False,
        "large_sale": False
    }
    
    try:
        insider_trades = await self.unusual_whales.get_insider_trades(symbol, limit=30)
        
        if not insider_trades:
            return signals
            
        # Count C-level sales
        c_level_titles = ['CEO', 'CFO', 'COO', 'CTO', 'President', 'Chairman']
        c_level_sales = 0
        total_sales = 0
        large_sales = 0
        
        for trade in insider_trades:
            title = str(trade.get('title', '')).upper()
            trans_type = str(trade.get('transaction_type', '')).lower()
            value = float(trade.get('value', 0) or 0)
            
            if 'sale' in trans_type or 'sell' in trans_type:
                total_sales += 1
                
                # Check if C-level
                if any(t in title for t in c_level_titles):
                    c_level_sales += 1
                    
                # Check for large sale (>$1M)
                if value > 1_000_000:
                    large_sales += 1
        
        # C-level selling: any C-level exec sold recently
        signals["c_level_selling"] = c_level_sales > 0
        
        # Insider cluster: 3+ insiders selling in period
        signals["insider_cluster"] = total_sales >= 3
        
        # Large sale: any sale >$1M
        signals["large_sale"] = large_sales > 0
        
        if signals["c_level_selling"]:
            logger.info(f"{symbol}: C-level insider selling detected!")
            
    except Exception as e:
        logger.debug(f"Error analyzing insider activity for {symbol}: {e}")
        
    return signals
```

Then call it in the `analyze()` method and add to scoring:
```python
# In analyze() method, add after dark pool analysis:
insider_signals = await self._analyze_insider_activity(symbol)
signal.c_level_selling = insider_signals.get("c_level_selling", False)
signal.insider_cluster = insider_signals.get("insider_cluster", False)
```

---

*Document generated: January 24, 2026*
*Version: 1.1 (Updated with live validation)*
*Analysis Scope: Complete PutsEngine codebase*
*All APIs validated and functional*
