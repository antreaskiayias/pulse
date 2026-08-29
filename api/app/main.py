import json
import os
from collections import deque, defaultdict
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from app.clickhouse_client import get_client
from app.redis_client import get_redis
from app.tda import build_point_cloud, build_vietoris_rips_edges, betti_numbers

price_buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
qty_buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

EPSILON = 0.5 

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
async def ohlc(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("1m", description="1m, 5m, 15m, or 1h"),
    limit: int = Query(100, le=1000),
):
    if interval not in VALID_INTERVALS:
        raise HTTPException(400, f"interval must be one of {list(VALID_INTERVALS)}")

    symbol = symbol.upper()
    cache_key = f"ohlc:{symbol}:{interval}:{limit}"
    r = get_redis()

    cached = await r.get(cache_key)
    if cached:
        return json.loads(cached)

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
        query, parameters={"symbol": symbol, "limit": limit}
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
    response = {"symbol": symbol, "interval": interval, "candles": list(reversed(candles))}

    await r.set(cache_key, json.dumps(response), ex=5)  # 5s TTL
    return response
@app.get("/top-symbols")
async def top_symbols(
    window_minutes: int = Query(5, le=1440, description="lookback window in minutes"),
    limit: int = Query(10, le=50),
):
    cache_key = f"top-symbols:{window_minutes}:{limit}"
    r = get_redis()

    cached = await r.get(cache_key)
    if cached:
        return json.loads(cached)

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
    response = {
        "window_minutes": window_minutes,
        "top_symbols": [
            {"symbol": row[0], "volume_quote": float(row[1]), "trade_count": row[2]}
            for row in result.result_rows
        ],
    }

    await r.set(cache_key, json.dumps(response), ex=15)  # 15s TTL
    return response
@app.get("/correlation")
async def correlation(
    interval: str = Query("1m"),
    lookback: int = Query(60, le=1440, description="minutes of history"),
):
    cache_key = f"correlation:{interval}:{lookback}"
    r = get_redis()
    cached = await r.get(cache_key)
    if cached:
        return json.loads(cached)

    if interval not in VALID_INTERVALS:
        raise HTTPException(400, f"interval must be one of {list(VALID_INTERVALS)}")
    bucket_fn = VALID_INTERVALS[interval]
    client = get_client()

    query = f"""
        SELECT symbol, {bucket_fn}(timestamp) AS bucket, argMax(price, timestamp) AS close
        FROM trades
        WHERE timestamp >= now() - INTERVAL {{lookback:UInt32}} MINUTE
        GROUP BY symbol, bucket
        ORDER BY symbol, bucket
    """
    result = client.query(query, parameters={"lookback": lookback})

    from collections import defaultdict
    series: dict = defaultdict(dict)
    for symbol, bucket, close in result.result_rows:
        series[symbol][bucket] = float(close)

    symbols = sorted(series.keys())
    common_buckets = sorted(set.intersection(*[set(series[s].keys()) for s in symbols])) if symbols else []

    import statistics
    def pearson(a: list, b: list) -> float:
        if len(a) < 2:
            return 0.0
        try:
            return statistics.correlation(a, b)
        except statistics.StatisticsError:
            return 0.0

    matrix = []
    for s1 in symbols:
        row = []
        vals1 = [series[s1][b] for b in common_buckets]
        for s2 in symbols:
            vals2 = [series[s2][b] for b in common_buckets]
            row.append(round(pearson(vals1, vals2), 3))
        matrix.append(row)

    response = {"symbols": symbols, "matrix": matrix}
    await r.set(cache_key, json.dumps(response), ex=30)
    return response

async def redis_listener():
    pubsub = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379")).pubsub()
    await pubsub.psubscribe("ticks:*")
    async for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        symbol = message["channel"].decode().split(":", 1)[1]
        tick = json.loads(message["data"])
        price_buffers[symbol].append(tick["price"])
        qty_buffers[symbol].append(tick["quantity"])

        if symbol in active_connections and len(price_buffers[symbol]) >= 15:
            points = build_point_cloud(list(price_buffers[symbol]), list(qty_buffers[symbol]))
            edges = build_vietoris_rips_edges(points, EPSILON)
            b0, b1 = betti_numbers(len(points), edges)

            payload = json.dumps({
                "symbol": symbol,
                "points": points.tolist(),
                "edges": edges,
                "betti_0": b0,
                "betti_1": b1,
            })
            for ws in active_connections[symbol]:
                await ws.send_text(payload)
