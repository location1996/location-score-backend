import os
import requests

ORS_URL = "https://api.openrouteservice.org/v2/isochrones/driving-car"

def build_isochrone(point, minutes=15):
    api_key = os.environ.get("ORS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ORS_API_KEY env var. Set it before starting uvicorn.")

    lon, lat = point
    body = {
        "locations": [[lon, lat]],
        "range": [minutes * 60],   # seconds
        "attributes": ["area"]
    }

    r = requests.post(
        ORS_URL,
        json=body,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()  # <- GeoJSON FeatureCollection with 'features'
