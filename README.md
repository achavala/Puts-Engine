# PutsEngine

**Institutional PUT Options Trading Engine**

A sophisticated algorithm for identifying -5% to -20% moves 1-10 days ahead with asymmetric put P&L, based on dealer microstructure and options flow analysis.

## Architecture

```
DATA
 ↓
MARKET REGIME (Index / Dealer Physics)
 ↓
DISTRIBUTION DETECTION (Supply > Demand)
 ↓
LIQUIDITY VACUUM (Buyers withdraw)
 ↓
ACCELERATION WINDOW (24–48h pre-break)
 ↓
STRIKE / DTE SELECTION
```

**Failure at ANY layer = NO TRADE**

> Empty days are a feature, not a bug.

## Core Principles

- **Calls = acceleration engines** - front-run emotion
- **Puts = permission engines** - front-run information
- **Price is lagging** - if price is the primary signal, engine will fail
- **Flow is leading** - options flow predicts price
- **Liquidity is decisive** - downside accelerates when buyers step away

## Installation

```bash
# Clone the repository
cd /path/to/PutsEngine

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Or install as package
pip install -e .
```

## Configuration

Create a `.env` file with your API credentials:

```env
# Alpaca Trading API
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2

# Polygon.io / Massive Data Provider
POLYGON_API_KEY=your_key

# Unusual Whales API
UNUSUAL_WHALES_API_KEY=your_key

# Engine Configuration
MIN_SCORE_THRESHOLD=0.68
MAX_DAILY_TRADES=2
```

## Usage

### CLI Commands

```bash
# Run daily pipeline (dry run - no actual trades)
python run.py run

# Run with specific symbols
python run.py run --symbols AAPL TSLA NVDA

# Run with live trading (use with caution!)
python run.py run --live

# Analyze a single symbol
python run.py analyze AAPL

# Check market regime only
python run.py regime

# Show status
python run.py status
```

### Python API

```python
import asyncio
from putsengine import PutsEngine, Settings

async def main():
    # Initialize engine
    engine = PutsEngine()

    try:
        # Run daily pipeline
        report = await engine.run_daily_pipeline()

        # Check results
        print(f"Scanned: {report.total_scanned}")
        print(f"Candidates: {report.passed_gates}")

        for candidate in report.candidates:
            print(f"  {candidate.symbol}: {candidate.composite_score:.2f}")

        # Analyze single symbol
        candidate = await engine.run_single_symbol("AAPL")
        print(f"AAPL Score: {candidate.composite_score:.2f}")

    finally:
        await engine.close()

asyncio.run(main())
```

## Scoring Model

| Component                        | Weight |
|----------------------------------|--------|
| Distribution Quality             | 30%    |
| Dealer Positioning (GEX / Delta) | 20%    |
| Liquidity Vacuum                 | 15%    |
| Options Flow Quality             | 15%    |
| Catalyst Proximity               | 10%    |
| Sentiment Divergence             | 5%     |
| Technical Alignment              | 5%     |

**Minimum actionable score: 0.68**

## Strike & DTE Rules

- **DTE:** 7-21 days only
- **Delta:** -0.25 to -0.40
- **Strike:** Slightly OTM (5-15%)
- **No lottery puts**
- **Prefer IV expansion AFTER entry**

## Failure Modes (Hard Blocks)

The engine will NOT trade when:

- Positive GEX regime (index pinned)
- Buyback window active
- Late-day IV spikes (>20%)
- Put wall support near price
- Insufficient distribution signals
- Mean-reversion shorts without distribution

## Daily Execution Windows

| Time        | Activity                          |
|-------------|-----------------------------------|
| 09:30-10:30 | Initial scan (overextension, VWAP)|
| 10:30-12:00 | Flow analysis (puts, call selling)|
| 14:30-15:30 | Final confirmation & execution    |

**Max output: 1-2 PUT candidates per day**

## API Rate Limits

- **Unusual Whales:** 5,000 calls/day (use surgically)
- **Polygon:** 5 requests/second
- **Alpaca:** Unlimited (for paper trading)

## Project Structure

```
putsengine/
├── __init__.py           # Package init
├── config.py             # Configuration
├── models.py             # Data models
├── engine.py             # Main orchestrator
├── cli.py                # CLI interface
├── clients/              # API clients
│   ├── alpaca_client.py
│   ├── polygon_client.py
│   └── unusual_whales_client.py
├── layers/               # Analysis layers
│   ├── market_regime.py
│   ├── distribution.py
│   ├── liquidity.py
│   ├── acceleration.py
│   └── dealer.py
├── scoring/              # Scoring & selection
│   ├── scorer.py
│   └── strike_selector.py
└── utils/                # Utilities
    ├── logging.py
    └── cache.py
```

## Risk Disclaimer

This software is for educational and research purposes only. Trading options involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results. Always consult with a qualified financial advisor before making investment decisions.

## License

MIT License - See LICENSE file for details.
# Puts-Engine
