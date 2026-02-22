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
    rec, adj_edge, req_threshold = build_recommendation(market, estimate, bankroll)

    if rec:
        console.print(f"\n[bold yellow]Trade Recommendation:[/]")
        console.print(f"  Side: {rec.side.value}")
        console.print(f"  Edge: {rec.adjusted_edge:.1%} (raw: {rec.raw_edge:.1%})")
        console.print(f"  Threshold: {req_threshold:.1%}")
        console.print(f"  Size: ${rec.recommended_size:.2f}")
        console.print(f"  Limit price: ${rec.limit_price:.4f}")
    else:
        console.print(f"\n[dim]No trade recommended (edge {adj_edge:.1%} below threshold {req_threshold:.1%})[/]")

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


@cli.group()
def backtest():
    """Backtest tools: collect historical data, analyze markets, manage strategy."""
    pass


@backtest.command()
@click.option("--histories-only", is_flag=True, help="Skip market collection, only fetch price histories")
@click.option("--min-volume", type=float, default=None, help="Only fetch histories for markets above this volume")
@click.option("--job-id", type=int, default=None, help="Use an existing bt_import_jobs row (set by dashboard)")
@click.option("--market-type", "market_types", multiple=True, help="Restrict history collection to market type (repeatable).")
def collect(histories_only: bool, min_volume: float | None, job_id: int | None, market_types: tuple[str, ...]):
    """Collect resolved markets and price histories from Polymarket."""
    from polymarket_agent.backtest.collector import BacktestCollector

    collector = BacktestCollector()
    try:
        if histories_only:
            console.print("Collecting price histories only...")
            collected, skipped = collector.collect_histories_only(
                min_volume=min_volume,
                job_id=job_id,
                market_types=list(market_types) if market_types else None,
            )
            console.print(f"\n[bold green]Collection complete[/]")
            console.print(f"  Price histories collected: {collected}")
            console.print(f"  Skipped: {skipped}")
        else:
            with console.status("Collecting resolved markets..."):
                result = collector.collect(job_id=job_id)
            console.print(f"\n[bold green]Collection complete[/]")
            console.print(f"  Markets collected: {result['markets_collected']}")
            console.print(f"  Price histories collected: {result['history_collected']}")
            console.print(f"  Skipped: {result['history_skipped']}")
        console.print(f"  Job ID: {collector._job_id}")
    finally:
        collector.close()


@backtest.command("jobs")
def list_jobs():
    """List recent import jobs from backtest.db."""
    from polymarket_agent.backtest.database import get_backtest_db
    from polymarket_agent.config import settings
    from datetime import datetime, timezone
    from rich.table import Table

    try:
        with get_backtest_db(settings.backtest_db_path) as conn:
            rows = conn.execute(
                """SELECT id, job_type, status, markets_done, histories_total,
                          histories_done, histories_skipped, started_at, completed_at, error_msg
                   FROM bt_import_jobs
                   ORDER BY id DESC LIMIT 10"""
            ).fetchall()
    except Exception as e:
        console.print(f"[red]Error reading jobs: {e}[/]")
        return

    if not rows:
        console.print("No import jobs found.")
        return

    now = datetime.now(timezone.utc)
    table = Table(title="Import Jobs", show_lines=False)
    table.add_column("ID", style="bold", width=5)
    table.add_column("Type", width=18)
    table.add_column("Status", width=10)
    table.add_column("Progress", width=20)
    table.add_column("Started", width=20)
    table.add_column("Duration", width=10)

    status_colors = {
        "running": "blue",
        "done": "green",
        "failed": "red",
        "stalled": "yellow",
        "cancelled": "dim",
    }

    for r in rows:
        status = r["status"]
        color = status_colors.get(status, "white")
        status_str = f"[{color}]{status}[/]"

        # Progress
        if r["histories_total"]:
            pct = round(r["histories_done"] / r["histories_total"] * 100, 1)
            progress = f"{r['histories_done']}/{r['histories_total']} ({pct}%)"
        elif r["markets_done"]:
            progress = f"markets: {r['markets_done']}"
        else:
            progress = "-"

        # Duration
        started = r["started_at"]
        end = r["completed_at"]
        if started:
            try:
                start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else now
                secs = int((end_dt - start_dt).total_seconds())
                if secs >= 3600:
                    duration = f"{secs // 3600}h {(secs % 3600) // 60}m"
                elif secs >= 60:
                    duration = f"{secs // 60}m {secs % 60}s"
                else:
                    duration = f"{secs}s"
            except Exception:
                duration = "-"
        else:
            duration = "-"

        started_display = started[:19].replace("T", " ") if started else "-"

        table.add_row(
            str(r["id"]),
            r["job_type"] or "-",
            status_str,
            progress,
            started_display,
            duration,
        )

    console.print(table)


@backtest.command("backfill")
@click.option("--stats", is_flag=True, help="Show current distribution without re-classifying")
def backtest_backfill(stats: bool):
    """Classify all bt_markets rows and write market_type. Use --stats to view without modifying."""
    from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
    from polymarket_agent.config import settings
    from rich.table import Table as RichTable

    init_backtest_db()

    if stats:
        with get_backtest_db(settings.backtest_db_path) as conn:
            rows = conn.execute(
                """SELECT COALESCE(market_type, '(null)') as mtype, COUNT(*) as cnt
                FROM bt_markets
                GROUP BY mtype
                ORDER BY cnt DESC"""
            ).fetchall()

        table = RichTable(title="Market Type Distribution (current)")
        table.add_column("market_type")
        table.add_column("count", justify="right")
        for r in rows:
            table.add_row(r["mtype"], f"{r['cnt']:,}")
        console.print(table)
        return

    # Full backfill
    from polymarket_agent.backtest.classifier import classify_market_type

    with get_backtest_db(settings.backtest_db_path) as conn:
        rows = conn.execute(
            "SELECT id, question, category FROM bt_markets"
        ).fetchall()

        total = len(rows)
        console.print(f"Classifying {total:,} markets...")

        batch_size = 1000
        for i in range(0, total, batch_size):
            batch = rows[i : i + batch_size]
            updates = [
                (classify_market_type(r["question"], r["category"]), r["id"])
                for r in batch
            ]
            conn.executemany(
                "UPDATE bt_markets SET market_type = ? WHERE id = ?", updates
            )
            if i % 10000 == 0 and i > 0:
                console.print(f"  {i:,}/{total:,}...")

        summary_rows = conn.execute(
            """SELECT COALESCE(market_type, '(null)') as mtype, COUNT(*) as cnt
            FROM bt_markets
            GROUP BY mtype
            ORDER BY cnt DESC"""
        ).fetchall()

    table = RichTable(title=f"Backfill Complete — {total:,} markets classified")
    table.add_column("market_type")
    table.add_column("count", justify="right")
    for r in summary_rows:
        table.add_row(r["mtype"], f"{r['cnt']:,}")
    console.print(table)


@backtest.command("analyze")
@click.option("--category", "-c", help="Filter by category")
@click.option("--regime", "-r", help="Filter by regime (e.g. o1-era, GPT4o-era)")
@click.option("--horizon", "-h", type=int, default=7, help="Days before resolution (default: 7)")
@click.option("--volume-min", type=float, help="Minimum volume filter")
@click.option("--volume-max", type=float, help="Maximum volume filter")
def analyze_backtest(
    category: str | None,
    regime: str | None,
    horizon: int,
    volume_min: float | None,
    volume_max: float | None,
):
    """Run analysis on historical market data."""
    from polymarket_agent.backtest.analysis import (
        category_calibration,
        cross_market_arbitrage,
        efficiency_index,
        load_markets,
        market_baseline_brier,
    )

    with console.status("Loading markets..."):
        markets = load_markets(
            category=category,
            regime=regime,
            volume_min=volume_min,
            volume_max=volume_max,
        )

    if not markets:
        console.print("[yellow]No markets found matching filters[/]")
        return

    console.print(f"\n[bold]Loaded {len(markets)} markets[/]")
    if category:
        console.print(f"  Category: {category}")
    if regime:
        console.print(f"  Regime: {regime}")

    # Market baseline Brier
    baseline = market_baseline_brier(markets, horizon=horizon)
    console.print(f"\n[bold]Market Baseline Brier (horizon={horizon}d)[/]")
    if baseline["brier_score"] is not None:
        console.print(f"  Brier score: {baseline['brier_score']:.4f} ({baseline['count']} markets)")
    else:
        console.print("  [dim]Insufficient data[/]")

    # Efficiency index
    eff = efficiency_index(markets)
    console.print(f"\n[bold]Efficiency Index[/]")
    for h, data in sorted(eff.items()):
        if data["efficiency"] is not None:
            console.print(f"  {h:2d}d: {data['efficiency']:.4f} ({data['count']} markets)")

    # Category calibration
    cal = category_calibration(markets)
    if cal:
        cal_table = Table(title="Category Calibration")
        cal_table.add_column("Category")
        cal_table.add_column("Avg Price", justify="right")
        cal_table.add_column("Avg Outcome", justify="right")
        cal_table.add_column("Bias", justify="right")
        cal_table.add_column("Count", justify="right")

        for cat, data in sorted(cal.items(), key=lambda x: abs(x[1]["bias"]), reverse=True):
            bias_style = "red" if abs(data["bias"]) > 0.05 else ""
            cal_table.add_row(
                cat,
                f"{data['avg_price']:.4f}",
                f"{data['avg_outcome']:.4f}",
                f"[{bias_style}]{data['bias']:+.4f}[/{bias_style}]" if bias_style else f"{data['bias']:+.4f}",
                str(data["count"]),
            )
        console.print(cal_table)

    # Cross-market arbitrage
    arb = cross_market_arbitrage(markets)
    flagged = [a for a in arb if abs(a["deviation"]) > 0.10]
    if flagged:
        console.print(f"\n[bold]Cross-Market Arbitrage ({len(flagged)} events flagged)[/]")
        for a in flagged[:10]:
            console.print(
                f"  Event {a['event_id'][:8]}: {a['market_count']} markets, "
                f"sum={a['price_sum']:.2f}, deviation={a['deviation']:+.4f}"
            )


@backtest.command("strategy")
def show_strategy():
    """Display current strategy configuration."""
    from polymarket_agent.backtest.strategy import load_strategy_config

    config = load_strategy_config()

    console.print(f"\n[bold]Strategy Configuration v{config.get('version', '?')}[/]")
    console.print(f"  Updated: {config.get('updated_at', 'unknown')}")
    console.print(f"  By: {config.get('updated_by', 'unknown')}")

    ms = config.get("market_selection", {})
    console.print(f"\n[bold]Market Selection[/]")
    console.print(f"  Target categories: {ms.get('target_categories') or 'all'}")
    console.print(f"  Avoid categories: {ms.get('avoid_categories') or 'none'}")
    console.print(f"  Volume range: {ms.get('volume_range', {})}")

    et = config.get("edge_thresholds", {})
    console.print(f"\n[bold]Edge Thresholds[/]")
    console.print(f"  Default: {et.get('default', '?')}")
    console.print(f"  Floor: {et.get('floor', '?')}, Ceiling: {et.get('ceiling', '?')}")
    overrides = et.get("category_overrides", {})
    if overrides:
        for cat, val in overrides.items():
            console.print(f"  Override: {cat} → {val}")

    ra = config.get("regime_awareness", {})
    console.print(f"\n[bold]Regime Awareness[/]")
    console.print(f"  Current: {ra.get('current_regime', '?')}")
    console.print(f"  Efficiency trend: {ra.get('efficiency_trend', '?')}")
    console.print(f"  Agent confidence: {ra.get('agent_confidence', '?')}")

    insights = config.get("insights", [])
    if insights:
        console.print(f"\n[bold]Recent Insights ({len(insights)} total)[/]")
        for ins in insights[-5:]:
            console.print(
                f"  [{ins.get('date', '?')}] {ins.get('finding', '')} "
                f"(confidence: {ins.get('confidence', '?')})"
            )


@backtest.command("simulate")
@click.option("--horizon", type=int, default=7, help="Days before resolution (default: 7)")
@click.option("--count", "-n", type=int, default=50, help="Number of markets to simulate (default: 50)")
@click.option("--category", "-c", help="Filter by category (default: null/prediction markets)")
@click.option("--min-volume", type=float, default=100000, help="Minimum volume (default: 100000)")
@click.option("--max-volume", type=float, default=None, help="Maximum volume")
@click.option("--regime", "-r", help="Filter by regime (e.g. o1-era)")
@click.option("--dry-run", is_flag=True, help="Preview market selection without running LLM")
@click.option("--concurrency", type=int, default=None, help="Max parallel trials (default: simulation_concurrency setting)")
@click.option("--market-type", "market_types", multiple=True,
              help="Restrict to market type (repeatable). Default: prediction.")
@click.option("--no-market-price", "blind", is_flag=True, default=False,
              help="Hide market price from LLM — measures independent signal only.")
def simulate_backtest(
    horizon: int,
    count: int,
    category: str | None,
    min_volume: float,
    max_volume: float | None,
    regime: str | None,
    dry_run: bool,
    concurrency: int | None,
    market_types: tuple[str, ...],
    blind: bool,
):
    """Run LLM estimation against historical markets to measure accuracy."""
    from polymarket_agent.backtest.simulator import run_simulation, select_markets

    resolved_types = list(market_types) if market_types else ["prediction"]

    console.print(f"\n[bold]Simulation Setup[/]")
    console.print(f"  Horizon: {horizon} days before resolution")
    console.print(f"  Target count: {count} markets")
    console.print(f"  Category: {category or '(null — prediction markets)'}")
    console.print(f"  Market types: {', '.join(resolved_types)}")
    console.print(f"  Volume: >= ${min_volume:,.0f}")
    if max_volume:
        console.print(f"  Max volume: <= ${max_volume:,.0f}")
    if regime:
        console.print(f"  Regime: {regime}")
    if blind:
        console.print(f"  [yellow]BLIND MODE — market price hidden from LLM[/]")
    if dry_run:
        console.print(f"  [yellow]DRY RUN — no LLM calls[/]")
    console.print("")

    with console.status("Selecting markets..."):
        markets = select_markets(
            count=count,
            category=category,
            volume_min=min_volume,
            volume_max=max_volume,
            regime=regime,
            horizon=horizon,
            market_types=resolved_types,
        )

    if not markets:
        console.print("[red]No eligible markets found matching filters.[/]")
        return

    console.print(f"Selected {len(markets)} markets.")

    if dry_run:
        result = run_simulation(markets, horizon=horizon, dry_run=True)
        table = Table(title=f"Dry Run: {result['total']} markets")
        table.add_column("ID", style="dim", max_width=16)
        table.add_column("Question", max_width=50)
        table.add_column("Volume", justify="right")
        table.add_column("Price@Horizon", justify="right")
        table.add_column("Outcome")

        for m in result["markets"]:
            table.add_row(
                m["id"],
                m["question"],
                f"${m['volume']:,.0f}",
                f"{m['price_at_horizon']:.3f}" if m["price_at_horizon"] else "N/A",
                m["outcome"],
            )
        console.print(table)
        if result["skipped"]:
            console.print(f"[yellow]Skipped {result['skipped']} markets (no price data at horizon)[/]")
        return

    console.print("Running estimation pipeline...\n")
    result = run_simulation(
        markets, horizon=horizon, concurrency=concurrency,
        include_market_price=not blind,
    )

    # Summary
    console.print(f"\n[bold green]Simulation Complete (Run #{result['run_id']})[/]")
    console.print(f"  Trials: {result['valid_trials']}/{result['market_count']}")
    console.print(f"  Elapsed: {result['elapsed_seconds']:.0f}s")
    console.print(f"  LLM cost: ${result['total_cost']:.4f}")

    console.print(f"\n[bold]Brier Score Comparison[/]")
    if result["agent_brier"] is not None:
        console.print(f"  Agent:  {result['agent_brier']:.4f}")
    console.print(f"  Market: {result['market_brier']:.4f}")
    if result["brier_diff"] is not None:
        diff = result["brier_diff"]
        style = "green" if diff < 0 else "red"
        console.print(f"  Diff:   [{style}]{diff:+.4f}[/{style}] ({'agent better' if diff < 0 else 'market better'})")

    console.print(f"\n[bold]Simulated P&L[/]")
    console.print(f"  Net P&L: ${result['simulated_pnl']:+.2f}")

    console.print(f"\n[dim]View details: polymarket backtest results --run-id {result['run_id']}[/]")


@backtest.command("results")
@click.option("--run-id", type=int, default=None, help="Simulation run ID (default: latest)")
def show_results(run_id: int | None):
    """Display simulation results."""
    from polymarket_agent.backtest.analysis import (
        simulation_by_category,
        simulation_by_volume_tier,
        simulation_summary,
    )
    from polymarket_agent.backtest.database import get_backtest_db

    # Get latest run if not specified
    if run_id is None:
        with get_backtest_db() as conn:
            row = conn.execute(
                "SELECT id FROM bt_simulation_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                console.print("[yellow]No simulation runs found. Run 'backtest simulate' first.[/]")
                return
            run_id = row["id"]

    # Summary
    summary = simulation_summary(run_id)
    if "error" in summary:
        console.print(f"[red]{summary['error']}[/]")
        return

    console.print(f"\n[bold]Simulation Run #{run_id}[/]")
    console.print(f"  Started: {summary['started_at']}")
    console.print(f"  Trials: {summary['valid_trials']}/{summary['trial_count']}")
    console.print(f"  Cost: ${summary['total_cost']:.4f}")

    # Brier comparison
    console.print(f"\n[bold]Brier Score Comparison[/]")
    if summary["agent_brier"] is not None:
        console.print(f"  Agent:  {summary['agent_brier']:.4f}")
    else:
        console.print(f"  Agent:  N/A")
    if summary["market_brier"] is not None:
        console.print(f"  Market: {summary['market_brier']:.4f}")
    if summary["brier_diff"] is not None:
        diff = summary["brier_diff"]
        style = "green" if diff < 0 else "red"
        console.print(f"  Diff:   [{style}]{diff:+.4f}[/{style}] ({'agent better' if diff < 0 else 'market better'})")
    if summary["valid_trials"] and summary["valid_trials"] < 10:
        console.print(f"  [yellow]Note: insufficient sample size for reliable comparison[/]")

    # P&L
    console.print(f"\n[bold]Simulated P&L[/]")
    console.print(f"  Net P&L: ${summary['simulated_pnl']:+.2f}")
    console.print(f"  Trades: {summary['trade_count']}")
    if summary["win_rate"] is not None:
        console.print(f"  Win rate: {summary['win_rate']:.0%}")

    # Category breakdown
    by_cat = simulation_by_category(run_id)
    if len(by_cat) > 1:
        cat_table = Table(title="By Category")
        cat_table.add_column("Category")
        cat_table.add_column("Agent Brier", justify="right")
        cat_table.add_column("Market Brier", justify="right")
        cat_table.add_column("Diff", justify="right")
        cat_table.add_column("Trials", justify="right")
        cat_table.add_column("P&L", justify="right")

        for cat, data in sorted(by_cat.items(), key=lambda x: x[1]["trial_count"], reverse=True):
            diff_str = ""
            if data["brier_diff"] is not None:
                d = data["brier_diff"]
                diff_str = f"[{'green' if d < 0 else 'red'}]{d:+.4f}[/]"
            cat_table.add_row(
                cat,
                f"{data['agent_brier']:.4f}" if data["agent_brier"] is not None else "N/A",
                f"{data['market_brier']:.4f}" if data["market_brier"] is not None else "N/A",
                diff_str,
                str(data["trial_count"]),
                f"${data['simulated_pnl']:+.2f}",
            )
        console.print(cat_table)

    # Volume tier breakdown
    by_vol = simulation_by_volume_tier(run_id)
    if len(by_vol) > 1:
        vol_table = Table(title="By Volume Tier")
        vol_table.add_column("Tier")
        vol_table.add_column("Agent Brier", justify="right")
        vol_table.add_column("Market Brier", justify="right")
        vol_table.add_column("Diff", justify="right")
        vol_table.add_column("Trials", justify="right")
        vol_table.add_column("P&L", justify="right")

        tier_order = [">10M", "1M-10M", "100K-1M", "10K-100K"]
        for tier in tier_order:
            if tier not in by_vol:
                continue
            data = by_vol[tier]
            diff_str = ""
            if data["brier_diff"] is not None:
                d = data["brier_diff"]
                diff_str = f"[{'green' if d < 0 else 'red'}]{d:+.4f}[/]"
            vol_table.add_row(
                tier,
                f"{data['agent_brier']:.4f}" if data["agent_brier"] is not None else "N/A",
                f"{data['market_brier']:.4f}" if data["market_brier"] is not None else "N/A",
                diff_str,
                str(data["trial_count"]),
                f"${data['simulated_pnl']:+.2f}",
            )
        console.print(vol_table)


# ---------------------------------------------------------------------------
# Model Aliases for evaluate command
# ---------------------------------------------------------------------------

MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}


def _resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name.lower(), name)


@backtest.command("evaluate")
@click.option("--models", "-m", multiple=True,
              help="Models to evaluate (haiku, sonnet, opus). Repeat for multiple.")
@click.option("--trials-per-cell", type=int, default=20,
              help="Minimum trials per category x volume cell (default: 20)")
@click.option("--categories", multiple=True,
              help="Categories to include (default: auto-discover). Use 'null' for null-category.")
@click.option("--horizon", type=int, default=7, help="Days before resolution (default: 7)")
@click.option("--budget", type=float, default=None, help="Maximum total LLM cost in USD")
@click.option("--all-at-once", is_flag=True, help="Run all models without intermediate prompts")
@click.option("--dry-run", is_flag=True, help="Preview market selection and cost estimate only")
@click.option("--concurrency", type=int, default=None, help="Max parallel trials (default: simulation_concurrency setting)")
@click.option("--market-type", "market_types", multiple=True,
              help="Restrict to market type (repeatable). Default: prediction.")
def evaluate_backtest(
    models: tuple[str, ...],
    trials_per_cell: int,
    categories: tuple[str, ...],
    horizon: int,
    budget: float | None,
    all_at_once: bool,
    dry_run: bool,
    concurrency: int | None,
    market_types: tuple[str, ...],
):
    """Run multi-model evaluation with stratified sampling and statistical comparison."""
    from polymarket_agent.backtest.simulator import (
        MODEL_COST_PER_TRIAL,
        select_markets_stratified,
        run_multi_model_evaluation,
    )

    # Resolve model names
    model_list = [_resolve_model(m) for m in models] if models else [
        MODEL_ALIASES["haiku"], MODEL_ALIASES["sonnet"]
    ]

    # Resolve categories
    cat_list = None
    if categories:
        cat_list = [None if c.lower() == "null" else c for c in categories]

    resolved_types = list(market_types) if market_types else ["prediction"]

    # Select markets
    with console.status("Selecting markets (stratified)..."):
        markets, cell_counts = select_markets_stratified(
            n_per_cell=trials_per_cell,
            categories=cat_list,
            horizon=horizon,
            market_types=resolved_types,
        )

    if not markets:
        console.print("[red]No eligible markets found.[/]")
        return

    # Display plan
    console.print(f"\n[bold]Evaluation Plan[/]")
    console.print(f"  Horizon: {horizon} days")
    console.print(f"  Trials per cell: {trials_per_cell}")
    console.print(f"  Total markets: {len(markets)}")
    console.print(f"  Cells: {len(cell_counts)}")

    # Cell counts table
    cell_table = Table(title="Market Selection by Cell")
    cell_table.add_column("Category")
    cell_table.add_column("Volume Tier")
    cell_table.add_column("Available", justify="right")
    cell_table.add_column("Selected", justify="right")
    cell_table.add_column("Flag")

    for (cat, tier), counts in sorted(cell_counts.items(), key=lambda x: (str(x[0][0]), x[0][1])):
        flag = "[yellow]![/]" if counts["selected"] < trials_per_cell else ""
        cell_table.add_row(
            str(cat) if cat is not None else "(null)",
            tier,
            str(counts["available"]),
            str(counts["selected"]),
            flag,
        )
    console.print(cell_table)

    # Cost estimate
    cost_table = Table(title="Cost Estimate")
    cost_table.add_column("Model")
    cost_table.add_column("Cost/Trial", justify="right")
    cost_table.add_column("Trials", justify="right")
    cost_table.add_column("Estimated", justify="right")

    total_est = 0.0
    for m in model_list:
        cpt = MODEL_COST_PER_TRIAL.get(m, 0.05)
        est = len(markets) * cpt
        total_est += est
        short_name = next((k for k, v in MODEL_ALIASES.items() if v == m), m)
        cost_table.add_row(short_name, f"${cpt:.3f}", str(len(markets)), f"${est:.2f}")

    cost_table.add_row("[bold]Total[/]", "", "", f"[bold]${total_est:.2f}[/]")
    console.print(cost_table)

    if budget is not None:
        if total_est <= budget:
            console.print(f"Budget: ${budget:.2f} — [green]all models fit[/]")
        else:
            console.print(f"Budget: ${budget:.2f} — [yellow]some models may be skipped[/]")

    if dry_run:
        console.print("\n[yellow]Dry run — no LLM calls made.[/]")
        return

    if not all_at_once:
        if not click.confirm("\nProceed with evaluation?", default=True):
            return

    # Progress callback for progressive mode
    def _progress_callback(model_name, result, comparison):
        short = next((k for k, v in MODEL_ALIASES.items() if v == model_name), model_name)
        console.print(f"\n[bold]--- {short.upper()} Results (Run #{result['run_id']}) ---[/]")
        if result.get("agent_brier") is not None:
            console.print(f"  Agent Brier: {result['agent_brier']:.4f}")
        console.print(f"  Market Brier: {result['market_brier']:.4f}")
        if result.get("brier_diff") is not None:
            d = result["brier_diff"]
            style = "green" if d < 0 else "red"
            console.print(f"  Diff: [{style}]{d:+.4f}[/{style}]")
        console.print(f"  Cost: ${result['total_cost']:.2f}")

        if comparison and "pairwise" in comparison:
            for pair, ci in comparison["pairwise"].items():
                sig = "[bold]*significant*[/]" if ci["significant"] else ""
                console.print(f"  {pair}: {ci['mean_diff']:+.4f} [{ci['ci_low']:+.4f}, {ci['ci_high']:+.4f}] {sig}")

        if all_at_once:
            return True
        return click.confirm(f"\nContinue to next model?", default=True)

    # Run evaluation
    console.print("\nRunning multi-model evaluation...\n")
    result = run_multi_model_evaluation(
        markets=markets,
        models=model_list,
        horizon=horizon,
        budget=budget,
        progressive=not all_at_once,
        progress_callback=_progress_callback if not all_at_once else None,
        concurrency=concurrency,
    )

    # Final report
    comparison = result.get("comparison", {})
    if comparison and "models" in comparison:
        console.print(f"\n[bold]{'=' * 60}[/]")
        console.print(f"[bold]Final Comparison Report[/]")

        model_table = Table(title="Model Comparison")
        model_table.add_column("Model")
        model_table.add_column("Brier", justify="right")
        model_table.add_column("vs Market", justify="right")
        model_table.add_column("Trials", justify="right")

        for m, summary in comparison["models"].items():
            short = next((k for k, v in MODEL_ALIASES.items() if v == m), m)
            diff_str = ""
            if summary.get("brier_diff") is not None:
                d = summary["brier_diff"]
                diff_str = f"[{'green' if d < 0 else 'red'}]{d:+.4f}[/]"
            model_table.add_row(
                short,
                f"{summary['agent_brier']:.4f}" if summary.get("agent_brier") else "N/A",
                diff_str,
                str(summary["trial_count"]),
            )
        console.print(model_table)

        if comparison.get("pairwise"):
            pair_table = Table(title="Pairwise Comparison")
            pair_table.add_column("Comparison")
            pair_table.add_column("Diff", justify="right")
            pair_table.add_column("95% CI", justify="right")
            pair_table.add_column("Sig?")

            for pair, ci in comparison["pairwise"].items():
                pair_table.add_row(
                    pair,
                    f"{ci['mean_diff']:+.4f}",
                    f"[{ci['ci_low']:+.4f}, {ci['ci_high']:+.4f}]",
                    "[green]Yes[/]" if ci["significant"] else "No",
                )
            console.print(pair_table)

    console.print(f"\n[dim]Total spent: ${result.get('total_spent', 0):.2f}[/]")


# ---------------------------------------------------------------------------
# Hypothesis CLI
# ---------------------------------------------------------------------------


@backtest.group()
def hypothesis():
    """Manage testable hypotheses about agent performance."""
    pass


@hypothesis.command("list")
@click.option("--status", "-s", type=click.Choice(
    ["proposed", "testing", "confirmed", "rejected", "invalidated", "all"]
), default="all", help="Filter by status")
def hypothesis_list(status: str):
    """List all hypotheses with their current status and confidence."""
    from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

    init_backtest_db()
    with get_backtest_db() as conn:
        if status == "all":
            rows = conn.execute(
                "SELECT * FROM bt_hypotheses ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bt_hypotheses WHERE status = ? ORDER BY id",
                (status,),
            ).fetchall()

        # Get evidence counts
        evidence_counts = {}
        for row in rows:
            cnt = conn.execute(
                "SELECT COUNT(*) as c FROM bt_hypothesis_evidence WHERE hypothesis_id = ?",
                (row["id"],),
            ).fetchone()
            evidence_counts[row["id"]] = cnt["c"]

    if not rows:
        console.print("[dim]No hypotheses found.[/]")
        return

    table = Table(title=f"Hypotheses ({len(rows)})")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Confidence", justify="right")
    table.add_column("Evidence", justify="right")
    table.add_column("Category")
    table.add_column("Volume Range")

    status_colors = {
        "proposed": "dim",
        "testing": "yellow",
        "confirmed": "green",
        "rejected": "red",
        "invalidated": "dim strikethrough",
    }

    for row in rows:
        s = row["status"]
        color = status_colors.get(s, "")
        vol_range = ""
        if row["volume_min"] or row["volume_max"]:
            vmin = f"${row['volume_min']:,.0f}" if row["volume_min"] else "-"
            vmax = f"${row['volume_max']:,.0f}" if row["volume_max"] else "-"
            vol_range = f"{vmin} - {vmax}"

        table.add_row(
            str(row["id"]),
            row["name"],
            f"[{color}]{s}[/{color}]",
            f"{row['confidence_score']:.2f}" if row["confidence_score"] else "0.00",
            str(evidence_counts.get(row["id"], 0)),
            row["category_filter"] or "(null)",
            vol_range,
        )
    console.print(table)


@hypothesis.command("propose")
@click.option("--name", "-n", required=True, help="Short unique name")
@click.option("--description", "-d", required=True, help="Testable description")
@click.option("--category", "-c", default=None, help="Category filter (use 'null' for prediction markets)")
@click.option("--volume-min", type=float, default=None, help="Minimum volume")
@click.option("--volume-max", type=float, default=None, help="Maximum volume")
@click.option("--half-life", type=int, default=90, help="Confidence decay half-life in days")
def hypothesis_propose(name, description, category, volume_min, volume_max, half_life):
    """Propose a new hypothesis about agent performance."""
    from polymarket_agent.backtest.hypothesis import propose

    cat = None if (category and category.lower() == "null") else category
    hyp_id = propose(
        name=name,
        description=description,
        category_filter=cat,
        volume_min=volume_min,
        volume_max=volume_max,
        decay_half_life_days=half_life,
    )
    console.print(f"\n[green]Hypothesis #{hyp_id} proposed: {name}[/]")
    console.print(f"  {description}")
    console.print(f"\n[dim]Next: polymarket backtest hypothesis test {hyp_id}[/]")


@hypothesis.command("test")
@click.argument("hypothesis_id", type=int)
@click.option("--count", "-n", type=int, default=50, help="Markets to simulate")
@click.option("--dry-run", is_flag=True, help="Preview market selection only")
def hypothesis_test(hypothesis_id: int, count: int, dry_run: bool):
    """Run targeted simulation to test a hypothesis."""
    from polymarket_agent.backtest.hypothesis import test as hyp_test

    console.print(f"\nTesting hypothesis #{hypothesis_id} with {count} markets...")

    if dry_run:
        console.print("[yellow]Dry run not yet supported for hypothesis test[/]")
        return

    result = hyp_test(hypothesis_id, count=count)
    if "error" in result:
        console.print(f"[red]{result['error']}[/]")
        return

    console.print(f"\n[green]Simulation complete (Run #{result['run_id']})[/]")
    console.print(f"  Trials: {result['valid_trials']}/{result['market_count']}")
    if result.get("agent_brier") is not None:
        console.print(f"  Agent Brier: {result['agent_brier']:.4f}")
    console.print(f"  Cost: ${result['total_cost']:.4f}")
    console.print(f"\n[dim]Next: polymarket backtest hypothesis evaluate {hypothesis_id}[/]")


@hypothesis.command("evaluate")
@click.argument("hypothesis_id", type=int)
def hypothesis_evaluate(hypothesis_id: int):
    """Evaluate evidence and update hypothesis status."""
    from polymarket_agent.backtest.hypothesis import evaluate

    result = evaluate(hypothesis_id)
    if "error" in result:
        console.print(f"[red]{result['error']}[/]")
        return

    prev = result.get("previous_status", "?")
    curr = result["status"]
    transition = f"{prev} → {curr}" if prev != curr else curr

    color = {"confirmed": "green", "rejected": "red", "invalidated": "red"}.get(curr, "yellow")
    console.print(f"\n[bold]Hypothesis #{hypothesis_id} Evaluation[/]")
    console.print(f"  Status: [{color}]{transition}[/{color}]")
    console.print(f"  Confidence: {result['confidence_score']:.2f}")
    console.print(f"  Evidence records: {result['evidence_count']}")
    console.print(f"  Weighted Brier diff: {result['weighted_brier_diff']:+.4f}")
    console.print(f"  Effective trials: {result['effective_trials']}")
    console.print(f"  Recommendation: {result['recommendation']}")


@hypothesis.command("retest")
@click.argument("hypothesis_id", type=int)
@click.option("--count", "-n", type=int, default=50, help="Markets to simulate")
def hypothesis_retest(hypothesis_id: int, count: int):
    """Run fresh simulation and re-evaluate with recency weighting."""
    from polymarket_agent.backtest.hypothesis import retest

    console.print(f"\nRe-testing hypothesis #{hypothesis_id}...")
    result = retest(hypothesis_id, count=count)

    test_result = result.get("test", {})
    eval_result = result.get("evaluation", {})

    if "error" in test_result:
        console.print(f"[red]{test_result['error']}[/]")
        return

    console.print(f"\n[green]Re-test complete[/]")
    console.print(f"  Run: #{test_result.get('run_id')}")
    console.print(f"  Status: {eval_result.get('status')}")
    console.print(f"  Confidence: {eval_result.get('confidence_score', 0):.2f}")
    console.print(f"  Recommendation: {eval_result.get('recommendation')}")


@hypothesis.command("actions")
def hypothesis_actions():
    """Display all active hypothesis-driven actions."""
    from polymarket_agent.backtest.hypothesis import load_active_hypothesis_actions

    actions = load_active_hypothesis_actions()
    if not actions:
        console.print("[dim]No active hypothesis actions.[/]")
        return

    table = Table(title=f"Active Hypothesis Actions ({len(actions)})")
    table.add_column("Hypothesis")
    table.add_column("Type")
    table.add_column("Config")
    table.add_column("Base Str", justify="right")
    table.add_column("Eff Str", justify="right")

    for a in actions:
        cfg_str = str(a["config"])[:40]
        table.add_row(
            a["hypothesis_name"],
            a["action_type"],
            cfg_str,
            f"{a['base_strength']:.2f}",
            f"{a['effective_strength']:.2f}",
        )
    console.print(table)


@hypothesis.command("decay-check")
def hypothesis_decay_check():
    """Check confirmed hypotheses for confidence decay."""
    from polymarket_agent.backtest.hypothesis import decay_check

    results = decay_check()
    if not results:
        console.print("[dim]No confirmed hypotheses to check.[/]")
        return

    table = Table(title="Hypothesis Decay Check")
    table.add_column("Name")
    table.add_column("Original", justify="right")
    table.add_column("Decayed", justify="right")
    table.add_column("Days Since", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Action")

    for r in results:
        color = {"ok": "green", "retest": "yellow", "invalidate": "red"}.get(
            r["recommendation"], ""
        )
        table.add_row(
            r["name"],
            f"{r['original_confidence']:.2f}",
            f"{r['decayed_confidence']:.2f}",
            str(r["days_since_evidence"]),
            f"{r['retest_threshold']:.2f}",
            f"[{color}]{r['recommendation'].upper()}[/{color}]",
        )
    console.print(table)


if __name__ == "__main__":
    cli()
