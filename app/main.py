from pathlib import Path
from dotenv import load_dotenv
import os
env_path = Path(__file__).resolve().parents[1] / ".env"
print("ENV PATH:", env_path, "exists:", env_path.exists())
load_dotenv(dotenv_path=env_path)
print("STRIPE_SECRET_KEY:", os.getenv("STRIPE_SECRET_KEY"))

import stripe
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import uuid
from typing import Optional, Literal, Dict, Any

from shapely.geometry import shape
from shapely.ops import transform
import pyproj
from .services.geocode import geocode
from .services.isochrone import build_isochrone
from .services.population import population_in_area
from .services.competition import charging_competition
from .services.scoring import score_location
from .services.interpretation import interpret_score
from .services.report import build_pdf, compute_customer_stability, build_compare_pdf
from .services.geocode_cache import get_geocode_meta
from .services.confidence import compute_confidence
from .services.stability import compute_stability
from .services.verticals import get_vertical_config, Vertical
from pydantic import BaseModel, Field

from .services.report_store import (
    utc_now_iso,
    write_report_meta,
    read_report_meta,
    update_report_meta,
    report_pdf_path,
)

import re

app = FastAPI(title="Charging Location Intelligence")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
if not stripe.api_key:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")
if not STRIPE_WEBHOOK_SECRET:
    print("WARN: STRIPE_WEBHOOK_SECRET is not set (webhook will fail)")

REPORTS_DIR = (Path(__file__).resolve().parents[1] / "reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET not set")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # ✅ Wir reagieren auf erfolgreiche Zahlung
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        # hier holen wir uns die report_id aus metadata
        report_id = (session.get("metadata") or {}).get("report_id")
        if report_id:
            meta = read_report_meta(REPORTS_DIR, report_id)
            if meta:
                update_report_meta(REPORTS_DIR, report_id, {
                    "status": "paid",
                    "paid_at_utc": utc_now_iso(),
                    "stripe_session_id": session.get("id"),
                })

    return {"ok": True}

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9äöüß\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:60]



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # später einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




ADMIN_TOKEN = "charra"

PROFILE_MINUTES = {
    "urban": 8,
    "daily": 15,
    "destination": 25,
    "rural": 30,
}

STRIPE_PRICES = {
    "standard": "price_1SkpBPPSuj2YcTgEzAeRnQhR",
    "express":  "price_1SkpBhPSuj2YcTgESJGEiwNZ",
    "pro":      "price_1SkpByPSuj2YcTgEJ0TlBNhD",
}
Plan = Literal["standard", "express", "pro"]
class CheckoutRequest(BaseModel):
    report_id: str
    plan: Plan  # "standard" | "express" | "pro"

@app.post("/stripe/create_checkout_session")
def create_checkout_session(body: CheckoutRequest):
    # 1) Report muss existieren
    meta = read_report_meta(REPORTS_DIR, body.report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Report not found")

    # 2) Preis aus Mapping holen
    price_id = STRIPE_PRICES.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Unknown plan")

    # 3) Checkout Session erstellen + report_id als metadata setzen (WICHTIG!)
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{FRONTEND_BASE_URL}/success?report_id={body.report_id}",
        cancel_url=f"{FRONTEND_BASE_URL}/cancel?report_id={body.report_id}",
        metadata={"report_id": body.report_id},
    )

    return JSONResponse({"url": session.url, "id": session.id})

class LocationRequest(BaseModel):
    address: str
    vertical: str = "ev_charging"   # ⬅️ DAS ist die Zeile
    minutes: Optional[int] = None
    profile: Optional[Literal["urban", "daily", "destination", "rural"]] = None
    multi_time: bool = False
    plan: Plan = "standard"

 # falls Field noch nicht importiert ist

class CompareRequest(BaseModel):
    addresses: list[str] = Field(..., min_length=2)
    vertical: str = "ev_charging"
    minutes: Optional[int] = None
    profile: Optional[Literal["urban", "daily", "destination", "rural"]] = None
    multi_time: bool = False
    plan: Plan = "standard"

def isochrone_area_km2(isochrone_geojson) -> float:
    geom = shape(isochrone_geojson["features"][0]["geometry"])
    project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    geom_m = transform(project, geom)
    return geom_m.area / 1_000_000.0


def enforce_plan(req: LocationRequest) -> LocationRequest:
    """
    Plan/Enforcement (MVP) + vertical-aware:
    - Multi-Time ist nur erlaubt, wenn der Plan das im Vertical erlaubt
    """
    cfg = get_vertical_config(req.vertical)

    # Multi-Time nur wenn Plan erlaubt
    if req.plan not in cfg.allow_multi_time_plans:
        req.multi_time = False

    return req


def resolve_minutes(req: LocationRequest) -> int:
    if req.minutes is not None:
        return int(req.minutes)
    if req.profile is not None:
        return PROFILE_MINUTES[req.profile]
    return 15


def safe_competition(isochrone) -> Dict[str, Any]:
    try:
        return charging_competition(isochrone)
    except Exception as e:
        return {
            "stations": None,
            "density": "unknown",
            "osm_base": None,
            "queried_at": None,
            "error": str(e),
        }


def compute_multi_results(point) -> list[dict]:
    results = []
    for m in [10, 15, 20]:
        try:
            iso_m = build_isochrone(point, minutes=m)
            pop_m = population_in_area(iso_m)
            comp_m = safe_competition(iso_m)
            score_m = score_location(pop_m, comp_m)

            results.append({
                "minutes": m,
                "population": pop_m,
                "stations": comp_m.get("stations"),
                "density": comp_m.get("density"),
                "osm_base": comp_m.get("osm_base"),
                "queried_at": comp_m.get("queried_at"),
                "score": score_m,
                "error": comp_m.get("error"),
            })
        except Exception as e:
            results.append({
                "minutes": m,
                "population": None,
                "stations": None,
                "density": "unknown",
                "osm_base": None,
                "queried_at": None,
                "score": 0,
                "error": f"multi-time failed for {m}min: {e}",
            })
    return results


def run_analysis(req: LocationRequest) -> Dict[str, Any]:
    req = enforce_plan(req)
    minutes = resolve_minutes(req)

    point = geocode(req.address)
    geocode_meta = get_geocode_meta(req.address)

    isochrone = build_isochrone(point, minutes=minutes)

    area_km2 = isochrone_area_km2(isochrone)
    population = population_in_area(isochrone)
    density = (population / area_km2) if area_km2 > 0 else None

    competition = safe_competition(isochrone)

    confidence = compute_confidence(area_km2, density, competition, geocode_meta)

    score = score_location(population, competition)
    explanation = interpret_score(score, population, competition, minutes)

    multi_results = None
    stability_pack = None
    stability = None

    if req.multi_time:
        multi_results = compute_multi_results(point)
        stability_pack = compute_customer_stability(multi_results, baseline_minutes=15, far_minutes=20)
        stability = compute_stability(multi_results) if multi_results else None

    return {
        "req": req.model_dump(),
        "minutes": minutes,
        "geocode_meta": geocode_meta,
        "area_km2": area_km2,
        "population": population,
        "density": density,
        "competition": competition,
        "confidence": confidence,
        "score": score,
        "explanation": explanation,
        "multi_results": multi_results,
        "stability_pack": stability_pack,
        "stability": stability,
    }
def analyze_one_for_compare(address: str, base_req: CompareRequest) -> Dict[str, Any]:
    req = LocationRequest(
        address=address,
        vertical=base_req.vertical,
        minutes=base_req.minutes,
        profile=base_req.profile,
        multi_time=base_req.multi_time,
        plan=base_req.plan,
    )
    data = run_analysis(req)
    return {
        "address": address,
        "minutes": data["minutes"],
        "score": data["score"],
        "population": data["population"],
        "stations": (data["competition"] or {}).get("stations"),
        "density": (data["competition"] or {}).get("density"),
        "confidence": data["confidence"],
        "competition": data["competition"],
        "explanation": data["explanation"],
        "geocode_meta": data["geocode_meta"],
        "multi_results": data["multi_results"],
    }

# -----------------------------
# SALES FLOW (MVP)
# -----------------------------

@app.post("/create_report")
def create_report(req: LocationRequest):
    req = enforce_plan(req)

    report_id = str(uuid.uuid4())
    meta = {
        "report_id": report_id,
        "created_at_utc": utc_now_iso(),
        "status": "created",     # created -> paid -> delivered
        "plan": req.plan,
        "payload": req.model_dump(),
    }
    write_report_meta(REPORTS_DIR, report_id, meta)

    return JSONResponse({"report_id": report_id, "status": meta["status"], "plan": req.plan})

@app.post("/create_compare_report")
def create_compare_report(req: CompareRequest):
    # Plan/Vertical Enforcement (wie in /compare)
    cfg = get_vertical_config(req.vertical)
    if req.plan not in cfg.allow_multi_time_plans:
        req.multi_time = False

    # sanitize / limit
    addresses = [a.strip() for a in req.addresses if a and a.strip()]
    if len(addresses) < 2:
        raise HTTPException(status_code=400, detail="Bitte mindestens 2 Adressen angeben.")
    if len(addresses) > 50:
        raise HTTPException(status_code=400, detail="Maximal 50 Adressen pro Vergleich.")

    req.addresses = addresses

    report_id = str(uuid.uuid4())
    meta = {
        "report_id": report_id,
        "created_at_utc": utc_now_iso(),
        "status": "created",      # created -> paid -> delivered
        "plan": req.plan,
        "kind": "compare",        # ✅ wichtig
        "payload": req.model_dump(),
    }
    write_report_meta(REPORTS_DIR, report_id, meta)
    return JSONResponse({"report_id": report_id, "status": meta["status"], "plan": req.plan, "kind": "compare"})

@app.post("/mark_paid/{report_id}")
def mark_paid(report_id: str, x_admin_token: str | None = Header(default=None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    meta = read_report_meta(REPORTS_DIR, report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Report not found")

    meta = update_report_meta(REPORTS_DIR, report_id, {"status": "paid", "paid_at_utc": utc_now_iso()})
    return JSONResponse({"ok": True, "report_id": report_id, "status": meta["status"]})


@app.get("/report/{report_id}", response_class=FileResponse)
def get_report(report_id: str):
    meta = read_report_meta(REPORTS_DIR, report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Report not found")

    if meta.get("status") not in ("paid", "delivered"):
        raise HTTPException(status_code=402, detail="Payment required")

    pdf_path = report_pdf_path(REPORTS_DIR, report_id)

    payload = meta.get("payload") or {}
    kind = meta.get("kind") or ("compare" if "addresses" in payload else "single")

    if not pdf_path.exists():
        if kind == "compare":
            creq = CompareRequest(**payload)

            results = [analyze_one_for_compare(a, creq) for a in creq.addresses]
            results_sorted = sorted(results, key=lambda r: int(r.get("score") or 0), reverse=True)

            effective_minutes = creq.minutes if creq.minutes is not None else (
                PROFILE_MINUTES.get(creq.profile) if creq.profile else 15
            )

            build_compare_pdf(
                path=pdf_path,
                compare_results=results_sorted,   # ✅ richtig
                minutes=effective_minutes,
                vertical=creq.vertical,
                plan=creq.plan,
                profile=creq.profile,
                multi_time=creq.multi_time,
            )
        else:
            req = LocationRequest(**payload)
            data = run_analysis(req)

            build_pdf(
                pdf_path,
                req.address,
                data["score"],
                data["explanation"],
                data["population"],
                data["competition"],
                data["minutes"],
                multi_results=data["multi_results"],
                confidence=data["confidence"],
                geocode_meta=data["geocode_meta"],
            )

        if not pdf_path.exists():
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {pdf_path}")

        update_report_meta(REPORTS_DIR, report_id, {"status": "delivered", "delivered_at_utc": utc_now_iso()})

    return FileResponse(str(pdf_path), filename=f"report_{report_id}.pdf")

# -----------------------------
# LEGACY (optional): direct analyze
# Keep for dev/testing. Make it admin-only.
# -----------------------------
@app.post("/analyze", response_class=FileResponse)
def analyze(req: LocationRequest, x_admin_token: str | None = Header(default=None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    req = enforce_plan(req)          # ✅ wichtig (Plan-Regeln auch hier)
    data = run_analysis(req)

    place = slugify(req.address)

    # ✅ minutes/profile sicher bestimmen
    mins = resolve_minutes(req)
    area = f"{mins}min"

    # Optional: Multi-Time im Dateinamen markieren
    if req.plan == "pro" and req.multi_time:
        area = "multitime-10-15-20"

    filename = f"Feasibility_{req.vertical}_{place}_{area}_{req.plan.capitalize()}.pdf"
    pdf_path = REPORTS_DIR / filename

    build_pdf(
        pdf_path,
        req.address,
        data["score"],
        data["explanation"],
        data["population"],
        data["competition"],
        data["minutes"],
        multi_results=data["multi_results"],
        confidence=data["confidence"],
        geocode_meta=data["geocode_meta"],
    )

    return FileResponse(str(pdf_path), filename=filename)

@app.post("/compare")
def compare(req: CompareRequest):
    # Multi-Time nur wenn Plan im Vertical erlaubt
    cfg = get_vertical_config(req.vertical)
    if req.plan not in cfg.allow_multi_time_plans:
        req.multi_time = False

    results = [analyze_one_for_compare(a, req) for a in req.addresses]
    results_sorted = sorted(results, key=lambda r: int(r.get("score") or 0), reverse=True)

    effective_minutes = req.minutes if req.minutes is not None else (PROFILE_MINUTES.get(req.profile) if req.profile else 15)

    return JSONResponse({
        "vertical": req.vertical,
        "minutes": effective_minutes,
        "profile": req.profile,
        "plan": req.plan,
        "results": results_sorted
    })