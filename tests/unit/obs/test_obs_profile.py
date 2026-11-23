from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
OBS = ROOT / "ops" / "obs"
OBS_SERVICES = {"prometheus", "grafana", "cadvisor", "postgres-exporter"}
OPT_IN_SERVICES = {"mlflow-port": ["mlflow-ui"]}
DIGEST = re.compile(r"^[a-z0-9./-]+:[\w.-]+@sha256:[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def compose() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((ROOT / "compose.yaml").read_text())


def test_obs_services_exist_only_in_the_obs_profile(compose: dict) -> None:  # type: ignore[type-arg]
    services = compose["services"]
    profiled = {name for name, svc in services.items() if "obs" in svc.get("profiles", [])}
    assert profiled == OBS_SERVICES
    for name, svc in services.items():
        if name in OPT_IN_SERVICES:
            assert svc["profiles"] == OPT_IN_SERVICES[name]
        elif name not in OBS_SERVICES:
            assert "profiles" not in svc, f"{name} must stay in core"


def test_obs_services_are_pinned_limited_hardened_and_checked(compose: dict) -> None:  # type: ignore[type-arg]
    for name in OBS_SERVICES:
        svc = compose["services"][name]
        assert DIGEST.match(svc["image"]), name
        assert svc["mem_limit"] == svc["memswap_limit"], name
        assert svc["read_only"] is True, name
        assert "healthcheck" in svc, name
        assert svc["cap_drop"] == ["ALL"] and "no-new-privileges:true" in svc["security_opt"], name
        assert "egress" not in svc["networks"], name
        for port in svc.get("ports", []):
            assert port.startswith("127.0.0.1:"), f"{name} publishes {port} beyond loopback"


def test_obs_memory_budget_stays_small(compose: dict) -> None:  # type: ignore[type-arg]
    units = {"m": 1, "g": 1024}
    total = sum(
        int(compose["services"][n]["mem_limit"][:-1]) * units[compose["services"][n]["mem_limit"][-1]]
        for n in OBS_SERVICES
    )
    assert total <= 768


def test_obs_host_ports_match_the_round_brief(compose: dict) -> None:  # type: ignore[type-arg]
    assert compose["services"]["prometheus"]["ports"] == ["127.0.0.1:9091:9090"]
    assert compose["services"]["grafana"]["ports"] == ["127.0.0.1:3001:3000"]
    assert "ports" not in compose["services"]["cadvisor"]
    assert "ports" not in compose["services"]["postgres-exporter"]


def test_grafana_is_admin_only_and_offline(compose: dict) -> None:  # type: ignore[type-arg]
    grafana = compose["services"]["grafana"]
    env = grafana["environment"]
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert env["GF_PLUGINS_PREINSTALL_DISABLED"] == "true"
    assert env["GF_ANALYTICS_REPORTING_ENABLED"] == "false"
    assert "GF_SECURITY_ADMIN_PASSWORD" not in env
    assert grafana["env_file"][0]["path"].endswith("/grafana.env")
    assert all(v.endswith(":ro") for v in grafana["volumes"] if "ops/obs" in v)


def test_exporter_gets_only_its_own_dsn(compose: dict) -> None:  # type: ignore[type-arg]
    exporter = compose["services"]["postgres-exporter"]
    assert [e["path"].rsplit("/", 1)[1] for e in exporter["env_file"]] == ["pg-exporter.env"]
    for name in ("prometheus", "cadvisor"):
        assert "env_file" not in compose["services"][name]


def test_prometheus_scrapes_only_known_internal_targets() -> None:
    config = yaml.safe_load((OBS / "prometheus" / "prometheus.yml").read_text())
    targets = {job["job_name"]: job["static_configs"][0]["targets"][0] for job in config["scrape_configs"]}
    assert targets == {
        "prometheus": "127.0.0.1:9090",
        "cadvisor": "cadvisor:8080",
        "api": "api:8000",
        "postgres": "postgres-exporter:9187",
    }
    keep = config["scrape_configs"][1]["metric_relabel_configs"][0]
    assert keep == {
        "source_labels": ["container_label_com_docker_compose_project"],
        "regex": "sgw",
        "action": "keep",
    }


def test_dashboards_are_provisioned_read_only_against_the_provisioned_datasource() -> None:
    provider = yaml.safe_load((OBS / "grafana" / "provisioning" / "dashboards" / "sgw.yaml").read_text())
    assert provider["providers"][0]["allowUiUpdates"] is False
    datasource = yaml.safe_load(
        (OBS / "grafana" / "provisioning" / "datasources" / "prometheus.yaml").read_text()
    )
    uid = datasource["datasources"][0]["uid"]
    assert datasource["datasources"][0]["editable"] is False
    boards = {p.stem: json.loads(p.read_text()) for p in (OBS / "grafana" / "dashboards").glob("*.json")}
    assert set(boards) == {"sgw-api", "sgw-containers", "sgw-postgres"}
    for name, board in boards.items():
        assert board["uid"] == name and board["editable"] is False
        assert board["panels"], name
        for panel in board["panels"]:
            assert panel["datasource"]["uid"] == uid
            assert all(t["datasource"]["uid"] == uid and t["expr"] for t in panel["targets"])


def test_api_dashboard_queries_the_metric_names_the_api_exports() -> None:
    from sgw.api.metrics import ApiMetrics

    metrics = ApiMetrics()
    metrics.record("GET", "/x", 200, 0.01)
    exported = set(re.findall(r"^(sgw_\w+?)(?:_bucket|_sum|_count)?[{ ]", metrics.render(), re.MULTILINE))
    board = json.loads((OBS / "grafana" / "dashboards" / "sgw-api.json").read_text())
    used = {m for p in board["panels"] for t in p["targets"] for m in re.findall(r"sgw_\w+", t["expr"])}
    used = {re.sub(r"_bucket$", "", m) for m in used}
    assert used <= exported | {"sgw_http_request_duration_seconds"}


NO_DOCKER = shutil.which("docker") is None


@pytest.mark.skipif(NO_DOCKER, reason="no docker CLI")  # sgw-allow-skip: Windows unit runner
def test_core_profile_does_not_render_obs_services(tmp_path: Path) -> None:
    secrets = tmp_path / "s"
    secrets.mkdir()
    for name in ("app.env", "postgres.env"):
        (secrets / name).write_text("")
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "SGW_SECRETS_DIR": str(secrets)}
    cmd = [shutil.which("docker") or "docker", "compose", "-p", "sgwci", "-f", str(ROOT / "compose.yaml")]
    core = subprocess.run(  # noqa: S603
        [*cmd, "--profile", "core", "config", "--services"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert core.returncode == 0, core.stderr
    assert not OBS_SERVICES & set(core.stdout.split())
