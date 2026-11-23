"""Held-out evaluation manifest: sha256 of every guarded eval file.

`uv run python evals/manifest.py check` exits 1 when a covered file changed, appeared or disappeared without a
manifest update; `write` regenerates the manifest (eval author only). Stdlib only: runs on any OS and in CI.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals" / "MANIFEST.sha256"
COVERED_DIRS = ("evals/heldout", "evals/dev", "data/synthetic/family_b")
COVERED_FILES = ("data/synthetic/family_b.yaml", "evals/README.md", "evals/manifest.py")
HEADER = (
    "# sha256 of held-out evaluation material. Regenerate only as the eval author:\n"
    "#   uv run python evals/manifest.py write\n"
)


def covered_paths(root: Path = ROOT) -> list[str]:
    paths = {p for p in COVERED_FILES if (root / p).is_file()}
    for d in COVERED_DIRS:
        base = root / d
        if base.is_dir():
            paths |= {f.relative_to(root).as_posix() for f in base.rglob("*") if f.is_file()}
    return sorted(p for p in paths if "__pycache__" not in p and not p.endswith(".DS_Store"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute(root: Path = ROOT) -> dict[str, str]:
    return {p: digest(root / p) for p in covered_paths(root)}


def read(manifest: Path = MANIFEST) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        sha, path = line.split(maxsplit=1)
        out[path.strip()] = sha
    return out


def problems(root: Path = ROOT, manifest: Path = MANIFEST) -> list[str]:
    if not manifest.is_file():
        return [f"missing {manifest.relative_to(root).as_posix()}"]
    want, have = read(manifest), compute(root)
    out = [f"not in manifest: {p}" for p in sorted(have.keys() - want.keys())]
    out += [f"listed but missing: {p}" for p in sorted(want.keys() - have.keys())]
    out += [f"changed without manifest update: {p}" for p in sorted(want) if p in have and have[p] != want[p]]
    return out


def write(root: Path = ROOT, manifest: Path = MANIFEST) -> None:
    lines = [f"{sha}  {path}" for path, sha in compute(root).items()]
    manifest.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "write":
        write()
        print(f"wrote {MANIFEST.relative_to(ROOT).as_posix()} ({len(covered_paths())} files)")
        return 0
    if cmd == "check":
        found = problems()
        for p in found:
            print(p)
        print("manifest ok" if not found else f"{len(found)} manifest problem(s)")
        return 1 if found else 0
    print("usage: manifest.py [check|write]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
