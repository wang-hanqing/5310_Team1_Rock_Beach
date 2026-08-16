import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv

# ── DATABASE CONNECTION ──────────────────────────────────────────────────────
# Team 1's shared DigitalOcean Postgres instance.
# Credentials live in a local .env file (never committed to git) — see
# .env.example for the template. Each teammate creates their own .env with
# the real values after the password rotation.
load_dotenv()


def _get_config():
    """Read connection settings from environment variables."""
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing database environment variable(s): {', '.join(missing)}. "
            "Create a .env file in this folder (see .env.example) with real values."
        )
    return {
        "host":     os.environ["DB_HOST"],
        "port":     int(os.environ.get("DB_PORT", 25061)),
        "database": os.environ["DB_NAME"],
        "user":     os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "sslmode":  os.environ.get("DB_SSLMODE", "require"),  # DO managed Postgres requires SSL
    }


def get_connection():
    """Open a connection to the PostgreSQL server."""
    return psycopg2.connect(**_get_config())


def run_query(sql: str, params=None) -> pd.DataFrame:
    """Run a SELECT query and return results as a pandas DataFrame."""
    conn = get_connection()
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        return df
    finally:
        conn.close()


def insert_and_return_id(sql: str, params=None):
    """Run an INSERT ... RETURNING <col> statement and commit it, returning
    that column's value."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
