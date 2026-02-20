"""Hypotheses API: hypothesis tracker data from backtest.db."""

import json

from fastapi import APIRouter, Request

router = APIRouter()


def _get_bt_db(request: Request):
    return request.app.state.backtest_db


@router.get("/list")
async def hypotheses_list(request: Request, status: str | None = None):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "tables_exist": False, "hypotheses": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_hypotheses"):
            return {"available": True, "tables_exist": False, "hypotheses": []}

        if status:
            rows = await conn.execute_fetchall(
                """SELECT h.*,
                          (SELECT COUNT(*) FROM bt_hypothesis_evidence e
                           WHERE e.hypothesis_id = h.id) as evidence_count
                FROM bt_hypotheses h
                WHERE h.status = ?
                ORDER BY h.id""",
                (status,),
            )
        else:
            rows = await conn.execute_fetchall(
                """SELECT h.*,
                          (SELECT COUNT(*) FROM bt_hypothesis_evidence e
                           WHERE e.hypothesis_id = h.id) as evidence_count
                FROM bt_hypotheses h
                ORDER BY h.id"""
            )

    hypotheses = []
    for r in rows:
        hypotheses.append({
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "status": r["status"],
            "confidence_score": round(r["confidence_score"], 4) if r["confidence_score"] else 0.0,
            "category_filter": r["category_filter"],
            "volume_min": r["volume_min"],
            "volume_max": r["volume_max"],
            "model_filter": r["model_filter"],
            "evidence_count": r["evidence_count"],
            "proposed_at": r["proposed_at"],
            "confirmed_at": r["confirmed_at"],
            "last_evaluated_at": r["last_evaluated_at"],
            "decay_half_life_days": r["decay_half_life_days"],
            "retest_threshold": r["retest_threshold"],
        })

    return {"available": True, "tables_exist": True, "hypotheses": hypotheses}


@router.get("/{hypothesis_id}/evidence")
async def hypothesis_evidence(request: Request, hypothesis_id: int):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "evidence": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_hypothesis_evidence"):
            return {"available": False, "evidence": []}

        rows = await conn.execute_fetchall(
            """SELECT e.*, r.started_at as run_started, r.config as run_config
            FROM bt_hypothesis_evidence e
            LEFT JOIN bt_simulation_runs r ON e.run_id = r.id
            WHERE e.hypothesis_id = ?
            ORDER BY e.recorded_at DESC""",
            (hypothesis_id,),
        )

    evidence = []
    for r in rows:
        model = None
        if r["run_config"]:
            try:
                cfg = json.loads(r["run_config"])
                model = cfg.get("model")
            except (json.JSONDecodeError, TypeError):
                pass

        evidence.append({
            "id": r["id"],
            "run_id": r["run_id"],
            "recorded_at": r["recorded_at"],
            "trial_count": r["trial_count"],
            "agent_brier": round(r["agent_brier"], 4) if r["agent_brier"] is not None else None,
            "market_brier": round(r["market_brier"], 4) if r["market_brier"] is not None else None,
            "brier_diff": round(r["brier_diff"], 4) if r["brier_diff"] is not None else None,
            "p_value": round(r["p_value"], 4) if r["p_value"] is not None else None,
            "supports_hypothesis": r["supports_hypothesis"],
            "model": model,
            "run_started": r["run_started"],
        })

    return {"available": True, "evidence": evidence}


@router.get("/{hypothesis_id}/actions")
async def hypothesis_actions(request: Request, hypothesis_id: int):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "actions": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_hypothesis_actions"):
            return {"available": False, "actions": []}

        rows = await conn.execute_fetchall(
            """SELECT * FROM bt_hypothesis_actions
            WHERE hypothesis_id = ?
            ORDER BY id""",
            (hypothesis_id,),
        )

    actions = []
    for r in rows:
        cfg = {}
        try:
            cfg = json.loads(r["config"])
        except (json.JSONDecodeError, TypeError):
            pass

        actions.append({
            "id": r["id"],
            "action_type": r["action_type"],
            "config": cfg,
            "base_strength": r["base_strength"],
            "active": bool(r["active"]),
            "created_at": r["created_at"],
            "activated_at": r["activated_at"],
            "deactivated_at": r["deactivated_at"],
        })

    return {"available": True, "actions": actions}
