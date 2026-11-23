# Platform guide

The SGW Resilience Platform is a working prototype of decision support for Southeastern Grid & Water (SGW), a power and water utility, during severe weather. It replays Hurricane Helene on synthetic SGW data and real public storm data, turns forecasts into decisions with computed deadlines, and lets the responsible teams sign them, with every step in a signed audit trail. The numbered pages below explain how it works; each mechanism names the code that implements it.

## Numbered pages

| Page | What it covers |
| --- | --- |
| [01. Overview](01-overview.md) | What the platform does, for whom, the problem, decision clocks, pages, real and synthetic data, the two scenarios |
| [02. Roles and decision workflow](02-roles-and-decision-workflow.md) | Roles and permissions, how a deadline is computed, proposals and tiers, two-team sign-off, send back, emergency approval, audit trail |
| [03. Architecture](03-architecture.md) | Containers, networks, trust boundaries, data flow, technology choices, database |
| [04. Data](04-data.md) | Real public sources and synthetic SGW data, ingestion, replay, the scenario clock, scenarios |
| [05. Ask AI agent system](05-ask-ai-agent-system.md) | The read-only agent team: routing, planner, workers, synthesis, verification, replay and live |
| [06. Outage forecast](06-outage-forecast.md) | Method, inputs, ranges and evaluation on real storms |
| [07. Surge and anomaly detection](07-surge-and-anomaly-detection.md) | Outage surge and water pressure anomalies: signals, thresholds, results |
| [08. Computer vision](08-computer-vision.md) | Damage photo triage: model, labels, scores and review order |
| [09. Water network model and what-if](09-water-network-model-and-what-if.md) | Tank drain to the pressure floor and the what-if grid |
| [10. Crew optimisation and restoration estimates](10-crew-optimisation-and-restoration-estimates.md) | Crew pre-positioning across forecast members and restoration times |
| [11. Security, governance and human oversight](11-security-governance-and-human-oversight.md) | Policy engine, signing, audit, what the LLM may do, egress, secrets, prompt injection |
| [12. Assumptions, limitations and improvements](12-assumptions-limitations-and-improvements.md) | What the prototype assumes, what it does not prove, what comes next |
| [13. LLM gateway](13-llm-gateway.md) | The single path to the model provider: interface, egress gate, budget caps, record and replay |
| [14. Code tour](14-code-tour.md) | The key files on the demo path, in reading order |

## Deliverables

| Document | File | Source |
| --- | --- | --- |
| Product Requirements Document | [deliverables/prd.pdf](deliverables/prd.pdf) | [latex/prd/prd.tex](latex/prd/prd.tex) |
| Executive management briefing | [deliverables/executive-briefing.pdf](deliverables/executive-briefing.pdf) | [latex/briefing/briefing.tex](latex/briefing/briefing.tex) |

## Reference

| Document | Use it for |
| --- | --- |
| [../data/ATTRIBUTION.md](../data/ATTRIBUTION.md) | Every public dataset with its source and licence |
| [models/](models/) | Model notes: outage forecast, outage surge detector, forecast pre-registration |
| [ops/stack.md](ops/stack.md) | Services, ports, limits, credentials, audit wiring, database roles |
| [ops/](ops/) | Golden-path API walk-through, multi-architecture builds |

Diagrams are built from TikZ sources in [diagrams/src/](diagrams/src/) with `docs/diagrams/build.sh <name>`; images live in [images/](images/). The PRD and the briefing are built with `uv run python scripts/build_docs.py prd --final` and `briefing --final`.
