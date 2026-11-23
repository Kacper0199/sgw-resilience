"""Field asset registry for untrusted text: the ids a field note, ticket or alert may refer to.

Membership is exact. Free text names assets loosely ("2216 S2", "Osprey-07", "PS 38"), so `resolve` maps a
reference to one registry id only when exactly one id fits; anything else stays an `unregistered_ref` and
is never promoted to an id. The Aiken detail area (SC-45003, prefix `AIK`) breaks ties, because the field
notes in this prototype come from Aiken crews and water operators."""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

from sgw.agent.render.verify import asset_registry

REPO_ROOT = Path(__file__).resolve().parents[4]
SECTIONS_FILE = REPO_ROOT / "data" / "fixtures" / "helene" / "sections.csv"
NETWORK_FILE = REPO_ROOT / "data" / "fixtures" / "helene" / "network.json"
HOME_AREA = "AIK"

_FEEDER_REF = re.compile(r"^(?:FDR[- ]?(?:[A-Z]{2,5}[- ])?)?(\d{4})(?:[- ]?S(\d{1,2}))?$", re.IGNORECASE)
_CREW_REF = re.compile(r"^(?:CRW[- ])?(?:MA[- ])?([A-Z]+)[- ]?(\d{2})$", re.IGNORECASE)
_STATION_REF = re.compile(r"^PS[- ]?(\d{2})$", re.IGNORECASE)


@lru_cache(maxsize=1)
def field_registry() -> frozenset[str]:
    ids = set(asset_registry())
    if SECTIONS_FILE.is_file():
        with SECTIONS_FILE.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                ids.update(v for v in (row["section_id"], row["feeder_id"], row["device_id"]) if v)
    return frozenset(ids)


@lru_cache(maxsize=1)
def named_assets_table() -> str:
    """Compact table of the named Aiken assets for the extractor's system prompt (stable, cacheable)."""
    named = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))["named"]
    lines = ["Pump stations (station, onsite generator, tank, zone, feeder):"]
    for ps, info in sorted(named["pump_stations"].items()):
        gen = info.get("onsite_generator") or "none"
        lines.append(
            f"- {ps}: generator {gen}; tank {info['tank']}; zone {info['zone']}; feeder {info['feeder']}"
        )
    hosp = named["hospital"]
    lines.append(f"Hospital: {hosp['id']} (generator {hosp['generator']}, feeder {hosp['feeder']})")
    detail = set(named["detail_yards"])
    crews = sorted(c for c, info in named["crews"].items() if info.get("yard") in detail)
    lines.append("Crews at the detail yards: " + ", ".join(crews))
    lines.append("Staging yards: " + ", ".join(sorted(named["detail_yards"])))
    lines.append(
        f"Fuel truck: {named['fuel_truck']['id']}; portable generator: {named['portable_generator']['id']}"
    )
    lines.append(
        "Feeders are FDR-<county>-<four digits>, sections FDR-<county>-<four digits>-S<n>; "
        "Aiken county is AIK."
    )
    return "\n".join(lines)


def _unique(candidates: list[str]) -> str | None:
    if len(candidates) == 1:
        return candidates[0]
    home = [c for c in candidates if f"-{HOME_AREA}-" in c]
    return home[0] if len(home) == 1 else None


def resolve(ref: str | None) -> str | None:
    """The one registry id `ref` names, or None. Exact ids pass; loose feeder, section, crew and station
    references resolve only when a single id (or a single id in the home area) fits."""
    if not ref:
        return None
    text = " ".join(ref.strip().split())
    reg = field_registry()
    if text.upper() in reg:
        return text.upper()
    m = _FEEDER_REF.match(text)
    if m:
        number, section = m.group(1), m.group(2)
        suffix = f"-{number}-S{int(section)}" if section else f"-{number}"
        return _unique(
            sorted(
                i
                for i in reg
                if i.startswith("FDR-") and i.endswith(suffix) and i.count("-") == suffix.count("-") + 1
            )
        )
    m = _STATION_REF.match(text)
    if m:
        cand = f"PS-{m.group(1)}"
        return cand if cand in reg else None
    m = _CREW_REF.match(text)
    if m:
        name, num = m.group(1).upper(), m.group(2)
        return _unique(sorted(i for i in reg if i.startswith("CRW-") and i.endswith(f"-{name}-{num}")))
    return None
