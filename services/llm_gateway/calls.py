"""K1 `llm_call` rows: one per gateway decision (live or record call, replay hit or miss, denial).

The CSV ledger stays the budget's source of truth (it works with the database down); these rows are the
queryable record for Health, `sgw llm-spend` and the after-action view. `PostgresSink` writes from a
background thread through a least-privilege DSN (`SGW_LLM_CALL_DSN`, role with INSERT on `llm_call` only),
so a slow or absent database never delays or fails a model call; what it could not write is counted.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

log = logging.getLogger("sgw.llm_gateway.calls")

DB_PURPOSES = frozenset({"spike", "dev", "eval", "redteam", "record", "demo", "test"})
DB_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
DB_CLASSES = frozenset({"C0", "C1", "C2", "C3", "C3-N", "C4", "CX"})
COLUMNS = (
    "call_id",
    "ts",
    "mode",
    "billed",
    "purpose",
    "wave",
    "run_id",
    "node",
    "prompt_version",
    "model",
    "effort",
    "batch",
    "route",
    "classes",
    "decision",
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
    "stop_reason",
    "latency_ms",
    "cost_usd_micros",
    "request_hash",
    "payload_hash",
)
_COLS = ", ".join(COLUMNS)
_PARAMS = ", ".join(["%s"] * len(COLUMNS))
INSERT_SQL = f"INSERT INTO llm_call ({_COLS}) VALUES ({_PARAMS})"  # noqa: S608


def new_call_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class LlmCallRecord:
    call_id: str
    ts: str
    mode: str
    billed: bool
    purpose: str
    wave: str
    run_id: str
    node: str
    prompt_version: str
    model: str
    effort: str
    route: str
    classes: tuple[str, ...]
    decision: str
    request_hash: str
    payload_hash: str
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    batch: bool = False

    def db_values(self) -> tuple[Any, ...]:
        row = asdict(self)
        row["cost_usd_micros"] = round(self.cost_usd * 1_000_000)
        row["effort"] = self.effort if self.effort in DB_EFFORTS else None
        row["classes"] = sorted({c if c in DB_CLASSES else "CX" for c in self.classes})
        for key in ("wave", "run_id", "prompt_version", "stop_reason", "route", "payload_hash"):
            row[key] = row[key] or None
        return tuple(row[c] for c in COLUMNS)


class CallSink(Protocol):
    kind: str

    def submit(self, record: LlmCallRecord) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...

    def close(self, timeout_s: float = 5.0) -> None: ...


class NullSink:
    kind = "none"

    def submit(self, record: LlmCallRecord) -> None:
        return None

    def snapshot(self) -> dict[str, Any]:
        return {"kind": self.kind}

    def close(self, timeout_s: float = 5.0) -> None:
        return None


@dataclass
class MemorySink:
    kind: str = "memory"
    records: list[LlmCallRecord] = field(default_factory=list)

    def submit(self, record: LlmCallRecord) -> None:
        self.records.append(record)

    def snapshot(self) -> dict[str, Any]:
        return {"kind": self.kind, "written": len(self.records)}

    def close(self, timeout_s: float = 5.0) -> None:
        return None


class PostgresSink:
    """Bounded queue drained by one daemon thread; reconnects with backoff, never raises into callers."""

    kind = "postgres"

    def __init__(self, dsn: str, *, max_queue: int = 10_000, retry_s: float = 2.0) -> None:
        self._dsn = dsn
        self._queue: queue.Queue[LlmCallRecord | None] = queue.Queue(maxsize=max_queue)
        self._retry_s = retry_s
        self._lock = threading.Lock()
        self.counters = {
            "written": 0,
            "dropped_full": 0,
            "skipped_unknown_purpose": 0,
            "errors": 0,
            "rejected": 0,
            "duplicates": 0,
            "dropped_on_close": 0,
        }
        self._stop = threading.Event()
        self.last_error: str | None = None
        self._thread = threading.Thread(target=self._run, name="llm-call-sink", daemon=True)
        self._thread.start()

    def _count(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counters[key] += n

    def submit(self, record: LlmCallRecord) -> None:
        if record.purpose not in DB_PURPOSES:
            self._count("skipped_unknown_purpose")
            return
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._count("dropped_full")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self.counters)
        return {"kind": self.kind, "queued": self._queue.qsize(), **counters, "last_error": self.last_error}

    def flush(self, timeout_s: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

    def close(self, timeout_s: float = 5.0) -> None:
        self.flush(timeout_s)
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return
        self._thread.join(timeout_s)

    def _run(self) -> None:
        import psycopg
        import psycopg.errors

        conn: psycopg.Connection[Any] | None = None
        pending: LlmCallRecord | None = None
        while True:
            if pending is not None and self._stop.is_set():
                self._count("dropped_on_close", 1 + self._queue.qsize())
                break
            record = pending if pending is not None else self._queue.get()
            if record is None:
                self._queue.task_done()
                break
            try:
                if conn is None or conn.closed:
                    conn = psycopg.connect(self._dsn, autocommit=True, connect_timeout=5)
                conn.execute(INSERT_SQL, record.db_values())
                self._count("written")
                self.last_error = None
                pending = None
                self._queue.task_done()
            except psycopg.errors.UniqueViolation:
                self._count("duplicates")
                pending = None
                self._queue.task_done()
            except (psycopg.OperationalError, psycopg.InterfaceError, OSError) as exc:
                self._count("errors")
                self.last_error = type(exc).__name__
                log.warning('{"event": "llm_call_sink_error", "error": "%s"}', type(exc).__name__)
                if conn is not None:
                    with contextlib.suppress(Exception):
                        conn.close()
                conn = None
                pending = record
                self._stop.wait(self._retry_s)
            except Exception as exc:  # noqa: BLE001
                self._count("rejected")
                self.last_error = type(exc).__name__
                log.warning('{"event": "llm_call_row_rejected", "error": "%s"}', type(exc).__name__)
                pending = None
                self._queue.task_done()
        if conn is not None:
            conn.close()


def make_sink(dsn: str | None) -> CallSink:
    return PostgresSink(dsn) if dsn else NullSink()
