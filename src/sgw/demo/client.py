"""HTTP as a demo persona: login cookie, double-submit CSRF header on writes, same-origin header, and K4 run
frames read from SSE with the gap between frames (for K19 capture). Credentials are passed in, never
printed."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

END_FRAMES = ("run_paused", "run_end", "run_error")


class DemoError(RuntimeError):
    pass


@dataclass
class Run:
    thread_id: str
    run_id: str
    frames: list[dict[str, Any]] = field(default_factory=list)
    gaps_ms: list[int] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    restarted: bool = False

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [f.get("payload") or {} for f in self.frames if f["type"] == kind]

    def artifacts(self, kind: str) -> list[dict[str, Any]]:
        return [p for p in self.of("artifact") if p.get("kind") == kind]

    @property
    def last(self) -> dict[str, Any]:
        if not self.frames:
            raise DemoError(f"run {self.run_id} streamed no frames")
        return self.frames[-1]

    @property
    def status(self) -> str:
        last = self.last
        if last["type"] == "run_paused":
            return "paused"
        return str((last.get("payload") or {}).get("status") or last["type"])


class Persona:
    def __init__(self, base: str, user_id: str, password: str, timeout_s: float = 60) -> None:
        self.user_id = user_id
        self.c = httpx.Client(base_url=base, timeout=timeout_s, headers={"Origin": base})
        r = self.c.post("/api/auth/login", json={"user_id": user_id, "password": password})
        if r.status_code != 200:
            raise DemoError(f"login {user_id}: HTTP {r.status_code}")

    def close(self) -> None:
        self.c.close()

    def _csrf(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return {"X-CSRF-Token": self.c.cookies.get("sgw_csrf") or "", **(extra or {})}

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.c.get(path, **kw)

    def get_json(self, path: str, **kw: Any) -> Any:
        r = self.get(path, **kw)
        if r.status_code != 200:
            raise DemoError(f"GET {path} as {self.user_id}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def post(self, path: str, body: Any = None, headers: Mapping[str, str] | None = None) -> httpx.Response:
        return self.c.post(path, json=body, headers=self._csrf(headers))

    def seek(self, at: str) -> dict[str, Any]:
        r = self.post("/api/scenario", {"action": "seek", "scenario_time": at})
        if r.status_code != 200:
            raise DemoError(f"seek {at}: HTTP {r.status_code} {r.text[:200]}")
        return dict(r.json())

    def frames(
        self, run: Run, after_seq: int = -1, until: tuple[str, ...] = END_FRAMES, timeout_s: float = 180
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        last = time.monotonic()
        with self.c.stream("GET", f"/api/threads/{run.thread_id}/events", timeout=timeout_s) as r:
            if r.status_code != 200:
                raise DemoError(f"events of {run.thread_id}: HTTP {r.status_code}")
            sse_id = ""
            for line in r.iter_lines():
                if line.startswith("id:"):
                    sse_id = line[3:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                frame = json.loads(line[5:])
                if frame["seq"] <= after_seq:
                    continue
                now = time.monotonic()
                run.gaps_ms.append(int((now - last) * 1000))
                run.ids.append(sse_id)
                last = now
                out.append(frame)
                if frame["type"] in until:
                    break
        run.frames += out
        return out

    def run(self, graph: str, run_input: Mapping[str, Any], module: str) -> Run:
        t = self.post("/api/threads", {"module": module})
        if t.status_code != 201:
            raise DemoError(f"thread for {graph}: HTTP {t.status_code} {t.text[:200]}")
        thread_id = t.json()["thread_id"]
        r = self.post(f"/api/threads/{thread_id}/runs", {"graph": graph, "input": dict(run_input)})
        if r.status_code != 202:
            raise DemoError(f"run {graph}: HTTP {r.status_code} {r.text[:200]}")
        run = Run(thread_id=thread_id, run_id=r.json()["run_id"])
        self.frames(run)
        return run

    def resume(self, run: Run) -> list[dict[str, Any]]:
        last = -1 if run.restarted else max((f["seq"] for f in run.frames), default=-1)
        run.restarted = False
        r = self.post(f"/api/runs/{run.run_id}/resume", {})
        if r.status_code != 202:
            raise DemoError(f"resume {run.run_id}: HTTP {r.status_code} {r.text[:200]}")
        return self.frames(run, after_seq=last)

    def card(self, proposal_id: str) -> httpx.Response:
        r = self.get(f"/api/proposals/{proposal_id}")
        if r.status_code != 200:
            raise DemoError(f"card {proposal_id}: HTTP {r.status_code} {r.text[:200]}")
        return r

    def write_on_card(self, proposal_id: str, path: str, body: Mapping[str, Any]) -> httpx.Response:
        card = self.card(proposal_id)
        c = card.json()
        payload = {"proposal_version": c["proposal_version"], "action_hash": c["action_hash"], **body}
        return self.post(
            f"/api/proposals/{proposal_id}/{path}",
            payload,
            headers={"If-Match": card.headers.get("etag", "")},
        )

    def decide(self, proposal_id: str, decision: str = "approve") -> dict[str, Any]:
        r = self.write_on_card(proposal_id, "approvals", {"decision": decision})
        if r.status_code != 200:
            raise DemoError(f"{self.user_id} {decision} {proposal_id}: HTTP {r.status_code} {r.text[:200]}")
        return dict(r.json())
