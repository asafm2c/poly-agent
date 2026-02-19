"""Operational metrics endpoints — LLM costs, API calls, storage, events."""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request

router = APIRouter()


async def _has_metrics(conn) -> bool:
    return await conn.table_exists("metric_events")


@router.get("/summary")
async def metrics_summary(request: Request, days: int = Query(1, ge=1, le=30)):
    db = request.app.state.db
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    async with db.connection() as conn:
        if not await _has_metrics(conn):
            return _empty_summary(days)

        # LLM aggregates
        llm = await conn.execute_fetchone(
            """SELECT COUNT(*) as calls,
                      COALESCE(SUM(json_extract(data, '$.input_tokens')), 0) as input_tokens,
                      COALESCE(SUM(json_extract(data, '$.output_tokens')), 0) as output_tokens,
                      COALESCE(SUM(json_extract(data, '$.cost')), 0) as cost
            FROM metric_events
            WHERE event_type = 'llm_call' AND timestamp >= ?""",
            (cutoff,),
        )

        # API call counts by service
        api_rows = await conn.execute_fetchall(
            """SELECT json_extract(data, '$.service') as service, COUNT(*) as calls
            FROM metric_events
            WHERE event_type = 'api_call' AND timestamp >= ?
            GROUP BY service""",
            (cutoff,),
        )

        # Error count
        errors = await conn.execute_fetchone(
            """SELECT COUNT(*) as c FROM metric_events
            WHERE event_type = 'api_error' AND timestamp >= ?""",
            (cutoff,),
        )

    api_by_service = {r["service"]: r["calls"] for r in api_rows}

    return {
        "period_days": days,
        "llm": {
            "calls": llm["calls"] if llm else 0,
            "input_tokens": llm["input_tokens"] if llm else 0,
            "output_tokens": llm["output_tokens"] if llm else 0,
            "cost": round(llm["cost"], 4) if llm else 0,
        },
        "api_calls": {
            "gamma": api_by_service.get("gamma", 0),
            "clob": api_by_service.get("clob", 0),
            "tavily": api_by_service.get("tavily", 0),
            "total": sum(api_by_service.values()),
        },
        "errors": errors["c"] if errors else 0,
    }


def _empty_summary(days):
    return {
        "period_days": days,
        "llm": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0},
        "api_calls": {"gamma": 0, "clob": 0, "tavily": 0, "total": 0},
        "errors": 0,
    }


@router.get("/timeseries")
async def metrics_timeseries(request: Request, days: int = Query(7, ge=1, le=30)):
    db = request.app.state.db
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    async with db.connection() as conn:
        if not await _has_metrics(conn):
            return {"days": []}

        rows = await conn.execute_fetchall(
            """SELECT
                DATE(timestamp) as date,
                SUM(CASE WHEN event_type = 'llm_call' THEN 1 ELSE 0 END) as llm_calls,
                COALESCE(SUM(CASE WHEN event_type = 'llm_call' THEN json_extract(data, '$.input_tokens') ELSE 0 END), 0) as llm_input_tokens,
                COALESCE(SUM(CASE WHEN event_type = 'llm_call' THEN json_extract(data, '$.output_tokens') ELSE 0 END), 0) as llm_output_tokens,
                COALESCE(SUM(CASE WHEN event_type = 'llm_call' THEN json_extract(data, '$.cost') ELSE 0 END), 0) as llm_cost,
                SUM(CASE WHEN event_type = 'api_call' AND json_extract(data, '$.service') = 'gamma' THEN 1 ELSE 0 END) as api_calls_gamma,
                SUM(CASE WHEN event_type = 'api_call' AND json_extract(data, '$.service') = 'clob' THEN 1 ELSE 0 END) as api_calls_clob,
                SUM(CASE WHEN event_type = 'api_call' AND json_extract(data, '$.service') = 'tavily' THEN 1 ELSE 0 END) as api_calls_tavily,
                SUM(CASE WHEN event_type = 'api_error' THEN 1 ELSE 0 END) as api_errors
            FROM metric_events
            WHERE timestamp >= ?
            GROUP BY DATE(timestamp)
            ORDER BY date ASC""",
            (cutoff,),
        )

    return {
        "days": [
            {
                "date": r["date"],
                "llm_calls": r["llm_calls"],
                "llm_input_tokens": r["llm_input_tokens"],
                "llm_output_tokens": r["llm_output_tokens"],
                "llm_cost": round(r["llm_cost"], 4),
                "api_calls_gamma": r["api_calls_gamma"],
                "api_calls_clob": r["api_calls_clob"],
                "api_calls_tavily": r["api_calls_tavily"],
                "api_errors": r["api_errors"],
            }
            for r in rows
        ]
    }


@router.get("/cost-breakdown")
async def cost_breakdown(request: Request, days: int = Query(7, ge=1, le=30)):
    db = request.app.state.db
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    async with db.connection() as conn:
        if not await _has_metrics(conn):
            return {"models": []}

        rows = await conn.execute_fetchall(
            """SELECT
                json_extract(data, '$.model') as model,
                COUNT(*) as calls,
                COALESCE(SUM(json_extract(data, '$.input_tokens')), 0) as input_tokens,
                COALESCE(SUM(json_extract(data, '$.output_tokens')), 0) as output_tokens,
                COALESCE(SUM(json_extract(data, '$.cost')), 0) as cost
            FROM metric_events
            WHERE event_type = 'llm_call' AND timestamp >= ?
            GROUP BY model
            ORDER BY cost DESC""",
            (cutoff,),
        )

    return {
        "period_days": days,
        "models": [
            {
                "model": r["model"],
                "calls": r["calls"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cost": round(r["cost"], 4),
            }
            for r in rows
        ],
    }


@router.get("/storage")
async def storage_metrics(request: Request):
    db = request.app.state.db

    async with db.connection() as conn:
        # DB size via PRAGMAs
        page_count = await conn.execute_fetchone("PRAGMA page_count")
        page_size = await conn.execute_fetchone("PRAGMA page_size")
        pc = page_count[0] if page_count else 0
        ps = page_size[0] if page_size else 4096
        db_size_bytes = pc * ps

        # Row counts for key tables
        tables = {}
        for table in ["markets", "predictions", "positions", "trades", "price_snapshots", "metric_events"]:
            if await conn.table_exists(table):
                row = await conn.execute_fetchone(f"SELECT COUNT(*) as c FROM {table}")
                tables[table] = row["c"] if row else 0
            else:
                tables[table] = 0

    return {
        "db_size_bytes": db_size_bytes,
        "db_size_mb": round(db_size_bytes / (1024 * 1024), 1),
        "tables": tables,
        "retention_days": 30,
    }


@router.get("/recent")
async def recent_events(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    event_type: str | None = None,
):
    db = request.app.state.db

    async with db.connection() as conn:
        if not await _has_metrics(conn):
            return {"events": []}

        if event_type:
            rows = await conn.execute_fetchall(
                """SELECT id, timestamp, event_type, data
                FROM metric_events
                WHERE event_type = ?
                ORDER BY id DESC LIMIT ?""",
                (event_type, limit),
            )
        else:
            rows = await conn.execute_fetchall(
                """SELECT id, timestamp, event_type, data
                FROM metric_events
                ORDER BY id DESC LIMIT ?""",
                (limit,),
            )

    return {
        "events": [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "event_type": r["event_type"],
                "data": json.loads(r["data"]),
            }
            for r in rows
        ]
    }
