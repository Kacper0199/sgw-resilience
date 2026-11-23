"""Serving artefact of the ETR model: fitted components and conformal calibrators as one JSON file.

Written by `sgw restoration eval` from the train and calibration storms; read by `sgw restoration etr`, so
publishing an ETR never refits. The file name carries the model version; `data_hash` ties it to the inputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from sgw.models.restoration.aft import StratifiedAft
from sgw.models.restoration.conformal import Calibrator
from sgw.models.restoration.etr import MODEL_NAME, MODEL_VERSION, EtrModel
from sgw.models.restoration.params import PARAMS_PATH

ARTEFACT_PATH = Path(__file__).with_name("etr_model.json")


def _arr(a: np.ndarray) -> list[float]:
    return [round(float(x), 6) for x in np.asarray(a).ravel()]


def _counts(values: np.ndarray) -> list[list[float]]:
    v, n = np.unique(np.asarray(values, dtype=float), return_counts=True)
    return [[float(a), int(b)] for a, b in zip(v, n, strict=True)]


def model_to_dict(model: EtrModel) -> dict[str, Any]:
    return {
        "aft": {
            "strata": list(model.aft.strata),
            "mu": _arr(model.aft.mu),
            "sigma": _arr(model.aft.sigma),
            "storm_sigma": round(model.aft.storm_sigma, 6),
            "storm_effects": _arr(model.aft.storm_effects),
            "county_sigma": round(model.aft.county_sigma, 6),
            "sigma_total": _arr(model.aft.sigma if model.aft.sigma_total is None else model.aft.sigma_total),
        },
        "gust_edges": _arr(model.gust_edges),
        "ds_probs": [_arr(row) for row in model.ds_probs],
        "sec_rate": _arr(model.sec_rate),
        "sec_storm_sigma": round(model.sec_storm_sigma, 6),
        "sec_customers_counts": _counts(model.sec_customers),
        "sec_share": model.sec_share,
        "p_blocked": _arr(model.p_blocked),
        "access_mu": round(model.access_mu, 6),
        "access_sigma": round(model.access_sigma, 6),
        "travel_load": _arr(model.travel_load),
        "train_seeds": list(model.train_seeds),
    }


def model_from_dict(d: dict[str, Any]) -> EtrModel:
    a = d["aft"]
    return EtrModel(
        aft=StratifiedAft(
            tuple(a["strata"]),
            np.array(a["mu"]),
            np.array(a["sigma"]),
            float(a["storm_sigma"]),
            np.array(a["storm_effects"]),
            float(a["county_sigma"]),
            np.array(a["sigma_total"]),
        ),
        gust_edges=np.array(d["gust_edges"]),
        ds_probs=np.array(d["ds_probs"]),
        sec_rate=np.array(d["sec_rate"]),
        sec_storm_sigma=float(d["sec_storm_sigma"]),
        sec_customers=np.repeat(
            np.array([float(v) for v, _ in d["sec_customers_counts"]]),
            [int(n) for _, n in d["sec_customers_counts"]],
        ),
        sec_share=float(d["sec_share"]),
        p_blocked=np.array(d["p_blocked"]),
        access_mu=float(d["access_mu"]),
        access_sigma=float(d["access_sigma"]),
        travel_load=np.array(d["travel_load"]),
        train_seeds=tuple(int(s) for s in d["train_seeds"]),
    )


def data_hash() -> str:
    return hashlib.sha256(PARAMS_PATH.read_bytes()).hexdigest()


def save(
    model: EtrModel, calibrators: dict[tuple[str, float], Calibrator], path: Path = ARTEFACT_PATH
) -> Path:
    doc = {
        "model": MODEL_NAME,
        "version": MODEL_VERSION,
        "data_hash": data_hash(),
        "label": "C (fitted on family-A synthetic train storms; calibrated on family-A calibration storms)",
        "components": model_to_dict(model),
        "calibrators": [
            {
                "population": pop,
                "offset_h": off,
                "widen_80": round(c.widen_80, 6),
                "widen_50": round(c.widen_50, 6),
                "shift_50": round(c.shift_50, 6),
                "n": c.n,
            }
            for (pop, off), c in sorted(calibrators.items())
        ],
    }
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(path: Path = ARTEFACT_PATH) -> tuple[EtrModel, dict[tuple[str, float], Calibrator], dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    cals = {
        (c["population"], float(c["offset_h"])): Calibrator(
            c["widen_80"], c["widen_50"], c["shift_50"], c["n"]
        )
        for c in doc["calibrators"]
    }
    return model_from_dict(doc["components"]), cals, doc


def calibrator_for(
    cals: dict[tuple[str, float], Calibrator], population: str, hours_after_peak: float
) -> Calibrator:
    """The calibrator of the nearest issue offset at or below the given hours after the peak."""
    offs = sorted(off for pop, off in cals if pop == population)
    below = [o for o in offs if o <= hours_after_peak + 1e-9]
    return cals[(population, below[-1] if below else offs[0])]
