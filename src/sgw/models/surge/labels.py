"""NCEI Storm Events as county event labels for the outage-surge evaluation.

Source: NOAA NCEI Storm Events Database, yearly `StormEvents_details-ftp_v1.0_dYYYY_c*.csv.gz`
(https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/), US federal work, public domain.

Times are local standard time with the offset in `CZ_TIMEZONE` (`EST-5`); they are converted to UTC.
County events (`CZ_TYPE` C) carry the county FIPS; zone events (Z: tropical, high wind) carry a forecast zone
whose name in GA and SC is the county name, sometimes with a part prefix or suffix ("COASTAL CHATHAM",
"GREATER GREENVILLE", "OCONEE MOUNTAINS"), so the zone is
mapped to the county of that name in the state. Names that match no county are counted and reported.

Two event sets, grouped per county and NCEI episode (begin = first report, end = last report):
- label events (`label` True): wind-driven types that damage overhead lines (`LABEL_TYPES`); recall is
  measured on these;
- explaining events (`label` False): other weather that can cut power (`EXPLAIN_TYPES`); a surge that matches
  a label or an explaining event is not a false alarm.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

LABEL_TYPES = frozenset(
    {
        "Thunderstorm Wind",
        "Tornado",
        "Tropical Storm",
        "Hurricane (Typhoon)",
        "Hurricane",
        "Tropical Depression",
        "High Wind",
        "Strong Wind",
    }
)
EXPLAIN_TYPES = frozenset(
    {
        "Hail",
        "Lightning",
        "Flash Flood",
        "Flood",
        "Heavy Rain",
        "Coastal Flood",
        "Storm Surge/Tide",
        "Funnel Cloud",
        "Debris Flow",
        "Winter Weather",
        "Winter Storm",
        "Ice Storm",
        "Heavy Snow",
        "Wildfire",
        "Excessive Heat",
        "Heat",
    }
)
TROPICAL = frozenset({"Tropical Storm", "Hurricane (Typhoon)", "Hurricane", "Tropical Depression"})
STATES = {"GEORGIA": "GA", "SOUTH CAROLINA": "SC"}
STATE_FIPS = {"GA": "13", "SC": "45"}
ZONE_PREFIXES = (
    "GREATER",
    "NORTH",
    "SOUTH",
    "NORTHWESTERN",
    "NORTHEASTERN",
    "SOUTHWESTERN",
    "SOUTHEASTERN",
    "COASTAL",
    "INLAND",
    "TIDAL",
    "MAINLAND",
    "NORTHERN",
    "SOUTHERN",
    "EASTERN",
    "WESTERN",
    "CENTRAL",
    "NORTHWEST",
    "NORTHEAST",
    "SOUTHWEST",
    "SOUTHEAST",
    "UPPER",
    "LOWER",
)
ZONE_SUFFIXES = ("MOUNTAINS", "PIEDMONT")
_PREFIX = re.compile(r"^(?:(?:" + "|".join(ZONE_PREFIXES) + r")\s+)+")
_SUFFIX = re.compile(r"(?:\s+(?:" + "|".join(ZONE_SUFFIXES) + r"))+$")
_MULT = {"K": 1e3, "M": 1e6, "B": 1e9}
USECOLS = (
    "EPISODE_ID",
    "EVENT_ID",
    "STATE",
    "EVENT_TYPE",
    "CZ_TYPE",
    "CZ_FIPS",
    "CZ_NAME",
    "BEGIN_DATE_TIME",
    "END_DATE_TIME",
    "CZ_TIMEZONE",
    "MAGNITUDE",
    "DAMAGE_PROPERTY",
)


def normalise_zone(name: str) -> str:
    return re.sub(r"[^A-Z]", "", _SUFFIX.sub("", _PREFIX.sub("", name.strip().upper())))


def to_utc(local: pd.Series, zone: pd.Series) -> pd.Series:
    naive = pd.to_datetime(local, format="%d-%b-%y %H:%M:%S")
    offset_h = zone.str.extract(r"([+-]\d+)$")[0].astype(float)
    return (naive - pd.to_timedelta(offset_h, unit="h")).dt.tz_localize("UTC")


def damage_usd(text: pd.Series) -> pd.Series:
    s = text.fillna("").astype(str).str.strip().str.upper()
    num = pd.to_numeric(s.str.rstrip("KMB"), errors="coerce").fillna(0.0)
    mult = s.str[-1:].map(_MULT).fillna(1.0)
    return num * mult


def read_details(paths: Iterable[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(p, usecols=list(USECOLS), dtype={"CZ_FIPS": int}, low_memory=False) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["STATE"].isin(STATES) & df["EVENT_TYPE"].isin(LABEL_TYPES | EXPLAIN_TYPES)].copy()
    df["st"] = df["STATE"].map(STATES)
    df["begin"] = to_utc(df["BEGIN_DATE_TIME"], df["CZ_TIMEZONE"])
    df["end"] = to_utc(df["END_DATE_TIME"], df["CZ_TIMEZONE"])
    df["damage_usd"] = damage_usd(df["DAMAGE_PROPERTY"])
    return df


def county_events(
    paths: Iterable[Path], names: Mapping[str, tuple[str, str]]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """County event table and the zone names that matched no county (name -> report count)."""
    df = read_details(paths)
    by_name = {(st, normalise_zone(n)): f for f, (n, st) in names.items()}
    county = df["CZ_TYPE"] == "C"
    df["fips"] = None
    codes = df.loc[county, "CZ_FIPS"].map("{:03d}".format)
    df.loc[county, "fips"] = df.loc[county, "st"].map(STATE_FIPS) + codes
    zone = df.loc[~county]
    keys = zip(zone["st"], zone["CZ_NAME"].map(normalise_zone), strict=True)
    df.loc[~county, "fips"] = [by_name.get(key) for key in keys]
    unmatched = Counter(df.loc[~county & df["fips"].isna(), "CZ_NAME"])
    df = df.dropna(subset=["fips"])
    df["label"] = df["EVENT_TYPE"].isin(LABEL_TYPES)
    grouped = (
        df.groupby(["fips", "EPISODE_ID", "label"])
        .agg(
            begin=("begin", "min"),
            end=("end", "max"),
            event_types=("EVENT_TYPE", lambda s: "|".join(sorted(set(s)))),
            n_reports=("EVENT_ID", "size"),
            damage_usd=("damage_usd", "sum"),
            max_magnitude=("MAGNITUDE", "max"),
        )
        .reset_index()
        .rename(columns={"EPISODE_ID": "episode_id"})
    )
    grouped["tier"] = grouped["event_types"].map(_tier)
    grouped = grouped[grouped["fips"].isin(names)]
    return grouped.sort_values(["begin", "fips"]).reset_index(drop=True), dict(unmatched)


def _tier(types: str) -> str:
    parts = set(types.split("|"))
    if parts & TROPICAL:
        return "tropical"
    if "Tornado" in parts:
        return "tornado"
    if parts & {"High Wind", "Strong Wind"}:
        return "high_wind"
    if "Thunderstorm Wind" in parts:
        return "thunderstorm"
    return "other"
