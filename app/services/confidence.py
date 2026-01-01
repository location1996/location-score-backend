def compute_confidence(area_km2, pop_density, competition, geocode_meta=None) -> str:
    """
    VERY simple + transparent confidence:
    - LOW: missing competition data (Overpass failed) or missing density/area
    - MEDIUM: geocode fallback was used OR implausible density/area
    - HIGH: everything looks consistent
    """
    stations = competition.get("stations")
    fallback_used = (geocode_meta or {}).get("fallback_used")

    # hard failures / missing signals
    if stations is None:
        return "LOW"
    if area_km2 is None or area_km2 <= 0 or pop_density is None:
        return "LOW"

    # conservative downgrade if fallback was needed
    if fallback_used is True:
        return "MEDIUM"

    # plausibility guards (very broad on purpose)
    if pop_density < 300 or pop_density > 6000:
        return "MEDIUM"
    if area_km2 < 1 or area_km2 > 2000:
        return "MEDIUM"

    return "HIGH"
