CREATE TABLE IF NOT EXISTS pulse.trades
(
    symbol          LowCardinality(String),
    trade_id        UInt64,
    price           Decimal(18, 8),
    quantity        Decimal(18, 8),
    quote_quantity  Decimal(18, 8),
    is_buyer_maker  UInt8,
    timestamp       DateTime64(3),
    ingested_at     DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree
PARTITION BY toDate(timestamp)
ORDER BY (symbol, trade_id)
TTL toDateTime(timestamp) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
