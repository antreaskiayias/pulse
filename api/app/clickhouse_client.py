import os
import clickhouse_connect

def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "pulse"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "pulse_dev_pw"),
        database=os.getenv("CLICKHOUSE_DB", "pulse"),
    )
