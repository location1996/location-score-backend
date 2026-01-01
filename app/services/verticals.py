from dataclasses import dataclass
from typing import Dict, Literal

Vertical = Literal["ev_charging"]

@dataclass(frozen=True)
class VerticalConfig:
    key: str
    label: str
    pdf_title: str
    pdf_subtitle: str
    default_profile: str
    allow_multi_time_plans: set

VERTICALS: Dict[str, VerticalConfig] = {
    "ev_charging": VerticalConfig(
        key="ev_charging",
        label="EV Charging",
        pdf_title="Charging Location Check",
        pdf_subtitle="Standortbewertung für Ladeinfrastruktur (MVP)",
        default_profile="urban",
        allow_multi_time_plans={"pro"},
    )
}

def get_vertical_config(vertical: str) -> VerticalConfig:
    return VERTICALS.get(vertical, VERTICALS["ev_charging"])