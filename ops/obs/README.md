# `obs` profile: platform monitoring (WP-39, D-054)

Optional Prometheus + Grafana for technical platform monitoring of the local stack: container CPU and memory, API request rate, latency and errors, Postgres connections, locks and size. Product health (feeds, pipelines, degraded modes) stays native in the Health module; this profile does not repeat it. It is not part of `core` or `make demo`, and nothing in the product depends on it. In production the same stack is the observability layer named in the PRD.

## Use

```
uv run sgw up            # core stack first
uv run sgw obs up        # obs services only; core containers are not recreated
uv run sgw obs check     # dashboards load with the admin login; scrape target health
uv run sgw obs down      # stops and removes only the obs services (add --volumes to drop their data)
```

`make obs-up`, `make obs-down` and `make obs-check` wrap the same commands. `uv run sgw up --profile obs` also works: it generates the obs credentials, starts core and obs together and then creates the `sgw_monitor` role.

| Service | Image (digest pinned, amd64 + arm64) | Host port | Networks | Memory limit |
| --- | --- | --- | --- | --- |
| grafana | `grafana/grafana:12.4.15` | 127.0.0.1:3001 | edge | 256 MiB |
| prometheus | `prom/prometheus:v3.15.1` | 127.0.0.1:9091 | edge, app | 256 MiB |
| cadvisor | `ghcr.io/google/cadvisor:0.56.2` | none | app | 160 MiB |
| postgres-exporter | `prometheuscommunity/postgres-exporter:v0.20.1` | none | app | 48 MiB |

## Admin → "System metrics ↗"

Link target: `http://127.0.0.1:3001/dashboards/f/sgw-platform/` (folder "SGW platform"), opened in a new tab, shown to the `admin` role only. The home dashboard is "SGW API: requests". Grafana asks for its own login (`sgw-admin`); the platform session is not shared with Grafana.

## Dashboards (provisioned, read-only)

| UID | Title | Source |
| --- | --- | --- |
| `sgw-api` | SGW API: requests | `sgw_http_*` from the API's `/metrics` (route templates, health probes excluded): rate, 5xx share, p50/p95/p99, top routes |
| `sgw-containers` | SGW containers: CPU and memory | cAdvisor, compose project `sgw` only, labelled by `service`: working set vs `mem_limit`, headroom, CPU, throttling, OOM kills |
| `sgw-postgres` | SGW Postgres: connections, locks, size | postgres_exporter: connections vs `max_connections`, locks by mode, database size, TPS, cache hit ratio, deadlocks |

Dashboards live in `ops/obs/grafana/dashboards/`; the provider has `allowUiUpdates: false`, so edits go through Git.

## Security

- **Credentials.** `sgw obs init` (also run by `sgw obs up`) writes `var/secrets/grafana.env` (Grafana admin) and `var/secrets/pg-exporter.env` (exporter DSN), mode 0600, git-ignored, never printed. `--rotate` replaces them; Grafana keeps its first admin password in its volume, so rotate with `sgw obs down --volumes`.
- **Grafana.** Anonymous access, sign-up and org creation off; plugin pre-install, update checks, analytics and news feed off; no embedding, no public dashboards or external snapshots.
- **Database.** The exporter logs in as `sgw_monitor` (`pg_monitor` only, connection limit 3), created idempotently by `sgw obs init` through the admin DSN. It cannot read application tables, but `pg_monitor` includes `pg_read_all_stats`, so it sees the query text of every session in `pg_stat_activity`; treat Prometheus and the exporter as holding SQL statements (the exporter's default collectors do not export query text).
- **API metrics.** `/metrics` answers only direct requests on the internal `app` network. Requests through the Caddy relays carry `X-Forwarded-For` and get 404, so host port 8000 does not expose it. It is not a K3 contract route.
- **cAdvisor:** see "cAdvisor risk" below before starting the profile.
- **Prometheus** has no login; it listens on 127.0.0.1 only. Retention is 3 days or 512 MB.

## cAdvisor risk

> **Warning.** With the `obs` profile running, the `cadvisor` container can control the Docker engine of this machine. Start the profile only on your own single-user machine, stop it when you are done (`uv run sgw obs down`), and never run it on a shared or production host.

- What it mounts: `/sys` (read-only, cgroup statistics), `/var/run/docker.sock` and `/run/containerd/containerd.sock` (read-only). A `:ro` mount does not limit what a client can ask over a socket: anyone who controls the process can start a privileged container and own the host.
- What was removed (security audit M1): root (it runs as uid 65534 with only group 0, which the sockets need on Docker Desktop), every capability (`cap_drop: ALL`, `no-new-privileges`), the `/var/lib/docker` mount, a writable root filesystem.
- Why the sockets stay: measured on Docker Desktop 29.7 with cAdvisor 0.56.2, per-service labels (`container_label_com_docker_compose_service`, which every panel of `sgw-containers` uses) appear only when both sockets are mounted (13 labelled series rootless); with one socket or with `/sys` alone it reports anonymous cgroup ids only. A cgroup-only setup therefore leaves the container dashboard without service names.
- Exposure: cAdvisor has no host port; it sits on the internal `app` network and only Prometheus scrapes it.
- Production: use the kubelet's built-in cAdvisor endpoint (or the cloud provider's container metrics); no container gets the runtime socket.
