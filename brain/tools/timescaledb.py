import psycopg2
from config import TIMESCALEDB_HOST, TIMESCALEDB_PORT, TIMESCALEDB_DATABASE, TIMESCALEDB_USER, TIMESCALEDB_PASSWORD


def query_timescaledb(sql: str) -> str:
    """Query TimescaleDB using SQL."""
    print(f"[TimescaleDB] Query: {sql}")
    try:
        conn = psycopg2.connect(
            host=TIMESCALEDB_HOST,
            port=TIMESCALEDB_PORT,
            dbname=TIMESCALEDB_DATABASE,
            user=TIMESCALEDB_USER,
            password=TIMESCALEDB_PASSWORD,
            connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                if not rows:
                    return "No data found."
                cols = [desc[0] for desc in cur.description]
                if len(rows) > 10:
                    rows = rows[:10]
                lines = []
                for row in rows:
                    lines.append(", ".join(f"{c}: {v}" for c, v in zip(cols, row)))
                return "\n".join(lines)
        finally:
            conn.close()
    except Exception as e:
        return f"TimescaleDB error: {e}"
