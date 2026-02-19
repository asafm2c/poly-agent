"""Calibration tracker: record predictions, compute accuracy, export for LLM."""

import logging
from datetime import datetime

from polymarket_agent.models import (
    CalibrationBucket,
    CalibrationReport,
    Prediction,
    ProbabilityEstimate,
)
from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)

BUCKETS = [(i / 10, (i + 1) / 10) for i in range(10)]  # 0.0-0.1, 0.1-0.2, ..., 0.9-1.0


def get_prediction_for_position(market_id: str) -> float | None:
    """Get the most recent prediction's final_estimate for a market.

    Returns the estimate value, or None if no prediction exists.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT final_estimate FROM predictions
            WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1""",
            (market_id,),
        ).fetchone()
    return row["final_estimate"] if row else None


def record_prediction(
    estimate: ProbabilityEstimate,
    market_price: float,
    category: str | None = None,
    edge: float | None = None,
    threshold: float | None = None,
) -> int:
    """Record a prediction in the database. Returns the prediction ID."""
    now = datetime.utcnow()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO predictions
            (market_id, timestamp, market_price, agent_estimate,
             confidence_low, confidence_high, base_rate, updated_estimate,
             final_estimate, reasoning, thesis, category,
             edge_at_prediction, threshold_at_prediction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                estimate.market_id,
                now.isoformat(),
                market_price,
                estimate.final_estimate,
                estimate.confidence_low,
                estimate.confidence_high,
                estimate.base_rate,
                estimate.updated_estimate,
                estimate.final_estimate,
                estimate.pass2_reasoning,
                estimate.thesis,
                category,
                edge,
                threshold,
            ),
        )
        return cursor.lastrowid


def update_prediction_outcome(market_id: str, outcome: float) -> int:
    """Update predictions for a resolved market. Returns count updated."""
    now = datetime.utcnow()
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE predictions SET
            outcome = ?,
            prediction_error = agent_estimate - ?,
            resolved_at = ?
            WHERE market_id = ? AND outcome IS NULL""",
            (outcome, outcome, now.isoformat(), market_id),
        )
        count = cursor.rowcount
    if count:
        logger.info("Updated %d predictions for market %s (outcome=%.1f)", count, market_id, outcome)
    return count


def compute_calibration(category: str | None = None) -> CalibrationReport:
    """Compute calibration statistics, optionally filtered by category."""
    with get_db() as conn:
        where = "WHERE outcome IS NOT NULL"
        params: list = []
        if category:
            where += " AND lower(category) = lower(?)"
            params.append(category)

        rows = conn.execute(
            f"SELECT agent_estimate, outcome FROM predictions {where}", params
        ).fetchall()

        total_count = conn.execute(
            f"SELECT COUNT(*) as c FROM predictions {'WHERE lower(category) = lower(?)' if category else ''}",
            [category] if category else [],
        ).fetchone()["c"]

    resolved = len(rows)

    if resolved < 2:
        return CalibrationReport(
            total_predictions=total_count,
            resolved_predictions=resolved,
            category=category,
            summary="Insufficient resolved predictions for calibration.",
        )

    # Compute Brier score
    brier = sum((r["agent_estimate"] - r["outcome"]) ** 2 for r in rows) / resolved

    # Compute buckets
    buckets = []
    for low, high in BUCKETS:
        bucket_rows = [
            r for r in rows if low <= r["agent_estimate"] < high or (high == 1.0 and r["agent_estimate"] == 1.0)
        ]
        if not bucket_rows:
            continue
        avg_pred = sum(r["agent_estimate"] for r in bucket_rows) / len(bucket_rows)
        actual_rate = sum(r["outcome"] for r in bucket_rows) / len(bucket_rows)
        buckets.append(
            CalibrationBucket(
                bucket_low=low,
                bucket_high=high,
                count=len(bucket_rows),
                avg_predicted=round(avg_pred, 3),
                actual_rate=round(actual_rate, 3),
                calibration_error=round(avg_pred - actual_rate, 3),
            )
        )

    return CalibrationReport(
        total_predictions=total_count,
        resolved_predictions=resolved,
        brier_score=round(brier, 4),
        buckets=buckets,
        category=category,
    )


def export_calibration_for_llm(min_resolved: int = 20) -> str:
    """Export calibration data as text for inclusion in LLM prompts."""
    report = compute_calibration()

    if report.resolved_predictions < min_resolved:
        return (
            f"Insufficient calibration data: only {report.resolved_predictions} "
            f"resolved predictions (need {min_resolved}). No calibration adjustment possible."
        )

    lines = [
        f"## Calibration Data ({report.resolved_predictions} resolved predictions)",
        f"Overall Brier Score: {report.brier_score:.4f} (lower is better, 0.25 = coin flip)",
        "",
        "Calibration by probability bucket:",
        "| Predicted Range | Count | Avg Predicted | Actual Rate | Error |",
        "|---|---|---|---|---|",
    ]
    for b in report.buckets:
        lines.append(
            f"| {b.bucket_low:.1f}-{b.bucket_high:.1f} | {b.count} | "
            f"{b.avg_predicted:.3f} | {b.actual_rate:.3f} | {b.calibration_error:+.3f} |"
        )

    # Detect biases
    lines.append("")
    lines.append("Detected biases:")
    overconfident = [b for b in report.buckets if b.calibration_error > 0.05 and b.count >= 3]
    underconfident = [b for b in report.buckets if b.calibration_error < -0.05 and b.count >= 3]

    if overconfident:
        for b in overconfident:
            lines.append(
                f"- OVERCONFIDENT in {b.bucket_low:.1f}-{b.bucket_high:.1f} range: "
                f"predicted {b.avg_predicted:.1%} but actual was {b.actual_rate:.1%}"
            )
    if underconfident:
        for b in underconfident:
            lines.append(
                f"- UNDERCONFIDENT in {b.bucket_low:.1f}-{b.bucket_high:.1f} range: "
                f"predicted {b.avg_predicted:.1%} but actual was {b.actual_rate:.1%}"
            )
    if not overconfident and not underconfident:
        lines.append("- No significant biases detected")

    # Category breakdown
    categories = _get_categories_with_data()
    if categories:
        lines.append("")
        lines.append("Category-level calibration:")
        for cat in categories:
            cat_report = compute_calibration(category=cat)
            if cat_report.brier_score is not None:
                lines.append(
                    f"- {cat}: Brier={cat_report.brier_score:.4f} "
                    f"({cat_report.resolved_predictions} predictions)"
                )

    return "\n".join(lines)


def compute_brier_comparison(min_resolved: int = 20) -> dict | None:
    """Compare agent Brier score against market-price-as-forecast baseline.

    Returns dict with agent_brier, market_brier, difference, and count.
    Returns None if fewer than min_resolved predictions have outcomes.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT agent_estimate, market_price, outcome FROM predictions WHERE outcome IS NOT NULL"
        ).fetchall()

    if len(rows) < min_resolved:
        return None

    n = len(rows)
    agent_brier = sum((r["agent_estimate"] - r["outcome"]) ** 2 for r in rows) / n
    market_brier = sum((r["market_price"] - r["outcome"]) ** 2 for r in rows) / n

    return {
        "agent_brier": round(agent_brier, 4),
        "market_brier": round(market_brier, 4),
        "difference": round(agent_brier - market_brier, 4),
        "resolved_count": n,
    }


def _get_categories_with_data() -> list[str]:
    """Get categories that have resolved predictions."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM predictions WHERE outcome IS NOT NULL AND category IS NOT NULL"
        ).fetchall()
        return [r["category"] for r in rows]
