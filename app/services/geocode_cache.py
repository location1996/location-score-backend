import sqlite3
from pathlib import Path

# absolute DB path (independent of where you start python/uvicorn)
BASE_DIR = Path(__file__).resolve().parents[1]          # .../app
DB_PATH = BASE_DIR / "data" / "geocode_cache.sqlite"   # .../app/data/geocode_cache.sqlite

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))

def _has_column(conn, table: str, col: str) -> bool:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return col in cols

def init_cache():
    with get_conn() as conn:
        # create (new installs)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT PRIMARY KEY,
            lon REAL,
            lat REAL
        )
        """)
        conn.commit()

        # migrate (existing installs)
        if not _has_column(conn, "geocode_cache", "matched_query"):
            conn.execute("ALTER TABLE geocode_cache ADD COLUMN matched_query TEXT")
        if not _has_column(conn, "geocode_cache", "fallback_used"):
            conn.execute("ALTER TABLE geocode_cache ADD COLUMN fallback_used INTEGER")
        conn.commit()

def get_geocode_meta(address: str):
    init_cache()
    key = address.strip()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT matched_query, fallback_used FROM geocode_cache WHERE address = ?",
            (key,),
        ).fetchone()

    if not row:
        return {"matched_query": None, "fallback_used": None}

    return {
        "matched_query": row[0],
        "fallback_used": bool(row[1]) if row[1] is not None else None,
    }
