# SGW Resilience Decision Platform

Kacper Kozik, prepared for SGW

> This repository demonstrates the platform for SGW (Southeastern Grid and Water), a fictional power and water utility from the assessment case. The same approach generalises to other problems, business areas and companies that need to collect and combine information from many sources, turn it into decisions with clear deadlines and owners, and keep an auditable record of who decided what and why.

A decision platform for a combined power and water utility during severe weather. Every open decision gets a computed decide-by time with its basis ("decide by 23:29 ET, because the feeder is likely lost at ... and the generator needs ... to hook up"). A decision moves forward only after the people its approval level requires have signed, and every step lands in a tamper-evident audit trail. Ask AI answers questions about the storm, the decisions and the platform in plain language, with links into the right page.

It is built for the people who run a storm response at a utility: the Incident Commander, electric and water duty staff, logistics, compliance, the ETR (restoration time) specialist and the executive who reads the briefing. The prototype replays Hurricane Helene (September 2024) on synthetic SGW data calibrated to public sources; Hurricane Ian (2022) runs as a second, scripted exercise. It runs on one laptop and needs no API key: AI answers replay from committed recordings.

## Read more in the docs folder

This README tells you how to run the demo. How the platform works, for whom, and how far to trust it is explained in the [`docs`](docs/README.md) folder, one topic per file:

| | |
| --- | --- |
| [01. Overview](docs/01-overview.md) | What the platform does, for whom, what is real and what is synthetic |
| [02. Roles and decision workflow](docs/02-roles-and-decision-workflow.md) | Roles, decision clocks, proposals, sign-off by two teams, emergency approval, audit |
| [03. Architecture](docs/03-architecture.md) | Containers, networks, trust boundaries, data flow, technology choices |
| [04. Data](docs/04-data.md) | Public sources, synthetic SGW data, ingestion, replay and scenarios |
| [05. Ask AI agent system](docs/05-ask-ai-agent-system.md) | The agent graph, models per step, tools, answer checks, replay and live mode |
| [06. Outage forecast](docs/06-outage-forecast.md) | Method, ranges, evaluation |
| [07. Surge and anomaly detection](docs/07-surge-and-anomaly-detection.md) | Detectors, signals, thresholds, confirmation logic |
| [08. Computer vision](docs/08-computer-vision.md) | Damage photo model, scores and review order |
| [09. Water network model and what-if](docs/09-water-network-model-and-what-if.md) | Water twin, pressure limits, boil water notices, what-if grid |
| [10. Crew optimisation and restoration estimates](docs/10-crew-optimisation-and-restoration-estimates.md) | Crew pre-positioning, dispatch, restoration time ranges |
| [11. Security, governance and human oversight](docs/11-security-governance-and-human-oversight.md) | Permissions, policy, audit, what the AI may and may not do |
| [12. Assumptions, limitations and improvements](docs/12-assumptions-limitations-and-improvements.md) | What is assumed, what is missing, what comes next |
| [13. LLM gateway](docs/13-llm-gateway.md) | The single path to the model provider, budget caps, record and replay |
| [14. Code tour](docs/14-code-tour.md) | The key files on the demo path, in reading order |
| [Product requirements document (PDF)](docs/deliverables/prd.pdf) | Deliverable 1 |
| [Executive briefing (PDF)](docs/deliverables/executive-briefing.pdf) | Deliverable 2 |

## Quickstart

Everything runs locally in Docker on one machine. Every port binds to 127.0.0.1, so nothing is reachable from other machines. Ask AI works without an API key (see [Ask AI](#ask-ai-replay-and-live)).

### 1. Install the prerequisites

You need Docker (Docker Desktop, or Docker Engine 25+ with Compose 2.24+) with at least 8 GB of memory and 15 GB of free disk, and [uv](https://docs.astral.sh/uv/), which installs Python 3.12 by itself. Node and pnpm are not needed: the web app is built inside its Docker image.

**macOS** (Apple silicon or Intel). Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/), start it, and give it at least 8 GB of memory (Settings, Resources). Then install uv in a terminal:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Linux.** Install [Docker Engine and the Compose plugin](https://docs.docker.com/engine/install/), add your user to the `docker` group (log out and in again), then install uv:

```sh
sudo usermod -aG docker "$USER"
```

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows.** Use WSL 2. In PowerShell as administrator, install it with Ubuntu and restart when asked:

```powershell
wsl --install -d Ubuntu
```

Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with the WSL 2 backend and turn on the integration for Ubuntu (Settings, Resources, WSL integration). Open the Ubuntu terminal and run every command below there, with the project in the Linux file system (for example `~/sgw`), not under `/mnt/c`, because bind mounts from the Windows drive are slow. Install uv in Ubuntu:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal after installing uv so that the `uv` command is found.

### 2. Get the project

From the zip, unpack it and open a terminal in the unpacked folder (on Windows, copy the zip into Ubuntu first, for example with `cp /mnt/c/Users/<you>/Downloads/<file>.zip ~/`, then `unzip` it there). From Git, clone it and enter the folder. All commands below run from the project root.

### 3. Prepare and check the machine

```sh
uv sync
```

```sh
uv run sgw doctor
```

`doctor` checks Docker, memory, disk and ports and prints the fix for each gap. On the first run it also reports the credentials and the audit key as missing; the next command creates them. Then create the local credentials (written to `var/`, which is never committed). With `--demo-password 123` every demo person gets the password `123`:

```sh
uv run sgw bootstrap --demo-password 123
```

### 4. Start the demo

Build and start the stack. The first run builds three images and pulls the rest, which takes several minutes; later starts take under a minute. The command starts Postgres first, creates the database tables, then starts the other services and returns when every service is healthy.

```sh
uv run sgw up --build --demo
```

Check that the database is up to date (after `up` this applies nothing; it is needed again after a reset) and load the demo data (users, reference data, map, the Helene replay, decision queue, document index, about 2 minutes):

```sh
uv run sgw migrate
```

```sh
uv run sgw seed --demo
```

Download the full-size damage photos (about 60 MB, CC BY 4.0, needs Internet) into `var/cv/`. The zip package already contains them, so skip this step there. Without them the app shows the committed small thumbnails:

```sh
uv run sgw photos
```

Build the story moments (about 4 minutes) and open the demo at the moment the forecast changes:

```sh
uv run sgw demo build --no-capture
```

```sh
uv run sgw demo goto at-n1 --yes
```

### 5. Open the app

Open **http://127.0.0.1:8080** in a browser and sign in (see [Sign in](#sign-in)). With the password above, pick a person and the page fills in the password `123`.

### 6. Stop or start again

Stop the stack and keep the data:

```sh
uv run sgw down
```

Start it again later with `uv run sgw up --demo`. To delete the local data and start from zero, run `uv run sgw reset --yes --demo` and then the commands of step 4 from `migrate` on. Service list, ports and memory limits: [docs/ops/stack.md](docs/ops/stack.md).

### Sign in

The sign-in page shows seven story people (Incident Commander, Duty Manager, Water Incident Lead, Water Compliance Officer, Logistics Section Chief, ETR Specialist, Executive) and, under "Other accounts", four more (Duty Manager (relief), Auditor, Platform Admin, Data and Models Owner). Picking a person fills the user ID.

- With `--demo-password 123` every password is `123`; the page then fills it and says so.
- Without it, each person has a generated password in `var/demo.env` (line `DEMO_PASSWORD_<USER_ID>`, for example `DEMO_PASSWORD_IC_01`); the page shows no password hint, so type the value from the file.

The short password is for this local demo only: the stack runs on 127.0.0.1 with synthetic people, and outside demo mode the minimum length is 8. The roles in one sentence: one person proposes, two people from two different functions sign, the executive only reads, the auditor checks the record, and the commander may approve alone in an emergency, with a second function co-signing within 24 hours.

### Demo moments

The story is stored as eight moments: before the previous advisory, the previous advisory, the latest advisory just after the reorder (`at-n1`), PS-17 signed, morning after landfall, ETR published, boil water notices lifted, after-action review. `uv run sgw demo list` shows them. The Incident Commander and the two Duty Managers can also switch moments in the app: the scenario chip in the top bar, a moment under "Replay", then "Load moment". Loading a moment replaces the demo database with a stored copy in seconds; other roles see the active moment read-only.

Scripted exercise decisions (synthetic) are layered on the same timeline (`SGW_SCENARIO_INJECTS=1`, on in the stack), so every signing role has something to decide. When a later moment is loaded, the earlier exercise decisions are already signed in the exercise script.

### Second scenario: Hurricane Ian (2022) exercise

The same presenters open the scenario chip, pick Hurricane Ian under "Other scenarios" and confirm with "Load scenario". Everyone using the demo then works in the exercise, a day before landfall; other roles see the active scenario in the chip read-only. To return, a presenter picks Hurricane Helene in the same list (this reloads the saved `at-n1` moment, with its decisions).

- **Real:** the storm track (NOAA HURDAT2 best track; the map draws the track only, because no cone archive for Ian is shipped).
- **Scripted (synthetic), and labelled "Scripted exercise data (synthetic)":** three moments (day before landfall, landfall near Georgetown, morning after landfall), customers out per county, four critical facilities, 54 crews and eleven timed decisions with rule deadlines, so every signing role signs at least one.
- **Works for every role:** Decisions (sign, co-sign, send back, emergency approval), Map, Briefing, Notifications, Crews (read-only roster), After-action (the exercise's deadlines, emergency approvals and timeline) and Ask AI (answers from the exercise data).
- **Not modelled for this scenario:** Forecast and Water say so on the page. The heat wave (July 2024) and Table Rock wildfire weather (March 2025) entries stay readiness previews.

### Ask AI: replay and live

The stack starts in `replay_then_live` mode. A question that was recorded (the starter questions and the demo questions on Helene) is answered from `data/fixtures/llm` at no cost and with no key. A replayed answer takes as long as the live call took when it was recorded (at most 12 s per model call), and the page names each step while it runs. A question nobody recorded, and every question in the Ian exercise, needs a live model call:

- **Without a key** the gateway cannot call the model, so Ask answers from code: the same facts and links, in shorter template text. Everything else in the platform works the same.
- **With a key** the gateway reads it from the file `llm.env` in the project root. The zip package already contains this file with an empty `ANTHROPIC_API_KEY=` line; in a Git clone, create it from the template:

```sh
cp llm.env.example llm.env
```

Open `llm.env` in a text editor, paste the key after `ANTHROPIC_API_KEY=` (no quotes, no spaces), save, and apply it:

```sh
uv run sgw bootstrap --demo-password 123
```

```sh
uv run sgw up --demo
```

`bootstrap` keeps the existing credentials and only records where the key file is; `up` recreates the gateway with the key. A key file in another place also works: `SGW_ENV_FILE=/absolute/path/to/file uv run sgw bootstrap`. Only the `llm-gateway` container reads the file, and `llm.env` is never committed (it is in `.gitignore`). Live answers are cached locally in `var/llm/live_cache/`, so the same question costs once. The gateway stops live calls at a daily cap of 30 USD and at a 40 USD running total; for a lower daily cap add a line such as `LLM_DAILY_CAP_USD=5` to the same file. Spend so far: `uv run sgw llm-spend`. Details: [docs/13-llm-gateway.md](docs/13-llm-gateway.md).

### Operating system notes

| OS | Notes |
| --- | --- |
| macOS (Apple silicon or Intel) | Docker Desktop. This is where the prototype was built and measured. |
| Linux | Docker Engine 25+ with the Compose plugin; your user in the `docker` group. |
| Windows | WSL 2 with Ubuntu and Docker Desktop (WSL 2 backend, Ubuntu integration on). Run every command in the Ubuntu terminal with the project in the Linux file system. PowerShell also works for the `uv run sgw` commands; there, set a key file path with `$env:SGW_ENV_FILE="C:\path\to\file"; uv run sgw bootstrap` and use `curl.exe` instead of `curl`. |

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `sgw doctor` reports a failed check | Follow the fix it prints; it knows the OS. |
| `uv: command not found` | Open a new terminal after installing uv, or run `source $HOME/.local/bin/env`. |
| `run 'uv run sgw bootstrap' first` | Credentials are missing in `var/`; run `uv run sgw bootstrap --demo-password 123`. |
| A port is in use (8080, 8000, 5434) | Stop the other program, or stop an older run of this stack with `uv run sgw down`. |
| A service is not healthy within the timeout | Give Docker at least 8 GB of memory; check `docker compose --env-file var/compose.env logs <service>`; run `uv run sgw up --demo` again. |
| Sign-in says the password is wrong | See [Sign in](#sign-in). After `uv run sgw bootstrap --demo-password ...` on a demo that was already seeded, run `uv run sgw seed --demo` and `uv run sgw demo build --no-capture` again. |
| "Load moment" is missing or fails | The stack must run with `--demo`, and the moments must be built (`uv run sgw demo build --no-capture`). |
| `demo build` fails at story step 9 | A known timing flake (a rule proposal raised asynchronously); run the same command again. |
| Photo previews are small | Without `uv run sgw photos` the preview uses the committed 240 px thumbnails; the command downloads the full images once (needs Internet). |
| Ask gives short template answers | The question was not recorded and no key is set: see [Ask AI](#ask-ai-replay-and-live). |
| Start again from zero | `uv run sgw reset --yes --demo`, then step 4 from `migrate`. |

## What you see

| Page | What it is for |
| --- | --- |
| Decisions | The queue: every open decision with its decide-by time, severity, timing (Act now, Before next advisory, Can wait) and signatures; detail tabs Deadline, Signatures, Sequence, History |
| Map | Assets, outages, the official NHC cone and track, river gauges, observed gusts and NWS warnings, with a history bar over the advisories |
| Forecast | County outage ranges and the forecast against what happened, on the same history bar |
| Crews | Crew plan options, dispatch with sign-off, staging yards and the damage-photo queue |
| Water | Pressure zones, pump stations, tank time left, boil-water notices |
| Ask AI | Questions in plain language, answers with deep links, inline photos and follow-ups |
| Briefing | The executive view: key numbers and the decisions that need the top level |
| After-action | Clocks met and missed, emergency approvals, lead times against assumptions, public storm records |
| System health, Readiness, Notifications, Admin, Help | Platform state and stop controls, the pre-season review, per-person notices, users and AI settings, glossary |

## The decision story: PS-17

PS-17 is a water pump station whose pressure zone serves Tallowbranch hospital (synthetic). When Helene's winds take down its feeder, the station needs a portable generator, and the generator needs a fuel truck. Each action has a lead time, so each has a latest safe time to decide. All values below are synthetic.

1. **Advisory N.** The platform computes the consequence time from the hazard ensemble (when the feeder is likely lost) and the water twin (how long the tank keeps the hospital connection above the state pressure floor). Subtracting the generator hookup lead time, and binding by the downstream pressure case, gives a decide-by of 00:45 ET (04:45Z) on 27 September. Timing: **Can wait**, because the next advisory arrives before the earliest safe time.
2. **Advisory N+1.** The forecast shifts. The same calculation gives 23:29 ET on 26 September (03:29Z), 1 h 16 min earlier, and the timing becomes **Before next advisory**: waiting for the next one would be too late. The Deadline tab and `uv run sgw clocks waterfall` show every term with the model or rule that produced it.
3. **Approval.** Feeder or generator priority for PS-17 needs two signatures: one from command and one from water operations, neither of them the proposer. A material change to the proposal voids earlier signatures. The boil-water rules draft a notice that water operations and compliance sign.
4. **Commitment.** After approval the platform tracks the milestones (crew dispatched, generator running, pressure held). When a milestone slips past tolerance, the decision reopens as a new version.
5. **After action.** The review lists clocks met or missed and any emergency approvals, and compares actual lead times with the assumed ones; it proposes new values as a policy change and never applies them.

The same mechanics run crew pre-positioning, field resource orders, boil-water notices and their lifting, the global restoration time (ETR) and the after-action review.

## Architecture

One Docker Compose project. The core profile has ten services: Caddy (the only HTTP entry, serves the web app), the API (FastAPI, SSE, agent runs, approvals, scenario jobs), a webhook delivery worker, a worker placeholder, an audit checkpointer, the LLM gateway (the only service with Internet egress), OPA for policy, Postgres 18 with TimescaleDB, PostGIS and pgvector, a Postgres port relay and MLflow. Optional profiles add an MLflow UI relay and Prometheus with Grafana.

- **Models predict, code computes, the LLM explains.** Forecasts come from statistical and physical models; clocks, rankings and rules are deterministic code; AI text only fills slots with values from code, and a verifier rejects any number or id it cannot trace.
- **Authority is a database row.** OPA sets the approval level; Postgres triggers check approvals, execution tokens and effects again.
- **One egress.** Only the gateway reaches the model provider, after a data-class policy check.
- **Ask AI is a read-only team.** A router and a wide gate decide the path; a planner sends the question to up to three specialist workers (forecast, grid, water, policy, data quality) in parallel; one synthesis step writes the answer; code adds the links. A guide path answers "where is", "what does this mean" and photo requests, and declines unrelated topics, write requests and injected instructions with suggestions instead of a bare refusal. Follow-ups are rewritten into standalone questions, and the answer comes in the language of the question. Ask knows the signed-in role: it names the decisions that role signs, says who signs the others, and links only pages the role can open. It gives the same customers-out figure as Briefing, and explains the platform's own models (method, inputs, measured quality) from a card per model.

Diagrams and data flow: [docs/03-architecture.md](docs/03-architecture.md). Ten files to read first: [docs/14-code-tour.md](docs/14-code-tour.md).

## Built, simulated, not built

| Status | What |
| --- | --- |
| **Built and tested** | Web app with eleven roles and per-role permissions; decision queue with clocks, critical path and timing; two-function sign-off with emergency approval and envelopes; signed audit chain with tamper detection; ingest adapters with fault injection, outbox and gapless ledger; data-quality checks; hazard ensemble (40 members plus the official forecast) and county outage forecast (wind-fragility curve, leave-one-storm-out on 24 real storms; richer models tested in a pre-registered test and not better); water continuity twin and pressure anomaly detectors; outage surge detector (honest verdict: it failed its pre-registered bar); crew pre-positioning optimiser (two-stage stochastic programme) and crew dispatch with sign-off; restoration simulator and ETR ranges; damage-photo triage from a published classifier; boil-water and zone rules; Ask AI team with deep links, photos, follow-ups and answer language; LLM gateway with egress policy, record and replay, spend caps; kill switch and degraded modes; integration API with scoped tokens and signed webhooks; commitment watch and lead-time learning loop; demo moments with "Load moment"; in-app API metrics |
| **Simulated** | SGW's network, customers, assets, staff, documents and storm-day feeds (synthetic, calibrated to HURDAT2, EAGLE-I and ASOS); scripted exercise decisions on the Helene timeline; recorded AI answers in replay; the action itself: "execute" records an effect row and never touches field equipment |
| **Scripted exercise** | Hurricane Ian (2022) on its real track: Decisions, Map, Briefing, Notifications, Crews, After-action and Ask AI for every role; Forecast and Water not modelled |
| **Readiness preview only** | Heat wave (July 2024) and Table Rock wildfire weather (March 2025): readiness checks on real station data, not a playable storm |
| **Not built** | A second modelled storm replay (Ian is scripted), scheduled background worker (loops start from the CLI or the API), field mobile app, public notice sending, crew road routing, reinforcement learning |

Details and how each gap would close: [docs/12-assumptions-limitations-and-improvements.md](docs/12-assumptions-limitations-and-improvements.md).

## How well Ask AI answers

A bank of 373 questions (English, Polish, German, Spanish, French; all eleven roles; three story moments; data, navigation, explanations, overviews, follow-ups, photos, vague and misspelled questions, refusals) is graded by code. Before the agentic increment, 36% of a stratified sample passed. After it, on the final build (injects on), 110 of 110 held-out questions passed (100%) and 39 of 40 dev smoke questions. Caveats: the bank was written by the development team, 10 held-out questions are no longer blind (they failed in the first final-build run, were read to find root causes and asked again after the fixes), and 36 held-out questions appeared in an early report before it was redacted. Reports: [data/artefacts/evals/ask_bank/](data/artefacts/evals/ask_bank/), method: [evals/ask_bank/README.md](evals/ask_bank/README.md).

## How it was checked

Besides the unit, contract, policy and end-to-end tests of the merge gate (`scripts/check.sh merge`), every role was walked through before hand-in: each of the eleven people on every page, tab and control at three Helene moments (29 findings), and every signing workflow end to end per role on a private copy of the stack: sign, co-sign, send back, withdraw, emergency approval, crew dispatch, boil-water notice and lifting, ETR publish and revise, after-action, Load moment and Load scenario, stop levels (37 findings). Every finding was fixed and checked on screen; the Ian exercise was probed for every role by the development team. The checks were run by the development team, not by an independent tester.

## Data and licences

Code: Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). Real public data: NOAA HURDAT2 and the NHC GIS archive (public domain), ORNL EAGLE-I county outages (CC BY 4.0), ASOS observations and NWS warnings via Iowa Environmental Mesonet, USGS gauges, OpenFEMA declarations, NCEI Storm Events, Natural Earth, US Census boundaries, DOE and EPA documents (public domain), LADI v2 imagery (CC BY 4.0) and its reference classifier (MIT). Everything about SGW itself is synthetic and labelled. Sources, labels and rebuild commands: [docs/04-data.md](docs/04-data.md); per-file attribution: [data/ATTRIBUTION.md](data/ATTRIBUTION.md). Dependency licences are checked by `make licences` (GPL, AGPL and LGPL fail the check unless allow-listed).

## Tools used

- Claude Code (Anthropic) for research, iterating on assumptions, looking for gaps, and writing and reviewing code and documents against the plan and its acceptance checks; the author made the decisions at each step in written review files.
- Python 3.12 with uv; FastAPI, Pydantic, LangGraph, psycopg; NumPy, pandas, SciPy, scikit-learn, LightGBM, SHAP, MAPIE, lifelines, statsmodels; HiGHS and OR-Tools; WNTR (host-side precompute); fastembed.
- Postgres 18 with TimescaleDB, PostGIS and pgvector; Open Policy Agent; Caddy; MLflow; Docker Compose.
- React, TypeScript, Vite, Tailwind CSS, shadcn/ui and MapLibre GL for the web app; Playwright for end-to-end tests.
- LaTeX, TikZ and Matplotlib for the PRD, the briefing and the diagrams in `docs/`.
- pytest, Hypothesis and Schemathesis; Vitest; Ruff and mypy; Biome; gitleaks; lefthook.

## Limitations

The short list; the full one with evidence is [docs/12-assumptions-limitations-and-improvements.md](docs/12-assumptions-limitations-and-improvements.md).

- All SGW data is synthetic. Model quality on SGW's real assets is unknown until a pilot has data access.
- The outage forecast beats a fitted wind-threshold rule on county error for 21 of 24 real storms but under-calls the storm total on 18 of them, most for the largest (Helene: 0.4 M customers out forecast against 2.3 M observed). Crews are never sized on it alone.
- ETR coverage is measured on synthetic storms; no real crew data exists.
- One storm is modelled end to end (Helene). Ian is a scripted exercise without forecast or water models; heat and wildfire are readiness previews.
- Ask AI answers new questions, and every Ian question, live only with a key; its question bank is written by the development team, and the held-out score carries the caveats above.
- Measured on macOS (Apple silicon); Linux and Windows paths are written and tested in code, not run end to end by hand.

## Repository map

| Path | Holds |
| --- | --- |
| `web/` | Web app (React, TypeScript), its unit and Playwright tests |
| `src/sgw/api/` | FastAPI app, sessions, scenario clock, SSE, routers |
| `src/sgw/agent/` | Agent graphs and nodes, Ask AI (router, gate, planner, workers, synthesis, guide), slot rendering and verifier, retrieval |
| `src/sgw/approval/` | Approval service, emergency approval, envelopes, audit chain, signer |
| `src/sgw/models/` | Hazard, outage, surge, clocks, water twin, anomaly, optimiser, restoration, CV queue, wildfire, heat, what-if, commitments |
| `src/sgw/rules/` | Boil-water, zone and priority rules, exercise injects |
| `src/sgw/ingest/`, `src/sgw/pipeline/` | Adapters, outbox, ledger relay, pipeline runner and data-quality checks |
| `src/sgw/demo/` | Story moments, snapshots, demo smoke |
| `src/sgw/scenarios/`, `data/scenarios/` | Scenario packs (Hurricane Ian 2022 exercise): loader, reads, pack and events list |
| `src/sgw/ops/`, `src/sgw/integrations/` | Kill switch, degraded modes, health views; `/v1` tokens, webhooks, delivery worker |
| `src/sgw/generator/` | Synthetic scenario generator |
| `src/sgw/evals/` | Ask question bank runner and graders |
| `src/sgw/contracts/`, `contracts/` | Contract sources and generated artefacts ([contracts/README.md](contracts/README.md)) |
| `src/sgw/cli/` | The `sgw` command |
| `services/llm_gateway/` | LLM gateway |
| `policy/` | OPA policies and their tests |
| `db/migrations/` | Forward-only SQL migrations |
| `data/` | Public data extracts, synthetic fixtures, corpus, numbers registry, recordings, artefacts |
| `evals/` | Evaluation sets (dev and held-out) and reports |
| `host/` | Host-only jobs (WNTR precompute, CV scoring) |
| `docker/`, `infra/`, `ops/`, `compose.yaml` | Images, Caddy and OPA config, observability profile, the stack |
| `docs/` | Platform guide (numbered files 01 to 14), deliverables (PRD and executive briefing PDFs), diagrams and their TikZ sources, ops notes, LaTeX sources |
| `examples/webhook-consumer/` | Minimal HTTPS webhook receiver that verifies signatures |
| `tests/`, `scripts/` | Unit, integration, security and end-to-end API tests; repository checks (`scripts/check.sh`) |
| [DESIGN.md](DESIGN.md) | Visual design source of truth for the UI |
