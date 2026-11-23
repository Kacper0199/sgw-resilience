# 04. Data

Audience: an assessor who wants to know which data in the prototype is real, which is invented, and how it moves through the platform. The full dataset tables with paths and rebuild commands are in [dataset reference](04-data.md#dataset-reference); licences and per-file sources are in [data/ATTRIBUTION.md](../data/ATTRIBUTION.md).

## The rule: real storm, synthetic utility

SGW's own systems are not available to the prototype, so everything about SGW is synthetic: its network of feeders and pump stations, customers, assets, staff, procedures and the storm-day events in its own systems. Real public data supplies the storm and the outside world: tracks, forecast cones, observed winds, river gauges, warnings, county outage counts, federal reports and aerial damage imagery. The synthetic data is calibrated to the real data or evaluated against it. Real storms keep their names.

![Map with the storm cone and forecast layers](images/screens/map-forecast.png)

## Real public data

| Source | What it gives the platform |
| --- | --- |
| NOAA NHC HURDAT2 best tracks (24 storms, 2016-2025) | storm tracks for the generator, the hazard features and the outage evaluation; the Ian track |
| NHC GIS archive, Helene advisories 5-16 | forecast cone and track on the map |
| ORNL EAGLE-I county outages, 15-minute series | outage forecast targets, customers per county, surge detector replay |
| ASOS stations via Iowa Environmental Mesonet | observed gusts on the map, hazard check, heat and fire-weather triggers |
| USGS NWIS river gauges (148), NWS warnings via IEM | map layers |
| OpenFEMA declarations, NCEI Storm Events | after-action public record; surge detector labels |
| DOE CESER Helene situation reports, EPA incident checklists | federal documents in the procedure corpus |
| LADI v2 aerial imagery (200 thumbnails) and its reference classifier | damage photo triage ([08](08-computer-vision.md)) |
| US Census county outlines, Natural Earth basemap | offline map |
| EIA electricity data | inputs to the ROI model of the executive briefing |

Totals computed from EAGLE-I in this repository are our own aggregation, not utility or DOE figures. Missing 15-minute rows count as zero, because the source does not tell zero from a gap ([dataset reference](04-data.md#dataset-reference)).

## Synthetic SGW data

| Data | How it is made |
| --- | --- |
| Helene scenario: feeders and sections over the footprint counties, advisories with forecast ensembles, outages, restoration, pump stations, tanks, generators, fuel, telemetry | deterministic generator `src/sgw/generator/` (seeded random streams per subsystem and entity, SHA-256 manifest per file), calibrated to the real track, EAGLE-I county peaks and ASOS gusts; `uv run sgw data generate --scenario helene` |
| Held-out "family B" world on the real Debby 2024 track | same generator with shifted parameters (`data/synthetic/family_b.yaml`); never used to train or tune |
| Water zone networks and the drain grid | `src/sgw/models/water/`, `host/water_twin/precompute.py` ([09](09-water-network-model-and-what-if.md)) |
| Procedure corpus, 120 documents | hand-written and template-generated in the style of real utility documents; no text copied |
| Seeded people, 11 users across ten functions | `data/seed/users.yaml` ([02](02-roles-and-decision-workflow.md)) |
| Exercise injects on the Helene timeline (31 decisions, 20 facilities) | scripted in `src/sgw/rules/injects.py`, labelled scripted exercise data |
| Hurricane Ian 2022 exercise pack | hand-written YAML on the real Ian track (below) |

Every number the documents, the UI or the video quote lives in the numbers registry `data/numbers/numbers.yaml` with a value, unit, source and label: F fact, C computed, A assumption, P SGW policy (assumed), S synthetic, U unverified ([dataset reference](04-data.md#dataset-reference), "Labels").

## How data comes in

All feeds enter through one adapter interface (contract K6, `src/sgw/contracts/adapter.py`). In the prototype the feeds are replayed:

1. **Replay adapter.** Each source's committed fixture events are served page by page with an opaque cursor, gated by the scenario clock, so an event appears only once its time has come (`src/sgw/ingest/adapters/replay.py`).
2. **Fault injection.** Environment flags reshape a feed in a deterministic way, so a faulted replay is as repeatable as a clean one: `FAULT_FEED_DELAY`, `FAULT_FEED_GAP`, `FAULT_FEED_DUPLICATE`, `FAULT_FEED_OUT_OF_ORDER`, `FAULT_FEED_SCHEMA_DRIFT`, `FAULT_FEED_FLOOD_10X` (`src/sgw/ingest/faults.py`).
3. **Outbox and ledger.** Events are written to an outbox in the producer's transaction; one relay moves them into the gapless `event` ledger, acknowledges duplicates by their key and quarantines rows the database refuses (`src/sgw/ingest/relay.py`). `uv run sgw replay` prints the ledger head, a gapless flag and its SHA-256.

A live adapter for NWS active alerts exists (`src/sgw/ingest/adapters/nws.py`) and is tested on recorded payloads. The stack gives it no route to the Internet, so the demo runs on replayed data only.

![Data flow from feeds to decisions](images/diagrams/data-flow.png)

## The scenario clock

Every page shows the same scenario time, not the wall clock. The time is a pure function of an anchor:

`scenario time = anchor scenario time + (wall time - anchor wall time) x speed`

clamped to the scenario window and stored in `control_state.scenario_clock`, so every process derives the same time (`src/sgw/api/clock.py`). Speeds are 0 (paused), 1, 60 and 900. Only `command`, `operations` and the presenter role may move the clock (`clock_operator` in `src/sgw/api/deps.py`). After each clock command, and every 5 seconds, the scenario-jobs loop raises the decisions known at the new time ([02](02-roles-and-decision-workflow.md)).

**Demo moments.** For a fast demo, eight moments of the Helene story are built as template databases from one driven story run (`sgw demo build`, `src/sgw/demo/bookmarks.py`). "Load moment" (`POST /api/demo/goto`, demo mode only) replaces the API's database with that copy in seconds. The UI offers seven of them (`JUMP_LABEL` in `src/sgw/api/scenario_info.py`); the eighth, "PS-17 priority and boil-water notice signed", is not in the UI list; `uv run sgw demo goto signed` loads it.

| Moment in the UI | Scenario time (UTC) |
| --- | --- |
| Before the 5 AM advisory | 2024-09-26 08:00 |
| 5 AM advisory | 2024-09-26 09:05 |
| 11 AM advisory: deadlines move | 2024-09-26 15:05 |
| Morning after landfall | 2024-09-27 12:00 |
| Restoration estimate published | 2024-09-28 18:00 |
| Boil-water notices lifted | 2024-09-30 12:00 |
| After-action review | 2024-10-06 02:00 |

## Scenarios

| Scenario | What is real | What is scripted or synthetic | Pages |
| --- | --- | --- | --- |
| Hurricane Helene 2024 (default) | track, NHC cone, gusts, gauges, warnings, county outages | the SGW network, its outages, telemetry, crews and decisions | all |
| Hurricane Ian 2022 exercise pack (`data/scenarios/ian-2022/`) | the HURDAT2 best track (no cone shipped) | three moments (day before landfall, landfall near Georgetown, morning after), a county outage curve, critical facilities, a crew roster and eleven timed decisions (`msel.yaml`), all labelled "Scripted exercise data (synthetic)" | Decisions, Map, Briefing, Notifications, Crews (read-only), After-action; Forecast and Water show "Not modelled for this scenario" |
| Heat wave (July 2024), Table Rock fire weather (March 2025) | ASOS station series | trigger rules | Readiness previews |

The active scenario is part of the scenario clock, so every user sees the same one. Loading a pack (`POST /api/demo/scenario`) first copies the quiet Helene template, so no Helene decision or signature carries over (`src/sgw/scenarios/packs.py`, [architecture reference](03-architecture.md#architecture-reference), "Scenarios").

## What is not in the repository

No utility customer data, no personal data beyond the seeded synthetic identities, no API keys, and no full-size LADI images (downloaded on demand into the git-ignored `var/cv/`).


## Dataset reference

Audience: anyone who quotes a number from the prototype or reuses its data. It says where each dataset comes from, whether it is real or synthetic, its licence, and the command that rebuilds it. Third-party licences and per-file attribution are in [data/ATTRIBUTION.md](../data/ATTRIBUTION.md); this page is the map.

**Rule.** SGW's network, customers, assets, staff, documents and storm-day events are synthetic. Real public data supplies the storm tracks, observed winds, county outages, weather station records, federal reference documents and benchmark imagery that the synthetic data is calibrated to or evaluated against. Real storms (Helene 2024, Michael 2018, Ian 2022, Debby 2024) keep their names.

### Labels

Every number that a document, the UI or the video quotes lives in [`data/numbers/numbers.yaml`](../data/numbers/numbers.yaml) with a value, unit, label and source, and is rendered from there (`uv run sgw numbers`). `uv run python -m sgw.common.numbers --audit` fails when a registered value is typed as a literal in `docs/` or `web/src/`.

| Label | Meaning |
| --- | --- |
| F | Fact from a cited public source |
| C | Computed by this repository from F or S inputs |
| A | Assumption, with its reason |
| P | SGW policy parameter, assumed (shown as "Assumed SGW policy") |
| S | Synthetic: produced by the generator or a model run on synthetic data |
| U | Unverified |

### Real public data

| Dataset | Used for | Where | Licence |
| --- | --- | --- | --- |
| NOAA NHC HURDAT2 best tracks (24 storms 2016-2025, incl. Michael, Ian, Debby, Helene) | Storm tracks for the generator, the hazard features and the outage evaluation | `data/open/eaglei/storm_tracks.csv`, `data/synthetic/helene.yaml` | Public domain (US federal) |
| ORNL EAGLE-I county outages and modelled customers (`MCC.csv`) | Outage model targets (leave-one-storm-out), customer counts per county, restoration calibration | `data/open/eaglei/county_storm_outages.csv`, `data/synthetic/footprint_counties.csv`, `data/synthetic/validation/helene_eaglei_county.csv` | CC BY 4.0 |
| ASOS observations via Iowa Environmental Mesonet | Helene peak gusts (hazard check), fire-weather and heat triggers | `data/open/eaglei/asos_helene_peak_gust.csv`, `data/fixtures/tablerock/`, `data/fixtures/heat/` | Public observations (NWS/FAA) |
| DOE CESER Helene situation reports #5, #11, #15 | Federal reference documents in the procedure corpus | `data/corpus/src/federal/` | Public domain (US federal) |
| EPA incident action checklists (hurricane, flooding) | Federal reference documents in the procedure corpus | `data/corpus/src/federal/` | Public domain (US federal) |
| LADI v2 aerial imagery (200-image sample, 240 px thumbnails) and the LADI v2 small reference classifier | Damage-assessment photo queue; scores computed on the host | `data/artefacts/cv/` | Imagery CC BY 4.0; classifier MIT |
| NHC GIS archive, Helene (AL092024) cone, track and points, advisories 5-16 | Map storm cone and track on the history bar | `web/public/geo/helene-nhc.json` | Public domain (US federal) |
| USGS NWIS gage height (148 gauges), IEM ASOS wind (6 stations), IEM NWS VTEC warnings | Map layers: river gauges, observed gusts, warnings | `data/open/usgs_nwis/`, `data/open/iem_asos/`, `data/open/iem_vtec/` | Public (US federal; IEM archive) |
| OpenFEMA disaster declarations, NCEI Storm Events (212 events) | After-action public records | `data/open/openfema/`, `data/open/ncei_storm_events/` | Public domain (US federal) |
| EAGLE-I 15-minute county series, Helene window | Outage surge detector replay | `data/artefacts/surge/` | CC BY 4.0 |
| Natural Earth land, states and lakes; US Census county outlines | Offline basemap | `web/public/geo/`, `data/reference/counties.geo.json` | Public domain |
| EIA electricity data (Table 11.4 series) and footprint scalars | Inputs to the ROI model of the executive briefing | `data/roi/footprint_inputs.json` | Public (US federal) |

EAGLE-I totals in this repository are our own aggregation (label C), not utility or DOE figures. Missing 15-minute rows count as zero, because the source does not distinguish zero from a gap.

### Synthetic data

| Dataset | Produced by | Calibrated to | Rebuild |
| --- | --- | --- | --- |
| Helene scenario (family A): network of feeders and sections over the footprint counties, advisories with 40-member ensembles plus the official forecast, outages, restoration, pump stations, tanks, generators, fuel, telemetry, reference clocks | `src/sgw/generator/` | HURDAT2 track, EAGLE-I county peaks and restoration medians, ASOS gusts | `uv run sgw data generate --scenario helene`, check with `uv run sgw data verify` |
| `helene_micro` fixture (the PS-17 story in about 200 events) | Hand-made | Story frame only | Not regenerated; used by thin-slice tests |
| Family B (Debby track, shifted parameters) | `src/sgw/generator/` with `data/synthetic/family_b.yaml` | Real Debby track | Held out: never used to train or tune; `make evals-family-b` |
| Blue-sky Readiness, Table Rock fire weather, heatwave | `src/sgw/generator/scenarios/` | Real ASOS station series | `uv run sgw scenarios generate` |
| What-if grid (81 truth runs) | `src/sgw/models/whatif/` | Helene scenario | `uv run sgw scenarios whatif` |
| Water zone networks and the WNTR drain grid | `src/sgw/models/water/`, `host/water_twin/precompute.py` | Seeded zones; SC and GA pressure floors from the regulations | `make water-precompute` (host dependency group), `uv run sgw water validate` |
| Procedure corpus (120 SGW documents: hand-written and template-generated) | `data/corpus/src/`, `src/sgw/agent/rag/generator.py` | Style of real utility documents (EPA, AWWA, PSC storm plans, ICS forms) read as evidence; no text copied | `uv run sgw rag corpus` |
| Seeded identities (11 users across ten functions) | `data/seed/users.yaml` | Utility emergency roles | `uv run sgw seed` |
| Exercise injects (31 scripted decisions, 20 facilities on the Helene timeline) | `src/sgw/rules/injects.py` | Exercise practice (timed injects with rule deadlines) | Raised by the API when `SGW_SCENARIO_INJECTS=1`; labelled scripted exercise data |
| Hurricane Ian 2022 exercise pack (three moments, scripted county outage curve, four critical facilities, crew roster, eleven timed decisions) | Hand-written: `data/scenarios/ian-2022/pack.yaml`, `msel.yaml` | Real NOAA HURDAT2 best track AL092022 (public domain); everything else invented under the synthetic naming rule | Not generated; loaded by `src/sgw/scenarios/packs.py`; labelled "Scripted exercise data (synthetic)" |
| Ask AI question bank (373 questions, 263 dev and 110 held-out, five languages) | `evals/ask_bank/` | Questions users asked on the live stack plus every page, role and moment | `python -m sgw.evals.ask_bank.split`; held-out never shown to the Ask builders |
| Held-out and dev evaluation items | `evals/heldout/`, `evals/dev/` | Written before the systems they test | Hash-locked in `evals/MANIFEST.sha256`; `make evals-check` |

The generator is deterministic: seeded streams per subsystem and entity, manifests with SHA-256 per file. Robustness of the PS-17 hinge to its pinned forecast error and thresholds is recorded in [data/synthetic/README.md](../data/synthetic/README.md).

### Model outputs and recordings

| Artefact | Where | Notes |
| --- | --- | --- |
| Evaluation reports (K17: metric, value, n, split, label, baseline) | `evals/reports/` | Outage LOSO, ETR, SAA, LADI reference |
| Outage model and LOSO detail | `data/artefacts/models/outage/` | Serving model trained without Helene |
| Water twin outputs (validation, PS-17 clock members, continuity, anomaly) | `data/artefacts/water_twin/` | Synthetic networks |
| Node selection evals | `data/artefacts/evals/`, `tests/unit/agent/` | Development sets |
| Ask question bank reports | `data/artefacts/evals/ask_bank/` | Held-out rows redacted to outcome only |
| LLM recordings (K11) | `data/fixtures/llm/`, `data/fixtures/copilot/`, `data/corpus/llm_fixtures/` | Made through the gateway in record mode with Claude Sonnet and Haiku; replay needs no key. Live answers to unrecorded questions are cached in the git-ignored `var/llm/live_cache/`, never in the fixtures |
| Chunk headers | `data/corpus/headers/chunk_headers.jsonl` | Generated once through the gateway; C2 documents never sent |
| ROI results | `data/roi/roi_results.json` | `uv run python -m sgw.roi --check` detects drift |

### What is not in the repository

No utility customer data, no personal data beyond the seeded synthetic identities, no screenshots of third-party products, no API keys (the gateway reads its key file only in record or live mode), and no full-size LADI images (`uv run sgw photos` or `make photos` downloads them into the git-ignored `var/cv/`; the API serves them to signed-in users and shows the committed thumbnails when they are missing).
