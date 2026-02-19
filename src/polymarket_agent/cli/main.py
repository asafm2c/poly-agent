"""CLI entry point with Click commands."""

import logging
import signal
import sys

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from polymarket_agent.config import settings
from polymarket_agent.storage.database import init_db

console = Console()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool):
    """Polymarket Agent - Autonomous prediction market trading."""
    setup_logging(verbose)
    init_db()


@cli.command()
@click.option("--category", "-c", help="Filter by category")
@click.option("--min-volume", type=float, help="Minimum volume filter")
@click.option("--limit", "-n", type=int, default=20, help="Max markets to display")
def scan(category: str | None, min_volume: float | None, limit: int):
    """Scan Polymarket for tradeable markets."""
    from polymarket_agent.market.filter import MarketFilter
    from polymarket_agent.market.scanner import MarketScanner

    categories = [category] if category else None
    scanner = MarketScanner(
        market_filter=MarketFilter(
            min_volume=min_volume or settings.min_volume,
            categories=categories,
        )
    )

    with console.status("Scanning markets..."):
        candidates, events = scanner.scan()

    if events:
        console.print(f"\n[bold yellow]Events detected: {len(events)}[/]")
        for event in events[:5]:
            console.print(f"  {event.event_type}: {event.market_id[:8]} ({event.magnitude or ''})")

    table = Table(title=f"Tradeable Markets ({len(candidates)} found)")
    table.add_column("ID", style="dim", max_width=10)
    table.add_column("Question", max_width=50)
    table.add_column("Category", max_width=12)
    table.add_column("YES Price", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Days Left", justify="right")

    from datetime import datetime, timezone

    for m in candidates[:limit]:
        days = ""
        if m.end_date:
            end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
            days = str((end - datetime.now(timezone.utc)).days)
        table.add_row(
            m.id[:8] + "...",
            m.question[:50],
            m.category or "",
            f"${m.last_price_yes:.2f}" if m.last_price_yes else "N/A",
            f"${m.volume:,.0f}",
            days,
        )

    console.print(table)
    scanner.close()


@cli.command()
@click.argument("market_id")
def analyze(market_id: str):
    """Run full analysis pipeline on a specific market."""
    from polymarket_agent.analyst.estimator import ProbabilityEstimator
    from polymarket_agent.market.storage import get_all_active_markets, get_market
    from polymarket_agent.trading.calibration import export_calibration_for_llm
    from polymarket_agent.trading.edge import build_recommendation
    from polymarket_agent.trading.paper import PaperTrader

    # Find market (support partial IDs)
    market = get_market(market_id)
    if not market:
        markets = get_all_active_markets()
        matches = [m for m in markets if m.id.startswith(market_id)]
        if len(matches) == 1:
            market = matches[0]
        elif len(matches) > 1:
            console.print(f"[red]Ambiguous ID '{market_id}', matches: {[m.id[:12] for m in matches]}[/]")
            return
        else:
            console.print(f"[red]Market '{market_id}' not found. Run 'scan' first.[/]")
            return

    console.print(f"\n[bold]Analyzing:[/] {market.question}")
    console.print(f"Current price: YES=${market.last_price_yes or 0:.2f}")

    # Warn about stale/extreme prices
    price = market.last_price_yes
    if price is not None and (price <= 0.03 or price >= 0.97):
        console.print(
            f"[bold yellow]Warning:[/] Price is extreme (${price:.2f}) — "
            "this market may be resolved or stale. Edge calculations may be unreliable."
        )
    if price is not None and price == 0.0:
        console.print("[bold red]Warning:[/] Price is $0.00 — this market appears dead/resolved.")
        if not click.confirm("Analyze anyway?", default=False):
            return

    estimator = ProbabilityEstimator()
    calibration_text = export_calibration_for_llm()

    with console.status("Running 3-pass estimation..."):
        estimate = estimator.estimate(market, calibration_text)

    console.print(f"\n[bold green]Agent Estimate:[/] {estimate.final_estimate:.1%}")
    console.print(f"Confidence: [{estimate.confidence_low:.1%}, {estimate.confidence_high:.1%}]")
    console.print(f"Base rate: {estimate.base_rate:.1%}")
    console.print(f"\n[bold]Thesis:[/] {estimate.thesis}")

    # Edge calculation
    paper = PaperTrader()
    bankroll = paper.get_cash_balance()
    rec = build_recommendation(market, estimate, bankroll)

    if rec:
        console.print(f"\n[bold yellow]Trade Recommendation:[/]")
        console.print(f"  Side: {rec.side.value}")
        console.print(f"  Edge: {rec.adjusted_edge:.1%} (raw: {rec.raw_edge:.1%})")
        console.print(f"  Size: ${rec.recommended_size:.2f}")
        console.print(f"  Limit price: ${rec.limit_price:.4f}")
    else:
        console.print("\n[dim]No trade recommended (edge below threshold)[/]")

    # Show LLM costs
    usage = estimator.llm.get_usage_summary()
    console.print(f"\n[dim]LLM usage: {usage['calls']} calls, ~${usage['estimated_cost']:.4f}[/]")


@cli.command()
def portfolio():
    """Display current portfolio status."""
    from polymarket_agent.trading.paper import PaperTrader

    paper = PaperTrader()
    summary = paper.get_portfolio_summary()

    console.print(f"\n[bold]Portfolio ({summary.mode.value} mode)[/]")
    console.print(f"  Cash: ${summary.cash_balance:.2f}")
    console.print(f"  Positions value: ${summary.total_position_value:.2f}")
    console.print(f"  Total value: ${summary.total_portfolio_value:.2f}")
    console.print(f"  Realized P&L: ${summary.realized_pnl:+.2f}")
    console.print(f"  Unrealized P&L: ${summary.unrealized_pnl:+.2f}")
    console.print(f"  Return: {summary.total_return_pct:+.2f}%")
    console.print(f"  Open positions: {summary.open_positions}")

    if summary.positions:
        table = Table(title="Open Positions")
        table.add_column("Market", max_width=40)
        table.add_column("Side")
        table.add_column("Shares", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Cost", justify="right")

        for pos in summary.positions:
            table.add_row(
                pos.market_id[:8] + "...",
                pos.side.value,
                f"{pos.size:.2f}",
                f"${pos.entry_price:.4f}",
                f"${pos.size * pos.entry_price:.2f}",
            )
        console.print(table)

    # Show recent trades
    trades = paper.get_trade_history(limit=10)
    if trades:
        trade_table = Table(title="Recent Trades")
        trade_table.add_column("Time", max_width=20)
        trade_table.add_column("Market", max_width=20)
        trade_table.add_column("Action")
        trade_table.add_column("Side")
        trade_table.add_column("Size", justify="right")
        trade_table.add_column("Price", justify="right")

        for t in trades:
            trade_table.add_row(
                t.timestamp.strftime("%Y-%m-%d %H:%M"),
                t.market_id[:8] + "...",
                t.action.value.upper(),
                t.side.value,
                f"{t.size:.2f}",
                f"${t.price:.4f}",
            )
        console.print(trade_table)


@cli.command()
@click.argument("market_id")
@click.option("--side", type=click.Choice(["YES", "NO"]), required=True)
@click.option("--amount", type=float, required=True, help="Amount in USD")
@click.option("--live", is_flag=True, help="Execute as live trade (default: paper)")
def trade(market_id: str, side: str, amount: float, live: bool):
    """Place a manual trade (paper or live)."""
    from polymarket_agent.market.storage import get_market
    from polymarket_agent.models import Side as SideEnum
    from polymarket_agent.models import TradeRecommendation

    market = get_market(market_id)
    if not market:
        console.print(f"[red]Market '{market_id}' not found.[/]")
        return

    price = market.last_price_yes if side == "YES" else (1.0 - (market.last_price_yes or 0.5))

    console.print(f"\n[bold]Trade Order:[/]")
    console.print(f"  Market: {market.question[:60]}")
    console.print(f"  Side: {side}")
    console.print(f"  Amount: ${amount:.2f}")
    console.print(f"  Price: ${price:.4f}")
    console.print(f"  Mode: {'LIVE' if live else 'PAPER'}")

    if not click.confirm("\nConfirm trade?"):
        console.print("[dim]Trade cancelled.[/]")
        return

    rec = TradeRecommendation(
        market_id=market.id,
        market_question=market.question,
        side=SideEnum(side),
        raw_edge=0,
        adjusted_edge=0,
        market_price=price,
        agent_estimate=0,
        recommended_size=amount,
        limit_price=price,
        reasoning="Manual trade",
        thesis="Manual trade",
        confidence_low=0,
        confidence_high=1,
    )

    if live:
        from polymarket_agent.trading.executor import LiveExecutor
        executor = LiveExecutor()
        order_id = executor.place_order(rec)
        if order_id:
            console.print(f"[green]Live order placed: {order_id}[/]")
        else:
            console.print("[red]Order failed.[/]")
    else:
        from polymarket_agent.trading.paper import PaperTrader
        paper = PaperTrader()
        trade_result = paper.execute_trade(rec)
        if trade_result:
            console.print("[green]Paper trade executed.[/]")
        else:
            console.print("[red]Paper trade failed (insufficient funds?).[/]")


@cli.command()
def report():
    """Generate a daily activity report."""
    from polymarket_agent.trading.calibration import compute_calibration
    from polymarket_agent.trading.paper import PaperTrader

    paper = PaperTrader()
    summary = paper.get_portfolio_summary()
    cal = compute_calibration()

    console.print("\n[bold]Daily Report[/]")
    console.print(f"  Portfolio value: ${summary.total_portfolio_value:.2f}")
    console.print(f"  Cash: ${summary.cash_balance:.2f}")
    console.print(f"  Open positions: {summary.open_positions}")
    console.print(f"  Realized P&L: ${summary.realized_pnl:+.2f}")
    console.print(f"  Return: {summary.total_return_pct:+.2f}%")

    console.print(f"\n[bold]Calibration[/]")
    console.print(f"  Total predictions: {cal.total_predictions}")
    console.print(f"  Resolved: {cal.resolved_predictions}")
    if cal.brier_score is not None:
        console.print(f"  Brier score: {cal.brier_score:.4f}")

    trades = paper.get_trade_history(limit=5)
    if trades:
        console.print(f"\n[bold]Recent trades: {len(trades)}[/]")
        for t in trades:
            console.print(
                f"  {t.timestamp.strftime('%m/%d %H:%M')} "
                f"{t.action.value.upper()} {t.side.value} {t.market_id[:8]}... "
                f"${t.size * t.price:.2f}"
            )


@cli.command()
@click.option("--paper", "paper_mode", is_flag=True, default=True, help="Run in paper trading mode")
@click.option("--live", "live_mode", is_flag=True, help="Run in live trading mode")
@click.option("--predict", "predict_mode", is_flag=True, help="Run in prediction-only mode (no trading)")
def run(paper_mode: bool, live_mode: bool, predict_mode: bool):
    """Start the automated agent loop."""
    from polymarket_agent.cli.scheduler import AgentScheduler

    if predict_mode:
        mode = "predict"
    elif live_mode:
        mode = "live"
    else:
        mode = "paper"
    console.print(f"\n[bold]Starting agent in {mode} mode[/]")
    console.print("Press Ctrl+C to stop.\n")

    scheduler = AgentScheduler(mode=mode)

    def handle_signal(sig, frame):
        console.print("\n[yellow]Shutting down...[/]")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    scheduler.start()


@cli.command()
@click.option("--cancel-orders", is_flag=True, help="Also cancel all open orders")
def kill(cancel_orders: bool):
    """Activate the kill switch to halt all trading."""
    from polymarket_agent.risk.manager import RiskManager

    rm = RiskManager()
    rm.activate_kill_switch("Manual CLI activation")
    console.print("[bold red]KILL SWITCH ACTIVATED[/]")

    if cancel_orders:
        from polymarket_agent.trading.executor import LiveExecutor
        executor = LiveExecutor()
        count = executor.cancel_all_open_orders()
        console.print(f"  Cancelled {count} open orders")


@cli.command()
def config():
    """Display current configuration."""
    table = Table(title="Configuration")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Anthropic API Key", "***" + settings.anthropic_api_key[-4:] if settings.anthropic_api_key else "[red]NOT SET[/]")
    table.add_row("Tavily API Key", "***" + settings.tavily_api_key[-4:] if settings.tavily_api_key else "[red]NOT SET[/]")
    table.add_row("Polymarket Key", "***" + settings.polymarket_private_key[-4:] if settings.polymarket_private_key else "[dim]NOT SET (paper only)[/]")
    table.add_row("", "")
    table.add_row("Screening Model", settings.screening_model)
    table.add_row("Analysis Model", settings.analysis_model)
    table.add_row("", "")
    table.add_row("Min Volume", f"${settings.min_volume:,.0f}")
    table.add_row("Price Range", f"${settings.min_price:.2f} - ${settings.max_price:.2f}")
    table.add_row("Resolution Window", f"{settings.min_days_to_resolution}-{settings.max_days_to_resolution} days")
    table.add_row("Categories", ", ".join(settings.tracked_categories))
    table.add_row("", "")
    table.add_row("Min Edge", f"{settings.min_edge_threshold:.0%}")
    table.add_row("Kelly Fraction", f"{settings.kelly_fraction:.0%}")
    table.add_row("Max Per Market", f"${settings.max_position_per_market:.0f}")
    table.add_row("Max Portfolio", f"${settings.max_portfolio_exposure:.0f}")
    table.add_row("Max Per Category", f"${settings.max_category_exposure:.0f}")
    table.add_row("Daily Loss Limit", f"${settings.daily_loss_limit:.0f}")
    table.add_row("", "")
    table.add_row("Scan Interval", f"{settings.scan_interval // 60} min")
    table.add_row("Analysis Interval", f"{settings.analysis_interval // 60} min")
    table.add_row("Max Analyses/Cycle", f"{settings.max_analyses_per_cycle}" if settings.max_analyses_per_cycle > 0 else "Unlimited")
    table.add_row("Re-eval Exit Threshold", f"{settings.reeval_edge_exit_threshold:.2f}")
    table.add_row("Re-eval Reanalysis Threshold", f"{settings.reeval_reanalysis_threshold:.2f}")
    table.add_row("Re-eval Staleness", f"{settings.reeval_staleness_days} days")
    table.add_row("Max Re-analyses/Cycle", f"{settings.max_reanalyses_per_cycle}")
    table.add_row("Snapshot Retention", f"{settings.snapshot_retention_days} days")
    table.add_row("DB Path", str(settings.db_path))

    # Kill switch status
    from polymarket_agent.risk.manager import RiskManager
    rm = RiskManager()
    ks_status = "[bold red]ACTIVE[/]" if rm.is_kill_switch_active() else "[green]Inactive[/]"
    table.add_row("Kill Switch", ks_status)

    console.print(table)


if __name__ == "__main__":
    cli()
