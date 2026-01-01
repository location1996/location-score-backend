def interpret_score(score, population, competition, minutes):
    stations = competition.get("stations", None)
    osm_base = competition.get("osm_base", "unbekannt")
    queried_at = competition.get("queried_at", "unbekannt")

    # competitor sentence (honest + professional)
    if stations is None:
        comp_line = (
            "Die Wettbewerbsdaten (OSM-Ladepunkte) konnten aktuell nicht zuverlässig abgerufen werden; "
            "der Score wurde daher ohne belastbare Wettbewerbszahl berechnet."
        )
    else:
        comp_line = (
            f"Im {minutes}-Minuten-Einzugsgebiet wurden {stations} öffentlich zugängliche Ladepunkte "
            f"(OpenStreetMap, innerhalb der Isochrone) identifiziert."
        )

    freshness_line = (
        f"Datenstand OSM (Overpass osm_base): {osm_base} | "
        f"Abfragezeitpunkt (UTC): {queried_at}"
    )

    # decision language
    if score >= 70:
        decision = "Der Standort wird grundsätzlich empfohlen (GO)."
    elif score >= 50:
        decision = "Der Standort wirkt grundsätzlich interessant, sollte aber vertieft geprüft werden (CHECK)."
    else:
        decision = "Der Standort wird derzeit nicht empfohlen (NO-GO)."

    return f"""Der untersuchte Standort weist ein Nutzerpotenzial von ca. {population:,} Personen im {minutes}-Minuten-Einzugsgebiet auf (WorldPop, 2020).
{comp_line}
{freshness_line}

{decision}
Nächste Schritte:
- Netzanschluss-/Leistungsprüfung
- Flächenverfügbarkeit
- Genehmigungen
- Betreiber-/Partnercheck
""".replace(",", ".")
