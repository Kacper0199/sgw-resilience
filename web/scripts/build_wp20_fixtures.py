"""Exports the Helene replay outputs the Map and Forecast screens read on MSW.

Everything comes from the repository's own code and fixtures: the A2 county fans and plan diff, the
A1 official tracks and peak gusts, the precomputed what-if grid, the K17 LOSO reports and the named
network. Run from the repository root: `uv run --frozen python web/scripts/build_wp20_fixtures.py`.
"""

import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path

import yaml

from sgw.models.outage.forecast import advisory_risk
from sgw.models.outage.plan_diff import plan_diff
from sgw.reference.load import placed_assets

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web/src/features"
FIXTURES = ROOT / "data/fixtures/helene"
SEVERITY = {
    "very_high": "critical",
    "high": "severe",
    "moderate": "elevated",
    "low": "advisory",
    "very_low": "normal",
}
QUANTILES = ("q0025", "q0100", "q0250", "q0500", "q0750", "q0900", "q0975")


def advisories() -> list[dict]:
    return json.loads((FIXTURES / "ensemble.json").read_text())["advisories"]


def county_points() -> list[str]:
    points = json.loads((FIXTURES / "ensemble.json").read_text())["points"]
    return [i for i, k in zip(points["ids"], points["kinds"], strict=True) if k == "county"]


def analysis_track(issued: str) -> list[list[float | str]]:
    helene = yaml.safe_load((ROOT / "data/synthetic/helene.yaml").read_text())
    return [[row[0], row[1], row[2], row[3]] for row in helene["storm"]["track"] if row[0] <= issued]


def family_cone() -> dict[str, list[float]]:
    family = yaml.safe_load((ROOT / "data/synthetic/family_a.yaml").read_text())
    params = family["params"]
    return {
        "lead_h": params["forecast.cone_lead_h"]["value"],
        "radius_nmi": params["forecast.cone_radius_nmi"]["value"],
    }


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(path.relative_to(ROOT), path.stat().st_size, "bytes")


def build_forecast() -> None:
    ensemble = {a["advisory_label"]: a for a in advisories()}
    labels = list(ensemble)
    ids = county_points()
    truth = json.loads((FIXTURES / "truth_table.json").read_text())
    titles = {cid: case["title"] for cid, case in truth["clocks_by_advisory"]["N+1"]["cases"].items()}
    risks = {label: advisory_risk("helene", label) for label in labels}
    hazard, risk_out, fans = [], {}, {}
    for label in labels:
        r = risks[label]
        adv = ensemble[label]
        gust = dict(zip(ids, adv["official"]["peak_gust_ms"][: len(ids)], strict=True))
        hazard.append(
            {
                "advisory_label": label,
                "issued_utc": r.issued_utc,
                "next_advisory_utc": r.next_advisory_utc,
                "analysis_track": analysis_track(r.issued_utc),
                "official_track": adv["official"]["track"],
                "county_peak_gust_ms": gust,
            }
        )
        risk_out[label] = {
            "as_of": r.issued_utc,
            "snapshot_id": f"risk-helene-{label}-{r.model_name}",
            "items": [
                {
                    "entity_id": c["fips"],
                    "level": "county",
                    "p_ppm": int(c["p_ppm"]),
                    "band": c["band"],
                    "severity": SEVERITY[c["band"]],
                    "expected_impact": int(c["mean_out"]),
                    "drivers": [d["feature"] for d in c["drivers"]],
                }
                for c in r.counties.to_dict("records")
            ],
        }
        fans[label] = {
            "advisory_label": label,
            "issued_utc": r.issued_utc,
            "next_advisory_utc": r.next_advisory_utc,
            "model_version": r.model_name,
            "members": r.meta["members"],
            "trained_on": r.meta["trained_on"],
            "counties": [
                {
                    "fips": c["fips"],
                    "name": c["name"],
                    "customers": int(c["customers"]),
                    **{q: int(c[f"{q}_out"]) for q in QUANTILES},
                    "mean": int(c["mean_out"]),
                }
                for c in r.counties.to_dict("records")
            ],
            "actions": [
                {
                    "action_id": a.action_id,
                    "label": titles.get(a.decision_case_ids[0], a.action_id),
                    "decision_case_ids": list(a.decision_case_ids),
                    "share_ppm": a.share_ppm,
                    "members_needed": a.members_needed,
                    "members": a.members,
                }
                for a in r.actions
            ],
        }
    diffs = {}
    for before, after in zip(labels, labels[1:], strict=False):
        d = plan_diff(risks[before], risks[after])
        for action in d["actions"]:
            action["label"] = titles.get(action["decision_case_ids"][0], action["action_id"])
        diffs[after] = d
    write(WEB / "map/mock/hazard.gen.json", {"cone": family_cone(), "advisories": hazard})
    write(WEB / "map/mock/risk.gen.json", risk_out)
    write(WEB / "forecast/mock/forecast.gen.json", {"advisories": fans, "plan_diffs": diffs})


def build_whatif() -> None:
    grid = json.loads((ROOT / "src/sgw/models/whatif/helene_grid.json").read_text())
    baseline = grid["baseline"]

    def cell(**change: float) -> dict:
        want = {**baseline, **change}
        found = [c for c in grid["cells"] if c["levers"] == want]
        assert len(found) == 1, want
        return found[0]

    scenarios = [
        ("track_east", "Storm track 40 km further east", cell(track_shift_km=40.0)),
        ("wind_up", "Winds 10% stronger", cell(gust_scale=1.1)),
        ("aid_late", "Mutual-aid request 12 h later", cell(mutual_aid_request_shift_h=12.0)),
    ]
    write(
        WEB / "forecast/mock/whatif.gen.json",
        {
            "scenario": grid["scenario"],
            "label": grid["label"],
            "metric_notes": grid["metric_notes"],
            "baseline": cell(),
            "scenarios": [{"id": i, "title": t, **c} for i, t, c in scenarios],
        },
    )


def build_assets() -> None:
    customers: dict[str, int] = defaultdict(int)
    with (FIXTURES / "sections.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            customers[row["feeder_id"]] += int(row["customers"])
    points = json.loads((FIXTURES / "ensemble.json").read_text())["points"]
    footprint = list(csv.DictReader((ROOT / "data/synthetic/footprint_counties.csv").open(encoding="utf-8")))
    by_fips = {r["fips"]: r for r in footprint}

    def region(fips: str) -> str:
        return f"{by_fips[fips]['st']}-{fips}"

    def county_of(lon: float, lat: float) -> str:
        nearest = min(footprint, key=lambda r: (float(r["lon"]) - lon) ** 2 + (float(r["lat"]) - lat) ** 2)
        return nearest["fips"]

    def asset(asset_id, name, domain, kind, fips, lat, lon, critical, served=0):
        return {
            "asset_id": asset_id,
            "name": name,
            "domain": domain,
            "kind": kind,
            "region_id": region(fips),
            "lon_e6": round(lon * 1e6),
            "lat_e6": round(lat * 1e6),
            "criticality": None,
            "critical_facility": critical,
            "customers_served": served,
            "classification": "C1",
        }

    assets = []
    placed_ids = set()
    for a in placed_assets():
        placed_ids.add(a.asset_id)
        assets.append(
            asset(
                a.asset_id,
                a.name,
                a.domain,
                a.kind,
                a.fips or county_of(a.lon, a.lat),
                a.lat,
                a.lon,
                a.critical_facility or a.asset_id == "PS-17",
                customers.get(a.asset_id, 0),
            )
        )
    for feeder, kind, lat, lon in zip(
        points["ids"], points["kinds"], points["lat"], points["lon"], strict=True
    ):
        if kind == "feeder" and feeder not in placed_ids:
            assets.append(
                asset(
                    feeder,
                    f"Feeder {feeder} (synthetic)",
                    "electric",
                    "feeder",
                    "45003",
                    lat,
                    lon,
                    False,
                    customers[feeder],
                )
            )
    regions = [
        {
            "region_id": region(r["fips"]),
            "state": r["st"],
            "county_fips": r["fips"],
            "name": f"{r['name']} County",
        }
        for r in footprint
    ]
    write(WEB / "map/mock/assets.gen.json", {"assets": assets, "regions": regions})


def copy_reports() -> None:
    target = WEB / "forecast/mock"
    shutil.copyfile(ROOT / "evals/reports/outage_loso.json", target / "outage_loso.json")


if __name__ == "__main__":
    build_forecast()
    build_whatif()
    build_assets()
    copy_reports()
