def score_location(population, competition):
    """
    Scoring-Logik (heuristisch, nachvollziehbar):
    - Population: Sättigung ab ~150.000 Personen
    - Wettbewerb: basiert auf öffentlich zugänglichen Ladepunkten
      innerhalb der Isochrone (Polygon-gefiltert)
    """

    # --- Population score ---
    # 150k = sehr starkes urbanes Einzugsgebiet
    pop_score = min(population / 150_000, 1.0)

    # --- Competition score ---
    stations = competition.get("stations")

    if stations is None:
        # harte Unsicherheit → leicht negativ
        comp_score = 0.5
    elif stations <= 5:
        comp_score = 0.9     # sehr wenig Wettbewerb
    elif stations <= 15:
        comp_score = 0.75    # moderat
    elif stations <= 30:
        comp_score = 0.6     # hoch
    else:
        comp_score = 0.45    # sehr hoch

    # --- Final weighted score ---
    score = (0.6 * pop_score + 0.4 * comp_score) * 100
    return round(score)
