# Golden path through the API

The story "PS-17: one pump station, one hospital, one clock" (PLAN SC-1 to SC-5 and the SC-7 drills), walked as an operator would walk it, with HTTP calls only and no UI. The automated version is `tests/e2e_api/test_golden_path.py` (marked `slow`: it runs in `scripts/check.sh merge` and `full`, not in `quick`). All values are synthetic.

Every number below is what the replayed Helene scenario gives on a fresh database.

## 1. Prepare a database

Setup uses the CLI once; everything after section 2 is HTTP. Replace `sgw_golden` with your own database name.

```bash
uv run sgw migrate --database sgw_golden --create
uv run sgw seed --demo --database sgw_golden
```

`sgw seed --demo` loads, in this order and idempotently:

| Step | Loads |
| --- | --- |
| users | the 11 K18 personas with their demo passwords from `var/demo.env` (per persona; read by name, never printed) |
| reference rows | regions, the Helene crew proposal, the PS-17 cascade assets (FDR-AIK-2207, PS-17, WZ-PS17-CEDARFALL, HSP-AIK-TALLOWBRANCH) and the D4 ETR case |
| scenario | the Helene replay into the ledger (gapless) |
| queue | the PS-17 decision queue at advisory N on the water twin (PS-17 effective decide-by 04:45Z, verdict wait) |
| ETR | the ETR publication the `etr` graph reads |
| corpus | the procedure corpus the copilot cites (embeddings from the committed cache) |

Without `--demo`, `sgw seed` loads only users, reference rows and the crew proposal.

## 2. Start the services

The API needs an OPA with the policy loaded, the LLM gateway in replay mode (no key) and, for webhooks, an integration key and the consumer's host on the allow-list. Inside the Compose stack these are already set; outside it, start them on your own ports:

```bash
docker run -d --rm --name sgw-golden-opa -p 127.0.0.1:8806:8181 \
  openpolicyagent/opa:1.22.4-static run --server --addr=0.0.0.0:8181 --disable-telemetry
LLM_EGRESS_PDP=reference uv run sgw gateway --mode replay --port 8805
DEMO_MODE=1 SGW_SCENARIO=helene SGW_DATABASE_URL=<runtime DSN of sgw_golden> \
  SGW_GATEWAY_URL=http://127.0.0.1:8805 SGW_OPS_GATEWAY_URL=http://127.0.0.1:8805 \
  SGW_OPA_URL=http://127.0.0.1:8806 SGW_OPA_LOAD_POLICY=1 \
  SGW_INTEGRATION_KEY=<64 hex> SGW_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8803 SGW_SCENARIO_JOBS_S=5 \
  uv run uvicorn sgw.api.app:create_app --factory --host 127.0.0.1 --port 8800
```

`SGW_SCENARIO_JOBS_S` turns on the scenario jobs (compose sets 5 s): after every scenario command and on that interval the API stores the queue of the advisory in force, re-plans open proposals whose clock moved and marks expired proposals. The runtime DSN comes from the local credentials (`var/secrets/postgres.env`, role `sgw_runtime`); never print it. Without `SGW_OPA_LOAD_POLICY=1` against an empty OPA, the first proposal fails with `PolicyUnavailableError`.

## 3. Walk the story

Log in as each persona once and keep its cookie jar. Every write sends the CSRF cookie back as `X-CSRF-Token` and an `Origin` header of the API itself.

```bash
API=http://127.0.0.1:8800
pw() {  # the persona's DEMO_PASSWORD_<USER_ID> from var/demo.env, never echoed
  local v; v="DEMO_PASSWORD_$(printf %s "$1" | tr '[:lower:]' '[:upper:]')"; printf %s "${!v:-$DEMO_PASSWORD}"
}
login() {  # login <user_id>: cookie jar in /tmp/sgw-<user_id>.jar
  curl -s -c "/tmp/sgw-$1.jar" -H "Origin: $API" -H 'Content-Type: application/json' \
    -d "{\"user_id\":\"$1\",\"password\":\"$(pw "$1")\"}" "$API/api/auth/login" >/dev/null
}
as() {  # as <user_id> <method> <path> [json body] [extra header]
  local csrf; csrf=$(awk '$6=="sgw_csrf"{print $7}' "/tmp/sgw-$1.jar")
  curl -s -b "/tmp/sgw-$1.jar" -X "$2" -H "Origin: $API" -H "X-CSRF-Token: $csrf" \
    -H 'Content-Type: application/json' ${4:+-d "$4"} ${5:+-H "$5"} "$API$3"
}
for u in ic_01 ops_dm_01 log_01 wtr_lead_01 wtr_comp_01 plan_etr_01 audit_01 admin_01; do login $u; done
```

Load `var/demo.env` into your shell without echoing it (`set -a; . var/demo.env; set +a`): each persona has its own `DEMO_PASSWORD_<USER_ID>`.

| # | Who | Call | Expect |
| --- | --- | --- | --- |
| 1 | `ic_01` | `GET /api/me` | `function: command`, `demo_mode: true` |
| 2 | `ops_dm_01` | `POST /api/scenario` `{"action":"seek","scenario_time":"2024-09-26T09:05:00Z"}` (advisory N) | 200; `plan_etr_01` gets 403 `SCENARIO_CONTROL_DENIED` |
| 3 | `admin_01` | `POST /api/admin/tokens` `{"name":"Golden path bridge","scopes":["decisions:read","commitments:read","webhooks:manage"],"expires_at":"<ISO>"}` | 201 with the token, shown once |
| 3a | bearer | `POST /v1/webhooks` `{"url":"https://127.0.0.1:8803/hooks/sgw","event_types":["DecisionApproved","CommitmentCreated","CommitmentDrifted"]}` | 201; the secret is in the `SGW-Webhook-Secret` header, start the example consumer with it (section 4) |
| 4 | `ops_dm_01` | `POST /api/threads` `{"module":"water"}`, then `POST /api/threads/{id}/runs` `{"graph":"water_continuity","input":{"advisory":"N"}}`, then `GET /api/threads/{id}/events` (SSE) | frames end with `run_end` status `no_action`: at N no rule fires |
| 5 | `ops_dm_01` | seek `2024-09-26T15:05:00Z` (advisory N+1) | the scenario jobs store the N+1 queue: PS-17 effective decide-by 03:29Z, `decide_now`; any open proposal whose case moved (e.g. a crew proposal signed by command at N) comes back as version 2 with its signatures voided and a `ProposalUpdated` event (SC-3) |
| 6 | `ops_dm_01` | water_continuity run with `{"advisory":"N+1"}` | two `approval_required` frames, then `run_paused`: the T3 priority (`command` + `water_operations`, proposer `system:rule:ps17_pressure_floor`) and the T3 BWA (`water_operations` + `compliance`) |
| 7 | any | `GET /api/proposals` | the decision queue: PS-17 priority `effective_decide_by_utc` 2024-09-27T03:29:00Z, `on_critical_path` true |
| 7a | any | `GET /api/proposals/{priority}` and `/clock` | `case.no_regret_verdict` `decide_now`; waterfall consequence 06:29Z (basis `water_twin.zone_drain_critical_node`) minus 150 min hookup = 03:59Z, effective 03:29Z, `bound_by_case_id` DC-D3-PS17-PRESSURE |
| 8 | `ops_dm_01` | `assess` run `{"advisory":"N+1"}` (module `decisions`) | `run_paused` on the T3 crew proposal (`command` + `logistics`) |
| 9 | `ic_01`, `wtr_lead_01` | `POST /api/proposals/{priority}/approvals` `{"decision":"approve","proposal_version":1,"action_hash":"<from the card>"}` with `If-Match: <ETag of the card>` | first `in_review` (remaining `water_operations`), then `approved` |
| 10 | `ops_dm_01` | `POST /api/runs/{run_id}/resume` `{}` and follow the SSE stream with `Last-Event-ID` | the run executes the priority: proposal `executed`, audit `execution_token_burned`; the run pauses again while the BWA waits |
| 11 | `wtr_lead_01`, `wtr_comp_01` | approve the BWA, then resume | `run_end` status `executed` |
| 12 | `ic_01` | `POST /api/proposals/{crew}/break-glass` `{"proposal_version":1,"action_hash":"...","reason":"Logistics chief unreachable; storm onset forces crew staging now."}` | 200, state `approved`; the card's `break_glass` shows the co-sign due in 24 h and the after-action flag |
| 12a | `log_01` | `POST /api/proposals/{crew}/cosign` `{}` | `cosigned_by: log_01`, `overdue: false`; resuming the assess run ends `executed` |
| 13 | `ops_dm_01` | seek `2024-09-28T18:00:00Z`; `plan_etr_01` runs `etr` `{}` (module `brief`) | `run_paused` on the T3 ETR (`command` + `operations`) |
| 13a | `ic_01`, `ops_dm_01` | approve, then `plan_etr_01` resumes | `run_end` `executed`; 12 `EtrPublished` events in the ledger (global + regions) |
| 14 | operator | restart the API with `FAULT_LLM_DOWN=1`; `GET /api/control/mode` | `degraded_mode: M2` within a few seconds |
| 14a | `ops_dm_01` | `sitrep` run `{}` | `sitrep_draft` artifact on path `m2` ("Template text: ..."), same slots as the LLM path; status `draft_ready`. Restart without the flag: back to `M0` |
| 15 | `ic_01` | seek `2024-10-06T02:00:00Z`; `after_action` run `{}` | evidence: clocks met/missed, break-glass uses 1 (co-signed on time 1), SC 103-314 report draft artifact |
| 16 | `audit_01` | `POST /api/audit/verify` `{}` | `ok: true`, `first_bad_seq: null` |
| 17 | `ic_01` | `POST /api/control/kill` `{"kill_level":"K1","reason":"..."}` | `K1`; `GET /api/control/capabilities` shows `approve_and_execute: false` |
| 17a | `ic_01` then `wtr_comp_01` | `POST /api/control/kill` `{"kill_level":"K0","reason":"..."}` | IC: 202 with `X-SGW-Restore: pending; ...; awaiting=compliance` (again: 409); compliance: 200, `K0` |
| 18 | bearer | `GET /v1/decisions`, `GET /v1/commitments` | PS-17 `executed`; commitments after step 20 |
| 19 | worker | `sgw integrations worker --once` (or the long-running worker) | the consumer verifies and records every `DecisionApproved` since the subscription |
| 20 | `ops_dm_01` | seek `2024-09-28T18:00:00Z`; `copilot` run `{"question":"When do I have to revise a global ETR that is already out?"}` (module `ask`) | assistant message on path `llm` with `DOM 14.206 Rev K` citations; `GET /api/threads/{id}/messages` lists the turn |
| 21 | watch | the commitment watch over the ledger (`sgw commitments replay-ps17` does the same for its own seeded decision) | `CMT-<priority>-V1` created, then `at_risk` and `drifted` (generator work order stuck in the helene_micro replay); `/v1/commitments` shows `drifted`; `CommitmentCreated` and `CommitmentDrifted` reach the consumer |

Approvals do not wake a paused run: the client calls `resume` (a wake-up only; the approval store decides). T3 proposals expire one hour after they were drafted or re-planned, in scenario time; the scenario jobs then list them as `expired`.

## 4. The example consumer

```bash
SGW_WEBHOOK_SECRETS=<secret from step 3a> uv run examples/webhook-consumer/consumer.py \
  --cert <server.pem> --key <server-key.pem> --port 8803 --out received.jsonl
SGW_INTEGRATION_KEY=<same key as the API> SGW_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8803 \
  SGW_WEBHOOK_CA_FILE=<ca.pem> uv run sgw integrations worker --once
```

The certificate must name `127.0.0.1`; the test makes a throwaway CA (`tests/integration/integrations_webhooks/tls_testkit.py`).

## 5. Run the automated version

```bash
SGW_TEST_DATABASE_URL=<admin DSN> uv run pytest tests/e2e_api -q
```

It creates its own scratch database and runtime login, an OPA container (or `SGW_TEST_OPA_URL`), the replay gateway, the API and the consumer on OS-assigned free ports, and drops them afterwards. It makes no live LLM call; a replay miss shows as an M2 template (asserted on the water brief, where it would be a regression).

## 6. Known gaps (from the golden-path round)

- The commitment watch has no runtime consumer of the ledger, so the API alone never creates commitments; the test runs the watch in-process. A drift on an executed decision cannot reopen it (`revise` refuses an executed proposal).
- Co-sign tasks have no HTTP listing (only `sgw audit cosign-tasks`); the proposal card carries the break-glass record.
