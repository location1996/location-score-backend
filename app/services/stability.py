from typing import Dict, List, Optional


# -----------------------------
# Helpers
# -----------------------------
def _i(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _decision_label(score: int) -> str:
    score = _i(score, 0)
    if score >= 70:
        return "GO"
    if score >= 50:
        return "CHECK"
    return "NO-GO"


def _ampel_from_swing(core_ok: bool, swing: int, core_is_go: bool) -> Dict[str, str]:
    """
    Ampel ist bewusst auf den Kernbereich (z.B. 15→20) bezogen:
      - SEHR ROBUST: Kern bleibt GO und swing <= 5
      - ROBUST:      Kern bleibt mindestens CHECK und swing <= 15
      - INSTABIL:    sonst
    """
    if not core_ok:
        return {"label": "INSTABIL", "color": "#B71C1C"}  # rot

    if core_is_go and swing <= 5:
        return {"label": "SEHR ROBUST", "color": "#1B5E20"}  # grün

    if swing <= 15:
        return {"label": "ROBUST", "color": "#8D6E63"}  # neutral/braun-grau

    return {"label": "INSTABIL", "color": "#B71C1C"}


def _best_available_minute(target: int, available: List[int]) -> int:
    """nimmt target wenn vorhanden, sonst den nächstliegenden (fallback)."""
    if target in available:
        return target
    if not available:
        return target
    return min(available, key=lambda m: abs(m - target))


# -----------------------------
# Public API (used by main.py)
# -----------------------------
def compute_stability(
    multi_results: Optional[List[Dict]],
    baseline_minutes: int = 15,
    far_minutes: int = 20,
) -> Optional[Dict]:
    """
    Customer-friendly Stability Output (für PDF).

    Rückgabe:
    {
      "label": "INSTABIL" | "ROBUST" | "SEHR ROBUST",
      "color": "#RRGGBB",
      "summary": "Ampel-Text (Kernbereich)",
      "recommendation_title": "Empfehlung (Einzugsgebiet)",
      "recommendation_text": "Kundentext (GO klar, CHECK grenzwertig, NO-GO Warnung)"
    }

    Logik:
    - Ampel beurteilt die Robustheit im Kernbereich baseline->far (z.B. 15->20)
    - Empfehlungstext erklärt verständlich, ab wann es GO ist und wie CHECK/NO-GO zu deuten sind
    """

    if not multi_results or len(multi_results) < 2:
        return None

    # sort by minutes
    rs = sorted(multi_results, key=lambda r: _i(r.get("minutes", 0), 0))

    # map minutes -> values
    scores = {_i(r.get("minutes", 0), 0): _i(r.get("score", 0), 0) for r in rs}
    stations = {_i(r.get("minutes", 0), 0): r.get("stations") for r in rs}
    pops = {_i(r.get("minutes", 0), 0): _i(r.get("population", 0), 0) for r in rs}

    mins_all = sorted(scores.keys())
    if not mins_all:
        return None

    # choose baseline & far with safe fallback
    base_m = _best_available_minute(baseline_minutes, mins_all)
    far_m = _best_available_minute(far_minutes, mins_all)

    base_score = scores.get(base_m, 0)
    far_score = scores.get(far_m, 0)

    # -----------------------------
    # 1) Recommendation Text (customer logic)
    # -----------------------------
    go_minutes = [m for m in mins_all if scores.get(m, 0) >= 70]
    check_minutes = [m for m in mins_all if 50 <= scores.get(m, 0) < 70]
    nog_minutes = [m for m in mins_all if scores.get(m, 0) < 50]

    rec_title = "Empfehlung (Einzugsgebiet)"
    rec_parts: List[str] = []

    if go_minutes:
        min_go = min(go_minutes)
        max_go = max(go_minutes)

        if min_go == max_go:
            rec_parts.append(
                f"Der Standort ist bei <b>{min_go} Minuten Fahrzeit</b> klar wirtschaftlich attraktiv (<b>GO</b>)."
            )
        else:
            rec_parts.append(
                f"Der Standort ist <b>ab {min_go} Minuten Fahrzeit</b> klar wirtschaftlich attraktiv (<b>GO</b>)."
            )

        # Wenn darunter CHECK: nicht als Empfehlung verkaufen
        if check_minutes:
            min_check = min(check_minutes)
            rec_parts.append(
                f"Bei <b>{min_check} Minuten</b> liegt das Ergebnis nur bei <b>CHECK</b> – "
                f"das ist grenzwertig und sollte nur mit zusätzlicher Prüfung (z.B. Netzanschluss/Standortfaktoren) entschieden werden."
            )

        # Wenn darunter NO-GO: klar sagen warum
        if nog_minutes:
            min_nogo = min(nog_minutes)
            rec_parts.append(
                f"Bei <b>{min_nogo} Minuten</b> kippt das Ergebnis auf <b>NO-GO</b> "
                f"(Einzugsgebiet zu klein / zu wenig Nachfrage im unmittelbaren Umfeld)."
            )

    elif check_minutes:
        min_check = min(check_minutes)
        max_check = max(check_minutes)
        if min_check == max_check:
            rec_parts.append(
                f"Der Standort erreicht bei <b>{min_check} Minuten</b> nur <b>CHECK</b> "
                f"(wirtschaftlich plausibel, aber fragil)."
            )
        else:
            rec_parts.append(
                f"Der Standort erreicht <b>ab {min_check} Minuten</b> mindestens <b>CHECK</b> "
                f"(wirtschaftlich plausibel, aber fragil)."
            )

        if nog_minutes:
            min_nogo = min(nog_minutes)
            rec_parts.append(
                f"Unterhalb davon (z.B. <b>{min_nogo} Minuten</b>) liegt er bei <b>NO-GO</b> "
                f"(zu kleines Einzugsgebiet)."
            )

    else:
        rec_parts.append(
            "Der Standort bleibt in den getesteten Fahrzeiten unter der <b>CHECK</b>-Schwelle "
            "(aktuell nicht empfehlenswert)."
        )

    recommendation_text = " ".join(rec_parts).strip()

    # -----------------------------
    # 2) Ampel / Core Stability Summary (15→20)
    # -----------------------------
    swing = abs(far_score - base_score)

    # competition narrative
    comp_txt = ""
    try:
        b = stations.get(base_m)
        f = stations.get(far_m)
        if b is not None and f is not None and _i(f) > _i(b):
            comp_txt = "trotz zunehmendem Wettbewerb"
    except Exception:
        pass

    demand_txt = ""
    if pops.get(far_m, 0) > pops.get(base_m, 0):
        demand_txt = "bei gleichzeitig steigender Nachfrage"

    core_ok = (base_score >= 50 and far_score >= 50)
    core_is_go = (base_score >= 70 and far_score >= 70)

    ampel = _ampel_from_swing(core_ok, swing, core_is_go)

    if swing <= 5:
        change = "Der Score bleibt sehr stabil"
    elif swing <= 15:
        change = "Der Score schwankt/sinkt moderat"
    else:
        change = "Der Score schwankt/sinkt deutlich"

    reasons = " ".join([t for t in [comp_txt, demand_txt] if t]).strip()
    if reasons:
        reasons = " " + reasons

    core_summary = (
        f"Im Kernbereich (<b>{base_m}→{far_m} min</b>) bleibt die Entscheidung <b>{_decision_label(far_score)}</b> "
        f"({base_score}→{far_score}/100). {change}{reasons}."
    ).strip()

    return {
        "label": ampel["label"],
        "color": ampel["color"],
        "summary": core_summary,
        "recommendation_title": rec_title,
        "recommendation_text": recommendation_text,
        "baseline_minutes": base_m,
        "far_minutes": far_m,
    }