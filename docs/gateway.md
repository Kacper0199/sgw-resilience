# LLM gateway interface (K13) and recording format (K11)

`services/llm_gateway` is the only process that talks to the Anthropic Messages API and the only holder of
`ANTHROPIC_API_KEY`. Node code calls it exactly as it would call the API, with `base_url` pointing at the
gateway, any placeholder API key, and client retries off:

```python
ChatAnthropic(
    model="claude-sonnet-5-5",
    base_url=GATEWAY_URL,
    api_key="unused-by-gateway",
    max_retries=0,
    reasoning_effort="medium",
    default_headers=sgw_headers,
)
anthropic.Anthropic(
    base_url=GATEWAY_URL, api_key="unused-by-gateway", max_retries=0, default_headers=sgw_headers
)
```

Run: `uv run sgw gateway` (replay on 8100, no key needed). Record or live:
`uv run --env-file <abs path>/.env sgw gateway --mode record`. In compose the service runs
`python -m services.llm_gateway --host 0.0.0.0 --port 8100`.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /v1/messages` | Messages API proxy, streaming and non-streaming, same request and response shapes as the API |
| `GET /healthz` | `status` (`ok` or `degraded` with reasons), mode, whether a key is present (boolean only), breaker (state, consecutive failures, seconds to the next probe), budget (level, spend, stops, ack, estimated balance), egress (policy engine, reachable, route), `llm_call` sink counters, replay/live/denied/blocked counters |
| `GET /budget?wave=W0` | cumulative spend, soft and hard stop, acknowledged level, estimated balance, daily cap and today's UTC spend, wave spend and caps |
| `POST /budget/ack` | `{"ack_usd": 40, "console_balance_usd": 118.5}` with header `x-sgw-admin-token`; maintainer only |

## Request headers

| Header | Required | Meaning | In replay hash |
| --- | --- | --- | --- |
| `x-sgw-node` | yes | node id, `[a-z0-9_.-]{1,64}`; selects the allowlist row and the fixture folder | yes |
| `x-sgw-purpose` | yes | `spike`, `dev`, `eval`, `redteam`, `record`, `demo`, `test` | no |
| `x-sgw-wave` | yes | build wave, `[A-Za-z0-9][A-Za-z0-9._-]{0,15}`, e.g. `W0`; wave caps count per wave | no |
| `x-sgw-run` | no | run id, `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` | no |
| `x-sgw-classes` | yes (400 `sgw_classes_missing`) | data classes of the inputs, comma-separated (`C0` `C1` `C2` `C3` `C3-N` `C4` `CX`); decided by the egress gate below; above `C1` the recording keeps no verbatim request | no |
| `x-sgw-pseudonymized` | no | `1` when C2 content was pseudonymized before the call; counts only from a service with `may_send_c2` for a node whose rule lists `R2` in `routes` | no |
| `Authorization: Bearer <token>` (or the SDK's `x-api-key`) | yes (401 `sgw_unauthenticated`) | the calling service's token; see Caller authentication | no |
| `x-sgw-prompt-version` | no | prompt version from K14, `[A-Za-z0-9][A-Za-z0-9._@:-]{0,63}` | yes |
| `x-sgw-deadline-s` | no (default 120) | retry deadline for this call | no |
| `anthropic-version`, `anthropic-beta` | from the SDK | forwarded upstream | yes (beta list sorted) |

Tag headers that fail their pattern or contain a key-shaped value are refused (400 `sgw_bad_tag`) before any egress. Every other header, the client's `x-api-key` included, is dropped. `anthropic-beta` values must be listed in the node's `betas`. The gateway adds its own key upstream.

Every response carries `x-sgw-call-id` (the `llm_call` row), `x-sgw-budget` (budget level: `ok`,
`soft_stop`, `soft_stop_acknowledged`, `daily_cap`, `balance_floor`, `hard_stop`) and, once the gate has
decided, `x-sgw-egress` (`allow` or `deny`). A replayed answer also carries `x-sgw-replay: hit` and
`x-sgw-replay-source` (`fixtures` or `live_cache`).

## Caller authentication (security audit M4)

Every `/v1/messages` request carries its service's token. `sgw bootstrap` generates one per service into
`var/secrets/gateway_tokens.env` (never committed): the api and worker read `SGW_GATEWAY_TOKEN_API` /
`SGW_GATEWAY_TOKEN_WORKER` from `app.env` (picked by `SGW_SERVICE`), the host CLI reads
`SGW_GATEWAY_TOKEN_CLI` from `host.env`, and the gateway receives only SHA-256 digests in `gateway.env`
(`LLM_CALLER_TOKEN_SHA256=api:<hex>,worker:<hex>,cli:<hex>`, compared in constant time). The agent client
(`sgw.agent.nodes.llm.GatewayClient`) passes the token as the SDK key, which the SDK sends as
`Authorization: Bearer`; `SGW_GATEWAY_TOKEN` overrides it for one process.

`services/llm_gateway/callers.yaml` binds each service to its nodes: api runs the product graphs, worker
`extract_note` and `rag_chunk_header`, cli every node (evals and recordings). A token outside its set gets
403 `sgw_node_not_allowed_for_caller` (with an `llm_call` deny row); no or an unknown token, or a bearer and an
`x-api-key` that disagree, get 401 with no row. The class ceiling of a request is the node's
`class_ceiling` in `llm_nodes.yaml`: `x-sgw-classes` may lower it (C0 on a C1 node) and never raise it.
`may_send_c2` is false for every service today, so no `x-sgw-pseudonymized` claim is honoured. Tests use the
public tokens `sgw-test-caller-<service>` with `accept_test_tokens=True` (`LLM_ACCEPT_TEST_TOKENS=1`), which
the gateway refuses to start with for live or record runs against the real API. `/healthz` lists the services
it knows (`callers.services`) and whether test tokens are on, never a token.

## Egress gate

One decision per call, in every mode, before any fixture lookup or network request, from package
`sgw.egress` in `policy/egress.rego` (query `POST /v1/data/sgw/egress/decision`, answer
`{allow, deny[], policy_version}`). With `SGW_OPA_URL` set the gateway asks that OPA (compose mounts
`policy/` into it); without it, the Python twin in `services/llm_gateway/egress.py` decides, kept equal to the
Rego by a parity test over one case table on the pinned OPA image. Live and record runs against the real API
refuse to start without OPA unless `LLM_EGRESS_PDP=reference` is set explicitly. An unreachable OPA or an
undefined or malformed decision denies (503 `sgw_egress_policy_unavailable`).

Input: route (`LLM_EGRESS_ROUTE`, default `R1`), node, model, declared classes, pseudonymized flag, beta
headers, non-custom tool types, the node's K14 rule (`models`, `class_ceiling`, `betas`, `tool_types`; from
`LLM_NODES_FILE`, else `src/sgw/agent/llm_nodes.yaml` when present, list or mapping form, model aliases
`sonnet`/`haiku`/`opus` resolved; K14 `betas`, `tool_types`, `source_types` optional), the document and
image sources that are not inline text (`document.base64`, `document.url`, `document.file`, `image.*`; each must
be listed in the node's `source_types`), and detector counts over the outbound body and the decoded bytes of
every base64 source (canary tokens `CANARY-<hex>` plus `LLM_CANARY_TOKENS`, Anthropic key shapes, private-key
headers; counts only, never values). A url or file source cannot be scanned, so only list it for nodes whose
sources are known. An OPA answer with another `policy_version` than `egress-v1` denies.

| Route | Allowed classes | Note |
| --- | --- | --- |
| R1 external API, standard terms (default) | C0, C1 | the prototype route |
| R2 external API under zero retention | C0, C1, C2 | C2 only with `x-sgw-pseudonymized: 1` |
| any | never C3, C3-N, C4, CX | threat model 3.3 |

**What `x-sgw-classes` declares.** LLM nodes receive K15 evidence agent views: telemetry values stay in
slots (`{E<n>.<field>}`) and never enter the prompt, so a prompt built from such a view is C1 by construction.
The evidence-view builder sets `x-sgw-classes` from what the view it rendered actually contains (the
classes of the text that entered the prompt, not of the sources behind the slots), never from a constant.
C2 content in a prompt needs route R2 and `x-sgw-pseudonymized: 1`; on R1 it is denied. Golden labels stay as
they are.

| Deny reason | Error type | Status |
| --- | --- | --- |
| `unclassified_payload` | `sgw_classes_missing` | 400 |
| `unknown_class_label`, `class_not_allowed_on_route`, `class_requires_pseudonymization` | `sgw_class_denied` | 403 |
| `route_unknown` | `sgw_route_unknown` | 403 |
| `secret_detected` / `canary_detected` | `sgw_secret_blocked` / `sgw_canary_blocked` | 403 |
| `detectors_missing` | `sgw_egress_input_invalid` | 403 |
| `node_not_configured`, `node_ceiling_invalid` | `sgw_node_not_allowed` | 403 |
| `model_not_allowed` / `class_above_node_ceiling` | `sgw_model_not_allowed` / `sgw_class_above_ceiling` | 403 |
| `beta_not_allowed` / `tool_type_not_allowed` | `sgw_beta_not_allowed` / `sgw_tool_not_allowed` | 403 |
| `source_type_not_allowed` | `sgw_source_not_allowed` | 403 |

Model output is checked with the same detectors before the client sees it: a non-streamed or replayed
message with a canary is withheld (502 `sgw_output_canary_blocked`; a key shape gives 502
`sgw_key_leak_blocked`) and never recorded; a stream is released event by event, holding back any delta whose
text could be the start of a canary (events in between, `ping` included, join the hold so order is kept;
the end of the block releases it), and ends with an SSE `error` event of the same type when one appears.
The call is still booked in the ledger. Logs, ledger and error messages scrub canary and key shapes.

## `llm_call` rows (K1)

One row per decision: live and record calls (tokens, cache tokens, latency, cost in micro-USD, status as
`stop_reason`), replay hits and misses (`billed=false`), denials by the gate, the payload checks, the budget
or the breaker (`decision='deny'`, `stop_reason` = error type), and withheld output (`decision='deny'`,
billed). `route`, `classes`, `request_hash` and `payload_hash` (SHA-256 of the body) are set on every row;
`call_id` is the response's `x-sgw-call-id`. A background thread writes them through `SGW_LLM_CALL_DSN`, a
login role in `sgw_llm_writer` (INSERT on `llm_call` only, migration 3000); `llm_call` is append-only for
every role (UPDATE, DELETE and TRUNCATE raise 42501). Migration 3001 adds `test` to the purpose check. The
roles are cluster objects the stack creates (`sgw_llm_writer` NOLOGIN, `sgw_gateway IN ROLE sgw_llm_writer`);
migration 3000 only grants to them when they exist. `/healthz` `egress.reachable` is true only when the
decision itself answers with the current policy version. The database being down
never delays or fails a call: the sink retries, counts errors and shows them on `/healthz`; the CSV ledger
stays the budget's source of truth.

## Modes (`LLM_MODE`)

| Mode | Behaviour |
| --- | --- |
| `replay` (default) | serve `data/fixtures/llm/<node>/<sha256>.json`; a miss returns **424 `sgw_replay_miss`** with the hash in `x-sgw-request-hash`; never calls upstream, never needs a key |
| `record` | serve an existing recording, otherwise call live and write the recording; `LLM_RECORD_OVERWRITE=1` forces live |
| `live` | call live, write nothing to fixtures |
| `replay_then_live` | serve a recording from `data/fixtures/llm` (spends 0), else one from the live cache; on a miss call live once and store the answer in the live cache `var/llm/live_cache/<node>/<sha256>.json` (`LLM_LIVE_CACHE_DIR`; the gateway refuses a cache path inside `data/fixtures`), never in the fixtures. Each call is logged with the mode it was served in (`replay` or `live`) |

Streaming requests replay from the same recording: the gateway stores the final message and synthesises the
SSE event sequence (`message_start`, block start/delta/stop incl. `citations_delta`, `thinking_delta`,
`signature_delta`, `input_json_delta`, `message_delta`, `message_stop`).

## Payload checks (before the egress gate, HTTP 400)

`sgw_sampling_param` (temperature, top_p, top_k), `sgw_forced_tool_choice` (`any`/`tool`), `sgw_thinking`
(only omitted or `adaptive`), `sgw_effort_implicit` (`output_config.effort` required), `sgw_max_tokens`,
`sgw_unknown_model` (no price row), `sgw_fallbacks_off`, `sgw_mixed_search_result` (a tool result holding a
`search_result` holds only `search_result`), `sgw_citations_with_format` (citation-enabled blocks or cited
history together with `output_config.format`: use a fresh message list), `sgw_user_citations`,
`sgw_mixed_citation_settings`, `sgw_param_not_allowed` (top-level fields outside model, max_tokens, messages,
system, tools, tool_choice, thinking, output_config, stream, metadata, stop_sequences, cache_control: so no
`mcp_servers`, `container`, `speed`, `inference_geo`). Node, model, class, beta and tool rules are the egress
gate's (above). The default rules `spike.*` and `test.*` (Sonnet 5.5 or Haiku 5.5, ceiling C2) always apply;
a nodes file (`LLM_NODES_FILE`, else `src/sgw/agent/llm_nodes.yaml`) adds its nodes and may override a default
pattern by naming it. The upstream URL is locked to `https://api.anthropic.com` (tests set
`LLM_ALLOW_TEST_UPSTREAM=1`) and proxy environment variables are ignored.

## Retries, breaker, budget

- Retries belong to the gateway: 429, 500, 502, 503, 504, 529 and connection errors before the body is sent,
  exponential backoff with full jitter (0.5 s base, 8 s cap), `retry-after` honoured, at most
  `LLM_MAX_ATTEMPTS` (default 4, must be >= 1) and never past the deadline. A read timeout or dropped
  connection after the body was sent is never retried: 504 `sgw_upstream_post_send_failure`, booked at worst
  case. A 200 whose body cannot be read is booked at worst case (502 `sgw_upstream_unreadable`). Clients run
  with `max_retries=0`.
- Breaker: 5 consecutive failures open it for 30 s (503 `sgw_breaker_open`); one half-open probe; results
  from an older generation are ignored. `/healthz` shows its state and the seconds to the next probe.
- Budget (HTTP 402) counts the ledger plus an in-memory worst-case reservation for every call in flight, taken
  under a lock before egress and released when the call's ledger row is written, so concurrent calls cannot
  overrun a stop. `sgw_budget_hard_stop` at 90 USD cumulative including the worst case of the call
  (raised only by changing `LLM_HARD_STOP_USD` after a user tick); `sgw_budget_soft_stop` at 40 USD until
  `LLM_BUDGET_ACK` (or `/budget/ack`) is at least 40; `sgw_balance_floor` when the estimated console balance
  is at or below 100 USD (`LLM_BALANCE_FLOOR_USD`; not lifted by the acknowledgement, so the hard stop and
  the floor stop live calls, whichever comes first); `sgw_daily_cap` when today's UTC billed spend plus the
  calls in flight plus this call's worst case would exceed `LLM_DAILY_CAP_USD` (default 30, `off` for none;
  the day resets at 00:00 UTC; the copilot then answers by code); `sgw_wave_cap_calls` / `sgw_wave_cap_usd` from `LLM_WAVE_CAP_CALLS` /
  `LLM_WAVE_CAP_USD` (calls = every live request, billed or not, plus those in flight). Zero values are honoured.
  Replay never touches the budget. The level is on every response (`x-sgw-budget`) and on `/healthz`.

## Spend ledger

`var/llm_spend.csv` (git-ignored), one row per upstream request: `ts, mode, purpose, wave, run_id, node,
prompt_version, model, effort, batch, input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
output_tokens, stop_reason, latency_ms, cost_usd, request_hash, billed, attempts, status`. Cost uses
`services/llm_gateway/prices.py` (5-minute and 1-hour cache writes split, Haiku long-prompt tier). A stream
that ends without `message_stop` is booked at its worst case (`incomplete_stream_worst_case`); a completed
stream is booked and recorded as soon as `message_stop` is parsed, before the last chunk reaches the client.
Key-shaped values are scrubbed from ledger rows instead of failing the write. Summary:
`uv run sgw llm-spend --by wave,purpose,node`.

## K11 recording format

Path `data/fixtures/llm/<node>/<request_sha256>.json`, JSON with sorted keys:

| Field | Meaning |
| --- | --- |
| `format` | `sgw.llm_recording/v1` |
| `canonical_version` | `k11-v1` |
| `request_sha256` | SHA-256 of the RFC 8785 (JCS) form of `{canonical_version, body, headers}` |
| `request` | canonical body (no `stream`, no `metadata`; tool ids renamed `toolu_0000...` in order of appearance; thinking signatures and redacted-thinking data replaced by `<signature>`), or `null` above C1 |
| `request_headers` | the hashed headers |
| `response` | the final Message exactly as returned |
| `node`, `model`, `prompt_version`, `data_classes`, `price_table`, `cost_usd_at_record`, `latency_ms`, `recorded_at` | metadata |

The writer refuses any file that contains an Anthropic key pattern or the gateway's own key
(`sgw_key_leak_blocked`, 502), and the test suite scans every committed fixture for the key prefix.
