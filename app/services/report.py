from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER

from typing import Dict, List, Optional
from reportlab.lib.colors import HexColor

# --- Theme (modern dark, not too dark) ---
PAGE_BG   = HexColor("#12121A")
CARD_BG   = HexColor("#1A1A24")
CARD_BG_2 = HexColor("#202032")   # header area
TEXT      = HexColor("#F4F4FF")
MUTED_TXT = HexColor("#B9B9C9")
BORDER    = HexColor("#2C2C3A")
ACCENT    = HexColor("#7B5CFF")


# -----------------------------
# Stability (Customer Friendly)
# -----------------------------
def _draw_page_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)

    # Top accent line (subtle)
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(2)
    canvas.line(doc.leftMargin, A4[1]-14*mm, A4[0]-doc.rightMargin, A4[1]-14*mm)

    canvas.restoreState()


def card_table_style(bg=CARD_BG, border=BORDER, pad=10):
    return TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg),
        ("BOX", (0,0), (-1,-1), 1, border),
        ("INNERGRID", (0,0), (-1,-1), 0, border),  # effectively none
        ("LEFTPADDING", (0,0), (-1,-1), pad),
        ("RIGHTPADDING", (0,0), (-1,-1), pad),
        ("TOPPADDING", (0,0), (-1,-1), pad),
        ("BOTTOMPADDING", (0,0), (-1,-1), pad),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ])

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


def _ampel_from_swing(min_score_ok: bool, swing: int) -> Dict[str, str]:
    """
    Ampel-Logik nur für Kernbereich (z.B. 15→20):
      - SEHR ROBUST: beide >= CHECK und swing <= 5
      - ROBUST:      beide >= CHECK und swing <= 15
      - INSTABIL:    sonst
    """
    if not min_score_ok:
        return {"label": "INSTABIL", "color": "#B71C1C"}
    if swing <= 5:
        return {"label": "SEHR ROBUST", "color": "#4CAF50"}
    if swing <= 15:
        return {"label": "ROBUST", "color": "#8D6E63"}
    return {"label": "INSTABIL", "color": "#B71C1C"}


def compute_customer_stability(
    multi_results: Optional[List[Dict]],
    baseline_minutes: int = 15,
    far_minutes: int = 20,
) -> Optional[Dict]:
    if not multi_results:
        return None

    rs = sorted(multi_results, key=lambda r: _i(r.get("minutes", 0), 0))
    if len(rs) < 2:
        return None

    scores = {_i(r.get("minutes"), 0): _i(r.get("score"), 0) for r in rs}
    stations = {_i(r.get("minutes"), 0): r.get("stations") for r in rs}
    mins = sorted(scores.keys())
    if not mins:
        return None

    # -----------------------------
    # 1) Empfehlung (kundenverständlich)
    # -----------------------------
    recommendation_title = "Empfehlung (Einzugsgebiet)"

    s10 = scores.get(10)
    s15 = scores.get(15)

    # Standard-Text (falls 15/10 nicht vorhanden)
    attractive = [m for m in mins if scores[m] >= 50]
    if attractive:
        rec_min = min(attractive)
        recommendation_text = (
            f"Der Standort ist <b>ab {rec_min} Minuten Fahrzeit</b> mindestens CHECK (wirtschaftlich plausibel)."
        )
    else:
        recommendation_text = (
            "In den getesteten Fahrzeiten bleibt der Standort unter der CHECK-Schwelle "
            "(aktuell nicht empfehlenswert)."
        )

    # Speziell: 15 ist GO -> „ab 15 klar attraktiv“ und 10 als grenzwertig markieren
    if s15 is not None and s15 >= 70:
        recommendation_text = "Der Standort ist <b>ab 15 Minuten Fahrzeit</b> klar wirtschaftlich attraktiv (GO)."

        if s10 is not None:
            if 50 <= s10 < 70:
                recommendation_text += (
                    " Bei <b>10 Minuten</b> liegt das Ergebnis nur knapp über der CHECK-Schwelle "
                    "und ist als <b>grenzwertig</b> zu bewerten."
                )
            elif s10 < 50:
                recommendation_text += (
                    " Bei <b>10 Minuten</b> kippt das Ergebnis unter CHECK (NO-GO) – das Einzugsgebiet ist zu klein."
                )

    # -----------------------------
    # 2) Kern-Stabilität (baseline -> far)
    # -----------------------------
    base_m = baseline_minutes if baseline_minutes in scores else mins[len(mins) // 2]
    far_m = far_minutes if far_minutes in scores else mins[-1]

    base_score = scores[base_m]
    far_score = scores[far_m]
    swing = abs(far_score - base_score)

    comp_txt = ""
    try:
        b = stations.get(base_m)
        f = stations.get(far_m)
        if b is not None and f is not None and _i(f) > _i(b):
            comp_txt = "trotz zunehmendem Wettbewerb"
    except Exception:
        comp_txt = ""

    core_ok = (base_score >= 50) and (far_score >= 50)
    core_ampel = _ampel_from_swing(core_ok, swing)

    if swing <= 5:
        change = "Der Score bleibt sehr stabil"
    elif swing <= 15:
        change = "Der Score sinkt/schwankt moderat"
    else:
        change = "Der Score sinkt/schwankt deutlich"

    core_summary = (
        f"Im Kernbereich ({base_m}→{far_m} min) bleibt die Entscheidung <b>{_decision_label(far_score)}</b> "
        f"({base_score}→{far_score}/100). {change} {comp_txt}."
    ).replace("  ", " ").strip()

    # -----------------------------
    # 3) Early warning (nur wenn kleinste Zeit NO-GO)
    # -----------------------------
    early_warning = None

# Nur warnen, wenn:
# - 10 min NO-GO
# - aber mindestens eine längere Zeit >= CHECK
    if scores.get(mins[0], 0) < 50 and any(scores[m] >= 50 for m in mins[1:]):
        early_warning = (
        f"Hinweis: Bei {mins[0]} Minuten ist das Einzugsgebiet zu klein "
        f"(NO-GO). Erst bei größeren Fahrzeiten wird die CHECK-Schwelle erreicht."
    )

    return {
        "recommendation_title": recommendation_title,
        "recommendation_text": recommendation_text,
        "core": {
            "label": core_ampel["label"],
            "color": core_ampel["color"],
            "summary": core_summary,
        },
        "early_warning": early_warning,
    }


# -----------------------------
# Other Helpers
# -----------------------------
def _label(score: int) -> str:
    return _decision_label(score)


def _decision_long(score: int) -> str:
    score = _i(score, 0)
    if score >= 70:
        return "GO (sehr hohes Potenzial)"
    if score >= 50:
        return "CHECK (mittleres Potenzial)"
    return "NO-GO (niedriges Potenzial)"


def _badge_color(score: int):
    score = _i(score, 0)
    if score >= 70:
        return colors.HexColor("#1B5E20")  # dunkelgrün
    if score >= 50:
        return colors.HexColor("#8D6E63")  # braun/grau
    return colors.HexColor("#B71C1C")  # dunkelrot


def _fmt_int(n):
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)


def _safe(s, default="unbekannt"):
    return s if (s is not None and str(s).strip() != "") else default


def _confidence_explain(conf: str) -> str:
    conf = (conf or "").upper()
    if conf == "HIGH":
        return "Datenlage stabil (Geocode/OSM plausibel)."
    if conf == "MEDIUM":
        return "Leichte Unsicherheit (z.B. Geocode-Fallback oder Plausibilitätsgrenzen)."
    if conf == "LOW":
        return "Erhöhte Unsicherheit (z.B. fehlende OSM/Overpass-Werte)."
    return "Datenqualität konnte nicht eindeutig bewertet werden."


# -----------------------------
# PDF
# -----------------------------
from pathlib import Path  # oben in der Datei ergänzen


    
def build_pdf(
    path,
    address,
    score,
    text,
    population,
    competition,
    minutes,
    multi_results=None,
    confidence=None,
    geocode_meta=None,
    stability=None,
    compare_results=None,   # ✅ NEU
):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title="Charging Location Check",
    )

    styles = getSampleStyleSheet()

    H1 = ParagraphStyle(
    "H1", parent=styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=22, leading=26,
    textColor=TEXT, spaceAfter=6
)
    H2 = ParagraphStyle(
    "H2", parent=styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=12.5, leading=16,
    textColor=TEXT, spaceBefore=10, spaceAfter=6
)
    BODY = ParagraphStyle(
    "BODY", parent=styles["BodyText"],
    fontName="Helvetica", fontSize=10.8, leading=15,
    textColor=TEXT
)
    MUTED = ParagraphStyle("MUTED", parent=BODY, textColor=MUTED_TXT)
    SMALL = ParagraphStyle("SMALL", parent=BODY, fontSize=9.6, leading=13, textColor=MUTED_TXT)
    CENTER = ParagraphStyle("CENTER", parent=BODY, alignment=TA_CENTER)

    KPI_TITLE = ParagraphStyle(
    "KPI_TITLE", parent=CENTER,
    fontName="Helvetica-Bold",
    fontSize=11.5,
    leading=14,
    textColor=TEXT
)

    KPI_VALUE = ParagraphStyle(
    "KPI_VALUE", parent=CENTER,
    fontName="Helvetica-Bold",
    fontSize=26,          # <- “knackiger”
    leading=28,           # <- Zeilenabstand für die Zahl
    textColor=TEXT
)

    KPI_SUB = ParagraphStyle(
    "KPI_SUB", parent=CENTER,
    fontName="Helvetica",
    fontSize=10.5,
    leading=14,           # <- mehr Luft unter der Zahl
    textColor=MUTED_TXT
)

    score_int = max(0, min(_i(score, 0), 100))
    decision = _decision_long(score_int)
    decision_color = _badge_color(score_int)

    competition = competition or {}
    stations = competition.get("stations", None)
    comp_density = competition.get("density", "unknown")
    osm_base = competition.get("osm_base", None)
    queried_at = competition.get("queried_at", None)

    stations_str = _safe(str(stations), "nicht verfügbar") if stations is not None else "nicht verfügbar"
    comp_density_str = _safe(comp_density, "nicht verfügbar")
    osm_base_str = _safe(osm_base, "unbekannt")
    queried_at_str = _safe(queried_at, "unbekannt")

    matched_query = (geocode_meta or {}).get("matched_query")
    fallback_used = (geocode_meta or {}).get("fallback_used")
    fallback_str = "ja" if fallback_used is True else "nein" if fallback_used is False else "unbekannt"
    matched_str = _safe(matched_query, "unbekannt")

    conf_str = _safe(confidence, "unbekannt")
    conf_expl = _confidence_explain(conf_str)

    story = []

    # -----------------------------
    # Page 1: Executive
    # -----------------------------
   
    story.append(Paragraph("Charging Location Check", H1))
    story.append(Paragraph("Professionelle Standortbewertung für Ladeinfrastruktur", MUTED))
    story.append(Spacer(1, 6))

    meta_tbl = Table(
        [[
            Paragraph(f"<b>Adresse</b><br/>{_safe(address)}", BODY),
            Paragraph(f"<b>Analyse</b><br/>{minutes} Minuten Fahrzeit", BODY),
            Paragraph(f"<b>Datenqualität</b><br/>{conf_str}<br/><font size=9>{conf_expl}</font>", BODY),
        ]],
        colWidths=[85 * mm, 35 * mm, 42 * mm],
    )
    meta_tbl.setStyle(card_table_style(bg=CARD_BG, border=BORDER, pad=10))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    chip_style = ParagraphStyle(
        "chip", parent=CENTER,
        textColor=colors.white, fontSize=9.5, leading=11
    )

    chip = Paragraph(
        f'<font backcolor="#{decision_color.hexval()[2:]}">&nbsp;&nbsp;<b>{decision}</b>&nbsp;&nbsp;</font>',
        chip_style
    )

    banner = Table(
        [[
            Paragraph("<b>RESULT</b>", ParagraphStyle("b1", parent=BODY, textColor=MUTED_TXT, fontSize=9)),
            Paragraph(
                f"<b>{score_int}</b><font size=10>/100</font>",
                ParagraphStyle("b2", parent=BODY, fontName="Helvetica-Bold", fontSize=30, leading=32, textColor=TEXT),
            ),
            chip
        ]],
        colWidths=[30*mm, 80*mm, 52*mm],
    )
    banner.setStyle(card_table_style(bg=CARD_BG, border=BORDER, pad=12))
    story.append(banner)
    story.append(Spacer(1, 10))

    def kpi_cell(title, value, sub, value_color=TEXT):
        # ReportLab <font color="..."> braucht einen String wie "#RRGGBB"
        def _c(x):
            return x.hexval() if hasattr(x, "hexval") else str(x)

        return Paragraph(
            f'<font size="11"><b>{title}</b></font>'
            f'<br/><br/>'
            f'<font size="28" color="{_c(value_color)}"><b>{value}</b></font>'
            f'<br/><br/>'
            f'<font size="10" color="{_c(MUTED_TXT)}">{sub}</font>',
            ParagraphStyle("KPI_MIX", parent=CENTER, leading=18)
        )

    # KPI Blocks
    pop_block      = kpi_cell("Nutzerpotenzial", _fmt_int(population), "WorldPop (2020)")
    stations_block = kpi_cell("Ladepunkte (Wettbewerb)", stations_str, "OSM in Isochrone")

    # starke visuelle Codierung für Wettbewerb "high"
    density_val = str(_safe(comp_density_str)).strip().lower()
    if density_val == "high":
        density_block = kpi_cell("Wettbewerbsdichte", "HIGH", "Low / Medium / High", value_color=HexColor("#FF3B30"))
    elif density_val == "medium":
        density_block = kpi_cell("Wettbewerbsdichte", "MEDIUM", "Low / Medium / High", value_color=HexColor("#FFCC00"))
    else:
        density_block = kpi_cell("Wettbewerbsdichte", str(_safe(comp_density_str)), "Low / Medium / High", value_color=HexColor("#34C759"))

    kpi_tbl = Table(
        [
            [Paragraph("KEY METRICS", ParagraphStyle("KM", parent=BODY, textColor=MUTED_TXT, fontName="Helvetica-Bold", fontSize=9)), "", ""],
            [pop_block, stations_block, density_block],
        ],
        colWidths=[55*mm, 55*mm, 52*mm],
    )

    kpi_tbl.setStyle(TableStyle([
        ("SPAN", (0,0), (-1,0)),
        ("BACKGROUND", (0,0), (-1,0), CARD_BG_2),
        ("TEXTCOLOR", (0,0), (-1,0), MUTED_TXT),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 9),
        ("ALIGN", (0,0), (-1,0), "LEFT"),
        ("LEFTPADDING", (0,0), (-1,0), 12),
        ("TOPPADDING", (0,0), (-1,0), 10),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),

        ("BACKGROUND", (0,1), (-1,-1), CARD_BG),
        ("TEXTCOLOR", (0,1), (-1,-1), TEXT),

        ("BOX", (0,0), (-1,-1), 1, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0, BORDER),

        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,1), (-1,-1), 12),
        ("RIGHTPADDING", (0,1), (-1,-1), 12),
        ("TOPPADDING", (0,1), (-1,-1), 14),
        ("BOTTOMPADDING", (0,1), (-1,-1), 14),
    ]))

    story.append(kpi_tbl)
    story.append(Spacer(1, 12))

    # -----------------------------
    # Warum diese Entscheidung?
    # -----------------------------
    story.append(Paragraph("Warum diese Entscheidung?", H2))

    why_lines = []
    try:
        if population and int(population) > 50000:
            why_lines.append("Hohe Nutzerbasis – Nachfragepotenzial grundsätzlich attraktiv.")
        else:
            why_lines.append("Begrenzte Nutzerbasis – Nachfragepotenzial eher niedrig.")
    except Exception:
        why_lines.append("Nutzerbasis konnte nicht sicher bewertet werden.")

    if stations is None:
        why_lines.append("Wettbewerbsdaten konnten nicht zuverlässig geladen werden.")
    else:
        try:
            s = int(stations)
            if s < 5:
                why_lines.append("Wenig Ladepunkte im Einzugsgebiet – geringer Wettbewerb.")
            elif s < 15:
                why_lines.append("Moderate Ladepunktdichte – Wettbewerb mittel.")
            else:
                why_lines.append("Viele Ladepunkte – Wettbewerb hoch (Differenzierung notwendig).")
        except Exception:
            why_lines.append("Wettbewerb konnte nicht eindeutig eingeordnet werden.")

    story.append(Paragraph("<br/>".join([f"• {l}" for l in why_lines]), BODY))

    # -----------------------------
    # Empfehlung
    # -----------------------------
    story.append(Spacer(1, 8))
    story.append(Paragraph("Empfehlung (nächste Schritte)", H2))
    story.append(Paragraph(
        "• Netzanschluss & Leistungsprüfung<br/>"
        "• Flächenverfügbarkeit vor Ort<br/>"
        "• Genehmigungsfähigkeit prüfen<br/>"
        "• Betreiber- und Partnerauswahl",
        BODY,
    ))

    # -----------------------------
    # Daten-Footer
    # -----------------------------
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"<b>OSM Datenstand</b>: {_safe(osm_base_str)} &nbsp;|&nbsp; "
        f"<b>Overpass</b>: {_safe(queried_at_str)}<br/>"
        f"<b>Geocoding</b>: Fallback {fallback_str} &nbsp;|&nbsp; Match: {matched_str}",
        SMALL,
    ))


    # =====================================================
    # COMPARE (falls vorhanden)
    # =====================================================

    if compare_results:
        story.append(PageBreak())
        story.append(Paragraph("Location Comparison", H1))
        story.append(Paragraph("Ranked results for the selected locations.", MUTED))
        story.append(Spacer(1, 8))

        header = ["Rank", "Address", "Score", "Population", "Charging Points", "Decision"]
        rows = [header]

        sorted_rows = sorted(compare_results, key=lambda r: _i(r.get("score"), 0), reverse=True)

        for idx, r in enumerate(sorted_rows, start=1):
            rows.append([
                f"#{idx}",
                _safe(r.get("address")),
                f"{_i(r.get('score'))}/100",
                _fmt_int(r.get("population")),
                "-" if r.get("stations") is None else str(r.get("stations")),
                _decision_label(_i(r.get("score"))),
            ])

        t = Table(rows, colWidths=[12*mm, 70*mm, 22*mm, 28*mm, 28*mm, 22*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), CARD_BG_2),
            ("TEXTCOLOR", (0,0), (-1,0), TEXT),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,1), (-1,-1), CARD_BG),
            ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
            ("BOX", (0,0), (-1,-1), 1, BORDER),
            ("INNERGRID", (0,0), (-1,-1), 0, BORDER),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (0,0), (0,-1), "CENTER"),
            ("ALIGN", (2,0), (-1,-1), "CENTER"),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t)

    
    # =====================================================
    # PAGE 2 – MULTI-TIME (falls vorhanden)
    # =====================================================
    if multi_results:
        story.append(PageBreak())
        story.append(Paragraph("Multi-Time Vergleich", H1))
        story.append(Paragraph(
            "Wie robust ist der Standort bei unterschiedlichen Fahrzeiten?",
            MUTED
        ))
        story.append(Spacer(1, 8))

        stability_pack = compute_customer_stability(
            multi_results,
            baseline_minutes=15,
            far_minutes=20
        )

        if stability_pack:
            core = stability_pack["core"]

            amp = Table(
                [[
                    Paragraph(f"<b>Stabilität:</b> {core['label']}", BODY),
                    Paragraph(core["summary"], BODY),
                ]],
                colWidths=[45 * mm, 117 * mm],
            )
            amp.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(core["color"])),
                ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.append(amp)
            story.append(Spacer(1, 10))

        header = ["Fahrzeit", "Bevölkerung", "Ladepunkte", "Score", "Entscheidung"]
        rows = [header]

        for r in sorted(multi_results, key=lambda x: _i(x.get("minutes", 0), 0)):
            rows.append([
                f"{r['minutes']} min",
                _fmt_int(r.get("population")),
                "-" if r.get("stations") is None else str(r.get("stations")),
                f"{_i(r.get('score'))}/100",
                _decision_label(_i(r.get("score")))
            ])

        t = Table(rows, colWidths=[25*mm, 40*mm, 30*mm, 25*mm, 44*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), CARD_BG_2),
            ("TEXTCOLOR", (0,0), (-1,0), TEXT),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,1), (-1,-1), CARD_BG),
            ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
            ("BOX", (0,0), (-1,-1), 1, BORDER),
            ("INNERGRID", (0,0), (-1,-1), 0, BORDER),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ]))
        story.append(t)

    # =====================================================
    # PAGE 3 – DETAILS
    # =====================================================
    story.append(PageBreak())
    story.append(Paragraph("Begründung & Details", H1))
    story.append(Paragraph("Executive Summary", H2))
    story.append(Paragraph(_safe((text or "").strip(), ""), BODY))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Hinweis", H2))
    story.append(Paragraph(
        "Die Analyse basiert auf öffentlich verfügbaren Daten (OSM, WorldPop) "
        "und ersetzt keine technische oder rechtliche Vor-Ort-Prüfung.",
        SMALL,
    ))

    # -----------------------------
    # PDF BUILD (IMMER GANZ AM ENDE)
    # -----------------------------
    doc.build(
        story,
        onFirstPage=_draw_page_bg,
        onLaterPages=_draw_page_bg,
    )

    if not path.exists():
        raise RuntimeError(f"PDF was not created: {path}")
    
def build_compare_pdf(
    path,
    compare_results: list[dict],
    minutes: int,
    vertical: str = "ev_charging",
    plan: str = "standard",
    profile: str | None = None,
    multi_time: bool = False,
):
    """
    Baut einen Compare-PDF, indem build_pdf() mit compare_results befüllt wird.
    Nimmt als "Headline-KPIs" den besten Standort (Rank #1).
    """
    compare_results = compare_results or []
    best = compare_results[0] if compare_results else {}

    best_score = best.get("score", 0)
    best_population = best.get("population", None)

    best_confidence = best.get("confidence")
    best_geocode_meta = best.get("geocode_meta")

    # Competition fürs KPI-Panel (nur grob nötig)
    competition = {
        "stations": best.get("stations"),
        "density": best.get("density", "unknown"),
        "osm_base": (best.get("competition") or {}).get("osm_base"),
        "queried_at": (best.get("competition") or {}).get("queried_at"),
    }

    headline = (
        f"Vergleich von {len(compare_results)} Standorten "
        f"({minutes} Minuten, Plan: {plan}, Vertical: {vertical}"
        + (f", Profil: {profile}" if profile else "")
        + (", Multi-Time: ja)" if multi_time else ")")
    )

    return build_pdf(
        path=path,
        address=f"COMPARE ({len(compare_results)} Standorte)",
        score=best_score,
        text=headline,
        population=best_population,
        competition=competition,
        minutes=minutes,
        compare_results=compare_results,  # ✅ das triggert deinen Compare-Block
        multi_results=None,
        confidence=best_confidence,
        geocode_meta=best_geocode_meta,  
    )

   