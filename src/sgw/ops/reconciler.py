"""Background reconciler: every few seconds read the `FAULT_*` flags and the configured probes and apply them
to the degraded mode (`ControlService.reconcile`). It runs inside the API process (router lifespan) and from
`python -m sgw.ops.cli watch`.

It starts only when something can raise a signal (a `FAULT_*` flag, a probe URL, `SGW_OPS_FEED_PROBE=1` or
an explicit `SGW_OPS_RECONCILE_S`), so a test database never changes mode on its own.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import psycopg

from sgw.ops.control import ControlService, ReconcileReport
from sgw.ops.errors import OpsUnavailable
from sgw.ops.levels import SIGNAL_RULES
from sgw.ops.probes import configured_probes, read_all

log = logging.getLogger("sgw.ops.reconciler")
INTERVAL_ENV = "SGW_OPS_RECONCILE_S"
FEED_PROBE_ENV = "SGW_OPS_FEED_PROBE"
DEFAULT_INTERVAL_S = 5.0


def enabled(env: Mapping[str, str]) -> bool:
    if env.get(INTERVAL_ENV) or env.get(FEED_PROBE_ENV) == "1":
        return True
    if configured_probes(env):
        return True
    return any(rule.fault_flag in env for rule in SIGNAL_RULES)


def interval_s(env: Mapping[str, str]) -> float:
    try:
        return max(0.5, float(env.get(INTERVAL_ENV, DEFAULT_INTERVAL_S)))
    except ValueError:
        return DEFAULT_INTERVAL_S


def reconcile_once(conn: psycopg.Connection[Any], service: ControlService) -> ReconcileReport:
    return service.reconcile(conn, read_all(configured_probes(service.env)))


@dataclass
class Reconciler:
    dsn: str
    service_factory: Callable[[], ControlService]
    every_s: float = DEFAULT_INTERVAL_S
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    last: ReconcileReport | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sgw-ops-reconciler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        service = self.service_factory()
        while not self._stop.is_set():
            try:
                with psycopg.connect(self.dsn, autocommit=True, connect_timeout=5) as conn:
                    while not self._stop.is_set():
                        self.last = reconcile_once(conn, service)
                        if self.last.changed:
                            log.info(
                                "degraded mode %s -> %s (active: %s)",
                                self.last.before.value,
                                self.last.after.value,
                                ", ".join(self.last.active) or "none",
                            )
                        self._stop.wait(self.every_s)
            except (OpsUnavailable, psycopg.OperationalError) as error:
                log.info("ops reconcile: database connection lost (%s); reconnecting", type(error).__name__)
                self._stop.wait(self.every_s)
            except Exception:
                log.warning("ops reconcile failed; retrying", exc_info=True)
                self._stop.wait(self.every_s)
