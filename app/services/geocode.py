from .geocode_cache import get_conn, init_cache
import requests
import re

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "charging-location-intelligence"}

def _query(q: str):
    r = requests.get(
        URL,
        params={
            "q": q,
            "format": "json",
            "limit": 1,
            "countrycodes": "de",
        },
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()

def geocode(address: str):
    init_cache()

    cache_key = address.strip()

    # --- CACHE LOOKUP ---
    with get_conn() as conn:
        row = conn.execute(
            "SELECT lon, lat FROM geocode_cache WHERE address = ?",
            (cache_key,),
        ).fetchone()
        if row:
            print("[GEOCODE CACHE HIT]", cache_key)
            return row[0], row[1]

    # --- enforce Germany scope ---
    if "germany" not in cache_key.lower() and "deutschland" not in cache_key.lower():
        address_germany = f"{cache_key}, Germany"
    else:
        address_germany = cache_key

    candidates = [address_germany]

    simplified = re.sub(r"\bservice\s+area\b", "raststaette", address_germany, flags=re.IGNORECASE)
    simplified = re.sub(r"\bautobahn\b", "", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\bA\s?\d+\b", "", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    candidates.append(simplified)

    if re.search(r"\bholzkirchen\b", address_germany, flags=re.IGNORECASE):
        candidates.append("Raststaette Holzkirchen, Germany")
        candidates.append("Holzkirchen, Germany")

    last_tried = None

    for q in candidates:
        if not q or q == last_tried:
            continue
        last_tried = q

        print("[GEOCODE TRY]", q)
        data = _query(q)
        print("[GEOCODE HIT]", "YES" if data else "NO")

        if data:
            lon = float(data[0]["lon"])
            lat = float(data[0]["lat"])

            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO geocode_cache
                    (address, lon, lat, matched_query, fallback_used)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        lon,
                        lat,
                        q,
                        int(q != address_germany),
                    ),
                )
                conn.commit()

            return lon, lat

    raise ValueError(
        f"Geocoding failed for address: {cache_key} (tried: {candidates})"
    )
