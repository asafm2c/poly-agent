"""Hypothesis tracker: lifecycle engine for alpha discovery.

Formalize findings as testable hypotheses, gather evidence via targeted
simulations, and translate confirmed hypotheses into pipeline actions.
"""

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

from polymarket_agent.backtest.database import get_backtest_db
from polymarket_agent.config import settings

logger = logging.getLogger(__name__)

# Confirmation / rejection thresholds
CONFIRM_MIN_TRIALS = 30
CONFIRM_BRIER_DIFF = -0.02  # Agent must be at least 0.02 better
CONFIRM_P_VALUE = 0.05
REJECT_MIN_TRIALS = 30
REJECT_BRIER_DIFF = 0.02  # Agent is 0.02 worse
REJECT_CONSECUTIVE_CONTRARY = 2  # 2 consecutive contradicting runs


# ---------------------------------------------------------------------------
# Hypothesis CRUD
# ---------------------------------------------------------------------------


def propose(
    name: str,
    description: str,
    category_filter: str | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
    model_filter: str | None = None,
    temporal_filter: dict | None = None,
    decay_half_life_days: int = 90,
    retest_threshold: float = 0.50,
    actions: list[dict] | None = None,
    db_path: Path | None = None,
) -> int:
    """Create a new hypothesis with status='proposed'. Returns hypothesis ID."""
    path = db_path or settings.backtest_db_path
    now = datetime.now(timezone.utc).isoformat()
    tf_json = json.dumps(temporal_filter) if temporal_filter else None

    with get_backtest_db(path) as conn:
        cursor = conn.execute(
            """INSERT INTO bt_hypotheses
            (name, description, status, confidence_score, category_filter,
             volume_min, volume_max, model_filter, temporal_filter,
             proposed_at, decay_half_life_days, retest_threshold, proposed_by)
            VALUES (?, ?, 'proposed', 0.0, ?, ?, ?, ?, ?, ?, ?, ?, 'user')""",
            (name, description, category_filter, volume_min, volume_max,
             model_filter, tf_json, now, decay_half_life_days, retest_threshold),
        )
        hyp_id = cursor.lastrowid

        if actions:
            for action in actions:
                conn.execute(
                    """INSERT INTO bt_hypothesis_actions
                    (hypothesis_id, action_type, config, base_strength, active, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)""",
                    (hyp_id, action["action_type"], action["config"],
                     action.get("base_strength", 1.0), now),
                )

    logger.info("Proposed hypothesis %d: %s", hyp_id, name)
    return hyp_id


def record_evidence(
    hypothesis_id: int,
    run_id: int,
    trial_count: int,
    agent_brier: float | None = None,
    market_brier: float | None = None,
    brier_diff: float | None = None,
    simulated_pnl: float | None = None,
    p_value: float | None = None,
    effect_size: float | None = None,
    supports_hypothesis: int | None = None,
    evaluation_notes: str | None = None,
    db_path: Path | None = None,
) -> int:
    """Insert evidence record. Returns evidence ID."""
    path = db_path or settings.backtest_db_path
    now = datetime.now(timezone.utc).isoformat()

    with get_backtest_db(path) as conn:
        cursor = conn.execute(
            """INSERT INTO bt_hypothesis_evidence
            (hypothesis_id, run_id, recorded_at, trial_count,
             agent_brier, market_brier, brier_diff, simulated_pnl,
             p_value, effect_size, supports_hypothesis, evaluation_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (hypothesis_id, run_id, now, trial_count,
             agent_brier, market_brier, brier_diff, simulated_pnl,
             p_value, effect_size, supports_hypothesis, evaluation_notes),
        )
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# Weighted Computation Helpers
# ---------------------------------------------------------------------------


def _compute_weighted_confidence(evidence_rows: list[dict]) -> float:
    """Compute confidence from recency-weighted evidence. Returns [0.0, 1.0]."""
    if not evidence_rows:
        return 0.0

    now = datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_signal = 0.0

    for ev in evidence_rows:
        recorded_str = ev["recorded_at"]
        try:
            recorded = datetime.fromisoformat(recorded_str)
            if recorded.tzinfo is None:
                recorded = recorded.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        age_days = (now - recorded).total_seconds() / 86400.0
        weight = 1.0 / (1.0 + age_days / 30.0)

        bd = ev.get("brier_diff")
        tc = ev.get("trial_count", 0)
        if bd is not None and tc >= 5:
            # Sigmoid-like: maps [-0.10, +0.10] to [1.0, 0.0]
            clamped = max(-0.10, min(0.10, bd))
            signal = 0.5 - (clamped / 0.20)

            # Scale by sample size (up to 2x at n=100)
            n_factor = min(2.0, 1.0 + tc / 100.0)
            weight *= n_factor

            weighted_signal += signal * weight
            total_weight += weight

    if total_weight == 0:
        return 0.0

    return max(0.0, min(1.0, weighted_signal / total_weight))


def _compute_weighted_brier_diff(evidence_rows: list[dict]) -> tuple[float, int]:
    """Compute recency-weighted average Brier diff and effective trial count."""
    now = datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_diff = 0.0
    effective_n = 0.0

    for ev in evidence_rows:
        bd = ev.get("brier_diff")
        if bd is None:
            continue

        recorded_str = ev["recorded_at"]
        try:
            recorded = datetime.fromisoformat(recorded_str)
            if recorded.tzinfo is None:
                recorded = recorded.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        age_days = (now - recorded).total_seconds() / 86400.0
        weight = 1.0 / (1.0 + age_days / 30.0)
        tc = ev.get("trial_count", 0)

        weighted_diff += bd * weight * tc
        total_weight += weight * tc
        effective_n += tc * weight

    if total_weight == 0:
        return 0.0, 0

    return weighted_diff / total_weight, int(effective_n)


# ---------------------------------------------------------------------------
# Lifecycle Engine
# ---------------------------------------------------------------------------


def evaluate(hypothesis_id: int, db_path: Path | None = None) -> dict:
    """Evaluate all evidence and transition status. Returns summary dict."""
    path = db_path or settings.backtest_db_path
    now = datetime.now(timezone.utc).isoformat()

    with get_backtest_db(path) as conn:
        hyp = conn.execute(
            "SELECT * FROM bt_hypotheses WHERE id = ?", (hypothesis_id,)
        ).fetchone()
        if not hyp:
            return {"error": f"Hypothesis {hypothesis_id} not found"}

        evidence = conn.execute(
            """SELECT * FROM bt_hypothesis_evidence
            WHERE hypothesis_id = ? ORDER BY recorded_at""",
            (hypothesis_id,),
        ).fetchall()

        if not evidence:
            return {"status": hyp["status"], "confidence_score": 0.0,
                    "evidence_count": 0, "recommendation": "need_evidence"}

        evidence_dicts = [dict(e) for e in evidence]
        confidence = _compute_weighted_confidence(evidence_dicts)
        weighted_bd, effective_n = _compute_weighted_brier_diff(evidence_dicts)

        old_status = hyp["status"]
        new_status = old_status
        recommendation = "inconclusive"

        # Demotion check (for confirmed hypotheses)
        if old_status == "confirmed":
            recent = evidence_dicts[-REJECT_CONSECUTIVE_CONTRARY:]
            if len(recent) >= REJECT_CONSECUTIVE_CONTRARY:
                if all(e.get("supports_hypothesis") == 0 for e in recent):
                    new_status = "invalidated"
                    recommendation = "demoted"
                    conn.execute(
                        """UPDATE bt_hypotheses
                        SET status = 'invalidated', invalidated_at = ?,
                            confidence_score = ?, last_evaluated_at = ?
                        WHERE id = ?""",
                        (now, confidence, now, hypothesis_id),
                    )
                    # Deactivate actions
                    conn.execute(
                        """UPDATE bt_hypothesis_actions
                        SET active = 0, deactivated_at = ?
                        WHERE hypothesis_id = ? AND active = 1""",
                        (now, hypothesis_id),
                    )
                    return {
                        "status": new_status, "previous_status": old_status,
                        "confidence_score": confidence, "evidence_count": len(evidence),
                        "weighted_brier_diff": weighted_bd,
                        "effective_trials": effective_n,
                        "recommendation": recommendation,
                    }

        # Confirmation check
        latest_p = evidence_dicts[-1].get("p_value")
        if (effective_n >= CONFIRM_MIN_TRIALS
                and weighted_bd <= CONFIRM_BRIER_DIFF
                and (latest_p is not None and latest_p <= CONFIRM_P_VALUE)):
            new_status = "confirmed"
            recommendation = "confirmed"
            conn.execute(
                """UPDATE bt_hypotheses
                SET status = 'confirmed', confirmed_at = ?,
                    confidence_score = ?, last_evaluated_at = ?
                WHERE id = ?""",
                (now, confidence, now, hypothesis_id),
            )
            # Activate actions
            conn.execute(
                """UPDATE bt_hypothesis_actions
                SET active = 1, activated_at = ?
                WHERE hypothesis_id = ? AND active = 0""",
                (now, hypothesis_id),
            )

        # Rejection check
        elif (effective_n >= REJECT_MIN_TRIALS
              and weighted_bd >= REJECT_BRIER_DIFF):
            new_status = "rejected"
            recommendation = "rejected"
            conn.execute(
                """UPDATE bt_hypotheses
                SET status = 'rejected', confidence_score = ?, last_evaluated_at = ?
                WHERE id = ?""",
                (confidence, now, hypothesis_id),
            )

        # Inconclusive — update confidence
        else:
            conn.execute(
                """UPDATE bt_hypotheses
                SET confidence_score = ?, last_evaluated_at = ?
                WHERE id = ?""",
                (confidence, now, hypothesis_id),
            )

    return {
        "status": new_status,
        "previous_status": old_status,
        "confidence_score": confidence,
        "evidence_count": len(evidence),
        "weighted_brier_diff": weighted_bd,
        "effective_trials": effective_n,
        "recommendation": recommendation,
    }


def test(
    hypothesis_id: int,
    count: int = 50,
    horizon: int | None = None,
    db_path: Path | None = None,
) -> dict:
    """Run a simulation matching the hypothesis filters."""
    from polymarket_agent.backtest.simulator import select_markets, run_simulation

    path = db_path or settings.backtest_db_path
    now = datetime.now(timezone.utc).isoformat()

    with get_backtest_db(path) as conn:
        hyp = conn.execute(
            "SELECT * FROM bt_hypotheses WHERE id = ?", (hypothesis_id,)
        ).fetchone()
        if not hyp:
            raise ValueError(f"Hypothesis {hypothesis_id} not found")

        if hyp["status"] not in ("proposed", "testing", "confirmed", "invalidated"):
            raise ValueError(f"Cannot test hypothesis with status '{hyp['status']}'")

        # Transition proposed -> testing
        if hyp["status"] == "proposed":
            conn.execute(
                """UPDATE bt_hypotheses
                SET status = 'testing', first_tested_at = ?
                WHERE id = ?""",
                (now, hypothesis_id),
            )

    # Extract filters
    cat_filter = hyp["category_filter"]
    category = None if cat_filter is None else (None if cat_filter == "*" else cat_filter)
    vol_min = hyp["volume_min"]
    vol_max = hyp["volume_max"]

    tf = None
    if hyp["temporal_filter"]:
        try:
            tf = json.loads(hyp["temporal_filter"])
        except (json.JSONDecodeError, TypeError):
            pass

    h = horizon or (tf.get("horizon_days") if tf else None) or 7
    regime = tf.get("regime") if tf else None

    # Select markets
    markets = select_markets(
        count=count, category=category, volume_min=vol_min,
        volume_max=vol_max, regime=regime, horizon=h, db_path=path,
    )

    if not markets:
        return {"error": "No markets match hypothesis filters", "market_count": 0}

    # Run simulation
    result = run_simulation(
        markets=markets, horizon=h, db_path=path,
        hypothesis_id=hypothesis_id,
    )

    return result


def retest(hypothesis_id: int, count: int = 50, db_path: Path | None = None) -> dict:
    """Run fresh simulation and re-evaluate."""
    test_result = test(hypothesis_id, count=count, db_path=db_path)
    eval_result = evaluate(hypothesis_id, db_path=db_path)
    return {"test": test_result, "evaluation": eval_result}


def decay_check(db_path: Path | None = None) -> list[dict]:
    """Scan confirmed hypotheses for confidence decay. Returns flagged list."""
    path = db_path or settings.backtest_db_path
    now = datetime.now(timezone.utc)
    results = []

    with get_backtest_db(path) as conn:
        hypotheses = conn.execute(
            "SELECT * FROM bt_hypotheses WHERE status = 'confirmed'"
        ).fetchall()

        for hyp in hypotheses:
            # Find latest evidence
            latest = conn.execute(
                """SELECT recorded_at FROM bt_hypothesis_evidence
                WHERE hypothesis_id = ? ORDER BY recorded_at DESC LIMIT 1""",
                (hyp["id"],),
            ).fetchone()

            if not latest:
                continue

            try:
                last_evidence = datetime.fromisoformat(latest["recorded_at"])
                if last_evidence.tzinfo is None:
                    last_evidence = last_evidence.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            days_elapsed = (now - last_evidence).total_seconds() / 86400.0
            half_life = hyp["decay_half_life_days"] or 90
            base_confidence = hyp["confidence_score"] or 0.0

            # Exponential decay
            decayed = base_confidence * (0.5 ** (days_elapsed / half_life))

            # Update confidence
            conn.execute(
                "UPDATE bt_hypotheses SET confidence_score = ? WHERE id = ?",
                (decayed, hyp["id"]),
            )

            recommendation = "ok"
            retest_threshold = hyp["retest_threshold"] or 0.50

            if decayed < 0.25:
                # Critical — invalidate
                recommendation = "invalidate"
                now_str = now.isoformat()
                conn.execute(
                    """UPDATE bt_hypotheses
                    SET status = 'invalidated', invalidated_at = ?
                    WHERE id = ?""",
                    (now_str, hyp["id"]),
                )
                conn.execute(
                    """UPDATE bt_hypothesis_actions
                    SET active = 0, deactivated_at = ?
                    WHERE hypothesis_id = ? AND active = 1""",
                    (now_str, hyp["id"]),
                )
            elif decayed < retest_threshold:
                recommendation = "retest"

            results.append({
                "hypothesis_id": hyp["id"],
                "name": hyp["name"],
                "original_confidence": base_confidence,
                "decayed_confidence": decayed,
                "days_since_evidence": int(days_elapsed),
                "half_life": half_life,
                "retest_threshold": retest_threshold,
                "recommendation": recommendation,
            })

    return results


# ---------------------------------------------------------------------------
# Action Queries
# ---------------------------------------------------------------------------


def load_active_hypothesis_actions(db_path: Path | None = None) -> list[dict]:
    """Load all active hypothesis actions with effective strength."""
    path = db_path or settings.backtest_db_path
    try:
        with get_backtest_db(path) as conn:
            rows = conn.execute(
                """SELECT a.id, a.hypothesis_id, a.action_type, a.config, a.base_strength,
                          h.name as hypothesis_name, h.confidence_score
                FROM bt_hypothesis_actions a
                JOIN bt_hypotheses h ON a.hypothesis_id = h.id
                WHERE a.active = 1 AND h.status = 'confirmed'
                ORDER BY h.confidence_score DESC"""
            ).fetchall()

        results = []
        for row in rows:
            cfg = {}
            try:
                cfg = json.loads(row["config"])
            except (json.JSONDecodeError, TypeError):
                pass

            results.append({
                "hypothesis_id": row["hypothesis_id"],
                "hypothesis_name": row["hypothesis_name"],
                "action_type": row["action_type"],
                "config": cfg,
                "base_strength": row["base_strength"],
                "effective_strength": row["base_strength"] * (row["confidence_score"] or 0),
                "hypothesis_confidence": row["confidence_score"],
            })

        return results
    except Exception:
        return []


def load_confirmed_hypotheses(db_path: Path | None = None) -> list[dict]:
    """Load all confirmed hypotheses as dicts."""
    path = db_path or settings.backtest_db_path
    try:
        with get_backtest_db(path) as conn:
            rows = conn.execute(
                """SELECT id, name, description, confidence_score,
                          category_filter, volume_min, volume_max
                FROM bt_hypotheses WHERE status = 'confirmed'
                ORDER BY confidence_score DESC"""
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_confirmed_hypotheses_summary(db_path: Path | None = None) -> str | None:
    """Generate markdown summary of confirmed hypotheses for LLM prompts."""
    hypotheses = load_confirmed_hypotheses(db_path)
    if not hypotheses:
        return None

    lines = [
        "## Validated Findings from Backtesting",
        "The following hypotheses have been confirmed through simulation:",
    ]
    for h in hypotheses:
        lines.append(
            f"- **{h['name']}** (confidence: {h['confidence_score']:.0%}): "
            f"{h['description']}"
        )
    lines.append("")
    lines.append(
        "Consider these findings when calibrating your estimate. They represent "
        "statistically validated patterns in your own prediction performance."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Seed Hypotheses
# ---------------------------------------------------------------------------


SEED_HYPOTHESES = [
    {
        "name": "probable-no-alpha",
        "description": "Agent outperforms market on markets where the market price "
                       "implies probable NO (price < 0.30), by tempering overconfidence "
                       "on unlikely YES outcomes.",
        "category_filter": None,
        "volume_min": 100_000,
        "volume_max": None,
        "actions": [
            {
                "action_type": "edge_override",
                "config": json.dumps({"base_threshold": 0.08, "applies_to": "probable_no"}),
                "base_strength": 1.0,
            }
        ],
    },
    {
        "name": "mid-volume-sweet-spot",
        "description": "Agent has alpha in the $100K-$1M volume tier where markets "
                       "are liquid enough to be real but thin enough for mispricing.",
        "category_filter": None,
        "volume_min": 100_000,
        "volume_max": 1_000_000,
        "actions": [
            {
                "action_type": "edge_override",
                "config": json.dumps({"base_threshold": 0.08, "applies_to": "100K-1M"}),
                "base_strength": 1.0,
            },
            {
                "action_type": "weight_adjustment",
                "config": json.dumps({"kelly_multiplier": 1.2, "reason": "Sweet spot tier"}),
                "base_strength": 0.8,
            },
        ],
    },
    {
        "name": "high-volume-efficient",
        "description": "Agent is market-neutral or slightly worse on >$1M volume "
                       "markets, which are too efficient to beat.",
        "category_filter": None,
        "volume_min": 1_000_000,
        "volume_max": None,
        "actions": [
            {
                "action_type": "edge_override",
                "config": json.dumps({"base_threshold": 0.12, "applies_to": ">1M"}),
                "base_strength": 1.0,
            },
            {
                "action_type": "weight_adjustment",
                "config": json.dumps({"kelly_multiplier": 0.8, "reason": "Efficient markets"}),
                "base_strength": 1.0,
            },
        ],
    },
    {
        "name": "sports-no-alpha",
        "description": "Agent has no demonstrated alpha on sports markets (named "
                       "categories like Match Winner, O/U, Spread).",
        "category_filter": "*",
        "volume_min": 100_000,
        "volume_max": None,
        "actions": [
            {
                "action_type": "category_avoid",
                "config": json.dumps({"category": "Match Winner", "reason": "No demonstrated alpha"}),
                "base_strength": 1.0,
            },
        ],
    },
]


def seed_hypotheses(db_path: Path | None = None) -> int:
    """Seed initial hypotheses if the table is empty. Returns count seeded."""
    path = db_path or settings.backtest_db_path
    try:
        with get_backtest_db(path) as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM bt_hypotheses").fetchone()["c"]
            if count > 0:
                return 0

            seeded = 0
            now = datetime.now(timezone.utc).isoformat()
            for hyp_data in SEED_HYPOTHESES:
                actions = hyp_data.get("actions", [])
                tf = hyp_data.get("temporal_filter")
                tf_json = json.dumps(tf) if tf else None

                cursor = conn.execute(
                    """INSERT INTO bt_hypotheses
                    (name, description, status, category_filter, volume_min, volume_max,
                     temporal_filter, proposed_at, proposed_by)
                    VALUES (?, ?, 'proposed', ?, ?, ?, ?, ?, 'seed')""",
                    (hyp_data["name"], hyp_data["description"],
                     hyp_data.get("category_filter"),
                     hyp_data.get("volume_min"), hyp_data.get("volume_max"),
                     tf_json, now),
                )
                hyp_id = cursor.lastrowid

                for action in actions:
                    conn.execute(
                        """INSERT INTO bt_hypothesis_actions
                        (hypothesis_id, action_type, config, base_strength, active, created_at)
                        VALUES (?, ?, ?, ?, 0, ?)""",
                        (hyp_id, action["action_type"], action["config"],
                         action.get("base_strength", 1.0), now),
                    )
                seeded += 1

        logger.info("Seeded %d initial hypotheses", seeded)
        return seeded
    except Exception as e:
        logger.debug("Hypothesis seeding skipped: %s", e)
        return 0
