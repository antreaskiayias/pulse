import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import websockets
import clickhouse_connect
from dotenv import load_dotenv

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
redis_client = redis.from_url(REDIS_URL)

import signal

shutdown_event = asyncio.Event()

def handle_shutdown(*_):
    log.info("shutdown signal received, will flush buffer before exiting")
    shutdown_event.set()


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pulse-ingestion")

SYMBOLS = ["btcusdt", "ethusdt", "solusdt"]
STREAM_URL = (
    "wss://stream.binance.com:9443/stream?streams="
    + "/".join(f"{s}@trade" for s in SYMBOLS)
)

BATCH_SIZE = 200
FLUSH_INTERVAL_SEC = 2.0

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "pulse")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "pulse_dev_pw")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "pulse")

async def publish_tick(raw: dict):
    data = raw["data"]
    try:
        await redis_client.publish(
            f"ticks:{data['s']}",
            json.dumps({
                "price": float(data["p"]),
                "quantity": float(data["q"]),
                "ts": data["T"],
            }),
        )
    except Exception as e:
        log.warning(f"tick publish failed (non-fatal): {e}")

def get_client():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DB,
    )

def normalize_trade(raw: dict) -> tuple:
    """Binance trade payload -> row tuple matching pulse.trades column order."""
    data = raw["data"]
    price = float(data["p"])
    quantity = float(data["q"])
    return (
        data["s"],                                              # symbol
        int(data["t"]),                                         # trade_id
        price,                                                  # price
        quantity,                                                # quantity
        price * quantity,                                        # quote_quantity
        1 if data["m"] else 0,                                   # is_buyer_maker
        datetime.fromtimestamp(data["T"] / 1000, tz=timezone.utc),  # timestamp
    )


async def flush(client, buffer: list):
    if not buffer:
        return
    try:
        client.insert(
            "trades",
            buffer,
            column_names=[
                "symbol", "trade_id", "price", "quantity",
                "quote_quantity", "is_buyer_maker", "timestamp",
            ],
        )
        log.info(f"flushed {len(buffer)} trades")
    except Exception as e:
        log.error(f"flush failed, dropping batch of {len(buffer)}: {e}")
        # NOTE: a real production system would retry or write to a dead-letter
        # queue here instead of dropping — documented as a known limitation.

async def consume():
    client = get_client()
    buffer: list = []
    last_flush = asyncio.get_event_loop().time()
    backoff = 1

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(STREAM_URL, ping_interval=20) as ws:
                log.info("connected to Binance stream")
                backoff = 1
                async for message in ws:
                    if shutdown_event.is_set():
                        break
                    raw = json.loads(message)
                    buffer.append(normalize_trade(raw))
                    await publish_tick(raw)

                    now = asyncio.get_event_loop().time()
                    if len(buffer) >= BATCH_SIZE or (now - last_flush) >= FLUSH_INTERVAL_SEC:
                        await flush(client, buffer)
                        buffer = []
                        last_flush = now

        except (websockets.ConnectionClosed, OSError) as e:
            log.warning(f"connection lost ({e}), reconnecting in {backoff}s")
            await flush(client, buffer)
            buffer = []
            if not shutdown_event.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # final flush on graceful shutdown
    await flush(client, buffer)
    log.info("flushed remaining buffer, exiting")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    asyncio.run(consume())
