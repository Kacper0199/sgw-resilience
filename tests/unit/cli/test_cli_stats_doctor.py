from __future__ import annotations

import json
import socket

import pytest

from sgw.cli.commands import doctor
from sgw.cli.commands.stack import ContainerStat, parse_size, parse_stats_line, render_table


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0B", 0),
        ("512KiB", 512 * 1024),
        ("38.12MiB", int(38.12 * 1024**2)),
        ("1.5GiB", int(1.5 * 1024**3)),
        ("10MB", 10_000_000),
    ],
)
def test_parse_size(text: str, expected: int) -> None:
    assert parse_size(text) == expected


def test_parse_stats_line_maps_container_to_service() -> None:
    line = json.dumps({"Name": "sgw-postgres-1", "MemUsage": "120MiB / 1.5GiB", "CPUPerc": "0.40%"})
    stat = parse_stats_line(line, {"sgw-postgres-1": "postgres"})
    assert stat.service == "postgres"
    assert round(stat.used_mib) == 120
    assert round(stat.limit_mib) == 1536


def test_render_table_totals() -> None:
    rows = render_table(
        [
            ContainerStat("a", 100 * 1024**2, 200 * 1024**2, "1%"),
            ContainerStat("b", 50 * 1024**2, 100 * 1024**2, "0%"),
        ]
    )
    assert rows[-1].startswith("| **total** | **150** | **300** | 50%")


def test_doctor_findings_use_known_statuses() -> None:
    findings = doctor.run_checks()
    assert findings
    assert {f.status for f in findings} <= {doctor.OK, doctor.WARN, doctor.FAIL}
    assert all(f.fix for f in findings if f.status == doctor.FAIL)


def test_doctor_flags_a_port_held_by_another_program(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        monkeypatch.setattr(doctor, "HOST_PORTS", {"probe": port})
        monkeypatch.setattr(doctor, "_ports_held_by_stack", set)
        [finding] = doctor.check_ports()
    assert finding.status == doctor.FAIL
    assert str(port) in finding.fix


def test_windows_port_probe_uses_exclusive_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    monkeypatch.setattr(doctor.os, "name", "nt")
    assert doctor._bind_option() == -5
    monkeypatch.setattr(doctor.os, "name", "posix")
    assert doctor._bind_option() == socket.SO_REUSEADDR


def fake_docker(info: dict[str, object]):
    def run(*cmd: str, timeout: float = 20) -> tuple[int, str]:
        if cmd[1] == "info":
            return 0, json.dumps(info)
        if cmd[1:3] == ("compose", "version"):
            return 0, "2.40.0"
        return 0, "buildx v0.30"

    return run


def test_doctor_fails_on_docker_engine_older_than_25(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "_run", fake_docker({"ServerVersion": "24.0.7", "MemTotal": 8 * 1024**3}))
    engine = [f for f in doctor.check_docker() if f.check == "docker engine"]
    assert engine and engine[0].status == doctor.FAIL
    monkeypatch.setattr(doctor, "_run", fake_docker({"ServerVersion": "29.7.2", "MemTotal": 8 * 1024**3}))
    assert not [f for f in doctor.check_docker() if f.check == "docker engine"]


def test_stats_reports_docker_failure_in_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from typer.testing import CliRunner

    from sgw.cli.commands import stack
    from sgw.cli.main import app

    def failing(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="Cannot connect to the Docker daemon\n")

    monkeypatch.setattr(stack, "docker_bin", lambda: "docker")
    monkeypatch.setattr(stack.subprocess, "run", failing)
    result = CliRunner().invoke(app, ["stats"])
    assert result.exit_code == 1
    assert "docker ps failed: Cannot connect to the Docker daemon" in result.output
    assert "Traceback" not in result.output


def test_reset_reports_migration_failure_in_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    from typer.testing import CliRunner

    from sgw.cli.commands import database, stack
    from sgw.cli.main import app

    def broken(**kwargs):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(stack, "compose_cmd", lambda *a, **k: ["docker", "compose", *a])
    monkeypatch.setattr(stack, "run", lambda cmd, **k: None)
    monkeypatch.setattr(database, "apply_migrations", broken)
    result = CliRunner().invoke(app, ["reset", "--yes"])
    assert result.exit_code == 1
    assert "migration failed: connection refused" in result.output
    assert "Traceback" not in result.output
