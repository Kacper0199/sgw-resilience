"""The integration API as its own OpenAPI 3.1 document (`contracts/openapi-v1.json`).

What an integrator needs and nothing else: the `/v1` operations exactly as K3 defines them (copied from
`openapi_document()`, so they cannot drift apart), the token admin routes, bearer security only, and an
OpenAPI 3.1 `webhooks` section with one entry per event type: the signed POST the platform sends, its
headers and the K2 payload under `data`.

Regenerate: `uv run sgw contracts` (or `uv run sgw integrations openapi`); `sgw contracts-check` and
`sgw integrations openapi --check` fail on drift.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pydantic.json_schema import models_json_schema

from sgw.contracts.api_models import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    CommitmentV1,
    DecisionV1,
    ErrorBody,
    WebhookDeliveryV1,
    WebhookSecretRotated,
    WebhookSubscriptionCreate,
    WebhookSubscriptionV1,
    openapi_document,
)
from sgw.contracts.base import Contract
from sgw.contracts.events import CURRENT_SCHEMA_VERSION, EVENT_MODELS, WEBHOOK_EVENT_TYPES
from sgw.contracts.webhooks import ID_HEADER, SIGNATURE_HEADER, TOLERANCE_S, WebhookEventV1
from sgw.integrations.backoff import RetryPolicy
from sgw.integrations.delivery import ATTEMPT_HEADER, USER_AGENT
from sgw.integrations.tokens import EVENT_SCOPE

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCUMENT = REPO_ROOT / "contracts" / "openapi-v1.json"
REF = "#/components/schemas/"
K3_PATHS = ("/v1/", "/api/admin/tokens")
SECRET_HEADER = "SGW-Webhook-Secret"  # noqa: S105
MAX_ATTEMPTS = RetryPolicy().max_attempts


def payload_model(event_type: str) -> type[Contract]:
    annotation = EVENT_MODELS[event_type].model_fields["payload"].annotation
    if not (isinstance(annotation, type) and issubclass(annotation, Contract)):
        raise TypeError(f"{event_type} payload is not a contract model")
    return annotation


PAYLOAD_MODELS: tuple[type[Contract], ...] = tuple(payload_model(t) for t in WEBHOOK_EVENT_TYPES)
MODELS: tuple[type[Contract], ...] = (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    CommitmentV1,
    DecisionV1,
    ErrorBody,
    WebhookDeliveryV1,
    WebhookEventV1,
    WebhookSecretRotated,
    WebhookSubscriptionCreate,
    WebhookSubscriptionV1,
    *PAYLOAD_MODELS,
)


def _webhook(event_type: str, payload_model: str) -> dict[str, Any]:
    header = {"required": True, "schema": {"type": "string"}}
    return {
        "post": {
            "operationId": f"webhook{event_type}",
            "summary": f"{event_type} (needs scope {EVENT_SCOPE[event_type].value})",
            "description": (
                f"Signed POST to the subscription URL. `{SIGNATURE_HEADER}: t=<unix s>,v1=<hex>`[,v1=...]"
                f" with v1 = HMAC-SHA256(secret, `<t>.<{ID_HEADER}>.<raw body>`), one v1 per active secret"
                f" during rotation. Reject timestamps more than {TOLERANCE_S} s from your clock and"
                f" de-duplicate on `{ID_HEADER}` (stable across retries). Answer 2xx within 10 s; anything"
                f" else is retried with exponential backoff and dead-lettered after {MAX_ATTEMPTS} attempts;"
                " 410 disables"
                " the subscription."
            ),
            "parameters": [
                {"name": SIGNATURE_HEADER, "in": "header", **header},
                {"name": ID_HEADER, "in": "header", **header},
                {"name": ATTEMPT_HEADER, "in": "header", "required": True, "schema": {"type": "integer"}},
                {"name": "User-Agent", "in": "header", "required": True, "schema": {"const": USER_AGENT}},
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "allOf": [
                                {"$ref": REF + "WebhookEventV1"},
                                {
                                    "properties": {
                                        "type": {"const": event_type},
                                        "data": {"$ref": REF + payload_model},
                                    }
                                },
                            ]
                        }
                    }
                },
            },
            "responses": {"2XX": {"description": "Accepted by the receiver"}},
        }
    }


QUERY_SCHEMAS: dict[tuple[str, str, str], dict[str, Any]] = {
    ("/v1/webhooks/{subscription_id}/rotate-secret", "post", "overlap_s"): {
        "type": "integer",
        "minimum": 0,
        "maximum": 7 * 86_400,
        "default": 86_400,
    },
    ("/v1/webhooks/{subscription_id}/deliveries", "get", "limit"): {
        "type": "integer",
        "minimum": 1,
        "maximum": 500,
        "default": 100,
    },
}
"""K3 types every query parameter as a string; the integration document states what the routes enforce
(a unit test compares these with the routers' own constraints)."""


def _k3_paths() -> dict[str, dict[str, Any]]:
    k3 = openapi_document()["paths"]
    paths = {p: copy.deepcopy(v) for p, v in k3.items() if p.startswith(K3_PATHS)}
    for (path, method, name), schema in QUERY_SCHEMAS.items():
        for param in paths[path][method].get("parameters", []):
            if param["in"] == "query" and param["name"] == name:
                param["schema"] = dict(schema)
                break
        else:
            raise KeyError(f"{method.upper()} {path} has no query parameter {name}")
    return paths


def build() -> dict[str, Any]:
    _, defs = models_json_schema([(m, "serialization") for m in MODELS], ref_template=REF + "{model}")
    paths = _k3_paths()
    created = paths["/v1/webhooks"]["post"]["responses"]["201"]
    created["headers"] = {
        SECRET_HEADER: {
            "description": "the signing secret, shown once (the body carries only its last 4 characters)",
            "schema": {"type": "string"},
        }
    }
    payload_names = {t: payload_model(t).__name__ for t in WEBHOOK_EVENT_TYPES}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SGW Resilience Decision Platform Integration API",
            "version": f"1.0.0+schema{CURRENT_SCHEMA_VERSION}",
            "description": (
                "Versioned read API, webhook subscriptions and an SSE subscription for external systems."
                " Authenticate with `Authorization: Bearer sgwi_...` (scoped, expiring, revocable). No scope"
                " can approve a decision."
            ),
        },
        "servers": [{"url": "/"}],
        "security": [{"apiToken": []}],
        "paths": dict(sorted(paths.items())),
        "webhooks": {t: _webhook(t, payload_names[t]) for t in WEBHOOK_EVENT_TYPES},
        "components": {
            "schemas": dict(sorted(defs["$defs"].items())),
            "securitySchemes": {
                "apiToken": {"type": "http", "scheme": "bearer", "description": "sgwi_<token_id>_<64 hex>"},
                "session": {"type": "apiKey", "in": "cookie", "name": "sgw_session"},
            },
        },
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def write(path: Path = DOCUMENT) -> Path:
    path.write_text(render(), encoding="utf-8", newline="\n")
    return path


def drift(path: Path = DOCUMENT) -> bool:
    return not path.exists() or path.read_text(encoding="utf-8") != render()
