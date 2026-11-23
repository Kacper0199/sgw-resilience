"""Rebuild `data/open/{usgs_nwis,iem_asos,iem_vtec,openfema,ncei_storm_events}/helene_*.json` from `raw/data/`
(dev-only; raw downloads are not committed).
Usage: `uv run python -I scripts/build_open_data.py [RAW] [OUT]`."""

import sys
from pathlib import Path

from sgw.opendata.build import OUT_ROOT, RAW_ROOT, build_all

if __name__ == "__main__":
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else RAW_ROOT
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_ROOT
    for name, size in build_all(raw, out).items():
        print(f"{size:>8} B  {name}")
