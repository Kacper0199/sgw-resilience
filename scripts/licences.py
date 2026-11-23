"""Licence gate (DC-29): fail on GPL, AGPL or LGPL in uv.lock or pnpm-lock.yaml unless allow-listed.

Python: every package in uv.lock (all groups and platforms). Metadata comes from the installed environment
when the version matches, else from the PyPI JSON API, cached under var/licence-cache/.
Web: `pnpm licenses list --json -r` over the frozen install.
Usage: python scripts/licences.py [--offline] [--strict-unknown]
Exit 0 pass, 1 copyleft (or unknown with --strict-unknown), 2 could not evaluate.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "licences-allow.txt"
CACHE = ROOT / "var" / "licence-cache" / "pypi"
COPYLEFT = re.compile(r"\b(A|L)?GPL|GNU (Affero|Lesser|Library|General)", re.IGNORECASE)
CLASSIFIER_PREFIX = "License :: "


@dataclass(frozen=True)
class Package:
    ecosystem: str
    name: str
    version: str
    licence: str


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def is_copyleft(expression: str) -> bool:
    """A licence fails only when every alternative of an OR, or every classifier, is copyleft."""
    if not expression.strip():
        return False
    alternatives = re.split(r"\s+OR\s+|\s*;\s*|\s+or\s+", expression.strip("() "))
    return all(COPYLEFT.search(alt) for alt in alternatives if alt.strip())


def licence_from_fields(expression: str | None, text: str | None, classifiers: list[str]) -> str:
    if expression:
        return expression.strip()
    found = [c.split(" :: ")[-1] for c in classifiers if c.startswith(CLASSIFIER_PREFIX)]
    found = [f for f in found if f not in ("OSI Approved", "")]
    if found:
        return "; ".join(found)
    first = (text or "").strip().splitlines()
    return first[0][:80] if first else ""


def load_allowlist(path: Path = ALLOWLIST) -> set[tuple[str, str]]:
    allowed = set()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                ecosystem, name, *_ = line.split()
                allowed.add((ecosystem, normalise(name)))
    return allowed


def uv_lock_packages(lock: Path) -> list[tuple[str, str]]:
    data = tomllib.loads(lock.read_text())
    packages = []
    for package in data.get("package", []):
        source = package.get("source", {})
        if "editable" in source or "virtual" in source:
            continue
        packages.append((package["name"], package["version"]))
    return packages


def installed_licence(name: str, version: str) -> str | None:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    if dist.version != version:
        return None
    meta = dist.metadata
    return licence_from_fields(
        meta.get("License-Expression"), meta.get("License"), meta.get_all("Classifier") or []
    )


def pypi_licence(name: str, version: str, offline: bool) -> str | None:
    cached = CACHE / f"{normalise(name)}-{version}.json"
    if cached.exists():
        info = json.loads(cached.read_text())
    elif offline:
        return None
    else:
        url = f"https://pypi.org/pypi/{name}/{version}/json"
        try:
            with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310
                info = json.load(response)["info"]
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
            return None
        info = {k: info.get(k) for k in ("license_expression", "license", "classifiers")}
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(info, sort_keys=True))
    return licence_from_fields(
        info.get("license_expression"), info.get("license"), info.get("classifiers") or []
    )


def python_packages(offline: bool) -> list[Package]:
    packages = []
    for name, version in uv_lock_packages(ROOT / "uv.lock"):
        licence = installed_licence(name, version)
        if licence is None:
            licence = pypi_licence(name, version, offline)
        packages.append(Package("py", name, version, licence if licence is not None else "?"))
    return packages


def web_packages() -> list[Package]:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm not found. Fix: corepack enable, then pnpm install --frozen-lockfile")
    result = subprocess.run(  # noqa: S603
        [pnpm, "licenses", "list", "--json", "-r"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pnpm licenses failed: {result.stderr.strip()[:400]}. Fix: pnpm install --frozen-lockfile"
        )
    packages = []
    for licence, entries in json.loads(result.stdout or "{}").items():
        for entry in entries:
            for version in entry.get("versions", []):
                packages.append(Package("npm", entry["name"], version, licence))
    return packages


def evaluate(
    packages: list[Package], allowed: set[tuple[str, str]]
) -> tuple[list[Package], list[Package], list]:
    blocked, unknown, waived = [], [], []
    for package in packages:
        key = (package.ecosystem, normalise(package.name))
        if package.licence in ("", "?", "UNKNOWN", "Unknown"):
            (waived if key in allowed else unknown).append(package)
        elif is_copyleft(package.licence):
            (waived if key in allowed else blocked).append(package)
    return blocked, unknown, waived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Licence gate")
    parser.add_argument("--offline", action="store_true", help="use installed metadata and the cache only")
    parser.add_argument("--strict-unknown", action="store_true", help="fail when a licence cannot be read")
    args = parser.parse_args(argv)
    try:
        packages = python_packages(args.offline) + web_packages()
    except RuntimeError as error:
        print(f"licences: {error}", file=sys.stderr)
        return 2
    blocked, unknown, waived = evaluate(packages, load_allowlist())
    counts = {eco: sum(p.ecosystem == eco for p in packages) for eco in ("py", "npm")}
    print(
        f"licences: {counts['py']} Python (uv.lock) + {counts['npm']} npm (pnpm-lock.yaml) packages checked"
    )
    for package in waived:
        print(f"  allow-listed  {package.ecosystem} {package.name} {package.version}: {package.licence}")
    for package in unknown:
        print(f"  unknown       {package.ecosystem} {package.name} {package.version}")
    for package in blocked:
        print(f"  COPYLEFT      {package.ecosystem} {package.name} {package.version}: {package.licence}")
    if blocked:
        print(
            "  Fix: drop or replace the dependency; if it is only imported, never vendored, "
            f"ask the maintainer to add '<py|npm> <name> <reason>' to {ALLOWLIST.relative_to(ROOT)}"
        )
    if unknown:
        print(
            "  Unknown licences: check network access to pypi.org, or review the package and ask the "
            f"maintainer to add '<py|npm> <name> <licence and reason>' to {ALLOWLIST.relative_to(ROOT)}"
        )
    failed = bool(blocked) or (args.strict_unknown and bool(unknown))
    print(f"licences: {'FAIL' if failed else 'PASS'} ({len(blocked)} copyleft, {len(unknown)} unknown)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
