"""`opa check`, `opa fmt`, `opa test` and coverage for `policy/`, by local opa or the pinned image."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

OPA_IMAGE = (
    "openpolicyagent/opa:1.22.4-static"
    "@sha256:12cecac5a174368f7d3f09d3a19d040ebe0c91d576e520335ae7a985a26e39d3"
)
OPA_VERSION = "1.22.4"
MIN_COVERAGE_PCT = 95.0


class OpaRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyTestResult:
    passed: int
    failed: int
    coverage_pct: float
    output: str


def _local_opa() -> str | None:
    found = shutil.which("opa")
    if not found:
        return None
    out = subprocess.run([found, "version"], capture_output=True, text=True, check=False)  # noqa: S603
    return found if f"Version: {OPA_VERSION}" in out.stdout else None


def opa_command(policy_dir: Path, *args: str) -> list[str]:
    local = _local_opa()
    if local:
        return [local, *args, str(policy_dir)]
    docker = shutil.which("docker")
    if not docker:
        raise OpaRunError(f"neither opa {OPA_VERSION} nor docker is on PATH")
    mount = f"{policy_dir.resolve()}:/policy:ro"
    return [docker, "run", "--rm", "--network", "none", "-v", mount, OPA_IMAGE, *args, "/policy"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603


def run_policy_tests(policy_dir: Path, *, min_coverage: float = MIN_COVERAGE_PCT) -> PolicyTestResult:
    check = _run(opa_command(policy_dir, "check", "--strict"))
    if check.returncode != 0:
        raise OpaRunError(f"opa check --strict failed:\n{check.stdout}{check.stderr}")
    fmt = _run(opa_command(policy_dir, "fmt", "--list"))
    if fmt.returncode != 0 or fmt.stdout.strip():
        raise OpaRunError(f"opa fmt would change: {fmt.stdout.strip() or fmt.stderr.strip()}")
    test = _run(opa_command(policy_dir, "test", "--format=json"))
    try:
        results = json.loads(test.stdout or "[]")
    except json.JSONDecodeError as error:
        raise OpaRunError(f"opa test output is not JSON: {test.stdout}{test.stderr}") from error
    failed = [r for r in results if r.get("fail") or r.get("error")]
    passed = len(results) - len(failed)
    verbose = _run(opa_command(policy_dir, "test", "-v"))
    if failed or test.returncode != 0:
        raise OpaRunError(f"{len(failed)} rego test(s) failed:\n{verbose.stdout}{verbose.stderr}")
    cov = _run(opa_command(policy_dir, "test", "--coverage", "--format=json"))
    coverage = float(json.loads(cov.stdout)["coverage"])
    if coverage < min_coverage:
        raise OpaRunError(f"rego coverage {coverage:.1f}% is below {min_coverage:.0f}%")
    return PolicyTestResult(passed=passed, failed=0, coverage_pct=coverage, output=verbose.stdout)
