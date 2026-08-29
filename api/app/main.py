import asyncio
import json
import os
from collections import deque, defaultdict
from contextlib import asynccontextmanager
from typing import Set

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.clickhouse_client import get_client
from app.redis_client import get_redis
from app.tda import build_point_cloud, build_vietoris_rips_edges, betti_numbers

price_buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
qty_buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

# Track active WebSocket clients per symbol
active_connections: dict[str, Set[WebSocket]] = defaultdict(set)

EPSILON = 0.5 

async def redis_listener():
    r_url = os.getenv("REDIS_URL", "redis://redis:6379")
    r = aioredis.from_url(r_url)
    pubsub = r.pubsub()
    await pubsub.psubscribe("ticks:*")
    
    async for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        
        channel_name = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]
        symbol = channel_name.split(":", 1)[1]
        
        data = message["data"].decode() if isinstance(message["data"], bytes) else message["data"]
        tick = json.loads(data)
        
        price_buffers[symbol].append(tick["price"])
        qty_buffers[symbol].append(tick["quantity"])

        # Broadcast if connections exist for this symbol
        if symbol in active_connections and active_connections[symbol] and len(price_buffers[symbol]) >= 15:
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
            
            disconnected = set()
            for ws in list(active_connections[symbol]):
                try:
                    await ws.send_text(payload)
                except Exception:
                    disconnected.add(ws)
            
            for ws in disconnected:
                active_connections[symbol].discard(ws)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(redis_listener())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="PULSE API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_INTERVALS = {
    "1m": "toStartOfMinute",
    "5m": "toStartOfFiveMinutes",
    "15m": "toStartOfFifteenMinutes",
    "1h": "toStartOfHour",
}

# --- WEBSOCKET HANDLERS ---
@app.websocket("/ws/tda/")
@app.websocket("/ws/tda/{symbol}")
async def websocket_tda(websocket: WebSocket, symbol: str = "BTCUSDT"):
    symbol = symbol.upper()
    await websocket.accept()
    active_connections[symbol].add(websocket)
    try:
        while True:
            # Keep connection alive without crashing if client sends pings/text
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_connections[symbol].discard(websocket)
        if not active_connections[symbol]:
            del active_connections[symbol]

# --- HTTP ENDPOINTS ---
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/symbols")
def list_symbols():
    client = get_client()
    result = client.query("SELECT DISTINCT symbol FROM trades ORDER BY symbol")
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
    result = client.query(query, parameters={"symbol": symbol, "limit": limit})
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

    await r.set(cache_key, json.dumps(response), ex=5)
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
    result = client.query(query, parameters={"window": window_minutes, "limit": limit})
    response = {
        "window_minutes": window_minutes,
        "top_symbols": [
            {"symbol": row[0], "volume_quote": float(row[1]), "trade_count": row[2]}
            for row in result.result_rows
        ],
    }

    await r.set(cache_key, json.dumps(response), ex=15)
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
