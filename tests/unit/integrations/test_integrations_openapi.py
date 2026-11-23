"""Contract tests for the `/v1` OpenAPI 3.1 document (`contracts/openapi-v1.json`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import jsonschema
import schemathesis

from sgw.api.app import app_routes
from sgw.contracts.api_models import openapi_document
from sgw.contracts.events import WEBHOOK_EVENT_TYPES
from sgw.integrations import openapi
from sgw.integrations.payload import body_bytes, event_v1
from sgw.integrations.testkit import build_app

DOC = json.loads(openapi.DOCUMENT.read_text(encoding="utf-8"))


def validator(ref: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator({"$ref": ref, "components": DOC["components"]})


def test_committed_document_has_no_drift() -> None:
    assert not openapi.drift(), "run `uv run sgw integrations openapi` and commit contracts/openapi-v1.json"


def test_document_is_valid_openapi_31_and_every_ref_resolves() -> None:
    assert DOC["openapi"] == "3.1.0"
    schemathesis.openapi.from_dict(DOC)
    text = json.dumps(DOC)
    for name in {part.split('"')[0] for part in text.split('"$ref": "#/components/schemas/')[1:]}:
        assert name in DOC["components"]["schemas"], name
    jsonschema.Draft202012Validator.check_schema({"components": DOC["components"]})


def test_k3_operations_are_copied_verbatim() -> None:
    k3 = openapi_document()["paths"]
    for path, ops in k3.items():
        if not path.startswith(openapi.K3_PATHS):
            continue
        for method, op in ops.items():
            mine = json.loads(json.dumps(DOC["paths"][path][method]))
            for response in mine["responses"].values():
                response.pop("headers", None)
            for param in mine.get("parameters", []):
                if (path, method, param["name"]) in openapi.QUERY_SCHEMAS:
                    param["schema"] = {"type": "string"}
            assert mine == op, f"{method.upper()} {path}"
    for name, schema in DOC["components"]["schemas"].items():
        if name in openapi_document()["components"]["schemas"]:
            assert schema == openapi_document()["components"]["schemas"][name], name


def test_served_routes_equal_documented_routes() -> None:
    app = build_app("postgresql://unused/unused")
    served = {r for r in app_routes(app) if r[1].startswith(openapi.K3_PATHS)}
    documented = {(m.upper(), p) for p, ops in DOC["paths"].items() for m in ops}
    assert served == documented
    assert {("GET", "/v1/events"), ("DELETE", "/api/admin/tokens/{token_id}")} <= documented
    assert not any("x-sgw-status" in op for ops in DOC["paths"].values() for op in ops.values())


def test_no_operation_can_approve_and_v1_needs_bearer() -> None:
    for path, ops in DOC["paths"].items():
        for op in ops.values():
            assert "approv" not in op["operationId"].lower()
            if path.startswith("/v1/"):
                assert op["security"] == [{"apiToken": []}]
    scopes = DOC["components"]["schemas"]["ApiScope"]["enum"]
    assert all(s.endswith(":read") or s == "webhooks:manage" for s in scopes)


def test_webhooks_section_covers_every_event_and_validates_real_bodies() -> None:
    assert set(DOC["webhooks"]) == set(WEBHOOK_EVENT_TYPES)
    payload: dict[str, Any] = {
        "decision_case_id": "DC-D2-CREWS-AIK",
        "proposal_id": "PRP-CREW-AIK-0926A",
        "proposal_version": 2,
        "action_hash": "ab" * 32,
        "tier": "T2",
        "approver_ids": ["ic_01", "log_01"],
        "break_glass": False,
    }
    event = event_v1(
        event_id="3f0d5c2e-8a51-5d8e-9d6a-7b1f0c2e4a91",
        event_type="DecisionApproved",
        ledger_seq=91,
        event_time=datetime(2024, 9, 26, 18, 10, tzinfo=UTC),
        payload=payload,
    )
    schema = DOC["webhooks"]["DecisionApproved"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    check = jsonschema.Draft202012Validator({**schema, "components": DOC["components"]})
    check.validate(json.loads(body_bytes(event)))
    broken = json.loads(body_bytes(event))
    del broken["data"]["action_hash"]
    assert list(check.iter_errors(broken))
    headers = {p["name"] for p in DOC["webhooks"]["DecisionApproved"]["post"]["parameters"]}
    assert {"SGW-Signature", "SGW-Webhook-Id", "SGW-Webhook-Attempt"} <= headers


def test_typed_query_parameters_match_what_the_routes_enforce() -> None:
    from fastapi.openapi.utils import get_openapi

    from sgw.api.routers import v1_integrations

    served = get_openapi(title="v1", version="1", routes=v1_integrations.router.routes)["paths"]
    for (path, method, name), schema in openapi.QUERY_SCHEMAS.items():
        (enforced,) = [p["schema"] for p in served[path][method]["parameters"] if p["name"] == name]
        assert {k: v for k, v in enforced.items() if k != "title"} == schema
        (documented,) = [p["schema"] for p in DOC["paths"][path][method]["parameters"] if p["name"] == name]
        assert documented == schema and documented["type"] == "integer"
