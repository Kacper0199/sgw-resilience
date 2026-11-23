# 12. Assumptions, limitations and improvements

Audience: a reviewer deciding how far to trust what the prototype shows, and what it would take to go further. The task brief left the client context incomplete on purpose; this page lists the assumptions that fill the gaps, what the prototype does not prove, and what would come next. The full limitation register with evidence is [limitations.md](limitations.md); the PRD's "Key assumptions and unknowns" section lists every assumption with its owner and how to validate it ([deliverables/prd.pdf](deliverables/prd.pdf)).

## Key assumptions

Each assumption shapes the design; each would be checked with SGW in the first weeks of a pilot.

| Area | Assumption | What it changes in the design |
| --- | --- | --- |
| Organisation | SGW is an investor-owned holding with an electric utility and a regulated water subsidiary, overseen by the state utility commissions | ROI is shown as utility cash and customer value; water decisions need a compliance signature |
| Territory | South Carolina plus Georgia east of 83.6 W: 123 counties | The footprint of the synthetic network, the map and the county outage data |
| Decision rights | Storms run under the Incident Command System: the Incident Commander approves event type and the global restoration estimate; a certified water operator and the compliance officer own boil-water decisions | The tier table and the two-team pairs ([02](02-roles-and-decision-workflow.md)) |
| Systems of record | GIS, asset management, outage management, SCADA historians, meter data, field service and lab systems exist and offer read access | One adapter interface; replay adapters stand in for them |
| OT boundary | The platform is advisory, outside the control network, with no write path to operational technology | "Execute" records an effect; T4 has no tool |
| Advisory role | Outage management, SCADA and the incident command system stay the systems of record; operations continue without the platform | Degraded modes keep clocks and approvals working without the LLM |
| Data to external AI | Only synthetic or public content reaches an external model in the prototype; production routes follow a data-class table | Egress policy route R1 allows C0 and C1 only ([11](11-security-governance-and-human-oversight.md)) |
| Field input | Field notes, tickets and public alert text are untrusted and never carry authority | Guards, taint marks and the read-only Ask |
| Deadlines | A decide-by clock is an estimate; a missed clock is a learning signal for the after-action review, except where a rule sets the deadline (boil-water notice) | Clocks show P10 to P90 ranges; rule deadlines are labelled as such |
| Approver response | Approvers for two-team decisions can respond within the approval window during a storm | Emergency approval with a 24-hour co-sign exists for when they cannot |
| Retention | Audit records are kept 7 years as SGW policy | Insert-only audit with signed anchors |
| Users | English UI, accessibility to WCAG 2.2 AA, desktop-first use in the operations centre | [DESIGN.md](../DESIGN.md) |
| Results | Model results in the prototype are verification on simulated or replayed data, not evidence of SGW field accuracy | Every figure carries a label ([04](04-data.md)) |

Policy values in the platform (lead times, tier limits, thresholds) are SGW policy assumptions and are shown in the UI as "Assumed SGW policy".

## Limitations

The most important ones, in plain terms. Evidence and the full list: [limitations.md](limitations.md).

| Area | What the prototype does not do or prove |
| --- | --- |
| Data | SGW's network, customers and storm-day events are synthetic. Results on SGW's real assets are unknown. |
| Second scenario | Hurricane Ian is a scripted exercise on the real track, not a modelled replay: Forecast and Water are not modelled for it, Crews is a read-only roster. |
| Outage forecast | It under-calls large storm totals, so crews are never sized on it alone; the Helene replay still shows ranges from an earlier model ([06](06-outage-forecast.md)). |
| Detectors | The outage surge detector failed its pre-registered bar on the held-out 2022-2025 seasons and is shown with that verdict; pressure anomaly recall (0.713, `eval_anomaly_recall_dev`) is below its 0.8 target ([07](07-surge-and-anomaly-detection.md)). |
| Computer vision | Benchmark imagery of 2023 US events, scored by a published classifier that was not fine-tuned ([08](08-computer-vision.md)). |
| Water model | Validated against a hydraulic grid on the same synthetic networks, not a real utility model ([09](09-water-network-model-and-what-if.md)). |
| Crew plans | No real yard capacity data (an assumed cap of 1,000 persons per yard stands in), and straight-line travel at a fixed speed without road closures (blocked access only as an expected debris-clearance delay) ([10](10-crew-optimisation-and-restoration-estimates.md)). |
| Ask AI | Recorded questions replay at no cost; any other question needs a live model call, or gets a shorter answer built by code without a key. Its question bank was written by the development team and is no longer fully blind ([05](05-ask-ai-agent-system.md)). |
| Ask AI, one recorded answer | On the demo moment "11 AM advisory: deadlines move", before any signature, the recorded answer to the starter question prints a raw decision id in brackets, "(DC-D3-PS17-FUEL)", where a decision name should be. The answer recorded after the signatures is clean. |
| Decision graph evaluation | The held-out sets of the decision graphs (including the red-team set) are hash-locked but not yet scored by a release harness. |
| Background jobs | The `worker` container is a placeholder; some loops (commitment watch, optimisation jobs, pipeline runs) start from the CLI. |
| Security | The gateway trusts the declared data class of each payload; approvals are bound to sessions, not per-user signing keys; a revoked session keeps an open stream until the client disconnects; audit rows after the newest checkpoint are protected only by the chain until the next one (at most 60 seconds). |
| Platforms | Measured on macOS with Docker Desktop on Apple silicon; Linux and Windows (WSL 2) paths are written and configured in CI but not run by hand. |

## Improvements

| Next step | What it closes |
| --- | --- |
| Read-only adapters to SGW's own systems behind the existing adapter interface, starting with one operating area and one water system | Synthetic data; unknown behaviour on real assets |
| SGW's own lead times, tier tables and thresholds, reviewed by operations and compliance | "Assumed SGW policy" values |
| Rainfall forecast input and a new pre-registered forecast test on unseen storms | Forecast under-calls on large storms |
| Flow metering in the water model and a run against a utility hydraulic model | Anomaly recall; water model validation |
| SGW imagery from a past storm, labelled by its damage assessors | Benchmark imagery |
| Yard capacities and road travel times with closures | Crew plan realism |
| A release harness that scores the held-out sets once per release, and questions from real users in a pilot | Evaluation gaps |
| Fix the Ask synthesis text for the raw id and re-record that answer | The one recorded answer with a raw id |
| One scheduled worker for ingest, pipelines, commitment watch and optimisation jobs | CLI-started loops |
| SSO from SGW's identity provider, per-user signing keys or the utility's PKI, content detectors for infrastructure identifiers, write-once storage for audit anchors | Security gaps |
| A second modelled storm with its own generated network | Ian as a scripted exercise only |

The smallest architecture for a real pilot, and what it leaves out on purpose, is in [tradeoffs.md](tradeoffs.md), "Minimum pilot architecture".
