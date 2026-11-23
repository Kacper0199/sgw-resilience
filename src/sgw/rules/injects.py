"""Exercise injects: the scripted decisions of `data/synthetic/helene_injects.yaml`, a master
scenario events list (HSEEP MSEL style) that gives every moment of the Helene replay a realistic decision load
next to the PS-17 story. Each inject becomes a `ZoneHit` with its own decision case clock (anchor plus terms,
minus the lead time, through the clock service like the zone rules), raised by `system:rule:exercise_inject`
while the scenario time is inside its window. Everything here is synthetic: invented facilities and resources,
scripted times and quantities; the zone rules and the story's seeded cases are not read or changed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.contracts.vocab import ActionType, ClockKind, DecisionStep, Domain
from sgw.models.clocks.waterfall import AddOnTerm
from sgw.rules.zones import CaseClock, ZoneHit, basis, iso, utc

REPO = Path(__file__).resolve().parents[3]
INJECTS_PATH = REPO / "data" / "synthetic" / "helene_injects.yaml"
RULE_KEY_PREFIX = "inject."
PARAM_TYPES = (int, str, bool)


@dataclass(frozen=True)
class InjectAsset:
    asset_id: str
    kind: str
    domain: Domain
    region_id: str
    name: str
    lat: float
    lon: float
    critical: bool
    customers: int
    in_hazard_zone: bool
    mobile: bool


@dataclass(frozen=True)
class Injects:
    version: str
    proposer: str
    incident_id: str
    label: str
    assets: tuple[InjectAsset, ...]
    hits: tuple[ZoneHit, ...]
    regions: Mapping[str, str]


def _param(value: Any, where: str) -> int | str | bool | list[str]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    if isinstance(value, PARAM_TYPES):
        return value
    raise ValueError(f"{where}: parameters are whole numbers, text, yes/no or lists of text, not {value!r}")


def _asset(raw: Mapping[str, Any]) -> InjectAsset:
    return InjectAsset(
        asset_id=str(raw["id"]),
        kind=str(raw["kind"]),
        domain=Domain(str(raw["domain"])),
        region_id=str(raw["region"]),
        name=str(raw["name"]),
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        critical=bool(raw.get("critical", False)),
        customers=int(raw.get("customers", 0)),
        in_hazard_zone=bool(raw.get("in_hazard_zone", True)),
        mobile=bool(raw.get("mobile", False)),
    )


def _hit(raw: Mapping[str, Any], proposer: str, label: str) -> ZoneHit:
    inject_id = str(raw["id"])
    step = DecisionStep(str(raw["step"]))
    known_at = utc(str(raw["known_at"]))
    resolved_at = utc(str(raw["resolved_at"]))
    anchor = utc(str(raw["anchor_utc"]))
    if not known_at < resolved_at:
        raise ValueError(f"{inject_id}: known_at must be before resolved_at")
    if not known_at < anchor:
        raise ValueError(f"{inject_id}: the consequence must come after the inject is known")
    citation = "Scripted exercise data (synthetic)"
    consequence = basis(f"inject.{inject_id.lower()}", citation, ClockKind.MODEL_ESTIMATE)
    params = {k: _param(v, f"{inject_id}.{k}") for k, v in dict(raw.get("params") or {}).items()}
    return ZoneHit(
        key=RULE_KEY_PREFIX + inject_id,
        rule="exercise_inject",
        proposer=proposer,
        case_id=f"DC-{step.value}-{inject_id}",
        action_type=ActionType(str(raw["action_type"])),
        known_at=known_at,
        resolved_at=resolved_at,
        target_ids=tuple(str(t) for t in raw["targets"]),
        params={
            "rule_id": "rule." + proposer.removeprefix("system:rule:"),
            "known_at_utc": iso(known_at),
            "inject_id": inject_id,
            "data_label": label,
            **params,
        },
        rationale=str(raw["rationale"]),
        clock=CaseClock(
            step=step,
            title=str(raw["title"]),
            domain=Domain(str(raw["domain"])),
            consequence_basis=consequence,
            anchor_label=str(raw["anchor_label"]),
            anchor_basis=consequence,
            anchor_utc=anchor,
            terms=tuple(
                AddOnTerm(str(t["label"]), consequence, float(t["minutes"])) for t in raw.get("terms") or ()
            ),
            lead_key=str(raw["lead_key"]),
            if_late=str(raw["if_late"]),
        ),
        evidence=(f"inject:{inject_id}",),
    )


def parse(raw: Mapping[str, Any]) -> Injects:
    proposer = str(raw["proposer"])
    label = str(raw["label"])
    assets = tuple(_asset(a) for a in raw["assets"])
    hits = tuple(_hit(i, proposer, label) for i in raw["injects"])
    regions = {f"DC-{i['step']}-{i['id']}": str(i["region"]) for i in raw["injects"]}
    ids = [h.key for h in hits]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate inject ids")
    asset_ids = [a.asset_id for a in assets]
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("duplicate inject asset ids")
    return Injects(
        version=str(raw["version"]),
        proposer=proposer,
        incident_id=str(raw["incident_id"]),
        label=label,
        assets=assets,
        hits=tuple(sorted(hits, key=lambda h: (h.known_at, h.key))),
        regions=regions,
    )


@cache
def load(path: Path = INJECTS_PATH) -> Injects:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))


def active(now: datetime, hits: Sequence[ZoneHit] | None = None) -> list[ZoneHit]:
    return [h for h in (load().hits if hits is None else hits) if h.active(now)]
