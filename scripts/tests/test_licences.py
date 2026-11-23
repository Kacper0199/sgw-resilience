from __future__ import annotations

from pathlib import Path

import pytest
from conftest import load_script

licences = load_script("licences")


@pytest.mark.parametrize(
    ("expression", "copyleft"),
    [
        ("MIT", False),
        ("Apache-2.0", False),
        ("MPL-2.0", False),
        ("BSD-3-Clause", False),
        ("GPL-3.0-only", True),
        ("AGPL-3.0-or-later", True),
        ("LGPL-3.0-only", True),
        ("GNU Lesser General Public License v3 (LGPLv3)", True),
        ("MIT OR GPL-2.0-or-later", False),
        ("(GPL-2.0-only OR AGPL-3.0-only)", True),
        ("BSD License; GNU General Public License v2 (GPLv2)", False),
        ("", False),
    ],
)
def test_is_copyleft(expression: str, copyleft: bool) -> None:
    assert licences.is_copyleft(expression) is copyleft


def test_licence_from_fields_prefers_expression_then_classifiers() -> None:
    classifiers = ["License :: OSI Approved :: MIT License", "Programming Language :: Python"]
    assert licences.licence_from_fields("Apache-2.0", "x", classifiers) == "Apache-2.0"
    assert licences.licence_from_fields(None, "long text", classifiers) == "MIT License"
    assert licences.licence_from_fields(None, "BSD\nfull text", []) == "BSD"
    assert licences.licence_from_fields(None, None, []) == ""


def test_evaluate_waives_only_allow_listed(tmp_path: Path) -> None:
    allow = tmp_path / "allow.txt"
    allow.write_text("# reviewed\npy psycopg_binary imported only\npy nvidia-nvtx NVIDIA EULA, host group\n")
    allowed = licences.load_allowlist(allow)
    packages = [
        licences.Package("py", "psycopg-binary", "3.3.9", "LGPL-3.0-only"),
        licences.Package("py", "readline-gpl", "1.0", "GPL-3.0-only"),
        licences.Package("npm", "psycopg-binary", "1.0", "GPL-3.0-only"),
        licences.Package("npm", "react", "19.0.0", "MIT"),
        licences.Package("py", "mystery", "0.1", "?"),
        licences.Package("py", "nvidia_nvtx", "13.2.86", "?"),
    ]
    blocked, unknown, waived = licences.evaluate(packages, allowed)
    assert [p.name for p in waived] == ["psycopg-binary", "nvidia_nvtx"]
    assert [(p.ecosystem, p.name) for p in blocked] == [("py", "readline-gpl"), ("npm", "psycopg-binary")]
    assert [p.name for p in unknown] == ["mystery"]


def test_uv_lock_parsing_skips_the_project_itself(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        'version = 1\n[[package]]\nname = "sgw-resilience-platform"\nversion = "0.1.0"\n'
        'source = { editable = "." }\n[[package]]\nname = "httpx"\nversion = "0.28.1"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    )
    assert licences.uv_lock_packages(lock) == [("httpx", "0.28.1")]
