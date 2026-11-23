"""Deterministic `link` step: typed references for the ids an answer names (K3 `Message.references`).

Runs after the answer is checked (or rendered by code on M2). A reference is made only for an id that the
answer text names and that belongs to this run: its evidence (entity ids of the tool results), the decision
catalog of the member table, the named Helene assets, the run's region (county) or a passage cited in this
run (clause). The model never writes a reference: it can only name ids, which the verifier already checks,
so no model text can invent a link. Labels are plain words made by code."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from sgw.agent.copilot.investigate import reader_time
from sgw.agent.copilot.tools import NETWORK_FILE, advisory_in_force
from sgw.agent.nodes import evidence_source as es
from sgw.agent.render.evidence import EvidenceItem

RefKind = Literal[
    "decision",
    "asset",
    "county",
    "zone",
    "advisory",
    "crew",
    "yard",
    "readiness",
    "clause",
    "photo",
    "surge",
    "gauge",
    "check",
]
DECISION_KINDS = frozenset({"decision", "decision_clock"})
ITEM_KINDS: Mapping[str, RefKind] = {
    "damage_photo": "photo",
    "damage_case": "photo",
    "readiness_check": "check",
    "outage_surge": "surge",
}

REPO = Path(__file__).resolve().parents[4]
COUNTIES_FILE = REPO / "data" / "reference" / "counties.geo.json"
ID_RE = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?![\w-])")
DOC_RE = re.compile(r"(?<![\w-])(?:GEP|DOM|TSO|WDS|WQC|MAL|PCN)\s\d[0-9A-Z]?\.\d{2,3}(?![\w.])")
ADVISORY_RE = re.compile(r"\b(?:the\s+)?latest\s+advisory\b", re.IGNORECASE)
ASSET_PREFIXES = ("PS-", "FDR-", "HSP-", "GEN-", "MGEN-", "FTK-", "TNK-", "SUB-", "PT-")
YARD_PREFIXES = ("STG-", "DEP-")


def _words(token: str) -> str:
    return " ".join(w.capitalize() for w in token.split())


@lru_cache(maxsize=1)
def _named() -> dict[str, Any]:
    named: dict[str, Any] = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))["named"]
    return named


@lru_cache(maxsize=1)
def feeder_name(feeder_id: str) -> str:
    """A feeder by its number (FDR-AIK-2219 -> "Feeder 2219"), so two feeders never read the same."""
    return f"Feeder {feeder_id.rsplit('-', 1)[-1]}"


def asset_labels() -> dict[str, tuple[RefKind, str]]:
    """Plain label and kind for every named Helene asset, zone, crew and yard."""
    n = _named()
    out: dict[str, tuple[RefKind, str]] = {}
    for ps, info in n["pump_stations"].items():
        place = _words(info["zone"].rsplit("-", 1)[-1])
        out[ps] = ("asset", f"{place} pump station")
        out[info["zone"]] = ("zone", f"{place} water zone")
        out[info["tank"]] = ("asset", f"{place} water tank")
        out[info["feeder"]] = ("asset", f"{feeder_name(info['feeder'])} (feeds {ps})")
        if info.get("onsite_generator"):
            out[info["onsite_generator"]] = ("asset", f"Onsite generator at {ps}")
    hosp = n["hospital"]
    name = _words(hosp["id"].rsplit("-", 1)[-1])
    out[hosp["id"]] = ("asset", f"{name} hospital")
    out[hosp["generator"]] = ("asset", f"{name} hospital generator")
    out[hosp["pressure_sensor"]] = ("asset", f"{name} hospital pressure sensor")
    out.setdefault(hosp["feeder"], ("asset", f"{feeder_name(hosp['feeder'])} (feeds {name} hospital)"))
    for feeder in n["feeders"]:
        out.setdefault(feeder, ("asset", feeder_name(feeder)))
    out[n["substation"]["id"]] = ("asset", f"{_words(n['substation']['id'].rsplit('-', 1)[-1])} substation")
    truck = n["fuel_truck"]
    out[truck["id"]] = ("asset", "Fuel truck")
    out[n["portable_generator"]["id"]] = ("asset", f"Portable generator, {n['portable_generator']['kw']} kW")
    out[truck["depot"]] = ("yard", f"{_words(truck['depot'].rsplit('-', 1)[-1])} depot")
    for yard in n["yards"]:
        out[yard] = ("yard", f"{_words(yard.split('-')[2])} staging yard")
    for crew, info in n["crews"].items():
        parts = crew.split("-")
        what = "mutual-aid crew" if info.get("mutual_aid") else "crew"
        out[crew] = ("crew", f"{_words(parts[-2])} {parts[-1]} {what}")
    return out


@lru_cache(maxsize=1)
def counties() -> dict[str, str]:
    data = json.loads(COUNTIES_FILE.read_text(encoding="utf-8"))
    return {f["properties"]["fips"]: f["properties"]["name"] for f in data["features"]}


def decision_titles(member_table: Mapping[str, Any], as_of: datetime) -> dict[str, str]:
    advisory, _ = advisory_in_force(member_table, as_of)
    queue, _ = es.clock_queue(member_table, advisory)
    from sgw.agent.copilot.plain import plain_title

    return {c.case.decision_case_id: plain_title(c.case.title) for c in es.ordered_cases(queue)}


def _kind(token: str) -> RefKind | None:
    if token.startswith("DC-"):
        return "decision"
    if token.startswith("WZ-"):
        return "zone"
    if token.startswith("CRW-"):
        return "crew"
    if token.startswith(YARD_PREFIXES):
        return "yard"
    if token.startswith(ASSET_PREFIXES):
        return "asset"
    return None


def evidence_refs(items: Iterable[EvidenceItem]) -> list[dict[str, str]]:
    """References the evidence itself offers (photos, damage cases, readiness checks, outage surges), with
    the words an answer uses for them (`match`): the id, or a surge's label (its id is `<fips>@<onset>`)."""
    out: list[dict[str, str]] = []
    for item in items:
        case = next((e for e in item.entity_ids if e.startswith("DC-")), None)
        if item.kind in DECISION_KINDS and case is not None:
            out.append({"kind": "decision", "id": case, "label": item.label.split(" (", 1)[0], "match": case})
            continue
        kind = ITEM_KINDS.get(item.kind)
        if kind is None or not item.entity_ids:
            continue
        if kind == "surge":
            onset = item.values.get("onset")
            fips = item.entity_ids[-1]
            at = (
                onset.value.isoformat().replace("+00:00", "Z")
                if onset and isinstance(onset.value, datetime)
                else ""
            )
            out.append({"kind": kind, "id": f"{fips}@{at}", "label": item.label, "match": item.label})
        else:
            ref = item.entity_ids[0]
            out.append({"kind": kind, "id": ref, "label": item.label, "match": ref})
    return out


def references(
    text: str,
    *,
    evidence_ids: Iterable[str],
    citations: Sequence[Mapping[str, Any]],
    member_table: Mapping[str, Any],
    as_of: datetime,
    region_ids: Iterable[str] = (),
    pool: Sequence[Mapping[str, str]] = (),
) -> list[dict[str, str]]:
    """References in order of first mention, one per id. `pool` holds the references the run's evidence
    offers (`evidence_refs`); one becomes a reference only when the answer names its words."""
    decisions = {
        **{r["id"]: r["label"] for r in pool if r["kind"] == "decision"},
        **decision_titles(member_table, as_of),
    }
    named = asset_labels()
    allowed = set(evidence_ids) | set(decisions) | set(named)
    pooled = {r["id"]: r["label"] for r in pool if r["kind"] == "decision"}
    found: list[tuple[int, dict[str, str]]] = []
    seen: set[tuple[str, str]] = set()

    def add(at: int, kind: RefKind, ref_id: str, label: str) -> None:
        if (kind, ref_id) in seen:
            return
        seen.add((kind, ref_id))
        found.append((at, {"kind": kind, "id": ref_id, "label": label}))

    for m in ID_RE.finditer(text):
        token = m.group(0)
        kind = _kind(token)
        if kind is None or token not in allowed:
            continue
        if kind == "decision":
            add(m.start(), kind, token, decisions.get(token) or pooled.get(token, token))
        else:
            named_kind, label = named.get(token, (kind, token))
            add(m.start(), named_kind, token, label)
    cited = {str(c.get("doc_id")): c for c in citations}
    for m in DOC_RE.finditer(text):
        doc = m.group(0)
        if doc in cited:
            add(m.start(), "clause", doc, str(cited[doc].get("title") or cited[doc].get("section") or doc))
    fips = {r.split("-", 1)[1] for r in region_ids if "-" in r}
    for code in sorted(fips):
        name = counties().get(code)
        hit = re.search(rf"\b{re.escape(name)}\b", text) if name else None
        if hit and name:
            add(hit.start(), "county", code, f"{name} County")
    for ref in pool:
        at = text.find(ref["match"]) if ref["match"] else -1
        if at >= 0:
            add(at, cast(RefKind, ref["kind"]), ref["id"], ref["label"])
    adv = ADVISORY_RE.search(text)
    if adv:
        _, issued = advisory_in_force(member_table, as_of)
        stamp = issued.isoformat().replace("+00:00", "Z")
        add(adv.start(), "advisory", stamp, f"Advisory of {reader_time(issued)}")
    return [ref for _, ref in sorted(found, key=lambda kv: kv[0])]
