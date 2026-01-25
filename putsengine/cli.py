"""
CLI Interface for PutsEngine.
Provides command-line access to the PUT trading engine.
"""

import asyncio
import argparse
import sys
from datetime import datetime
from typing import Optional, List
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from putsengine.config import get_settings, Settings
from putsengine.engine import PutsEngine
from putsengine.models import PutCandidate, DailyReport


# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO"
)

console = Console()


def print_banner():
    """Print the engine banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║   ██████╗ ██╗   ██╗████████╗███████╗                         ║
    ║   ██╔══██╗██║   ██║╚══██╔══╝██╔════╝                         ║
    ║   ██████╔╝██║   ██║   ██║   ███████╗                         ║
    ║   ██╔═══╝ ██║   ██║   ██║   ╚════██║                         ║
    ║   ██║     ╚██████╔╝   ██║   ███████║                         ║
    ║   ╚═╝      ╚═════╝    ╚═╝   ╚══════╝                         ║
    ║                                                               ║
    ║   ENGINE v1.0 - Institutional PUT Options Trading Engine     ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold blue")


def print_report(report: DailyReport, candidates: List[PutCandidate]):
    """Print the daily report in a formatted table."""

    # Summary panel
    summary = f"""
    Date: {report.date}
    Symbols Scanned: {report.total_scanned}
    Shortlist: {report.shortlist_count}
    Passed All Gates: {report.passed_gates}
    Trades Executed: {report.trades_executed}
    """

    if report.market_regime:
        regime = report.market_regime
        summary += f"""
    Market Regime: {regime.regime.value}
    SPY Below VWAP: {regime.spy_below_vwap}
    QQQ Below VWAP: {regime.qqq_below_vwap}
    Index GEX: {regime.index_gex:,.0f}
    VIX: {regime.vix_level:.2f} ({regime.vix_change:+.2%})
    Tradeable: {regime.is_tradeable}
    """

    console.print(Panel(summary, title="Daily Report Summary", border_style="green"))

    # Candidates table
    if candidates:
        table = Table(title="PUT Candidates", show_header=True, header_style="bold magenta")
        table.add_column("Rank", style="cyan", width=4)
        table.add_column("Symbol", style="bold", width=8)
        table.add_column("Score", justify="right", width=6)
        table.add_column("Price", justify="right", width=10)
        table.add_column("Contract", width=20)
        table.add_column("Strike", justify="right", width=8)
        table.add_column("DTE", justify="right", width=4)
        table.add_column("Entry", justify="right", width=8)
        table.add_column("Status", width=10)

        for i, c in enumerate(candidates, 1):
            status = "BLOCKED" if c.block_reasons else ("ACTIONABLE" if c.composite_score >= 0.68 else "LOW SCORE")
            status_style = "red" if status == "BLOCKED" else ("green" if status == "ACTIONABLE" else "yellow")

            table.add_row(
                str(i),
                c.symbol,
                f"{c.composite_score:.2f}",
                f"${c.current_price:.2f}" if c.current_price else "N/A",
                c.contract_symbol or "None",
                f"${c.recommended_strike:.0f}" if c.recommended_strike else "N/A",
                str((c.recommended_expiration - datetime.now().date()).days) if c.recommended_expiration else "N/A",
                f"${c.entry_price:.2f}" if c.entry_price else "N/A",
                f"[{status_style}]{status}[/{status_style}]"
            )

        console.print(table)

        # Detailed breakdown for top candidate
        if candidates and candidates[0].composite_score > 0:
            top = candidates[0]
            breakdown = f"""
    Distribution Score: {top.distribution_score:.2f}
    Dealer Score: {top.dealer_score:.2f}
    Liquidity Score: {top.liquidity_score:.2f}
    Flow Score: {top.flow_score:.2f}
    Technical Score: {top.technical_score:.2f}

    Block Reasons: {top.block_reasons if top.block_reasons else 'None'}
    """
            console.print(Panel(breakdown, title=f"Top Candidate: {top.symbol}", border_style="cyan"))
    else:
        console.print("[yellow]No actionable candidates found[/yellow]")


async def run_pipeline(symbols: Optional[List[str]] = None, dry_run: bool = True):
    """Run the full daily pipeline."""
    print_banner()

    settings = get_settings()
    engine = PutsEngine(settings)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running pipeline...", total=None)

            report = await engine.run_daily_pipeline(symbols)
            progress.update(task, description="Pipeline complete!")

        print_report(report, report.candidates)

        # Execute trades if any actionable candidates
        if report.candidates and report.passed_gates > 0:
            console.print("\n[bold yellow]Actionable candidates found![/bold yellow]")

            if dry_run:
                console.print("[cyan]Running in DRY RUN mode - no actual trades[/cyan]")
                for candidate in report.candidates[:settings.max_daily_trades]:
                    if candidate.composite_score >= settings.min_score_threshold:
                        execution = await engine.execute_trade(candidate, dry_run=True)
                        if execution:
                            console.print(f"  [green]Simulated: {execution.contract_symbol} x{execution.quantity}[/green]")
            else:
                console.print("[red]LIVE TRADING MODE[/red]")
                confirm = input("Execute trades? (yes/no): ")
                if confirm.lower() == "yes":
                    for candidate in report.candidates[:settings.max_daily_trades]:
                        if candidate.composite_score >= settings.min_score_threshold:
                            execution = await engine.execute_trade(candidate, dry_run=False)
                            if execution:
                                console.print(f"  [green]Executed: {execution.order_id}[/green]")

    finally:
        await engine.close()


async def analyze_symbol(symbol: str):
    """Analyze a single symbol."""
    print_banner()
    console.print(f"\n[bold]Analyzing: {symbol}[/bold]\n")

    settings = get_settings()
    engine = PutsEngine(settings)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Analyzing {symbol}...", total=None)
            candidate = await engine.run_single_symbol(symbol)
            progress.update(task, description="Analysis complete!")

        # Print detailed results
        console.print(Panel(f"""
    Symbol: {candidate.symbol}
    Current Price: ${candidate.current_price:.2f}
    Composite Score: {candidate.composite_score:.2f}
    Passed Gates: {candidate.passed_all_gates}
    Block Reasons: {candidate.block_reasons if candidate.block_reasons else 'None'}
    """, title="Analysis Summary", border_style="green"))

        # Score breakdown
        scores_table = Table(title="Score Breakdown", show_header=True)
        scores_table.add_column("Component", style="cyan")
        scores_table.add_column("Score", justify="right")
        scores_table.add_column("Weight", justify="right")
        scores_table.add_column("Weighted", justify="right")

        weights = {
            "Distribution": (candidate.distribution_score, 0.30),
            "Dealer": (candidate.dealer_score, 0.20),
            "Liquidity": (candidate.liquidity_score, 0.15),
            "Flow": (candidate.flow_score, 0.15),
            "Catalyst": (candidate.catalyst_score, 0.10),
            "Sentiment": (candidate.sentiment_score, 0.05),
            "Technical": (candidate.technical_score, 0.05),
        }

        for name, (score, weight) in weights.items():
            scores_table.add_row(
                name,
                f"{score:.2f}",
                f"{weight:.0%}",
                f"{score * weight:.3f}"
            )

        console.print(scores_table)

        # Distribution signals
        if candidate.distribution:
            dist = candidate.distribution
            signals_table = Table(title="Distribution Signals", show_header=True)
            signals_table.add_column("Signal", style="cyan")
            signals_table.add_column("Status")

            for signal_name, status in dist.signals.items():
                status_str = "[green]YES[/green]" if status else "[red]NO[/red]"
                signals_table.add_row(signal_name.replace("_", " ").title(), status_str)

            console.print(signals_table)

        # Contract recommendation
        if candidate.contract_symbol:
            console.print(Panel(f"""
    Contract: {candidate.contract_symbol}
    Strike: ${candidate.recommended_strike:.0f}
    Expiration: {candidate.recommended_expiration}
    Delta: {candidate.recommended_delta:.2f}
    Entry Price: ${candidate.entry_price:.2f}
    """, title="Recommended Contract", border_style="cyan"))

    finally:
        await engine.close()


async def check_regime():
    """Check market regime only."""
    print_banner()
    console.print("\n[bold]Checking Market Regime[/bold]\n")

    settings = get_settings()
    engine = PutsEngine(settings)

    try:
        regime = await engine.market_regime.analyze()

        status_color = "green" if regime.is_tradeable else "red"
        status_text = "TRADEABLE" if regime.is_tradeable else "BLOCKED"

        console.print(Panel(f"""
    Regime: {regime.regime.value}
    Status: [{status_color}]{status_text}[/{status_color}]

    SPY Below VWAP: {regime.spy_below_vwap}
    QQQ Below VWAP: {regime.qqq_below_vwap}
    Index GEX: {regime.index_gex:,.0f}
    VIX Level: {regime.vix_level:.2f}
    VIX Change: {regime.vix_change:+.2%}

    Block Reasons: {regime.block_reasons if regime.block_reasons else 'None'}
    """, title="Market Regime", border_style=status_color))

    finally:
        await engine.close()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="PutsEngine - Institutional PUT Options Trading Engine"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the daily pipeline")
    run_parser.add_argument(
        "--symbols",
        nargs="+",
        help="Specific symbols to analyze (optional)"
    )
    run_parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (default: dry run)"
    )

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a single symbol")
    analyze_parser.add_argument("symbol", help="Symbol to analyze")

    # Regime command
    subparsers.add_parser("regime", help="Check market regime only")

    # Status command
    subparsers.add_parser("status", help="Show engine status")

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_pipeline(
            symbols=args.symbols,
            dry_run=not args.live
        ))
    elif args.command == "analyze":
        asyncio.run(analyze_symbol(args.symbol.upper()))
    elif args.command == "regime":
        asyncio.run(check_regime())
    elif args.command == "status":
        print_banner()
        settings = get_settings()
        console.print(f"""
    Configuration:
    - Min Score Threshold: {settings.min_score_threshold}
    - Max Daily Trades: {settings.max_daily_trades}
    - DTE Range: {settings.dte_min}-{settings.dte_max} days
    - Delta Range: {settings.delta_min} to {settings.delta_max}
    - UW Daily Limit: {settings.uw_daily_limit}

    API Endpoints:
    - Alpaca: {settings.alpaca_base_url}
    - Polygon: Configured
    - Unusual Whales: Configured
        """)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
