#!/usr/bin/env python3
"""
PutsEngine Detailed Scanner - Shows PUT analysis for all tickers
Displays results regardless of market regime for planning purposes
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import box

sys.path.insert(0, '.')

from putsengine.config import EngineConfig, get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


console = Console()


def get_all_unique_tickers() -> List[str]:
    """Get all unique tickers from the universe."""
    return sorted(EngineConfig.get_all_tickers())


async def get_ticker_price_data(polygon: PolygonClient, symbol: str) -> Dict[str, Any]:
    """Get basic price data for a ticker."""
    try:
        # Get current snapshot
        snapshot = await polygon.get_snapshot(symbol)
        if snapshot:
            return {
                "symbol": symbol,
                "price": snapshot.get("ticker", {}).get("day", {}).get("c", 0) or 
                        snapshot.get("ticker", {}).get("prevDay", {}).get("c", 0) or 0,
                "change_pct": snapshot.get("ticker", {}).get("todaysChangePerc", 0) or 0,
                "volume": snapshot.get("ticker", {}).get("day", {}).get("v", 0) or 0,
                "prev_close": snapshot.get("ticker", {}).get("prevDay", {}).get("c", 0) or 0,
                "success": True
            }
        return {"symbol": symbol, "price": 0, "change_pct": 0, "volume": 0, "prev_close": 0, "success": False}
    except Exception as e:
        return {"symbol": symbol, "price": 0, "change_pct": 0, "volume": 0, "prev_close": 0, "success": False, "error": str(e)}


async def scan_tickers_basic(tickers: List[str]) -> List[Dict[str, Any]]:
    """Scan tickers for basic price data only (minimal API calls)."""
    settings = get_settings()
    polygon = PolygonClient(settings)
    
    results = []
    
    console.print(Panel(
        f"[bold cyan]🔍 PutsEngine Quick Scanner[/bold cyan]\n"
        f"Scanning [bold yellow]{len(tickers)}[/bold yellow] tickers\n"
        f"Expiry Target: [bold green]1-2 weeks (7-14 DTE)[/bold green]",
        title="[bold white]TradeNova PUTS ENGINE[/bold white]",
        border_style="cyan"
    ))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Fetching prices...", total=len(tickers))
        
        # Process in batches
        batch_size = 10
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            batch_results = await asyncio.gather(
                *[get_ticker_price_data(polygon, symbol) for symbol in batch],
                return_exceptions=True
            )
            
            for result in batch_results:
                if isinstance(result, dict):
                    results.append(result)
                progress.advance(task, len(batch))
            
            await asyncio.sleep(0.2)  # Rate limiting
    
    await polygon.close()
    return results


def display_ticker_universe(results: List[Dict[str, Any]]):
    """Display all tickers with their current prices and sectors."""
    
    # Get sector mapping
    ticker_to_sector = {}
    for sector, tickers in EngineConfig.UNIVERSE_SECTORS.items():
        for ticker in tickers:
            if ticker not in ticker_to_sector:
                ticker_to_sector[ticker] = sector
    
    # Filter successful results and sort by sector then price
    valid_results = [r for r in results if r.get("success") and r.get("price", 0) > 0]
    
    # Group by sector
    by_sector = {}
    for result in valid_results:
        sector = ticker_to_sector.get(result["symbol"], "other")
        if sector not in by_sector:
            by_sector[sector] = []
        by_sector[sector].append(result)
    
    # Calculate expiry dates
    today = date.today()
    exp_1week = today + timedelta(days=7)
    exp_2week = today + timedelta(days=14)
    days_to_friday_1 = (4 - exp_1week.weekday()) % 7
    exp_1week_friday = exp_1week + timedelta(days=days_to_friday_1)
    days_to_friday_2 = (4 - exp_2week.weekday()) % 7
    exp_2week_friday = exp_2week + timedelta(days=days_to_friday_2)
    
    # Header
    console.print()
    console.print(Panel(
        f"[bold white]📅 RECOMMENDED EXPIRY DATES FOR PUTS[/bold white]\n\n"
        f"[bold green]1-Week:[/bold green] {exp_1week_friday.strftime('%b %d, %Y')} ({(exp_1week_friday - today).days} DTE)\n"
        f"[bold cyan]2-Week:[/bold cyan] {exp_2week_friday.strftime('%b %d, %Y')} ({(exp_2week_friday - today).days} DTE)\n\n"
        f"[dim]Delta Target: -0.25 to -0.40 | Avoid lottery puts | Watch for IV expansion[/dim]",
        title="[bold yellow]PUTS EXPIRY GUIDE[/bold yellow]",
        border_style="yellow"
    ))
    
    # Summary table
    console.print()
    summary_table = Table(
        title="📊 UNIVERSE OVERVIEW",
        box=box.ROUNDED,
        header_style="bold white on dark_blue"
    )
    summary_table.add_column("Sector", style="cyan")
    summary_table.add_column("Tickers", justify="center")
    summary_table.add_column("Avg Price", justify="right")
    summary_table.add_column("Day Movers", justify="center")
    
    sector_names = {
        "mega_cap_tech": "🏢 Mega Cap Tech",
        "high_vol_tech": "⚡ High Vol Tech",
        "space_aerospace": "🚀 Space & Aerospace",
        "nuclear_energy": "☢️ Nuclear & Energy",
        "quantum": "🔬 Quantum Computing",
        "ai_datacenters": "🤖 AI & Data Centers",
        "biotech": "🧬 Biotech",
        "crypto": "₿ Crypto Related",
        "semiconductors": "💾 Semiconductors",
        "meme": "🎮 Meme Stocks",
        "fintech": "💳 Fintech",
        "healthcare": "🏥 Healthcare",
        "industrials": "🏭 Industrials",
        "etfs": "📈 Major ETFs",
        "financials": "🏦 Financials",
        "consumer": "🛒 Consumer",
        "telecom": "📡 Telecom",
    }
    
    for sector, sector_results in sorted(by_sector.items()):
        if not sector_results:
            continue
        avg_price = sum(r["price"] for r in sector_results) / len(sector_results)
        movers = [r for r in sector_results if abs(r.get("change_pct", 0)) > 2]
        display_name = sector_names.get(sector, sector.replace("_", " ").title())
        
        summary_table.add_row(
            display_name,
            str(len(sector_results)),
            f"${avg_price:.2f}",
            f"{len(movers)} (>2%)" if movers else "—"
        )
    
    console.print(summary_table)
    
    # Detailed table by sector with PUT recommendations
    for sector in ["mega_cap_tech", "high_vol_tech", "semiconductors", "ai_datacenters", 
                   "quantum", "nuclear_energy", "biotech", "fintech", "crypto", "meme",
                   "space_aerospace", "etfs", "financials", "consumer", "healthcare", 
                   "industrials", "telecom"]:
        if sector not in by_sector or not by_sector[sector]:
            continue
            
        sector_results = sorted(by_sector[sector], key=lambda x: x["price"], reverse=True)
        display_name = sector_names.get(sector, sector)
        
        console.print()
        table = Table(
            title=f"{display_name} - PUT Targets",
            box=box.SIMPLE,
            header_style="bold white on dark_green",
            row_styles=["", "dim"]
        )
        
        table.add_column("Symbol", style="bold yellow", width=8)
        table.add_column("Price", justify="right", width=12)
        table.add_column("Day %", justify="center", width=10)
        table.add_column("1-Wk Strike (OTM)", justify="center", width=16)
        table.add_column("2-Wk Strike (OTM)", justify="center", width=16)
        table.add_column("Notes", width=25)
        
        for result in sector_results:
            price = result.get("price", 0)
            if price <= 0:
                continue
                
            change_pct = result.get("change_pct", 0)
            
            # Calculate suggested strikes (5-10% OTM for puts)
            strike_1wk = round(price * 0.95, 0)  # 5% OTM for 1-week
            strike_2wk = round(price * 0.92, 0)  # 8% OTM for 2-week
            
            # Round to common strike increments
            if price > 500:
                strike_1wk = round(strike_1wk / 10) * 10
                strike_2wk = round(strike_2wk / 10) * 10
            elif price > 100:
                strike_1wk = round(strike_1wk / 5) * 5
                strike_2wk = round(strike_2wk / 5) * 5
            elif price > 50:
                strike_1wk = round(strike_1wk / 2.5) * 2.5
                strike_2wk = round(strike_2wk / 2.5) * 2.5
            
            # Determine notes based on price action
            notes = ""
            if change_pct > 5:
                notes = "[red]⬆️ Extended (Watch)[/red]"
            elif change_pct > 2:
                notes = "[yellow]↗️ Strong day[/yellow]"
            elif change_pct < -3:
                notes = "[green]↘️ Weak (Momentum)[/green]"
            elif change_pct < -1:
                notes = "[cyan]↘️ Soft[/cyan]"
            else:
                notes = "[dim]Neutral[/dim]"
            
            # Format change
            if change_pct > 0:
                change_display = f"[green]+{change_pct:.1f}%[/green]"
            elif change_pct < 0:
                change_display = f"[red]{change_pct:.1f}%[/red]"
            else:
                change_display = "[dim]0.0%[/dim]"
            
            table.add_row(
                result["symbol"],
                f"${price:.2f}",
                change_display,
                f"${strike_1wk:.0f}P ({exp_1week_friday.strftime('%m/%d')})",
                f"${strike_2wk:.0f}P ({exp_2week_friday.strftime('%m/%d')})",
                notes
            )
        
        console.print(table)
    
    # Market regime warning
    console.print()
    console.print(Panel(
        "[bold red]⚠️ MARKET REGIME WARNING[/bold red]\n\n"
        "[yellow]Current regime shows SPY & QQQ above VWAP (Bullish/Pinned)[/yellow]\n\n"
        "Per Anti-Trinity rules, PUT entries are blocked when:\n"
        "• Index is pinned (positive GEX)\n"
        "• SPY/QQQ above VWAP\n"
        "• Dealers are long gamma\n\n"
        "[dim]Wait for regime change before executing PUT trades.[/dim]\n"
        "[dim]This list shows potential targets for when conditions become favorable.[/dim]",
        title="[bold white]REGIME GATE ACTIVE[/bold white]",
        border_style="red"
    ))
    
    return valid_results


async def main():
    """Main entry point."""
    console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
    console.print("[bold white]   TradeNova PUTS ENGINE - Full Universe Scanner (170 Tickers)[/bold white]")
    console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
    console.print()
    
    # Get all tickers
    all_tickers = get_all_unique_tickers()
    console.print(f"[dim]Loaded [bold]{len(all_tickers)}[/bold] unique tickers from {len(EngineConfig.UNIVERSE_SECTORS)} sectors[/dim]")
    console.print()
    
    # Quick scan for prices
    results = await scan_tickers_basic(all_tickers)
    
    # Display results
    valid_results = display_ticker_universe(results)
    
    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"logs/puts_universe_{timestamp}.txt"
    
    with open(output_file, "w") as f:
        f.write(f"PUTSENGINE UNIVERSE SCAN - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        today = date.today()
        exp_1week = today + timedelta(days=7)
        exp_2week = today + timedelta(days=14)
        days_to_friday_1 = (4 - exp_1week.weekday()) % 7
        exp_1week_friday = exp_1week + timedelta(days=days_to_friday_1)
        days_to_friday_2 = (4 - exp_2week.weekday()) % 7
        exp_2week_friday = exp_2week + timedelta(days=days_to_friday_2)
        
        f.write(f"RECOMMENDED EXPIRY DATES:\n")
        f.write(f"  1-Week: {exp_1week_friday.strftime('%Y-%m-%d')} ({(exp_1week_friday - today).days} DTE)\n")
        f.write(f"  2-Week: {exp_2week_friday.strftime('%Y-%m-%d')} ({(exp_2week_friday - today).days} DTE)\n\n")
        
        f.write("ALL TICKERS WITH PUT STRIKE SUGGESTIONS:\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Symbol':<10} {'Price':>12} {'Change':>10} {'1-Wk Strike':>15} {'2-Wk Strike':>15}\n")
        f.write("-" * 80 + "\n")
        
        sorted_results = sorted(valid_results, key=lambda x: x.get("price", 0), reverse=True)
        for result in sorted_results:
            price = result.get("price", 0)
            if price <= 0:
                continue
            change_pct = result.get("change_pct", 0)
            strike_1wk = round(price * 0.95, 0)
            strike_2wk = round(price * 0.92, 0)
            
            if price > 500:
                strike_1wk = round(strike_1wk / 10) * 10
                strike_2wk = round(strike_2wk / 10) * 10
            elif price > 100:
                strike_1wk = round(strike_1wk / 5) * 5
                strike_2wk = round(strike_2wk / 5) * 5
            
            f.write(f"{result['symbol']:<10} ${price:>10.2f} {change_pct:>+9.1f}% ${strike_1wk:>12.0f}P ${strike_2wk:>12.0f}P\n")
    
    console.print(f"\n[dim]Full results saved to: {output_file}[/dim]")
    console.print()
    console.print("[bold green]✅ Universe scan complete![/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
