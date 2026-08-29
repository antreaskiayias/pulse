import json
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.clickhouse_client import get_client

app = FastAPI(title="PULSE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production; fine for a local dashboard
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_INTERVALS = {
    "1m": "toStartOfMinute",
    "5m": "toStartOfFiveMinutes",
    "15m": "toStartOfFifteenMinutes",
    "1h": "toStartOfHour",
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/symbols")
def list_symbols():
    client = get_client()
    result = client.query(
        "SELECT DISTINCT symbol FROM trades ORDER BY symbol"
    )
    return {"symbols": [row[0] for row in result.result_rows]}


@app.get("/ohlc")
def ohlc(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("1m", description="1m, 5m, 15m, or 1h"),
    limit: int = Query(100, le=1000),
):
    if interval not in VALID_INTERVALS:
        raise HTTPException(400, f"interval must be one of {list(VALID_INTERVALS)}")

    bucket_fn = VALID_INTERVALS[interval]
    client = get_client()

    query = f"""
        SELECT
            {bucket_fn}(timestamp) AS bucket,
            argMin(price, timestamp) AS open,
            max(price) AS high,
            min(price) AS low,
            argMax(price, timestamp) AS close,
            sum(quantity) AS volume,
            count() AS trade_count
        FROM trades
        WHERE symbol = {{symbol:String}}
        GROUP BY bucket
        ORDER BY bucket DESC
        LIMIT {{limit:UInt32}}
    """
    result = client.query(
        query, parameters={"symbol": symbol.upper(), "limit": limit}
    )

    candles = [
        {
            "bucket": row[0].isoformat(),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "trade_count": row[6],
        }
        for row in result.result_rows
    ]
    return {"symbol": symbol.upper(), "interval": interval, "candles": list(reversed(candles))}


@app.get("/top-symbols")
def top_symbols(
    window_minutes: int = Query(5, le=1440, description="lookback window in minutes"),
    limit: int = Query(10, le=50),
):
    client = get_client()
    query = """
        SELECT
            symbol,
            sum(quote_quantity) AS volume_quote,
            count() AS trade_count
        FROM trades
        WHERE timestamp >= now() - INTERVAL {window:UInt32} MINUTE
        GROUP BY symbol
        ORDER BY volume_quote DESC
        LIMIT {limit:UInt32}
    """
    result = client.query(
        query, parameters={"window": window_minutes, "limit": limit}
    )
    return {
        "window_minutes": window_minutes,
        "top_symbols": [
            {"symbol": row[0], "volume_quote": float(row[1]), "trade_count": row[2]}
            for row in result.result_rows
        ],
    }
