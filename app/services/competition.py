import requests
from datetime import datetime, timezone
from shapely.geometry import shape, Point

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# optional: stabiler Header (manche Overpass-Instanzen mögen User-Agent)
HEADERS = {
    "User-Agent": "charging-location-intelligence/1.0 (contact: you@example.com)",
}


def _bbox_from_featurecollection(geojson_fc):
    geom = shape(geojson_fc["features"][0]["geometry"])
    minx, miny, maxx, maxy = geom.bounds  # lon/lat bounds
    return miny, minx, maxy, maxx  # south, west, north, east


def _dedup(elements):
    seen = set()
    out = []
    for el in elements:
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out


def _point_from_element(el):
    # nodes
    if "lat" in el and "lon" in el:
        return Point(el["lon"], el["lat"])
    # ways/relations (we asked for out center)
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return Point(center["lon"], center["lat"])
    return None


def charging_competition(isochrone_geojson):
    # Fetch via bbox (stable), then filter strictly inside isochrone polygon (accurate)
    s, w, n, e = _bbox_from_featurecollection(isochrone_geojson)
    iso_poly = shape(isochrone_geojson["features"][0]["geometry"])

    query = f"""
    [out:json][timeout:40];
    (
      node["amenity"="charging_station"]({s},{w},{n},{e});
      way["amenity"="charging_station"]({s},{w},{n},{e});
      relation["amenity"="charging_station"]({s},{w},{n},{e});
    );
    out center tags;
    """

    last_err = None

    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data=query, headers=HEADERS, timeout=60)
            resp.raise_for_status()

            ctype = (resp.headers.get("Content-Type") or "").lower()
            # Overpass liefert manchmal HTML bei Rate-Limit/Wartung -> das fangen wir ab
            if ("json" not in ctype) and ("application/geo+json" not in ctype):
                raise RuntimeError(f"Overpass non-JSON response: {ctype}")

            data = resp.json()

            osm_base = (
                data.get("osm3s", {}).get("timestamp_osm_base")
                or data.get("osm_base")
                or "unknown"
            )
            queried_at = datetime.now(timezone.utc).isoformat()

            elements = _dedup(data.get("elements", []))

            filtered = []
            for el in elements:
                tags = el.get("tags", {}) or {}

                # filter private / no if tagged
                access = (tags.get("access") or "").lower()
                if access in {"private", "no"}:
                    continue

                pt = _point_from_element(el)
                if pt is None:
                    continue

                # strict: must lie inside isochrone polygon
                if not (iso_poly.contains(pt) or iso_poly.touches(pt)):
                    continue

                filtered.append(el)

            stations = len(filtered)

            # Density buckets (based on polygon-filtered count)
            density = "low" if stations < 10 else "medium" if stations < 30 else "high"

            return {
                "stations": stations,
                "density": density,
                "osm_base": osm_base,
                "queried_at": queried_at,
            }

        except Exception as e:
            last_err = f"{url}: {e}"
            continue

    # ✅ Fallback: lieber Report erzeugen als API crashen lassen
    print("[WARN] Overpass failed, returning stations=None. Last error:", last_err)
    return {
        "stations": None,
        "density": "unknown",
        "osm_base": None,
        "queried_at": None,
        "error": str(last_err),
    }
