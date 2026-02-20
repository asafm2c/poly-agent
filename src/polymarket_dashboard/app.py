"""Dashboard web server — fully decoupled from the trading engine."""

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from polymarket_dashboard.db import BacktestDB, DashboardDB
from polymarket_dashboard.routes import (
    calibration,
    evaluation,
    hypotheses,
    metrics,
    operations,
    portfolio,
    positions,
)


def create_app(db_path: Path | None = None, backtest_db_path: Path | None = None) -> FastAPI:
    path = db_path or Path(os.environ.get("DASHBOARD_DB_PATH", "polymarket_agent.db"))
    bt_path = backtest_db_path or Path(os.environ.get("BACKTEST_DB_PATH", "backtest.db"))

    app = FastAPI(title="Polymarket Agent Dashboard", docs_url="/api/docs")
    app.state.db = DashboardDB(path)
    app.state.backtest_db = BacktestDB.create(bt_path)
    app.state.starting_balance = float(os.environ.get("PAPER_STARTING_BALANCE", "1000.0"))

    app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
    app.include_router(calibration.router, prefix="/api/calibration", tags=["calibration"])
    app.include_router(operations.router, prefix="/api/operations", tags=["operations"])
    app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])
    app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])
    app.include_router(hypotheses.router, prefix="/api/hypotheses", tags=["hypotheses"])

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True))

    return app


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Polymarket Agent Dashboard")
    parser.add_argument("--db", type=Path, default=None, help="Path to SQLite database")
    parser.add_argument("--backtest-db", type=Path, default=None, help="Path to backtest database")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8050, help="Port to bind to")
    args = parser.parse_args()

    app = create_app(db_path=args.db, backtest_db_path=args.backtest_db)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
