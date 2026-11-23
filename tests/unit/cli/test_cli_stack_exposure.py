from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text())
SERVICES = COMPOSE["services"]


def default(value: str) -> str:
    return value.split(":-", 1)[1].rstrip("}") if ":-" in value else value


def published(service: dict) -> list[str]:
    return [str(p) for p in service.get("ports", [])]


def test_mlflow_is_not_published_by_default() -> None:
    core = {name: s for name, s in SERVICES.items() if not s.get("profiles")}
    assert not any("5001" in port for s in core.values() for port in published(s))
    relay = SERVICES["mlflow-port"]
    assert relay["profiles"] == ["mlflow-ui"]
    assert published(relay) == ["127.0.0.1:5001:5001"]
    assert ":5001" not in (ROOT / "infra" / "caddy" / "Caddyfile").read_text()


def test_every_published_port_binds_to_loopback() -> None:
    for name, service in SERVICES.items():
        for port in published(service):
            assert port.startswith("127.0.0.1:"), (name, port)


def test_api_trusts_forwarded_headers_from_caddy_only() -> None:
    caddy, api = SERVICES["caddy"], SERVICES["api"]
    assert set(caddy["networks"]) == {"edge", "proxy"}
    caddy_ip = default(caddy["networks"]["proxy"]["ipv4_address"])
    subnet = default(COMPOSE["networks"]["proxy"]["ipam"]["config"][0]["subnet"])
    assert ipaddress.ip_address(caddy_ip) in ipaddress.ip_network(subnet)
    dynamic = default(COMPOSE["networks"]["proxy"]["ipam"]["config"][0]["ip_range"])
    assert ipaddress.ip_address(caddy_ip) not in ipaddress.ip_network(dynamic), (
        "api could take Caddy's address"
    )
    assert COMPOSE["networks"]["proxy"]["internal"] is True
    command = api["command"]
    allowed = default(command[command.index("--forwarded-allow-ips") + 1])
    assert allowed == caddy_ip
    assert "*" not in command
    assert set(api["networks"]) == {"app", "proxy"}
    others = [
        n for n, s in SERVICES.items() if n not in {"caddy", "api"} and "proxy" in (s.get("networks") or [])
    ]
    assert others == []


@pytest.mark.parametrize(
    ("peer", "trusted"), [("10.213.37.6", True), ("10.213.37.2", False), ("172.21.0.9", False)]
)
async def test_uvicorn_ignores_forwarded_for_from_other_peers(peer: str, trusted: bool) -> None:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    seen: dict[str, object] = {}

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        seen["client"] = scope["client"]

    middleware = ProxyHeadersMiddleware(app, trusted_hosts="10.213.37.6")
    scope = {
        "type": "http",
        "client": (peer, 1234),
        "headers": [(b"x-forwarded-for", b"203.0.113.7")],
        "scheme": "http",
    }
    await middleware(scope, None, None)  # type: ignore[arg-type]
    assert seen["client"][0] == ("203.0.113.7" if trusted else peer)  # type: ignore[index]


def test_cadvisor_is_opt_in_rootless_and_without_docker_storage() -> None:
    cadvisor = SERVICES["cadvisor"]
    assert cadvisor["profiles"] == ["obs"]
    assert cadvisor["user"] == "65534:65534"
    assert cadvisor["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in cadvisor["security_opt"]
    assert cadvisor["read_only"] is True
    assert not any("/var/lib/docker" in v for v in cadvisor["volumes"])
    assert all(v.endswith(":ro") for v in cadvisor["volumes"])
    assert not cadvisor.get("ports")
    assert "cAdvisor risk" in (ROOT / "ops" / "obs" / "README.md").read_text()


def test_only_audit_checkpoint_mounts_the_signing_key() -> None:
    for name, service in SERVICES.items():
        mounts = [str(v) for v in service.get("volumes", [])]
        holds_key = any("/run/secrets/sgw-audit" in m for m in mounts)
        assert holds_key == (name == "audit-checkpoint"), name
    api = SERVICES["api"]
    assert api["volumes"] == [
        "${SGW_VAR_DIR:-./var}/audit:/var/lib/sgw/audit:ro",
        "${SGW_VAR_DIR:-./var}/cv:/app/var/cv:ro",
    ]
    assert api["environment"]["SGW_AUDIT_SIGNING"] == "0"
    assert api["environment"]["SGW_AUDIT_KEY_DIR"] == "/run/secrets/sgw-audit"  # set, never mounted
    assert SERVICES["audit-checkpoint"]["environment"]["SGW_AUDIT_KEY_DIR"] == "/run/secrets/sgw-audit"


def test_api_does_not_sign_after_commit_when_signing_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sgw.approval.breakglass_deps import post_commit_signer
    from sgw.approval.signer import AuditPaths

    paths = AuditPaths(tmp_path / "keyring.json", tmp_path / "keys", tmp_path / "anchors")
    monkeypatch.setenv("SGW_AUDIT_SIGNING", "0")
    assert post_commit_signer(paths) is None
    monkeypatch.delenv("SGW_AUDIT_SIGNING")
    assert post_commit_signer(paths) is not None


def test_containers_writing_host_dirs_run_as_the_host_uid() -> None:
    for name in ("api", "audit-checkpoint", "llm-gateway"):
        assert SERVICES[name]["user"] == "${SGW_RUN_UID:-10001}:${SGW_RUN_GID:-10001}", name
