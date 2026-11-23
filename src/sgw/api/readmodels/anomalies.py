"""Read side of the A7/A8 water anomaly detectors for K3 `/api/anomalies`.

The detectors run offline on the Helene SCADA replay (`uv run sgw water anomaly`) and write their alarms to
`data/artefacts/water_twin/anomaly_dev.json` (`results.helene_dev.alarms`). This module serves the alarms
detected at or before the scenario time, newest first. `score_ppm` is the detector's own score of the alarm
(`sgw.models.anomaly.detect.exceedance`): how far its statistic went past the alarm threshold as a share of
the peak (CUSUM peak against h, pressure deficit below the low-pressure alarm, frozen run against its
length); a status change or an exact replayed sequence scores 1 000 000. With `SGW_ZONE_RULES` on, the
grid-side W9 alarm joins them: an AMI section dark without last gasps (`sgw.rules.zones`), scored 1 000 000.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from sgw.contracts.api_models import AnomalyItem, Provenance
from sgw.contracts.base import PPM_SCALE
from sgw.contracts.vocab import NumberLabel

REPO = Path(__file__).resolve().parents[4]
REPORT_FILE = REPO / "data" / "artefacts" / "water_twin" / "anomaly_dev.json"
REPORT_SOURCE = "data/artefacts/water_twin/anomaly_dev.json"
MODEL_ID = "anomaly.a7_a8"
RUN = "helene_dev"


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@cache
def report() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    return data


def anomaly_id(alarm: dict[str, Any]) -> str:
    stamp = _utc(alarm["detected_utc"]).strftime("%Y%m%dT%H%MZ")
    return f"ANM-{alarm['station']}-{alarm['family']}-{alarm['kind']}-{stamp}"


def dark_sections(at: datetime) -> list[AnomalyItem]:
    from sgw.models.clocks import zone_cases
    from sgw.rules import zones

    if not zone_cases.enabled():
        return []
    return [
        AnomalyItem(
            anomaly_id=f"ANM-{h.params['section_id']}-AMI-dark_section-{h.known_at:%Y%m%dT%H%MZ}",
            entity_id=str(h.params["section_id"]),
            detected_at=h.known_at,
            score_ppm=PPM_SCALE,
            anomaly_class="ami_dark_section",
            status="open",
        )
        for h in zones.timeline()
        if h.rule == "ami_dark_section" and h.known_at <= at
    ]


def anomalies(at: datetime) -> list[AnomalyItem]:
    alarms = [a for a in report()["results"][RUN]["alarms"] if _utc(a["detected_utc"]) <= at]
    alarms.sort(key=lambda a: (a["detected_utc"], anomaly_id(a)), reverse=True)
    items = [
        AnomalyItem(
            anomaly_id=anomaly_id(a),
            entity_id=str(a["devices"][0]),
            detected_at=_utc(a["detected_utc"]),
            score_ppm=round(float(a.get("score", 1.0)) * PPM_SCALE),
            anomaly_class=str(a["kind"]),
            status="open",
        )
        for a in alarms
    ]
    return sorted([*items, *dark_sections(at)], key=lambda i: (i.detected_at, i.anomaly_id), reverse=True)


def provenance(at: datetime) -> Provenance:
    return Provenance(source=REPORT_SOURCE, model_id=MODEL_ID, as_of=at, label=NumberLabel.S)
