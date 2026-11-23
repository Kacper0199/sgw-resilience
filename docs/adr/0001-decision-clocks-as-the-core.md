# ADR 0001: Decision clocks as the core object

Status: Accepted (2026-11-19)

## Context

SGW's storm-day problem is not a missing forecast. Forecasts exist (NHC advisories, vendor outage models). What goes wrong is timing: a generator hookup ordered after the road closes, a crew request sent after the mutual-aid window, a boil-water notice drafted after pressure is already below the floor. Each action has a lead time, and each forecast update moves the time by which the action must start.

The emergency-management practice for evacuations already works this way. HURREVAC computes evacuation decision times from clearance times and the arrival of tropical-storm winds. The prototype applies the same idea to utility actions; it does not claim the idea is new.

## Decision

The primary object is a **decision case** with a computed clock (contract K16, `src/sgw/contracts/clocks.py`):

- `decide_by = consequence time - action lead time`, computed per ensemble member, reported as P10/P50/P90.
- Every term of the consequence time carries the id of the model or rule that produced it, so the clock opens as a waterfall (`uv run sgw clocks waterfall`).
- Prerequisites form a directed acyclic graph. A backward pass gives the **effective** decide-by: a prerequisite must finish its action by the time its dependent must be decided (critical path, `src/sgw/models/clocks/critical_path.py`).
- A no-regret / wait verdict says whether waiting for the next advisory is safe: only when that advisory lands before the earliest P10 effective decide-by over the case and its prerequisites.
- The queue is ordered by effective decide-by, then by impact.

Lead times live in a versioned registry with SOP citations (`src/sgw/models/clocks/lead_times.yaml`). After an event, the commitment watch compares actual and assumed lead times and proposes updated values as a T2 policy change (`uv run sgw commitments after-action`); it never applies them.

## Alternatives considered

- **Risk score per asset as the primary object.** Familiar from dashboards, but a score does not say when to act or who must sign. It stays as an input to the consequence time.
- **Rule-based alerts.** Easy to explain, but every threshold is a hidden clock with no basis shown and no link to the action's lead time.
- **Optimise everything in one model.** The crew pre-positioning optimiser (two-stage SAA) is used for one decision. A single model over every decision would hide the reasoning the approvers need.

## Consequences

- Models must output distributions, not point values, or the clock has no P10/P90. The hazard ensemble (40 members per advisory in the Helene scenario, `forecast.members` in `data/synthetic/family_a.yaml`) is the common random input.
- When fewer than a third of members reach the consequence, the case has no clock and says so instead of showing a number.
- Clocks are deterministic code. The LLM may describe a clock; it cannot set or edit one (ADR 0003).
- The story the prototype tells (PS-17, one pump station feeding one hospital zone) is a clock that moves earlier when the next advisory arrives; see the README.
