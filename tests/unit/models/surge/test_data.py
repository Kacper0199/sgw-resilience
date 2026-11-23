from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd

from sgw.models.surge.labels import county_events, normalise_zone, to_utc
from sgw.models.surge.series import season_matrix

NCEI_COLUMNS = (
    "EPISODE_ID,EVENT_ID,STATE,STATE_FIPS,YEAR,EVENT_TYPE,CZ_TYPE,CZ_FIPS,CZ_NAME,"
    "BEGIN_DATE_TIME,END_DATE_TIME,CZ_TIMEZONE,MAGNITUDE,DAMAGE_PROPERTY"
)


def _row(
    episode: int,
    event: int,
    kind: str,
    cz_type: str,
    cz: int,
    name: str,
    begin: str,
    end: str,
    mag: str,
    dmg: str,
) -> str:
    head = f"{episode},{event},GEORGIA,13,2024,{kind},{cz_type},{cz},{name}"
    return f"{head},{begin}:00,{end}:00,EST-5,{mag},{dmg}"


def test_zone_names_map_to_county_keys() -> None:
    assert normalise_zone("COASTAL CHATHAM") == "CHATHAM"
    assert normalise_zone("INLAND BERKELEY") == "BERKELEY"
    assert normalise_zone("DE KALB") == "DEKALB"
    assert normalise_zone("Northern Colleton") == "COLLETON"
    assert normalise_zone("Jeff Davis") == "JEFFDAVIS"
    assert normalise_zone("OCONEE MOUNTAINS") == "OCONEE"
    assert normalise_zone("GREATER GREENVILLE") == "GREENVILLE"
    assert normalise_zone("SOUTHEASTERN ORANGEBURG") == "ORANGEBURG"
    assert normalise_zone("NORTH FULTON") == "FULTON"


def test_storm_event_times_convert_from_the_listed_standard_offset() -> None:
    t = to_utc(pd.Series(["27-SEP-24 02:30:00"]), pd.Series(["EST-5"]))
    assert t.iloc[0] == pd.Timestamp("2024-09-27 07:30:00", tz="UTC")


def test_county_events_group_episodes_and_match_zones(tmp_path: Path) -> None:
    rows = [
        _row(
            1,
            11,
            "Thunderstorm Wind",
            "C",
            51,
            "CHATHAM",
            "27-SEP-24 02:30",
            "27-SEP-24 02:30",
            "52",
            "1.00K",
        ),
        _row(
            1, 12, "Thunderstorm Wind", "C", 51, "CHATHAM", "27-SEP-24 04:00", "27-SEP-24 04:10", "60", "2.5K"
        ),
        _row(
            2,
            21,
            "Tropical Storm",
            "Z",
            117,
            "COASTAL CHATHAM",
            "26-SEP-24 20:00",
            "27-SEP-24 10:00",
            "",
            "1.2M",
        ),
        _row(
            3, 31, "Drought", "Z", 117, "COASTAL CHATHAM", "01-SEP-24 00:00", "30-SEP-24 23:59", "", "0.00K"
        ),
        _row(4, 41, "Hail", "C", 51, "CHATHAM", "28-SEP-24 00:00", "28-SEP-24 00:00", "1.0", "0.00K"),
        _row(
            5,
            51,
            "Tropical Storm",
            "Z",
            999,
            "MOUNTAINS OF NOWHERE",
            "26-SEP-24 20:00",
            "27-SEP-24 10:00",
            "",
            "",
        ),
    ]
    path = tmp_path / "StormEvents_details-ftp_v1.0_d2024_c1.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(NCEI_COLUMNS + "\n" + "\n".join(rows) + "\n")
    names = {"13051": ("Chatham", "GA")}
    events, unmatched = county_events([path], names)
    wind = events[events["label"]]
    assert sorted(wind["episode_id"]) == [1, 2]
    tstm = wind[wind["episode_id"] == 1].iloc[0]
    assert tstm["begin"] == pd.Timestamp("2024-09-27 07:30", tz="UTC")
    assert tstm["end"] == pd.Timestamp("2024-09-27 09:10", tz="UTC")
    assert tstm["n_reports"] == 2 and tstm["damage_usd"] == 3500.0
    assert wind[wind["episode_id"] == 2].iloc[0]["tier"] == "tropical"
    explain = events[~events["label"]]
    assert list(explain["episode_id"]) == [4]
    assert unmatched == {"MOUNTAINS OF NOWHERE": 1}


def test_season_matrix_marks_feed_gaps_and_zero_fills_county_rows(tmp_path: Path) -> None:
    lines = ["fips_code,county,state,sum,run_start_time"]
    for t in ("2023-05-01 00:00:00", "2023-05-01 00:15:00", "2023-05-01 00:45:00"):
        lines.append(f"13051,Chatham,Georgia,10,{t}")
    lines.append("45019,Charleston,South Carolina,7,2023-05-01 00:15:00")
    lines.append("45019,Charleston,South Carolina,3,2023-05-01 00:15:00")
    path = tmp_path / "e.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    times, x = season_matrix(
        path,
        ["13051", "45019"],
        pd.Timestamp("2023-05-01", tz="UTC"),
        pd.Timestamp("2023-05-01 01:00", tz="UTC"),
    )
    assert len(times) == 4
    expected = np.array([[10, 0], [10, 10], [np.nan, np.nan], [10, 0]], dtype=float)
    np.testing.assert_array_equal(x, expected)
