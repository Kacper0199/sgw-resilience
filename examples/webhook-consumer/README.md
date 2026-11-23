# Example webhook consumer

A receiver for SGW webhooks in one standard-library Python file (`consumer.py`). It shows the checks an
integrating system must make before it trusts a delivery.

## Run it

1. Create a token with `decisions:read` and `webhooks:manage` (platform admin, stepped-up session):
   `uv run sgw integrations token-create --as admin_01 --name "Halvorsen SCADA bridge" --scope decisions:read --scope webhooks:manage`.
   The token is printed once.
2. Subscribe your HTTPS endpoint with that token: `POST /v1/webhooks` with
   `{"url": "https://<your host>/hooks/sgw", "event_types": ["DecisionApproved"]}`. The answer carries the
   signing secret once, in the `SGW-Webhook-Secret` header.
3. Start the consumer with a certificate your platform trusts:

   ```text
   SGW_WEBHOOK_SECRETS=whsec_... uv run examples/webhook-consumer/consumer.py \
       --cert server.pem --key server-key.pem --port 8701 --out received.jsonl
   ```

The platform refuses targets on private, loopback and link-local addresses. For a consumer on the same
machine, list it in `SGW_WEBHOOK_ALLOW_HOSTS` (for example `127.0.0.1:8701`) and point the worker at your CA
with `SGW_WEBHOOK_CA_FILE`.

## What it checks

| Step | Check | Answer when it fails |
| --- | --- | --- |
| 1 | Body present and at most 1 MiB | 413 |
| 2 | `SGW-Signature: t=<unix s>,v1=<hex>[,v1=<hex>]` well formed | 401 |
| 3 | `t` within 300 s of the local clock (replay window) | 401 |
| 4 | HMAC-SHA256(secret, `<t>.<SGW-Webhook-Id>.<raw body>`) equals one `v1`, compared in constant time | 401 |
| 5 | `SGW-Webhook-Id` not seen before (the id is stable across retries) | 200 `duplicate`, not processed again |

The body is parsed only after the signature matched. During secret rotation the platform signs with both
secrets for the overlap (24 h by default); set `SGW_WEBHOOK_SECRETS=<new>,<old>` and drop the old one
after the overlap.

## Delivery semantics

At least once, not ordered: use `ledger_seq` in the body to order events and `SGW-Webhook-Id` to
de-duplicate. A non-2xx answer or no answer within 10 s is retried with exponential backoff (10 s doubling
to 1 h, with jitter) for 8 attempts; then the delivery is dead-lettered and an operator can replay it.
Answer 410 to make the platform disable the subscription.
