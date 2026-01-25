#!/usr/bin/env python3
"""
API Validation Script for PutsEngine.
Tests all API connections and reports data freshness.
"""

import asyncio
import sys
import os
from datetime import datetime, date, timedelta
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class APIValidator:
    """Validates all API connections and data quality."""
    
    def __init__(self):
        self.results = {}
        
    def print_header(self, title: str):
        print("\n" + "=" * 70)
        print(f"  {title}")
        print("=" * 70)
        
    def print_result(self, name: str, status: str, details: str = ""):
        icon = "✅" if status == "OK" else "❌" if status == "FAIL" else "⚠️"
        print(f"  {icon} {name}: {status}")
        if details:
            for line in details.split("\n"):
                print(f"      {line}")
                
    async def validate_alpaca(self):
        """Validate Alpaca API connection and data."""
        self.print_header("ALPACA API VALIDATION")
        
        try:
            from putsengine.clients.alpaca_client import AlpacaClient
            from putsengine.config import get_settings
            
            settings = get_settings()
            client = AlpacaClient(settings)
            
            # Test 1: Account
            print("\n  Testing Account Endpoint...")
            account = await client.get_account()
            if account and "equity" in account:
                equity = float(account.get("equity", 0))
                self.print_result("Account Data", "OK", f"Equity: ${equity:,.2f}")
            else:
                self.print_result("Account Data", "FAIL", "No account data returned")
                
            # Test 2: Market Clock
            print("\n  Testing Market Clock...")
            is_open = await client.is_market_open()
            self.print_result("Market Clock", "OK", f"Market Open: {is_open}")
            
            # Test 3: Stock Quote
            print("\n  Testing Stock Quote (AAPL)...")
            quote = await client.get_latest_quote("AAPL")
            if quote and "quote" in quote:
                bid = quote["quote"].get("bp", 0)
                ask = quote["quote"].get("ap", 0)
                self.print_result("Stock Quote", "OK", f"AAPL Bid: ${bid:.2f} Ask: ${ask:.2f}")
            else:
                self.print_result("Stock Quote", "FAIL", "No quote data")
                
            # Test 4: Stock Bars
            print("\n  Testing Stock Bars (AAPL, 1Day)...")
            bars = await client.get_bars("AAPL", timeframe="1Day", limit=5)
            if bars and len(bars) > 0:
                last_bar = bars[-1]
                self.print_result("Stock Bars", "OK", 
                    f"Last bar: {last_bar.timestamp.date()} Close: ${last_bar.close:.2f} Vol: {last_bar.volume:,}")
            else:
                self.print_result("Stock Bars", "FAIL", "No bar data")
                
            # Test 5: Options Chain
            print("\n  Testing Options Chain (AAPL)...")
            today = date.today()
            exp_date = today + timedelta(days=14)
            # Find next Friday
            while exp_date.weekday() != 4:
                exp_date += timedelta(days=1)
                
            contracts = await client.get_options_chain(
                underlying="AAPL",
                expiration_date=exp_date,
                option_type="put"
            )
            if contracts and len(contracts) > 0:
                self.print_result("Options Chain", "OK", 
                    f"Found {len(contracts)} PUT contracts for {exp_date}")
            else:
                self.print_result("Options Chain", "WARN", "No options contracts found (may be weekend)")
                
            await client.close()
            self.results["alpaca"] = "OK"
            
        except Exception as e:
            self.print_result("Alpaca API", "FAIL", str(e))
            self.results["alpaca"] = "FAIL"
            
    async def validate_polygon(self):
        """Validate Polygon API connection and data."""
        self.print_header("POLYGON API VALIDATION")
        
        try:
            from putsengine.clients.polygon_client import PolygonClient
            from putsengine.config import get_settings
            
            settings = get_settings()
            client = PolygonClient(settings)
            
            # Test 1: Snapshot
            print("\n  Testing Snapshot (AAPL)...")
            snapshot = await client.get_snapshot("AAPL")
            if snapshot and "ticker" in snapshot:
                ticker = snapshot["ticker"]
                price = ticker.get("lastTrade", {}).get("p", 0)
                self.print_result("Snapshot", "OK", f"AAPL Last Trade: ${price:.2f}")
            else:
                self.print_result("Snapshot", "FAIL", "No snapshot data")
                
            # Test 2: Daily Bars
            print("\n  Testing Daily Bars (AAPL)...")
            bars = await client.get_daily_bars(
                "AAPL",
                from_date=date.today() - timedelta(days=10)
            )
            if bars and len(bars) > 0:
                last_bar = bars[-1]
                self.print_result("Daily Bars", "OK",
                    f"Last bar: {last_bar.timestamp.date()} Close: ${last_bar.close:.2f}")
            else:
                self.print_result("Daily Bars", "FAIL", "No bar data")
                
            # Test 3: Gainers/Losers
            print("\n  Testing Losers...")
            losers = await client.get_gainers_losers("losers")
            if losers and len(losers) > 0:
                top_loser = losers[0]
                self.print_result("Losers", "OK",
                    f"Top loser: {top_loser.get('ticker', 'N/A')}")
            else:
                self.print_result("Losers", "WARN", "No losers data (market may be closed)")
                
            # Test 4: Technical Indicators
            print("\n  Testing RSI (AAPL)...")
            rsi = await client.get_rsi("AAPL", window=14, timespan="day", limit=5)
            if rsi and len(rsi) > 0:
                last_rsi = rsi[-1]
                self.print_result("RSI", "OK", f"RSI(14): {last_rsi.get('value', 0):.2f}")
            else:
                self.print_result("RSI", "WARN", "No RSI data (may require premium)")
                
            # Test 5: News
            print("\n  Testing News (AAPL)...")
            news = await client.get_ticker_news("AAPL", limit=3)
            if news and len(news) > 0:
                self.print_result("News", "OK", f"Found {len(news)} articles")
                for article in news[:2]:
                    print(f"      - {article.get('title', 'N/A')[:60]}...")
            else:
                self.print_result("News", "WARN", "No news data")
                
            await client.close()
            self.results["polygon"] = "OK"
            
        except Exception as e:
            self.print_result("Polygon API", "FAIL", str(e))
            self.results["polygon"] = "FAIL"
            
    async def validate_unusual_whales(self):
        """Validate Unusual Whales API connection and data."""
        self.print_header("UNUSUAL WHALES API VALIDATION")
        
        try:
            from putsengine.clients.unusual_whales_client import UnusualWhalesClient
            from putsengine.config import get_settings
            
            settings = get_settings()
            client = UnusualWhalesClient(settings)
            
            print(f"\n  Daily API Limit: {client.daily_limit}")
            print(f"  Remaining Calls: {client.remaining_calls}")
            
            # Test 1: Options Flow
            print("\n  Testing Options Flow (AAPL)...")
            flows = await client.get_flow_recent("AAPL", limit=10)
            if flows and len(flows) > 0:
                self.print_result("Options Flow", "OK", f"Found {len(flows)} flow records")
                for flow in flows[:2]:
                    print(f"      - {flow.option_type.upper()} ${flow.strike:.0f} Premium: ${flow.premium:,.0f}")
            else:
                self.print_result("Options Flow", "WARN", "No flow data (check API key)")
                
            # Test 2: Dark Pool
            print("\n  Testing Dark Pool (AAPL)...")
            dp = await client.get_dark_pool_flow("AAPL", limit=10)
            if dp and len(dp) > 0:
                self.print_result("Dark Pool", "OK", f"Found {len(dp)} dark pool prints")
                for print_data in dp[:2]:
                    print(f"      - ${print_data.price:.2f} x {print_data.size:,} shares")
            else:
                self.print_result("Dark Pool", "WARN", "No dark pool data")
                
            # Test 3: GEX Data
            print("\n  Testing GEX Data (AAPL)...")
            gex = await client.get_gex_data("AAPL")
            if gex:
                self.print_result("GEX Data", "OK",
                    f"Net GEX: {gex.net_gex:,.0f}\n"
                    f"      Put Wall: ${gex.put_wall:.2f}" if gex.put_wall else "")
            else:
                self.print_result("GEX Data", "WARN", "No GEX data (check subscription)")
                
            # Test 4: OI by Strike
            print("\n  Testing OI by Strike (AAPL)...")
            oi = await client.get_oi_by_strike("AAPL")
            if oi and oi.get("data"):
                self.print_result("OI by Strike", "OK", f"Found OI data for {len(oi.get('data', []))} strikes")
            else:
                self.print_result("OI by Strike", "WARN", "No OI data")
                
            # Test 5: IV Rank
            print("\n  Testing IV Rank (AAPL)...")
            iv = await client.get_iv_rank("AAPL")
            if iv and iv.get("data"):
                data = iv.get("data", {})
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                iv_rank = data.get("iv_rank", 0)
                self.print_result("IV Rank", "OK", f"IV Rank: {iv_rank:.1f}%")
            else:
                self.print_result("IV Rank", "WARN", "No IV data")
                
            # Test 6: Insider Trades (CRITICAL - UNDERUTILIZED)
            print("\n  Testing Insider Trades (AAPL)...")
            insiders = await client.get_insider_trades("AAPL", limit=10)
            if insiders and len(insiders) > 0:
                self.print_result("Insider Trades", "OK", f"Found {len(insiders)} insider trades")
                for trade in insiders[:2]:
                    name = trade.get("name", "Unknown")
                    title = trade.get("title", "Unknown")
                    trans = trade.get("transaction_type", "Unknown")
                    print(f"      - {name} ({title}): {trans}")
            else:
                self.print_result("Insider Trades", "WARN", "No insider data")
                
            # Test 7: Congress Trades (CRITICAL - UNDERUTILIZED)
            print("\n  Testing Congress Trades...")
            congress = await client.get_congress_trades(limit=10)
            if congress and len(congress) > 0:
                self.print_result("Congress Trades", "OK", f"Found {len(congress)} congressional trades")
                for trade in congress[:2]:
                    member = trade.get("representative", "Unknown")
                    ticker = trade.get("ticker", "N/A")
                    trans = trade.get("transaction_type", "Unknown")
                    print(f"      - {member}: {ticker} ({trans})")
            else:
                self.print_result("Congress Trades", "WARN", "No congress data")
                
            print(f"\n  Remaining API Calls: {client.remaining_calls}")
            
            await client.close()
            self.results["unusual_whales"] = "OK"
            
        except Exception as e:
            self.print_result("Unusual Whales API", "FAIL", str(e))
            self.results["unusual_whales"] = "FAIL"
            
    async def run_single_analysis(self):
        """Run a complete single-symbol analysis to validate the full pipeline."""
        self.print_header("FULL PIPELINE VALIDATION (AAPL)")
        
        try:
            from putsengine.engine import PutsEngine
            from putsengine.config import get_settings
            
            settings = get_settings()
            engine = PutsEngine(settings)
            
            print("\n  Running full analysis on AAPL...")
            print("  (This tests all layers and API integrations)")
            
            candidate = await engine.run_single_symbol("AAPL")
            
            print("\n  Results:")
            print(f"  └─ Symbol: {candidate.symbol}")
            print(f"  └─ Current Price: ${candidate.current_price:.2f}")
            print(f"  └─ Composite Score: {candidate.composite_score:.3f}")
            print(f"  └─ Passed All Gates: {candidate.passed_all_gates}")
            
            if candidate.block_reasons:
                print(f"  └─ Block Reasons: {[r.value for r in candidate.block_reasons]}")
                
            print("\n  Score Breakdown:")
            print(f"  └─ Distribution: {candidate.distribution_score:.3f}")
            print(f"  └─ Dealer: {candidate.dealer_score:.3f}")
            print(f"  └─ Liquidity: {candidate.liquidity_score:.3f}")
            print(f"  └─ Flow: {candidate.flow_score:.3f}")
            print(f"  └─ Technical: {candidate.technical_score:.3f}")
            
            if candidate.distribution:
                print("\n  Distribution Signals:")
                for signal, active in candidate.distribution.signals.items():
                    icon = "✅" if active else "⬜"
                    print(f"  └─ {icon} {signal.replace('_', ' ').title()}")
                    
            if candidate.contract_symbol:
                print(f"\n  Recommended Contract: {candidate.contract_symbol}")
                print(f"  └─ Strike: ${candidate.recommended_strike:.2f}")
                print(f"  └─ Entry: ${candidate.entry_price:.2f}")
                
            self.print_result("Full Pipeline", "OK", "Analysis completed successfully")
            
            await engine.close()
            self.results["pipeline"] = "OK"
            
        except Exception as e:
            import traceback
            self.print_result("Full Pipeline", "FAIL", str(e))
            print(f"\n  Traceback: {traceback.format_exc()}")
            self.results["pipeline"] = "FAIL"
            
    def print_summary(self):
        """Print validation summary."""
        self.print_header("VALIDATION SUMMARY")
        
        all_ok = all(status == "OK" for status in self.results.values())
        
        for service, status in self.results.items():
            icon = "✅" if status == "OK" else "❌"
            print(f"  {icon} {service.upper()}: {status}")
            
        if all_ok:
            print("\n  🎉 All validations passed! PutsEngine is ready.")
        else:
            print("\n  ⚠️ Some validations failed. Check API keys and subscriptions.")
            
        print("\n" + "=" * 70)


async def main():
    print("\n" + "=" * 70)
    print("       PUTSENGINE API VALIDATION SUITE")
    print("       Validating all data sources and connections")
    print("=" * 70)
    print(f"\n  Timestamp: {datetime.now()}")
    
    validator = APIValidator()
    
    await validator.validate_alpaca()
    await validator.validate_polygon()
    await validator.validate_unusual_whales()
    await validator.run_single_analysis()
    
    validator.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
