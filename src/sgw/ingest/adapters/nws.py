"""K6 live adapter for NWS active alerts (`GET https://api.weather.gov/alerts/active?area=SC,GA`).

CAP properties map onto the K2 `WeatherAlert`; `Update`/`Cancel` messages point `supersedes` at the
referenced alert. Tests inject an `httpx.MockTransport` that serves recorded payloads, so they never touch
the network. The cursor carries the newest `sent` time and the ids seen at that instant.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from sgw.contracts.adapter import AdapterHealth, Coverage, FaultKind, FetchResult, Record
from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.contracts.vocab import Classification, FeedMode, RunMode, Trust, UiSeverity
from sgw.ingest.faults import FaultSpec, Reject, apply_faults

BASE_URL = "https://api.weather.gov"
SOURCE_ID = "nws-alerts"
DEFAULT_AREAS = ("SC", "GA")
DEFAULT_USER_AGENT = "sgw-resilience-platform/ingest"
TIMEOUT_S = 10.0
NWS_NAMESPACE = uuid.UUID("6c1f7f3e-55a4-5bd0-9b52-3d6d0b8e2a71")
CURSOR_PREFIX = "n1:"
SEVERITY = {
    "Extreme": UiSeverity.CRITICAL,
    "Severe": UiSeverity.SEVERE,
    "Moderate": UiSeverity.ELEVATED,
    "Minor": UiSeverity.ADVISORY,
}
STATE_BY_FIPS = {"12": "FL", "13": "GA", "37": "NC", "45": "SC", "47": "TN", "51": "VA"}
PRODUCTS = ("warning", "watch", "advisory", "statement")


class AdapterFetchError(RuntimeError):
    pass


def alert_event_id(nws_id: str) -> uuid.UUID:
    return uuid.uuid5(NWS_NAMESPACE, nws_id)


class MappingError(ValueError):
    pass


def _ts(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise MappingError(f"timestamp is {type(value).__name__}, not a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MappingError(f"timestamp {value[:40]!r} is not ISO 8601") from None
    if parsed.tzinfo is None:
        raise MappingError(f"timestamp {value[:40]!r} has no zone")
    return parsed.astimezone(UTC)


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _references(props: dict[str, Any]) -> str | None:
    refs = props.get("references")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("identifier"), str) and ref["identifier"]:
            return str(ref["identifier"])
    return None


def _product(event_name: str) -> str:
    lowered = event_name.lower()
    for product in PRODUCTS:
        if lowered.endswith(product):
            return product
    return "statement"


def _fips(properties: dict[str, Any]) -> list[str]:
    geocode = properties.get("geocode")
    same = geocode.get("SAME") if isinstance(geocode, dict) else None
    if not isinstance(same, list):
        return []
    return sorted({code[-5:] for code in same if isinstance(code, str) and len(code) >= 5 and code.isdigit()})


def _region(fips: list[str]) -> str | None:
    for code in fips:
        state = STATE_BY_FIPS.get(code[:2])
        if state:
            return f"{state}-{code}"
    return None


def encode_cursor(sent: datetime, ids: list[str]) -> str:
    raw = json.dumps({"sent": sent.isoformat(), "ids": sorted(ids)}, separators=(",", ":"))
    return CURSOR_PREFIX + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime | None, frozenset[str]]:
    if not cursor:
        return None, frozenset()
    if not cursor.startswith(CURSOR_PREFIX):
        raise ValueError(f"not an NWS cursor: {cursor!r}")
    body = cursor[len(CURSOR_PREFIX) :]
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    return _ts(data["sent"]), frozenset(data["ids"])


class NwsAlertsAdapter:
    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        areas: tuple[str, ...] = DEFAULT_AREAS,
        feed_mode: FeedMode = FeedMode.LIVE,
        run_mode: RunMode = RunMode.LIVE,
        clock: Callable[[], datetime] | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.feed_mode = feed_mode
        self.run_mode = run_mode
        self.areas = areas
        self._clock = clock or (lambda: datetime.now(UTC))
        agent = user_agent or os.environ.get("SGW_NWS_USER_AGENT", DEFAULT_USER_AGENT)
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S)
        self._headers = {"User-Agent": agent, "Accept": "application/geo+json"}
        self._faults: list[FaultSpec] = []
        self._rejects: list[Reject] = []
        self._rejects_reported = 0
        self._attempts = 0
        self._errors = 0
        self._last_success: datetime | None = None
        self._last_sent: datetime | None = None
        self._last_lag: int | None = None

    @property
    def rejects(self) -> list[Reject]:
        return list(self._rejects)

    def drain_rejects(self) -> list[Reject]:
        fresh = self._rejects[self._rejects_reported :]
        self._rejects_reported = len(self._rejects)
        return list(fresh)

    def _get(self) -> dict[str, Any]:
        self._attempts += 1
        try:
            response = self._client.get(
                "/alerts/active", params={"area": ",".join(self.areas)}, headers=self._headers
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            self._errors += 1
            raise AdapterFetchError(f"NWS alerts fetch failed: {type(error).__name__}: {error}") from error
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            self._errors += 1
            raise AdapterFetchError("NWS alerts payload has no features list")
        return data

    def _to_event(self, feature: object, now: datetime) -> EnvelopeBase:
        if not isinstance(feature, dict):
            raise MappingError(f"feature is {type(feature).__name__}, not an object")
        props = feature.get("properties")
        if not isinstance(props, dict):
            raise MappingError("feature has no properties object")
        nws_id = _text(props.get("id")) or _text(feature.get("id"))
        if not nws_id or len(nws_id) > 128:
            raise MappingError("alert id missing or longer than 128 characters")
        sent = _ts(props.get("sent"))
        effective = _ts(props.get("effective")) or sent
        expires = _ts(props.get("ends")) or _ts(props.get("expires"))
        if not nws_id or sent is None or effective is None or expires is None:
            raise MappingError("alert lacks sent, effective or expires")
        fips = _fips(props)
        reference = _references(props)
        supersedes = alert_event_id(reference) if reference else None
        event_name = _text(props.get("event"), "unknown") or "unknown"
        model = EVENT_MODELS["WeatherAlert"]
        return model.model_validate(
            {
                "type": "WeatherAlert",
                "event_id": alert_event_id(nws_id),
                "source_id": self.source_id,
                "feed_mode": self.feed_mode,
                "run_mode": self.run_mode,
                "event_time": sent,
                "issued_at": sent,
                "valid_at": effective,
                "received_at": now,
                "known_at": max(now, sent),
                "scenario_known_at": max(now, sent),
                "dedup_key": f"nws:{nws_id}"[:256],
                "classification": Classification.C0,
                "trust": Trust.EXTERNAL,
                "supersedes": supersedes,
                "region_id": _region(fips),
                "payload": {
                    "alert_id": nws_id,
                    "product": _product(event_name),
                    "event_name": event_name,
                    "severity": SEVERITY.get(_text(props.get("severity")), UiSeverity.ADVISORY),
                    "area_fips": fips,
                    "effective_utc": effective,
                    "expires_utc": expires,
                    "headline": _text(props.get("headline")) or event_name,
                },
            }
        )

    def fetch_since(self, cursor: str | None) -> FetchResult:
        since, seen = decode_cursor(cursor)
        data = self._get()
        now = self._clock()
        rejected_before = len(self._rejects)
        events: list[EnvelopeBase] = []
        for feature in data["features"]:
            try:
                event = self._to_event(feature, now)
            except Exception as error:  # noqa: BLE001
                record = feature if isinstance(feature, dict) else {"feature": feature}
                self._rejects.append(Reject(record, f"mapping: {type(error).__name__}: {str(error)[:200]}"))
                continue
            sent = event.event_time
            if since is not None and (sent < since or (sent == since and event.payload.alert_id in seen)):  # type: ignore[attr-defined]
                continue
            events.append(event)
        events.sort(key=lambda e: (e.event_time, e.dedup_key))
        outcome = apply_faults(events, self._faults)
        self._rejects.extend(outcome.rejects)
        self._last_success = now
        if events:
            newest = events[-1].event_time
            at_newest = [e.payload.alert_id for e in events if e.event_time == newest]  # type: ignore[attr-defined]
            if newest == since:
                at_newest = sorted(set(at_newest) | seen)
            next_cursor = encode_cursor(newest, at_newest)
            self._last_sent = newest
            self._last_lag = int((now - newest).total_seconds())
        else:
            next_cursor = cursor or ""
        return FetchResult(
            events=outcome.events,
            next_cursor=next_cursor,
            coverage=Coverage(
                from_utc=events[0].event_time if events else None,
                to_utc=now,
                complete=not outcome.gaps and len(self._rejects) == rejected_before,
            ),
        )

    def snapshot(self) -> list[Record]:
        return [
            Record(
                record_id=self.source_id,
                kind="feed",
                attributes={"areas": list(self.areas), "endpoint": f"{BASE_URL}/alerts/active"},
            )
        ]

    def health(self) -> AdapterHealth:
        age = None
        if self._last_sent is not None and self._last_success is not None:
            age = max(0, int((self._last_success - self._last_sent).total_seconds()))
        return AdapterHealth(
            source_id=self.source_id,
            last_success_at=self._last_success,
            ingest_lag_s=max(0, self._last_lag) if self._last_lag is not None else None,
            product_age_s=age,
            error_rate_ppm=self._errors * 1_000_000 // self._attempts if self._attempts else 0,
            feed_mode=self.feed_mode,
        )

    def inject_fault(self, kind: FaultKind, **params: Any) -> None:
        self._faults.append(FaultSpec(kind, params))
