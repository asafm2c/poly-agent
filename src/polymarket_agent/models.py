from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Side(str, Enum):
    YES = "YES"
    NO = "NO"


class TradeAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class OrderStatus(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


# --- Market ---


class Market(BaseModel):
    id: str
    condition_id: str | None = None
    question: str
    description: str | None = None
    category: str | None = None
    end_date: datetime | None = None
    outcome_yes_token: str | None = None
    outcome_no_token: str | None = None
    volume: float = 0.0
    liquidity: float = 0.0
    last_price_yes: float | None = None
    last_price_no: float | None = None
    active: bool = True
    resolved: bool = False
    resolution_outcome: str | None = None
    first_seen_at: datetime | None = None
    last_updated_at: datetime | None = None
    event_id: str | None = None
    event_title: str | None = None
    maker_base_fee: float = 0.0
    taker_base_fee: float = 0.0


class MarketEvent(BaseModel):
    market_id: str
    event_type: str  # "price_change", "volume_spike", "new_market", "approaching_resolution"
    magnitude: float | None = None
    direction: str | None = None  # "up", "down"
    detected_at: datetime = Field(default_factory=datetime.utcnow)


# --- Position & Trade ---


class Position(BaseModel):
    id: int | None = None
    market_id: str
    side: Side
    size: float
    entry_price: float
    entry_timestamp: datetime
    exit_price: float | None = None
    exit_timestamp: datetime | None = None
    realized_pnl: float | None = None
    status: PositionStatus = PositionStatus.OPEN
    mode: TradingMode = TradingMode.PAPER
    order_id: str | None = None


class Trade(BaseModel):
    id: int | None = None
    market_id: str
    position_id: int | None = None
    side: Side
    action: TradeAction
    size: float
    price: float
    timestamp: datetime
    mode: TradingMode = TradingMode.PAPER
    order_id: str | None = None
    status: str = "filled"


# --- Order Book ---


class OrderBookSignals(BaseModel):
    imbalance_ratio: float  # total_bid / (total_bid + total_ask), 0.5 = balanced
    spread_width: float  # best_ask - best_bid
    depth_at_price: float  # total liquidity within 5% of midpoint


# --- Research ---


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float | None = None


class ResearchDossier(BaseModel):
    market_id: str
    market_question: str
    market_description: str | None = None
    market_category: str | None = None
    market_end_date: datetime | None = None
    current_price_yes: float | None = None
    current_price_no: float | None = None
    web_search_results: list[SearchResult] = Field(default_factory=list)
    polymarket_comments: list[str] = Field(default_factory=list)
    comment_sentiment_summary: str | None = None
    related_markets: list[dict] = Field(default_factory=list)
    domain_data: dict | None = None
    price_history: list[dict] = Field(default_factory=list)
    order_book_signals: OrderBookSignals | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    cached: bool = False


# --- Probability Estimation ---


class ProbabilityEstimate(BaseModel):
    market_id: str
    final_estimate: float
    confidence_low: float
    confidence_high: float
    base_rate: float
    updated_estimate: float
    pass1_reasoning: str
    pass2_reasoning: str
    pass25_reasoning: str | None = None
    pass3_reasoning: str | None = None
    key_evidence: list[str] = Field(default_factory=list)
    thesis: str
    screening_passed: bool = True
    screening_reasoning: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    blind_pass2_estimate: float | None = None


# --- Edge & Trade Recommendation ---


class TradeRecommendation(BaseModel):
    market_id: str
    market_question: str
    side: Side
    raw_edge: float
    adjusted_edge: float
    market_price: float
    agent_estimate: float
    recommended_size: float
    limit_price: float
    reasoning: str
    thesis: str
    confidence_low: float
    confidence_high: float


class RiskCheckResult(BaseModel):
    passed: bool
    reason: str | None = None
    adjusted_size: float | None = None


# --- Portfolio ---


class PortfolioSummary(BaseModel):
    cash_balance: float
    total_position_value: float
    total_portfolio_value: float
    open_positions: int
    realized_pnl: float
    unrealized_pnl: float
    total_return_pct: float
    mode: TradingMode
    positions: list[Position] = Field(default_factory=list)


# --- Prediction (for calibration) ---


class Prediction(BaseModel):
    id: int | None = None
    market_id: str
    timestamp: datetime
    market_price: float
    agent_estimate: float
    confidence_low: float | None = None
    confidence_high: float | None = None
    base_rate: float | None = None
    updated_estimate: float | None = None
    final_estimate: float | None = None
    reasoning: str | None = None
    thesis: str | None = None
    category: str | None = None
    outcome: float | None = None
    prediction_error: float | None = None
    resolved_at: datetime | None = None


class CalibrationBucket(BaseModel):
    bucket_low: float
    bucket_high: float
    count: int
    avg_predicted: float
    actual_rate: float
    calibration_error: float


class CalibrationReport(BaseModel):
    total_predictions: int
    resolved_predictions: int
    brier_score: float | None = None
    buckets: list[CalibrationBucket] = Field(default_factory=list)
    category: str | None = None
    summary: str | None = None
