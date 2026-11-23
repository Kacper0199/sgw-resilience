"""The one registry of plain source names: what a person reads where a feed or source id would show.

Ids stay in tooltips and System health detail; every screen, sentence and provenance line uses these names.
An id not listed falls back to its words in sentence case, never to an empty string."""

from __future__ import annotations

import re

SOURCE_NAMES: dict[str, str] = {
    "ami-headend": "Smart meters",
    "asos": "Surface weather stations",
    "eaglei": "National outage counts",
    "eam": "Asset records",
    "fsm-crews": "Crew tracking",
    "gis-trace": "Network map",
    "lims": "Lab results",
    "nhc-advisory-synthetic": "Hurricane advisories",
    "nws-alerts": "Weather alerts",
    "oms": "Outage reports",
    "scada-electric": "Grid sensors",
    "scada-water": "Water system sensors",
    "sgw-platform": "SGW platform",
    "usgs": "River gauges",
}

_SPLIT = re.compile(r"[_.\-:\s]+")


def display_name(source_id: str) -> str:
    known = SOURCE_NAMES.get(source_id)
    if known is not None:
        return known
    words = [w for w in _SPLIT.split(source_id) if w]
    return " ".join(words).capitalize() if words else source_id
