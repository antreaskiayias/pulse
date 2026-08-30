# PULSE — Architecture

## Overview

PULSE ingests live Binance trade data, stores it in ClickHouse for analytical
querying, exposes aggregations through a cached FastAPI layer, and visualizes
it in a React dashboard. The extension adds a live topological summary of
recent trading activity via a Vietoris-Rips 1-skeleton and Betti numbers.

Pipeline: ingest → process → store → query → visualise

## Data source

Binance combined trade stream (`wss://stream.binance.com:9443/stream`) for
BTCUSDT, ETHUSDT, SOLUSDT. Chosen over the geospatial options because trade
data maps naturally onto ClickHouse's strengths (time-bucketed aggregation,
high-cardinality numeric rollups) and because I had prior domain experience
with market microstructure from a personal project (market-geometry).

## Ingestion

A long-running async worker (`ingestion/worker.py`) connects to Binance's
websocket, normalizes each trade, and batches inserts into ClickHouse.

- **Resilience**: automatic reconnect with exponential backoff (1s → 60s cap)
  on connection loss. Buffered trades are flushed before reconnecting so a
  drop doesn't silently discard in-flight data.
- **Batching**: inserts are batched (200 rows or 2s, whichever comes first)
  rather than per-trade, since ClickHouse is optimized for bulk inserts, not
  high-frequency single-row writes.
- **Known limitation**: no deduplication on `trade_id` at insert time. Binance
  trade IDs are unique per symbol, so a reconnect that re-delivers an
  in-flight trade could create a duplicate row. A production system would
  enforce this with a `ReplacingMergeTree` keyed on `(symbol, trade_id)` or an
  idempotency check before insert. Documented here rather than fixed, given
  time constraints.

## Storage — ClickHouse

Single `trades` table:

- **Engine**: `MergeTree` — trades are immutable append-only facts, no need
  for `ReplacingMergeTree` semantics beyond the dedup caveat above.
- **Ordering key**: `(symbol, timestamp)` — most queries filter by symbol
  first, so this lets ClickHouse skip irrelevant granules; timestamp second
  gives efficient range scans within a symbol.
- **Partitioning**: daily (`toDate(timestamp)`) — keeps parts a manageable
  size given trade volume, and makes retention (`DROP PARTITION`) cheap.
- **Types**: `LowCardinality(String)` for symbol (small fixed set, strong
  compression); `Decimal(18,8)` for price/quantity rather than `Float64` to
  avoid rounding error in financial data.
- **Retention**: 90-day TTL — arbitrary but deliberate; balances having
  enough history for correlation/heatmap queries against unbounded disk
  growth for a demo system.
- **Trade-off not taken**: no materialized view for OHLC pre-aggregation.
  Given more time, I'd add a `SummingMergeTree`-backed materialized view
  rolling trades into 1-minute buckets continuously, rather than computing
  OHLC via `argMin`/`argMax` on raw rows at query time — this becomes the
  first real bottleneck at scale (see "Scaling" below).

## API — FastAPI

Endpoints: `/symbols`, `/ohlc`, `/top-symbols`, `/correlation`,
`/ws/phase-space/{symbol}`.

- `/ohlc` buckets trades via ClickHouse's `toStartOfMinute`/`toStartOfHour`
  family of functions and derives OHLC using `argMin`/`argMax` (value of
  price at min/max timestamp in the bucket) — the idiomatic ClickHouse
  approach rather than a self-join.
- `/correlation` computes pairwise Pearson correlation of per-symbol close
  prices over a lookback window, entirely in Python after a single grouped
  ClickHouse query — chosen over a ClickHouse-native correlation function for
  clarity, given the small symbol count (3).
- Queries use ClickHouse parameter binding (`{param:Type}`), not string
  interpolation, to avoid injection from user-supplied query params.

### Caching

`/ohlc` and `/top-symbols` are cached in Redis, keyed by their exact query
parameters (e.g. `ohlc:BTCUSDT:1m:100`). Invalidation is TTL-based rather than
event-based:

- `/ohlc`: 5s TTL
- `/top-symbols`: 15s TTL
- `/correlation`: 30s TTL

**Rationale**: trades stream continuously, so there's no natural "this
changed, invalidate now" event to hook into without adding a write-through
cache-invalidation path from the ingestion worker. A short TTL trades a few
seconds of staleness for a large reduction in ClickHouse load under repeated
dashboard polling. Given more time, I'd consider having the ingestion worker
publish a "new data for symbol X" event and use that to invalidate
proactively instead of waiting out the TTL.

## Dashboard — React + TypeScript

Vite scaffold, `recharts` for charts, plain SVG for the topology view (needed
custom edge-drawing that a chart library doesn't provide out of the box).

- Live updates via polling (3-5s intervals) for price/top-symbols/correlation
  panels; the extension panel uses a WebSocket instead (see below).
- Controls: symbol selector, interval selector (1m/5m/15m/1h).

## Extension — Live topological summary of trade activity

Rather than a generic anomaly detector, the extension applies persistent
concepts from topological data analysis (TDA) to a live point cloud of
recent trades:

1. Each trade becomes a point: `(price_delta_from_window_mean, log(quantity))`.
2. A Vietoris-Rips 1-skeleton is built by connecting points within a fixed
   distance ε — this is the graph of "similar recent trades."
3. Betti numbers are computed from that graph: **β₀** (connected components,
   via union-find) and **β₁** (independent cycles, via `|E| - |V| + β₀`).
4. Ticks are pushed from the ingestion worker to Redis pub/sub as they
   arrive; the API subscribes and rebroadcasts the recomputed graph and
   Betti numbers over a WebSocket to connected dashboard clients.

This satisfies both "push-based delivery" and "advanced visualisation" as one
coherent feature rather than two shallow ones, and extends unfinished work
from a personal project (market-geometry) into a live-streaming context.

**Known limitations, stated deliberately:**
- Edge construction is O(n²) per update — fine for the ~100-point rolling
  window used here, but would need a spatial index (KD-tree) or an
  approximate method for larger windows.
- This is an exploratory visualization, not a rigorous persistent-homology
  pipeline — a real TDA analysis would use a library like `ripser` and
  proper persistence diagrams rather than a single-threshold snapshot.
- ε (the connection threshold) is a fixed constant, not adaptively chosen
  from the data's scale — a more robust version would compute ε from the
  point cloud's own distance distribution.

## Scaling — expected first failure points

- **ClickHouse**: at current query patterns, `/ohlc` and `/correlation`
  recompute aggregates from raw rows on every cache miss. At significantly
  higher trade volume, this becomes the first bottleneck — the fix is
  pre-aggregation via materialized views (noted above), not scaling
  ClickHouse hardware first.
- **Ingestion**: a single websocket connection per worker process. More
  symbols or higher-frequency streams would need either multiple worker
  processes sharded by symbol, or a message-queue intermediary (Kafka/Redis
  Streams) between ingestion and storage to decouple write throughput from
  ingestion throughput.
- **WebSocket fan-out**: the current implementation holds active connections
  in an in-process dict and iterates them synchronously on every tick. This
  doesn't scale past a single API process/replica — a real deployment would
  need a pub/sub fan-out layer (Redis pub/sub already sits in the path; the
  API's own broadcast step would need to move to a shared layer if running
  multiple API replicas behind a load balancer).
- **Redis caching**: at higher query volume, cache stampede on TTL expiry
  (many requests missing simultaneously) could spike ClickHouse load — a
  lock or "stale-while-revalidate" pattern would help.

## What I'd do with more time

- Materialized views for OHLC pre-aggregation (see Storage section)
- Trade ID deduplication in ingestion (see Ingestion section)
- Proper persistence diagrams instead of a single-ε snapshot for the TDA
  extension
- Integration tests around the ingestion worker's reconnect logic
- Move CORS/WebSocket origin handling to an explicit allowlist rather than
  wildcard, before anything resembling production use
