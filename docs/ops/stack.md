# Local stack

The prototype runs as one Docker Compose project named `sgw`. Every user command is either `docker compose ...` or `uv run sgw <command>`; `make` targets only wrap the CLI. The same commands work on macOS, Linux and Windows (Docker Desktop with WSL 2).

## Quickstart

```
uv sync
uv run sgw doctor        # what is missing on this machine, with the fix for this OS
uv run sgw bootstrap     # generate local credentials into var/ (git-ignored)
uv run sgw up            # start the core profile and wait until every service is healthy
uv run sgw db-smoke      # prove extensions, PostGIS, H3, routing, vectors, LangGraph checkpointer
uv run sgw migrate       # apply db/migrations in order
```

## Demo mode

The stack starts with `DEMO_MODE=0`: Secure session cookies, no persona switching, no `/api/docs` (unless `SGW_API_DOCS=1`). The demo is started explicitly:

```
uv run sgw bootstrap          # also writes var/demo.env: one generated password per persona (0600)
uv run sgw up --demo          # DEMO_MODE=1, plain-http cookies for 127.0.0.1, /api/docs on
uv run sgw migrate
uv run sgw seed               # users (each with its own password from var/demo.env) + Helene proposal
```

- Passwords: `var/demo.env` holds `DEMO_PASSWORD_<USER_ID>` for every persona in `data/seed/users.yaml` (for example `DEMO_PASSWORD_IC_01`). `uv run sgw bootstrap --demo-password <value>` (at least 3 characters, local demo only) sets every persona to that value and lowers `DEMO_PASSWORD_MIN_LENGTH` to its length; seed again after it. The sign-in page names the public demo password (`123`) only when `GET /api/auth/config` returns `demo_password`, which the API sends in demo mode only when every account in the database verifies against it. Open the file to log in as a persona; no command prints them. Re-running bootstrap keeps existing values; a legacy shared `DEMO_PASSWORD` is kept and used only for personas without their own value. `uv run sgw seed` and `uv run sgw api seed-users` read the file by name.
- Banner: with `DEMO_MODE=1` every API response carries `X-SGW-Demo-Mode: synthetic data; demo identities`, which the UI shows as the demo banner.
- Leaving the demo: `uv run sgw up` (without `--demo`) recreates the api with `DEMO_MODE=0`.

### Load moment from the UI

"Load moment" (`POST /api/demo/goto`) replaces the api's database with a built bookmark copy, so the api needs a server role that may create and drop databases. Run `uv run sgw bootstrap` once (it writes `var/secrets/demo_goto.env`, 0600, never committed; `--rotate` replaces the password), then `uv run sgw up --demo` (or `uv run sgw reset --yes --demo`): after compose it creates or updates the demo-only role `sgw_demo_goto` (LOGIN, CREATEDB, member of `sgw` and `pg_signal_backend`, connection limit 3, no superuser or role creation) and passes `SGW_DEMO_GOTO_DSN` to the api container only in demo mode. `uv run sgw up` without `--demo` passes an empty DSN and sets the role `NOLOGIN`, so it cannot be used while `DEMO_MODE` is off. Bookmarks must be built first (`uv run sgw demo build`).

Stop with `uv run sgw down` (data kept). `uv run sgw reset --yes` deletes the stack's volumes, starts it again and migrates. `uv run sgw stats` prints memory per container and host swap.

Raw Compose equivalent of `sgw up`, run from the repository root after `sgw bootstrap`:

```
docker compose --env-file var/compose.env --profile core up -d --wait
```

Passing `--env-file var/compose.env` also stops Compose from reading the project `.env` for variable interpolation.

## Commands

| Command | Does |
| --- | --- |
| `sgw doctor [--json]` | Checks Python, uv, git, Docker daemon (Engine >= 25, for healthcheck `start_interval`) and its memory, Compose (>= 2.24), buildx, Node (>= 22) and pnpm, ports 8080/8000/5434/5001, host memory, swap and disk, generated credentials and the LLM key file (existence only). Exit 1 when a check fails. Each gap comes with the fix for the current OS. |
| `sgw bootstrap [--rotate]` | Writes `var/secrets/{postgres,app,host}.env` (mode 0600, folders 0700) with random 43-character passwords, and `var/compose.env` with paths only. Idempotent: existing passwords are kept unless `--rotate`. Never reads or writes `.env`. |
| `sgw up [--profile core|full] [--build]` | `docker compose ... up -d --wait`; fails when a service is not healthy within the timeout. |
| `sgw down` | Removes containers and networks; keeps volumes. |
| `sgw reset [--yes]` | `down --volumes`, `up`, `migrate`. Asks for confirmation without `--yes`. |
| `sgw stats [--markdown FILE --label NAME]` | `docker stats` per service with limits and totals, plus host memory and swap; can append the table to a Markdown file. |
| `sgw db-smoke [--keep]` | Creates a scratch database, creates the eight extensions, a hypertable, a DiskANN index, an exclusion constraint, a PostGIS point, an H3 cell, runs `PostgresSaver.setup()` and logs in as the owner role; drops the scratch database. Exit 1 on any failed check. |
| `sgw migrate [--database NAME] [--create] [--dry-run]` | Applies `db/migrations/NNNN_<owner>_<name>.sql` in name order, each in its own transaction, recorded with its SHA-256 (over LF-normalised bytes, so CRLF checkouts match) in `public.schema_migrations`. Refuses an edited applied file, a duplicate number and a file numbered below the last applied one. `--dry-run` lists pending files and creates nothing, not even the ledger. See "No-transaction migrations" below. |

New commands: add `src/sgw/cli/commands/<name>.py` exposing `app = typer.Typer()`. Its commands appear at the top level; `typer.Typer(name="group")` mounts them under `sgw group ...`. A duplicate command name stops the CLI at start-up.

## No-transaction migrations

A migration whose first line is `-- sgw:no-transaction` runs outside a transaction, for statements Postgres refuses inside one (for example `CREATE INDEX CONCURRENTLY`). Such a file must hold **exactly one statement**; `sgw migrate` rejects it otherwise, because a failure halfway would leave the first statements applied and the file unrecorded. Write the statement so a rerun is safe, for example `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...`. TimescaleDB does not allow `CONCURRENTLY` on hypertables.

## One stack per machine

The compose project name is fixed (`sgw`), so every checkout on a machine talks to the same containers, volumes and database. `uv run sgw reset` deletes the volumes; `uv run sgw down` stops the stack.

## Services (profile `core`)

| Service | Image | Host port | Networks | Memory limit |
| --- | --- | --- | --- | --- |
| caddy | `sgw/caddy` (built from `docker/caddy/Dockerfile`: web app on the digest-pinned `caddy:2.11-alpine`) | 127.0.0.1:8080 (UI, `/api`), 127.0.0.1:8000 (api relay) | edge, proxy (fixed IP) | 64 MiB |
| api | `sgw/python`, `uvicorn sgw.api.app:create_app --factory` | via caddy 8000 | app, proxy | 900 MiB |
| worker | `sgw/python` (image placeholder process; jobs run from the CLI) | none | app | 1,024 MiB |
| audit-checkpoint | `sgw/python`, `python -m sgw.cli.main audit checkpoint --every 60` | none | app | 256 MiB |
| llm-gateway | `sgw/python`, `python -m services.llm_gateway --host 0.0.0.0 --port 8100` | none | app, egress | 192 MiB |
| opa | `openpolicyagent/opa:1.22.4-static` | none | app | 128 MiB |
| postgres | `timescale/timescaledb-ha:pg18.6-ts2.31.0` | via pg-port 5434 | app | 1,536 MiB |
| pg-port | `alpine/socat:1.8.0.3` | 127.0.0.1:5434 | edge, app | 32 MiB |
| mlflow | `sgw/mlflow` (from `ghcr.io/mlflow/mlflow:v3.18.0`) | none by default; 127.0.0.1:5001 via `mlflow-port` (profile `mlflow-ui`) | app | 768 MiB |
| mlflow-port (opt-in) | `alpine/socat:1.8.0.3` | 127.0.0.1:5001 | edge, app | 32 MiB |

Services without a profile form `core`, so a plain `docker compose up` starts the core stack; `full` services (observability, fault injection) carry `profiles: [full]`.

## Boundaries

- **Networks.** `app` is `internal: true`: api, worker, opa, postgres and mlflow have no route out (checked: a TCP connect to an Internet host fails from each). Only `llm-gateway` (model provider) and `webhooks` (signed deliveries to subscriber endpoints) also join `egress`. Docker cannot publish ports from an internal-only network (measured on Docker 29.7), so host access goes through two relays that sit on both `edge` and `app`: caddy for the api (8000) and socat for Postgres (5434). Every published port binds to 127.0.0.1. The relays send `X-Content-Type-Options`, `X-Frame-Options: SAMEORIGIN` and `Referrer-Policy` and drop `Server`; the full CSP is on the UI origin (8080) only, because the MLflow UI uses inline scripts. The api is reached by Caddy over a dedicated internal `proxy` network (`${SGW_PROXY_SUBNET:-10.213.37.0/29}`, Caddy fixed at `${SGW_CADDY_PROXY_IP:-10.213.37.6}`, dynamic addresses confined to `${SGW_PROXY_DYNAMIC_RANGE:-10.213.37.0/30}` so the api can never take Caddy's address, outside Docker's default address pools; override both if that range is in use), and uvicorn trusts `X-Forwarded-*` only from that address (`--forwarded-allow-ips`), so no other container can spoof a client IP for the login rate limits or logs.
- **MLflow** has no authentication, so it is not published by default. `uv run sgw up --profile mlflow-ui` adds the `mlflow-port` relay on 127.0.0.1:5001 (for the MLflow UI or host-side tracing); anyone on this machine can then read and write experiments and the registry, so stop it again with `uv run sgw up` (the relay is removed as an orphan). Services in the stack reach `http://mlflow:5001` on `app` either way.
- **Credentials.** Generated by `sgw bootstrap`; none are committed and none have defaults. Postgres gets `postgres.env` (superuser, owner, runtime and gateway passwords for the init script); api and worker get `app.env` (the `sgw_runtime` DSN only, never the owner); llm-gateway gets `gateway.env` (only `SGW_LLM_CALL_DSN`, the `sgw_gateway` DSN) next to its key file, and never the owner or runtime credentials. The Anthropic key lives only in `SGW_ENV_FILE`, never in a generated file. `host.env` holds the owner DSN (`SGW_DATABASE_URL`, for migrations and host jobs), the runtime DSN, the gateway DSN (`SGW_GATEWAY_DATABASE_URL`) and the admin DSN.
- **API key.** Only `llm-gateway` reads the LLM key file, through `env_file: ${SGW_ENV_FILE:-./var/llm.env}` with `required: false`. `sgw bootstrap` creates `var/llm.env` as an empty placeholder (no key: replay mode only), so CI and fresh clones need nothing. For live or record mode, point the gateway at your own file once: `SGW_ENV_FILE=/absolute/path/to/.env uv run sgw bootstrap` (the path is stored in `var/compose.env`), then `uv run sgw up`. No command opens the file; `doctor` and `bootstrap` only test that it exists.
- **Containers.** Non-root users (10001 sgw, 10002 mlflow, 65534 caddy and socat, 1000 opa and postgres), read-only root filesystems except Postgres, `cap_drop: ALL` (caddy keeps `NET_BIND_SERVICE` for its file capability), `no-new-privileges`, PID limits, rotated JSON logs, `memswap_limit` equal to the memory limit so a container cannot swap.
- **Images.** Every base pinned by digest. The Python image is built from `uv.lock` with `uv sync --frozen --no-dev`; the embedding model `BAAI/bge-small-en-v1.5` is baked in at build time because api and worker have no egress at run time. Build context is an allowlist (`docker/python/Dockerfile.dockerignore`): `pyproject.toml`, `uv.lock`, `src/`, `services/` and two helper scripts.

## Audit chain wiring

The audit chain is signed by an Ed25519 key and anchored to files:

| Host path | Container path | Mode | Used by |
| --- | --- | --- | --- |
| `var/secrets/audit/<key>.pem` | `/run/secrets/sgw-audit` (read-only) | dir 0700, key 0600 | audit-checkpoint only (the api never mounts the private key) |
| `var/audit/keyring.json` (public keys, active id) | `/var/lib/sgw/audit/keyring.json` | 0644 | api (verify), audit-checkpoint |
| `var/audit/anchors/<namespace>/<stream>/<seq>.json` | `/var/lib/sgw/audit/anchors` | writable for audit-checkpoint, read-only mount in the api | audit-checkpoint writes, api verifies |

- `uv run sgw bootstrap` keeps the active key when the keyring has one (also one made by `uv run sgw audit keygen`) and creates one only when there is none; a keyring that names a key whose `.pem` is missing is an error, never a silent rotation. A key created by bootstrap is not recorded in the chain (the database may be down); rotations go through `uv run sgw audit keygen`, which records them.
- bootstrap writes `SGW_AUDIT_ACTIVE_KEY` (the pin: the signer refuses a keyring whose active key differs) and `SGW_AUDIT_DATABASE_URL` (the `sgw_runtime` DSN to `postgres:5432/sgw`, never the owner) into `var/compose.env`, which is therefore 0600.
- Ownership across OSes: Docker Desktop (macOS, Windows) maps bind-mount ownership, so the image user 10001 reads the 0600 key and writes anchors. A Linux engine enforces host uids, so bootstrap writes `SGW_RUN_UID`/`SGW_RUN_GID` = the invoking user and api and audit-checkpoint run as that uid (default 10001); when bootstrap runs as root it keeps 10001 and chowns the audit dirs to it.
- `uv run sgw doctor` checks the active key (file present, not readable by others), the pin in `compose.env`, and that the anchors dir is writable.
- The api runs with `SGW_AUDIT_SIGNING=0`: after a break-glass commit it no longer signs on the spot; `audit-checkpoint` signs the new head within its 60 s interval. `POST /api/audit/verify` needs only the public keyring and the anchors.
- The checkpoint loop signs only when the chain has grown; on an empty or unchanged chain it logs `head already signed`.

CI-safe defaults: the audit variables default to empty and `gateway.env` is optional in `compose.yaml`, so `docker compose config` renders in CI with only the dummy `app.env` and `postgres.env`. Locally `uv run sgw up` refuses to start until bootstrap has written `postgres.env`, `app.env`, `gateway.env`, `SGW_AUDIT_ACTIVE_KEY` and `SGW_AUDIT_DATABASE_URL`.

## Readiness checks

| Service | Healthcheck |
| --- | --- |
| postgres | TCP login on 127.0.0.1 with the superuser password (the init-time server listens on the socket only, so this cannot pass before init ends), database `sgw` exists, all eight extensions available, `timescaledb` preloaded |
| pg-port | TCP connect to `postgres:5432` through the relay's network |
| api, worker | `GET /readyz`; the placeholder answers 503 when its database DSN does not connect |
| llm-gateway | `GET /healthz` (mode, key present as a boolean, breaker state) |
| opa | `opa eval` of `http.send` to its own `/health` (the static image has no shell or curl) |
| mlflow | `GET /health` |
| caddy | `GET /healthz` |
| audit-checkpoint | active signing key loads (and matches the `SGW_AUDIT_ACTIVE_KEY` pin), anchors dir writable, runtime DSN connects |

## Database layout

Roles:

| Role | Login | Purpose |
| --- | --- | --- |
| `sgw` | yes | owner of database `sgw`; runs migrations; CREATEDB, CREATEROLE |
| `sgw_app` | no | group role the migrations grant runtime rights to (audit tables: SELECT, INSERT only) |
| `sgw_readonly` | no | group role with SELECT grants |
| `sgw_runtime` | yes | api and worker login, member of `sgw_app`, connection limit 30; no CREATE, no UPDATE/DELETE on audit tables |
| `sgw_llm_writer` | no | group role; migration 3000 grants it INSERT on `llm_call` only (no SELECT, so the gateway uses plain INSERT) |
| `sgw_gateway` | yes | llm-gateway login, member of `sgw_llm_writer` only, connection limit 5 |

`docker/postgres/initdb/100_sgw_roles.sh` creates all six and database `sgw` on an empty volume. Because it never runs again on an existing volume, `sgw migrate` repeats the same setup as superuser before the first file (idempotent): it creates any missing role, resets the `sgw_runtime` and `sgw_gateway` passwords to the ones in `var/secrets/`, grants CONNECT on the target database, and creates the eight extensions. Migrations then run as `sgw`, so tables belong to the owner role. Credentials made before `sgw_runtime` or `sgw_gateway` existed are upgraded by `uv run sgw bootstrap` (existing passwords kept), then `uv run sgw migrate` and `uv run sgw up`; the volume is kept.

Server settings: `shared_buffers=384MB`, `max_connections=60`, `work_mem=16MB`, `maintenance_work_mem=64MB`, `effective_cache_size=768MB`, `idle_in_transaction_session_timeout=30s`, `timescaledb.telemetry_level=off`, `log_min_duration_statement=500ms`, `shm_size: 256m`. `NO_TS_TUNE=true` keeps these from being rewritten at init.

## Known limits

- worker runs the image's placeholder process (`/opt/sgw/placeholder.py`); background loops (webhook worker, SAA jobs, commitment watch) are started from the CLI until the worker gets its `command:`.
- llm-gateway mounts `data/fixtures/llm` read-only (replay recordings; record mode runs on the host per `docs/13-llm-gateway.md`) and writes its spend ledger to `var/llm/llm_spend.csv` (`LLM_SPEND_CSV`). `var/llm/` is 0700 and owned by the uid the gateway runs as (`SGW_RUN_UID`: the invoking user on Linux, 10001 on Docker Desktop; a root bootstrap chowns it to 10001).
- The worker has no egress.
- MLflow keeps metadata in SQLite inside its volume and runs with `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` (the 3.x job executor alone pushed it past 512 MiB). Server-side scorer jobs are not used.
