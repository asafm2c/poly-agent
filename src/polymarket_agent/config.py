from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # --- API Keys ---
    anthropic_api_key: str = ""
    tavily_api_key: str = ""

    # --- Polymarket (live trading) ---
    polymarket_private_key: str = ""
    polymarket_funder_address: str = ""

    # --- Telegram (optional) ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- LLM Models ---
    screening_model: str = "claude-haiku-4-5-20251001"
    analysis_model: str = "claude-sonnet-4-6"

    # --- Market Scanner Filters ---
    min_volume: float = 10_000.0
    min_liquidity: float = 1_000.0
    min_price: float = 0.10
    max_price: float = 0.90
    min_days_to_resolution: int = 1
    max_days_to_resolution: int = 60
    tracked_categories: list[str] = Field(default_factory=lambda: ["politics", "crypto"])
    price_change_threshold: float = 0.05

    # --- Edge & Position Sizing ---
    min_edge_threshold: float = 0.10
    kelly_fraction: float = 0.5
    max_position_per_market: float = 50.0
    max_portfolio_exposure: float = 500.0
    max_category_exposure: float = 200.0
    daily_loss_limit: float = -50.0
    max_slippage: float = 0.02
    default_fee_rate: float = 0.0  # Polymarket taker fee rate (0.0 = free)
    default_fee_exponent: float = 1.0  # Fee formula exponent

    # --- Opportunity Scoring Weights ---
    opportunity_weight_price: float = 0.20
    opportunity_weight_volume: float = 0.25
    opportunity_weight_event: float = 0.20
    opportunity_weight_screen: float = 0.15
    opportunity_weight_time: float = 0.10
    opportunity_weight_calibration: float = 0.10

    # --- Paper Trading ---
    paper_starting_balance: float = 1000.0

    # --- Scheduler Intervals (seconds) ---
    scan_interval: int = 900  # 15 minutes
    analysis_interval: int = 3600  # 1 hour
    reevaluation_interval: int = 14400  # 4 hours
    daily_report_hour: int = 18  # UTC
    max_analyses_per_cycle: int = 5  # Cap LLM calls per analysis cycle (0 = unlimited)

    # --- Re-evaluation ---
    reeval_edge_exit_threshold: float = 0.0  # Exit without re-analysis below this edge
    reeval_reanalysis_threshold: float = 0.05  # Trigger LLM re-analysis below this edge
    reeval_staleness_days: int = 7  # Re-analyze positions held longer than this
    max_reanalyses_per_cycle: int = 3  # Cap LLM calls per re-evaluation cycle

    # --- Price Snapshots ---
    snapshot_retention_days: int = 30

    # --- Order Management ---
    order_timeout_seconds: int = 3600  # 1 hour

    # --- Storage ---
    db_path: Path = Path("polymarket_agent.db")

    # --- Polymarket API ---
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"
    chain_id: int = 137


settings = Settings()
