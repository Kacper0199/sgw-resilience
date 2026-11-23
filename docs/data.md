# Data provenance

Audience: anyone who quotes a number from the prototype or reuses its data. It says where each dataset comes from, whether it is real or synthetic, its licence, and the command that rebuilds it. Third-party licences and per-file attribution are in [data/ATTRIBUTION.md](../data/ATTRIBUTION.md); this page is the map.

**Rule.** SGW's network, customers, assets, staff, documents and storm-day events are synthetic. Real public data supplies the storm tracks, observed winds, county outages, weather station records, federal reference documents and benchmark imagery that the synthetic data is calibrated to or evaluated against. Real storms (Helene 2024, Michael 2018, Ian 2022, Debby 2024) keep their names.

## Labels

Every number that a document, the UI or the video quotes lives in [`data/numbers/numbers.yaml`](../data/numbers/numbers.yaml) with a value, unit, label and source, and is rendered from there (`uv run sgw numbers`). `uv run python -m sgw.common.numbers --audit` fails when a registered value is typed as a literal in `docs/` or `web/src/`.

| Label | Meaning |
| --- | --- |
| F | Fact from a cited public source |
| C | Computed by this repository from F or S inputs |
| A | Assumption, with its reason |
| P | SGW policy parameter, assumed (shown as "Assumed SGW policy") |
| S | Synthetic: produced by the generator or a model run on synthetic data |
| U | Unverified |

## Real public data

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

## Synthetic data

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

## Model outputs and recordings

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

## What is not in the repository

No utility customer data, no personal data beyond the seeded synthetic identities, no screenshots of third-party products, no API keys (the gateway reads its key file only in record or live mode), and no full-size LADI images (`uv run sgw photos` or `make photos` downloads them into the git-ignored `var/cv/`; the API serves them to signed-in users and shows the committed thumbnails when they are missing).
