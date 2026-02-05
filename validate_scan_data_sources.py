#!/usr/bin/env python3
"""
Comprehensive Data Source Validation for All Scheduled Scans
============================================================
Validates that UW and Polygon (Massive) APIs are working correctly
for all scheduled scan types.

Feb 4, 2026
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import Dict, Any, List
import json

# Add project to path
sys.path.insert(0, '/Users/chavala/PutsEngine')

from putsengine.config import get_settings, EngineConfig
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


class DataSourceValidator:
    """Validates all data sources for scheduled scans."""
    
    def __init__(self):
        self.settings = get_settings()
        self.polygon = PolygonClient(self.settings)
        self.uw = UnusualWhalesClient(self.settings)
        self.results = {
            "polygon": {},
            "uw": {},
            "summary": {}
        }
        
    async def close(self):
        """Close all client connections."""
        await self.polygon.close()
        await self.uw.close()
    
    # =========================================================================
    # POLYGON (MASSIVE) VALIDATION
    # =========================================================================
    
    async def validate_polygon_snapshot(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon snapshot (used for real-time quotes)."""
        print(f"\n📊 Testing Polygon Snapshot for {symbol}...")
        try:
            snapshot = await self.polygon.get_snapshot(symbol)
            if snapshot and "ticker" in snapshot:
                ticker = snapshot["ticker"]
                last_trade = ticker.get("lastTrade", {})
                last_quote = ticker.get("lastQuote", {})
                day = ticker.get("day", {})
                
                result = {
                    "status": "✅ SUCCESS",
                    "price": last_trade.get("p"),
                    "bid": last_quote.get("p"),
                    "ask": last_quote.get("P"),
                    "volume": day.get("v"),
                    "change_pct": ticker.get("todaysChangePerc"),
                    "timestamp": datetime.now().isoformat()
                }
                print(f"   Price: ${result['price']:.2f}" if result['price'] else "   Price: N/A")
                print(f"   Bid/Ask: ${result['bid']:.2f} / ${result['ask']:.2f}" if result['bid'] else "   Bid/Ask: N/A")
                print(f"   Change: {result['change_pct']:.2f}%" if result['change_pct'] else "   Change: N/A")
                return result
            else:
                return {"status": "❌ FAILED", "error": "No ticker data in response"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_polygon_daily_bars(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon daily bars (used for historical analysis)."""
        print(f"\n📊 Testing Polygon Daily Bars for {symbol}...")
        try:
            from_date = date.today() - timedelta(days=10)
            to_date = date.today()
            bars = await self.polygon.get_daily_bars(symbol, from_date, to_date)
            
            if bars and len(bars) > 0:
                latest = bars[-1]
                result = {
                    "status": "✅ SUCCESS",
                    "bars_count": len(bars),
                    "latest_date": latest.timestamp.strftime("%Y-%m-%d"),
                    "latest_close": latest.close,
                    "latest_volume": latest.volume
                }
                print(f"   Bars returned: {result['bars_count']}")
                print(f"   Latest: {result['latest_date']} | Close: ${result['latest_close']:.2f} | Vol: {result['latest_volume']:,}")
                return result
            else:
                return {"status": "❌ FAILED", "error": "No bars returned"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_polygon_latest_quote(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon latest quote (new method)."""
        print(f"\n📊 Testing Polygon Latest Quote for {symbol}...")
        try:
            quote = await self.polygon.get_latest_quote(symbol)
            if quote:
                result = {
                    "status": "✅ SUCCESS",
                    "bid": quote.get("bid"),
                    "ask": quote.get("ask"),
                    "price": quote.get("price"),
                    "volume": quote.get("volume")
                }
                print(f"   Bid: ${result['bid']:.2f}" if result['bid'] else "   Bid: N/A")
                print(f"   Ask: ${result['ask']:.2f}" if result['ask'] else "   Ask: N/A")
                print(f"   Last Price: ${result['price']:.2f}" if result['price'] else "   Last Price: N/A")
                return result
            else:
                return {"status": "❌ FAILED", "error": "No quote data returned"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_polygon_latest_bar(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon latest bar (new method)."""
        print(f"\n📊 Testing Polygon Latest Bar for {symbol}...")
        try:
            bar = await self.polygon.get_latest_bar(symbol)
            if bar:
                result = {
                    "status": "✅ SUCCESS",
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                }
                print(f"   OHLC: ${result['open']:.2f} / ${result['high']:.2f} / ${result['low']:.2f} / ${result['close']:.2f}")
                print(f"   Volume: {result['volume']:,}")
                return result
            else:
                return {"status": "❌ FAILED", "error": "No bar data returned"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_polygon_intraday_change(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon intraday change (new method)."""
        print(f"\n📊 Testing Polygon Intraday Change for {symbol}...")
        try:
            change = await self.polygon.get_intraday_change(symbol)
            if change is not None:
                result = {
                    "status": "✅ SUCCESS",
                    "change_pct": change
                }
                print(f"   Intraday Change: {result['change_pct']:.2f}%")
                return result
            else:
                return {"status": "❌ FAILED", "error": "No change data returned"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_polygon_options_chain(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon options chain."""
        print(f"\n📊 Testing Polygon Options Chain for {symbol}...")
        try:
            chain = await self.polygon.get_options_chain(symbol, limit=10)
            if chain and len(chain) > 0:
                result = {
                    "status": "✅ SUCCESS",
                    "contracts_count": len(chain),
                    "sample_contract": chain[0].get("ticker") if chain else None
                }
                print(f"   Contracts returned: {result['contracts_count']}")
                print(f"   Sample: {result['sample_contract']}")
                return result
            else:
                return {"status": "⚠️ NO DATA", "error": "No options contracts returned (may be after hours)"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_polygon_technicals(self, symbol: str = "AAPL") -> Dict:
        """Test Polygon technical indicators."""
        print(f"\n📊 Testing Polygon Technical Indicators for {symbol}...")
        try:
            sma = await self.polygon.get_sma(symbol, window=20, limit=5)
            rsi = await self.polygon.get_rsi(symbol, window=14, limit=5)
            
            result = {
                "status": "✅ SUCCESS" if (sma or rsi) else "❌ FAILED",
                "sma_data": len(sma) if sma else 0,
                "rsi_data": len(rsi) if rsi else 0
            }
            print(f"   SMA(20) data points: {result['sma_data']}")
            print(f"   RSI(14) data points: {result['rsi_data']}")
            return result
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    # =========================================================================
    # UNUSUAL WHALES (UW) VALIDATION
    # =========================================================================
    
    async def validate_uw_options_flow(self, symbol: str = "AAPL") -> Dict:
        """Test UW options flow data."""
        print(f"\n🐋 Testing UW Options Flow for {symbol}...")
        try:
            flow = await self.uw.get_options_flow(symbol, limit=10)
            if flow and len(flow) > 0:
                result = {
                    "status": "✅ SUCCESS",
                    "flow_count": len(flow),
                    "sample": {
                        "type": getattr(flow[0], 'option_type', None) or getattr(flow[0], 'contract_type', None),
                        "premium": getattr(flow[0], 'premium', None),
                        "volume": getattr(flow[0], 'volume', None)
                    } if flow else None
                }
                print(f"   Flow records: {result['flow_count']}")
                if result['sample']:
                    print(f"   Sample: Type={result['sample']['type']} | Premium=${result['sample']['premium']:,.0f}" if result['sample']['premium'] else f"   Sample: Type={result['sample']['type']}")
                return result
            else:
                return {"status": "⚠️ NO DATA", "note": "No recent flow (may be API cooldown or after hours)"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_uw_dark_pool(self, symbol: str = "AAPL") -> Dict:
        """Test UW dark pool data."""
        print(f"\n🐋 Testing UW Dark Pool for {symbol}...")
        try:
            dp = await self.uw.get_dark_pool_flow(symbol, limit=10)
            if dp and len(dp) > 0:
                result = {
                    "status": "✅ SUCCESS",
                    "prints_count": len(dp),
                    "sample": {
                        "price": getattr(dp[0], 'price', None),
                        "size": getattr(dp[0], 'size', None)
                    } if dp else None
                }
                print(f"   Dark pool prints: {result['prints_count']}")
                if result['sample']:
                    print(f"   Sample: Price=${result['sample']['price']:.2f} | Size={result['sample']['size']:,}" if result['sample']['price'] else "   Sample data available")
                return result
            else:
                return {"status": "⚠️ NO DATA", "note": "No recent dark pool (may be API cooldown)"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_uw_iv_data(self, symbol: str = "AAPL") -> Dict:
        """Test UW IV data."""
        print(f"\n🐋 Testing UW IV Data for {symbol}...")
        try:
            iv = await self.uw.get_iv_data(symbol)
            if iv:
                result = {
                    "status": "✅ SUCCESS",
                    "current_iv": getattr(iv, 'current_iv', None) or iv.get('current_iv') if isinstance(iv, dict) else None,
                    "iv_rank": getattr(iv, 'iv_rank', None) or iv.get('iv_rank') if isinstance(iv, dict) else None
                }
                print(f"   Current IV: {result['current_iv']:.1%}" if result['current_iv'] else "   Current IV: N/A")
                print(f"   IV Rank: {result['iv_rank']:.1%}" if result['iv_rank'] else "   IV Rank: N/A")
                return result
            else:
                return {"status": "⚠️ NO DATA", "note": "No IV data (may be API cooldown)"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_uw_earnings(self) -> Dict:
        """Test UW earnings calendar."""
        print(f"\n🐋 Testing UW Earnings Calendar...")
        try:
            earnings = await self.uw.get_earnings_calendar()
            if earnings:
                result = {
                    "status": "✅ SUCCESS",
                    "earnings_count": len(earnings) if isinstance(earnings, list) else 1
                }
                print(f"   Earnings records: {result['earnings_count']}")
                return result
            else:
                return {"status": "⚠️ NO DATA", "note": "No earnings data"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    async def validate_uw_market_tide(self) -> Dict:
        """Test UW market tide (overall market sentiment)."""
        print(f"\n🐋 Testing UW Market Tide...")
        try:
            tide = await self.uw.get_market_tide()
            if tide:
                result = {
                    "status": "✅ SUCCESS",
                    "data": "Market tide data available"
                }
                print(f"   Market tide: Available")
                return result
            else:
                return {"status": "⚠️ NO DATA", "note": "No market tide data"}
        except Exception as e:
            return {"status": "❌ FAILED", "error": str(e)}
    
    # =========================================================================
    # SCAN-SPECIFIC VALIDATION
    # =========================================================================
    
    async def validate_scan_data_requirements(self) -> Dict:
        """Validate data requirements for each scan type."""
        print("\n" + "=" * 70)
        print("VALIDATING DATA REQUIREMENTS FOR EACH SCAN TYPE")
        print("=" * 70)
        
        scan_validations = {}
        
        # Test symbol
        test_symbol = "AAPL"
        
        # 1. Pre-Market Final Scan (9:00 AM) - UW API
        print("\n🎯 PRE-MARKET FINAL SCAN (9:00 AM) - UW API")
        print("-" * 50)
        scan_validations["pre_market_final"] = {
            "options_flow": await self.validate_uw_options_flow(test_symbol),
            "dark_pool": await self.validate_uw_dark_pool(test_symbol),
            "iv_data": await self.validate_uw_iv_data(test_symbol)
        }
        
        # 2. Market Pulse Scan (3:00 PM) - UW API
        print("\n📊 MARKET PULSE SCAN (3:00 PM) - UW API")
        print("-" * 50)
        scan_validations["market_pulse"] = {
            "options_flow": scan_validations["pre_market_final"]["options_flow"],  # Same data
            "dark_pool": scan_validations["pre_market_final"]["dark_pool"],
            "iv_data": scan_validations["pre_market_final"]["iv_data"]
        }
        
        # 3. Early Warning Scan (10:00 PM) - UW API
        print("\n🚨 EARLY WARNING SCAN (10:00 PM) - UW API")
        print("-" * 50)
        scan_validations["early_warning"] = {
            "options_flow": scan_validations["pre_market_final"]["options_flow"],
            "dark_pool": scan_validations["pre_market_final"]["dark_pool"],
            "iv_data": scan_validations["pre_market_final"]["iv_data"]
        }
        
        # 4. Pre-Market Gap Scan - Polygon/Massive
        print("\n📈 PRE-MARKET GAP SCAN - POLYGON/MASSIVE")
        print("-" * 50)
        scan_validations["gap_scan"] = {
            "latest_bar": await self.validate_polygon_latest_bar(test_symbol),
            "latest_quote": await self.validate_polygon_latest_quote(test_symbol),
            "daily_bars": await self.validate_polygon_daily_bars(test_symbol)
        }
        
        # 5. Intraday Big Mover Scan - Polygon/Massive
        print("\n🚨 INTRADAY BIG MOVER SCAN - POLYGON/MASSIVE")
        print("-" * 50)
        scan_validations["intraday_mover"] = {
            "snapshot": await self.validate_polygon_snapshot(test_symbol),
            "intraday_change": await self.validate_polygon_intraday_change(test_symbol)
        }
        
        # 6. After-Hours Scan - Polygon/Massive
        print("\n🌙 AFTER-HOURS SCAN - POLYGON/MASSIVE")
        print("-" * 50)
        scan_validations["afterhours"] = {
            "latest_bar": scan_validations["gap_scan"]["latest_bar"],
            "latest_quote": scan_validations["gap_scan"]["latest_quote"]
        }
        
        # 7. Multi-Day Weakness Scan - Polygon/Massive
        print("\n📉 MULTI-DAY WEAKNESS SCAN - POLYGON/MASSIVE")
        print("-" * 50)
        scan_validations["multiday_weakness"] = {
            "daily_bars": scan_validations["gap_scan"]["daily_bars"]
        }
        
        # 8. Pump-Dump Scan - UW + Polygon
        print("\n🔄 PUMP-DUMP REVERSAL SCAN - UW + POLYGON")
        print("-" * 50)
        scan_validations["pump_dump"] = {
            "daily_bars": scan_validations["gap_scan"]["daily_bars"],
            "options_flow": scan_validations["pre_market_final"]["options_flow"]
        }
        
        # 9. Earnings Priority Scan - UW API
        print("\n📅 EARNINGS PRIORITY SCAN - UW API")
        print("-" * 50)
        scan_validations["earnings_priority"] = {
            "earnings_calendar": await self.validate_uw_earnings(),
            "options_flow": scan_validations["pre_market_final"]["options_flow"],
            "dark_pool": scan_validations["pre_market_final"]["dark_pool"]
        }
        
        # 10. Pre-Catalyst Scan - UW API
        print("\n⚡ PRE-CATALYST DISTRIBUTION SCAN - UW API")
        print("-" * 50)
        scan_validations["pre_catalyst"] = {
            "dark_pool": scan_validations["pre_market_final"]["dark_pool"],
            "options_flow": scan_validations["pre_market_final"]["options_flow"],
            "daily_bars": scan_validations["gap_scan"]["daily_bars"]
        }
        
        return scan_validations
    
    async def run_full_validation(self):
        """Run complete validation of all data sources."""
        print("\n" + "=" * 70)
        print("🔍 PUTSENGINE DATA SOURCE VALIDATION")
        print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
        print("=" * 70)
        
        # Test Polygon (Massive) APIs
        print("\n" + "=" * 70)
        print("📊 POLYGON (MASSIVE) API VALIDATION")
        print("=" * 70)
        
        self.results["polygon"]["snapshot"] = await self.validate_polygon_snapshot()
        self.results["polygon"]["daily_bars"] = await self.validate_polygon_daily_bars()
        self.results["polygon"]["latest_quote"] = await self.validate_polygon_latest_quote()
        self.results["polygon"]["latest_bar"] = await self.validate_polygon_latest_bar()
        self.results["polygon"]["intraday_change"] = await self.validate_polygon_intraday_change()
        self.results["polygon"]["options_chain"] = await self.validate_polygon_options_chain()
        self.results["polygon"]["technicals"] = await self.validate_polygon_technicals()
        
        # Test UW APIs
        print("\n" + "=" * 70)
        print("🐋 UNUSUAL WHALES API VALIDATION")
        print("=" * 70)
        
        self.results["uw"]["options_flow"] = await self.validate_uw_options_flow()
        self.results["uw"]["dark_pool"] = await self.validate_uw_dark_pool()
        self.results["uw"]["iv_data"] = await self.validate_uw_iv_data()
        self.results["uw"]["earnings"] = await self.validate_uw_earnings()
        self.results["uw"]["market_tide"] = await self.validate_uw_market_tide()
        
        # Validate scan-specific data requirements
        scan_validations = await self.validate_scan_data_requirements()
        
        # Summary
        print("\n" + "=" * 70)
        print("📋 VALIDATION SUMMARY")
        print("=" * 70)
        
        polygon_success = sum(1 for v in self.results["polygon"].values() if "SUCCESS" in v.get("status", ""))
        polygon_total = len(self.results["polygon"])
        
        uw_success = sum(1 for v in self.results["uw"].values() if "SUCCESS" in v.get("status", ""))
        uw_total = len(self.results["uw"])
        
        print(f"\n📊 POLYGON (MASSIVE): {polygon_success}/{polygon_total} tests passed")
        for name, result in self.results["polygon"].items():
            status = result.get("status", "UNKNOWN")
            print(f"   {status} {name}")
        
        print(f"\n🐋 UNUSUAL WHALES: {uw_success}/{uw_total} tests passed")
        for name, result in self.results["uw"].items():
            status = result.get("status", "UNKNOWN")
            print(f"   {status} {name}")
        
        # Scan readiness
        print("\n" + "=" * 70)
        print("🎯 SCAN READINESS")
        print("=" * 70)
        
        scans_ready = {
            "🎯 Pre-Market Final (9 AM)": polygon_success >= 3 and uw_success >= 2,
            "📊 Market Pulse (3 PM)": polygon_success >= 3 and uw_success >= 2,
            "🚨 Early Warning (10 PM)": uw_success >= 2,
            "📈 Pre-Market Gap": polygon_success >= 3,
            "🚨 Intraday Big Mover": polygon_success >= 2,
            "🌙 After-Hours": polygon_success >= 2,
            "📉 Multi-Day Weakness": polygon_success >= 1,
            "🔄 Pump-Dump Reversal": polygon_success >= 1 and uw_success >= 1,
            "📅 Earnings Priority": uw_success >= 2,
            "⚡ Pre-Catalyst": uw_success >= 2 and polygon_success >= 1,
            "📊 Volume-Price Divergence": polygon_success >= 1,
            "🔗 Sector Correlation": polygon_success >= 1
        }
        
        for scan, ready in scans_ready.items():
            status = "✅ READY" if ready else "❌ NOT READY"
            print(f"   {status} {scan}")
        
        # Overall status
        all_ready = all(scans_ready.values())
        print("\n" + "=" * 70)
        if all_ready:
            print("✅ ALL SCANS READY - System is fully operational")
        else:
            print("⚠️ SOME SCANS MAY HAVE ISSUES - Check individual results above")
        print("=" * 70)
        
        return self.results


async def main():
    """Run the validation."""
    validator = DataSourceValidator()
    try:
        results = await validator.run_full_validation()
        
        # Save results to file
        output_file = "/Users/chavala/PutsEngine/logs/data_source_validation.json"
        with open(output_file, "w") as f:
            # Convert results to JSON-serializable format
            json_results = {}
            for category, tests in results.items():
                if isinstance(tests, dict):
                    json_results[category] = {}
                    for name, result in tests.items():
                        if isinstance(result, dict):
                            json_results[category][name] = result
            json.dump(json_results, f, indent=2, default=str)
        print(f"\n📁 Results saved to: {output_file}")
        
    finally:
        await validator.close()


if __name__ == "__main__":
    asyncio.run(main())
