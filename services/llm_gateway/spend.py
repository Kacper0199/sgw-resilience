from __future__ import annotations

import csv
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

from .redact import scrub_text


@dataclass
class CallRow:
    ts: str
    mode: str
    purpose: str
    wave: str
    run_id: str
    node: str
    prompt_version: str
    model: str
    effort: str
    batch: bool
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int
    stop_reason: str
    latency_ms: int
    cost_usd: float
    request_hash: str
    billed: bool
    attempts: int
    status: int


COLUMNS = [f.name for f in fields(CallRow)]


class SpendLedger:
    def __init__(self, path: Path, *, secrets: tuple[str | None, ...] = ()) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._secrets = secrets

    def _scrub(self, value: str) -> str:
        value = scrub_text(value)
        for secret in self._secrets:
            if secret:
                value = value.replace(secret, "<redacted>")
        return value

    def rows(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        with self.path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def append(self, row: CallRow) -> None:
        values = {k: (self._scrub(v) if isinstance(v, str) else v) for k, v in asdict(row).items()}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.is_file() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
                if new:
                    writer.writeheader()
                writer.writerow(values)

    def total_usd(self, *, wave: str | None = None) -> float:
        return round(
            sum(
                float(r.get("cost_usd") or 0)
                for r in self.rows()
                if r.get("billed") == "True" and (wave is None or r.get("wave") == wave)
            ),
            6,
        )

    def day_usd(self, day: date) -> float:
        """Billed spend of one UTC calendar day (row `ts` is UTC ISO-8601)."""
        prefix = day.isoformat()
        return round(
            sum(
                float(r.get("cost_usd") or 0)
                for r in self.rows()
                if r.get("billed") == "True" and str(r.get("ts", "")).startswith(prefix)
            ),
            6,
        )

    def billed_calls(self, *, wave: str | None = None) -> int:
        return sum(
            1 for r in self.rows() if r.get("billed") == "True" and (wave is None or r.get("wave") == wave)
        )

    def live_calls(self, *, wave: str | None = None) -> int:
        return sum(1 for r in self.rows() if wave is None or r.get("wave") == wave)

    def summary(
        self, by: tuple[str, ...] = ("wave", "purpose", "node")
    ) -> dict[tuple[str, ...], dict[str, Any]]:
        agg: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "usd": 0.0, "input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
        )
        for r in self.rows():
            if r.get("billed") != "True":
                continue
            key = tuple(r.get(k, "") for k in by)
            a = agg[key]
            a["calls"] += 1
            a["usd"] = round(a["usd"] + float(r["cost_usd"]), 6)
            a["input"] += int(r["input_tokens"])
            a["cache_read"] += int(r["cache_read_input_tokens"])
            a["cache_write"] += int(r["cache_creation_input_tokens"])
            a["output"] += int(r["output_tokens"])
        return dict(agg)


SUMMARY_FIELDS = ("calls", "usd", "input", "cache_read", "cache_write", "output")


def format_summary(ledger: SpendLedger, by: tuple[str, ...]) -> list[str]:
    lines = [" | ".join([*by, *SUMMARY_FIELDS])]
    total_calls, total_usd = 0, 0.0
    for key, a in sorted(ledger.summary(by).items()):
        lines.append(" | ".join([*key, *(str(a[k]) for k in SUMMARY_FIELDS)]))
        total_calls += a["calls"]
        total_usd += a["usd"]
    lines.append(f"TOTAL | calls={total_calls} | usd={round(total_usd, 6)}")
    return lines


def main() -> None:
    import argparse

    from .config import Settings

    parser = argparse.ArgumentParser(description="Summarise the gateway spend ledger")
    parser.add_argument("--by", default="wave,purpose,node")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()
    ledger = SpendLedger(Path(args.csv) if args.csv else Settings.from_env().spend_csv)
    by = tuple(k.strip() for k in args.by.split(",") if k.strip())
    print("\n".join(format_summary(ledger, by)))


if __name__ == "__main__":
    main()
