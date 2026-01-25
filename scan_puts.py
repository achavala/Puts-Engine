#!/usr/bin/env python3
"""
PutsEngine Scanner - Scan all tickers for PUT candidates
Displays candidates with 1-2 week (7-14 DTE) expiry dates
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.live import Live
from rich import box

# Add project to path
sys.path.insert(0, '.')

from putsengine.config import EngineConfig, get_settings
from putsengine.engine import PutsEngine
from putsengine.models import PutCandidate, BlockReason


console = Console()


def get_all_unique_tickers() -> List[str]:
    """Get all unique tickers from the universe."""
    return sorted(EngineConfig.get_all_tickers())


async def scan_ticker(engine: PutsEngine, symbol: str) -> Optional[Dict[str, Any]]:
    """Scan a single ticker and return results if it passes analysis."""
    try:
        candidate = await engine.run_single_symbol(symbol)
        
        result = {
            "symbol": symbol,
            "price": candidate.current_price,
            "score": candidate.composite_score,
            "passed": candidate.passed_all_gates,
            "blocks": [r.value for r in candidate.block_reasons],
            "distribution_score": candidate.distribution_score,
            "dealer_score": candidate.dealer_score,
            "liquidity_score": candidate.liquidity_score,
            "engine_type": "N/A",
            "signals": {},
            "insider_boost": 0.0,
            "congress_boost": 0.0,
        }
        
        # Get engine type and additional data
        if candidate.acceleration:
            result["engine_type"] = getattr(candidate.acceleration, 'engine_type', 'N/A')
            if hasattr(result["engine_type"], 'value'):
                result["engine_type"] = result["engine_type"].value
        
        if candidate.distribution:
            result["signals"] = candidate.distribution.signals
            result["insider_boost"] = getattr(candidate.distribution, 'insider_boost', 0.0)
            result["congress_boost"] = getattr(candidate.distribution, 'congress_boost', 0.0)
        
        return result
        
    except Exception as e:
        return {
            "symbol": symbol,
            "price": 0.0,
            "score": 0.0,
            "passed": False,
            "blocks": [f"Error: {str(e)[:50]}"],
            "distribution_score": 0.0,
            "dealer_score": 0.0,
            "liquidity_score": 0.0,
            "engine_type": "N/A",
            "signals": {},
            "insider_boost": 0.0,
            "congress_boost": 0.0,
        }


async def scan_all_tickers(tickers: List[str], batch_size: int = 5) -> List[Dict[str, Any]]:
    """Scan all tickers with progress display."""
    results = []
    engine = PutsEngine()
    
    console.print(Panel(
        f"[bold cyan]🔍 PutsEngine Scanner[/bold cyan]\n"
        f"Scanning [bold yellow]{len(tickers)}[/bold yellow] tickers for PUT candidates\n"
        f"DTE Range: [bold green]7-14 days[/bold green] (1-2 weeks)\n"
        f"Min Score: [bold green]0.68[/bold green]",
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
        task = progress.add_task("[cyan]Scanning tickers...", total=len(tickers))
        
        # Process in batches
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            batch_results = await asyncio.gather(
                *[scan_ticker(engine, symbol) for symbol in batch],
                return_exceptions=True
            )
            
            for result in batch_results:
                if isinstance(result, dict):
                    results.append(result)
                progress.advance(task)
            
            # Rate limiting - wait between batches
            await asyncio.sleep(0.5)
    
    await engine.close()
    return results


def display_results(results: List[Dict[str, Any]], min_score: float = 0.0):
    """Display results in a formatted table."""
    
    # Filter and sort by score
    filtered = [r for r in results if r["score"] >= min_score]
    sorted_results = sorted(filtered, key=lambda x: x["score"], reverse=True)
    
    # Summary stats
    total_scanned = len(results)
    passed_gates = len([r for r in results if r["passed"]])
    actionable = len([r for r in results if r["score"] >= 0.68])
    high_potential = len([r for r in results if r["score"] >= 0.75])
    
    # Summary panel
    console.print()
    console.print(Panel(
        f"[bold white]📊 SCAN SUMMARY[/bold white]\n\n"
        f"Total Scanned: [cyan]{total_scanned}[/cyan]\n"
        f"Passed All Gates: [green]{passed_gates}[/green]\n"
        f"Actionable (≥0.68): [yellow]{actionable}[/yellow]\n"
        f"High Potential (≥0.75): [red]{high_potential}[/red]",
        border_style="blue"
    ))
    
    # Main results table - Top PUT candidates
    if actionable > 0:
        table = Table(
            title="🎯 TOP PUT CANDIDATES (Score ≥ 0.68)",
            box=box.DOUBLE_EDGE,
            border_style="green",
            header_style="bold white on dark_green",
            row_styles=["", "dim"]
        )
        
        table.add_column("Rank", style="cyan", width=5)
        table.add_column("Symbol", style="bold yellow", width=8)
        table.add_column("Price", justify="right", width=10)
        table.add_column("Score", justify="center", width=8)
        table.add_column("Engine", width=15)
        table.add_column("Distribution", justify="center", width=12)
        table.add_column("Dealer", justify="center", width=8)
        table.add_column("Liquidity", justify="center", width=10)
        table.add_column("Insider", justify="center", width=8)
        table.add_column("Status", width=15)
        
        for i, result in enumerate(sorted_results[:20], 1):
            if result["score"] < 0.68:
                continue
                
            score = result["score"]
            if score >= 0.80:
                score_style = "[bold white on red]"
            elif score >= 0.75:
                score_style = "[bold red]"
            elif score >= 0.70:
                score_style = "[bold yellow]"
            else:
                score_style = "[green]"
            
            engine_type = result.get("engine_type", "N/A")
            if engine_type == "gamma_drain":
                engine_display = "[bold magenta]⚡ GAMMA DRAIN[/]"
            elif engine_type == "distribution_trap":
                engine_display = "[bold orange3]🪤 DIST TRAP[/]"
            elif engine_type == "snapback":
                engine_display = "[bold red]↩️ SNAPBACK[/]"
            else:
                engine_display = f"[dim]{engine_type}[/]"
            
            insider = result.get("insider_boost", 0)
            insider_display = f"[green]+{insider:.2f}[/]" if insider > 0 else "[dim]—[/]"
            
            status = "[bold green]✅ ACTIONABLE" if result["passed"] else "[dim red]⚠️ BLOCKED"
            
            table.add_row(
                str(i),
                result["symbol"],
                f"${result['price']:.2f}",
                f"{score_style}{score:.3f}[/]",
                engine_display,
                f"{result['distribution_score']:.2f}",
                f"{result['dealer_score']:.2f}",
                f"{result['liquidity_score']:.2f}",
                insider_display,
                status
            )
        
        console.print(table)
    
    # Near-threshold table (0.55-0.68)
    near_threshold = [r for r in sorted_results if 0.55 <= r["score"] < 0.68]
    if near_threshold:
        console.print()
        table2 = Table(
            title="⏳ WATCHLIST (Near Threshold: 0.55-0.67)",
            box=box.ROUNDED,
            border_style="yellow",
            header_style="bold white on dark_blue"
        )
        
        table2.add_column("Symbol", style="yellow", width=8)
        table2.add_column("Price", justify="right", width=10)
        table2.add_column("Score", justify="center", width=8)
        table2.add_column("Engine", width=15)
        table2.add_column("Block Reasons", width=40)
        
        for result in near_threshold[:15]:
            blocks = ", ".join(result["blocks"][:2]) if result["blocks"] else "—"
            
            table2.add_row(
                result["symbol"],
                f"${result['price']:.2f}",
                f"[yellow]{result['score']:.3f}[/]",
                result.get("engine_type", "N/A"),
                f"[dim]{blocks}[/]"
            )
        
        console.print(table2)
    
    # Blocked candidates with high distribution
    blocked_high_dist = [
        r for r in sorted_results 
        if not r["passed"] and r["distribution_score"] >= 0.5
    ][:10]
    
    if blocked_high_dist:
        console.print()
        table3 = Table(
            title="🚫 BLOCKED (High Distribution Signal - Watch for Gate Changes)",
            box=box.SIMPLE,
            border_style="red"
        )
        
        table3.add_column("Symbol", width=8)
        table3.add_column("Price", justify="right", width=10)
        table3.add_column("Dist Score", justify="center", width=10)
        table3.add_column("Block Reason", width=50)
        
        for result in blocked_high_dist:
            blocks = result["blocks"][0] if result["blocks"] else "Unknown"
            table3.add_row(
                result["symbol"],
                f"${result['price']:.2f}",
                f"[red]{result['distribution_score']:.2f}[/]",
                f"[dim]{blocks}[/]"
            )
        
        console.print(table3)
    
    # Expiry recommendations
    console.print()
    today = date.today()
    exp_1week = today + timedelta(days=7)
    exp_2week = today + timedelta(days=14)
    
    # Find next Friday for options expiry
    days_to_friday_1 = (4 - exp_1week.weekday()) % 7
    exp_1week_friday = exp_1week + timedelta(days=days_to_friday_1)
    
    days_to_friday_2 = (4 - exp_2week.weekday()) % 7
    exp_2week_friday = exp_2week + timedelta(days=days_to_friday_2)
    
    console.print(Panel(
        f"[bold white]📅 RECOMMENDED EXPIRY DATES[/bold white]\n\n"
        f"1-Week Expiry: [bold green]{exp_1week_friday.strftime('%Y-%m-%d')}[/bold green] ({(exp_1week_friday - today).days} DTE)\n"
        f"2-Week Expiry: [bold cyan]{exp_2week_friday.strftime('%Y-%m-%d')}[/bold cyan] ({(exp_2week_friday - today).days} DTE)\n\n"
        f"[dim]Target Delta: -0.25 to -0.40 (Slightly OTM)[/dim]\n"
        f"[dim]Avoid: IV already expanded >20%, Lottery puts[/dim]",
        title="Strike Selection Guide",
        border_style="blue"
    ))
    
    return sorted_results


async def main():
    """Main entry point."""
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print("[bold white]   TradeNova PUTS ENGINE - Full Universe Scanner[/bold white]")
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print()
    
    # Get all tickers
    all_tickers = get_all_unique_tickers()
    console.print(f"[dim]Found [bold]{len(all_tickers)}[/bold] unique tickers in universe[/dim]")
    console.print()
    
    # Scan all tickers
    results = await scan_all_tickers(all_tickers, batch_size=3)
    
    # Display results
    sorted_results = display_results(results, min_score=0.0)
    
    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"logs/puts_scan_{timestamp}.txt"
    
    with open(output_file, "w") as f:
        f.write(f"PUTSENGINE SCAN RESULTS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("TOP PUT CANDIDATES (Score >= 0.68):\n")
        f.write("-" * 80 + "\n")
        
        for result in sorted_results:
            if result["score"] >= 0.68:
                f.write(f"{result['symbol']:8} | ${result['price']:>10.2f} | "
                       f"Score: {result['score']:.3f} | "
                       f"Engine: {result.get('engine_type', 'N/A'):15} | "
                       f"Dist: {result['distribution_score']:.2f} | "
                       f"{'✅ PASS' if result['passed'] else '❌ BLOCK'}\n")
        
        f.write("\n\nWATCHLIST (Score 0.55-0.67):\n")
        f.write("-" * 80 + "\n")
        
        for result in sorted_results:
            if 0.55 <= result["score"] < 0.68:
                f.write(f"{result['symbol']:8} | ${result['price']:>10.2f} | "
                       f"Score: {result['score']:.3f} | "
                       f"Blocks: {', '.join(result['blocks'][:2])}\n")
    
    console.print(f"\n[dim]Results saved to: {output_file}[/dim]")
    console.print()
    console.print("[bold green]✅ Scan complete![/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
