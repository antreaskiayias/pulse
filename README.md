# PULSE

Real-time intelligence platform ingesting live Binance trade data into
ClickHouse, exposing aggregations via a cached FastAPI layer, and
visualizing it in a React dashboard with a live topological-summary
extension.

## Prerequisites

- Docker and Docker Compose
- ~2GB free disk for ClickHouse/Redis volumes

## Running

```bash
git clone https://github.com/antreaskiayias/pulse
cd pulse
docker compose up --build -d
```

Then open:
- Dashboard: http://localhost:5173
- API: http://localhost:8000 (docs at http://localhost:8000/docs)
- ClickHouse HTTP interface: http://localhost:8123

Data should start flowing within a few seconds of startup — the ingestion
worker connects to Binance immediately and begins writing trades.

## Verifying it's working

```bash
curl -u pulse:pulse_dev_pw "http://localhost:8123/?query=SELECT+count()+FROM+pulse.trades"
```

The count should be increasing on repeated calls.

## Stopping

To stop all services and remove container volumes:

```bash
docker compose down -v
```

## Project structure

```
pulse/
├── ingestion/ # Binance websocket → ClickHouse worker
├── api/ # FastAPI aggregation + WebSocket API
├── dashboard/ # React + TypeScript frontend
├── clickhouse/init/ # Schema, applied on first container start
└── docker-compose.yml
```

## Assumptions

- Three symbols (BTCUSDT, ETHUSDT, SOLUSDT) are hardcoded in the ingestion
  worker for this demo; a production version would make this configurable.
- Default credentials in `.env.example` are for local development only.
- 90-day retention on trade data (see ARCHITECTURE.md for rationale).

See `ARCHITECTURE.md` for design decisions, trade-offs, and known
limitations.
