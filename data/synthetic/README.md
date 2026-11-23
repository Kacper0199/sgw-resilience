# Synthetic scenario inputs (generator family A)

Every value the generator produces is synthetic. Parameters carry a label: F sourced, C computed, A assumption, I inference, plus a source line. Numbers that documents and the UI quote come from `data/numbers/numbers.yaml` only; the family files reference those keys instead of copying them.

| File | What it holds |
| --- | --- |
| `helene.yaml` | Helene scenario: real HURDAT2 track (NHC, public domain), advisory schedule, named assets of the PS-17 story, seeded cases |
| `family_a.yaml` | Build and train parameters (wind, forecast error, fragility, restoration, water, generators, telemetry) |
| `family_b.yaml` | Held-out parameters for WP-15 (DC-15 shifts). Never read by family-A runs; never used to train or tune |
| `footprint_counties.csv` | 123 footprint counties, Census bbox midpoints, modelled customers from EAGLE-I `MCC.csv` (CC BY 4.0) |
| `validation/helene_eaglei_county.csv` | EAGLE-I Helene county peaks and restoration times (CC BY 4.0, ORNL, doi:10.6084/m9.figshare.24237376.v4); validation only |

Commands (output in `data/fixtures/helene/`):

- `uv run sgw data generate --scenario helene` (or `make data SCENARIO=helene`) writes the K9 fixtures per feed, `network.json`, `sections.csv`, `outages.csv`, `county_hourly.csv`, `ensemble.json`, `truth_table.json` and `manifest.json`.
- `uv run sgw data verify` checks every file against the manifest.
- `uv run sgw data calibrate` re-runs the one calibration: `restoration.repair_scale` to the Helene county t50 of 35.5 h.

Model chain: track and quadrant wind radii, Holland-shape wind and 3-s gust, lognormal section capacity, fault time, damage state, crew-constrained repair, customers out; pump-station power, generators and fuel, tank and pressure; per-advisory ensembles (30 members) and reference decide-by clocks for the PS-17 critical path. `truth_table.json` lists every seeded case, its outcome, the reference clocks per advisory and the validation against EAGLE-I and ASOS.

## Story of record and the PS-17 hinge

The generated `helene` scenario is the story of record for the UI, documents and video; `data/fixtures/helene_micro` is hand-made for thin-slice tests only. Quote the effective (critical-path-bound) decide-by of `DC-D3-PS17-POWER`, not the case's own clock: `truth_table.json` holds both under the `HINGE-PS17-N-N1` outcome (`quoted: effective`).

Robustness (`truth_table.json` → `hinge_robustness`, from `sgw.generator.sensitivity`), all synthetic:

- The N to N+1 shift grows monotonically with advisory N's pinned forecast error: 0, -29, -45, -60, -76, -91, -103 min for pin scales 0 to 1.5. The verdict flips (N wait, N+1 act now) from a quarter of the pin upward.
- The flip holds for a member threshold `clocks.no_regret_member_p_loss` from 0.20 to 0.35; at 0.40 or above both advisories say wait, at 0.15 or below both say act now.
- The absolute decide-by depends strongly on the exposure level `clocks.material_loss_p`: at N+1 the own clock is 02:28Z at 0.05, 04:58Z at 0.1, 07:16Z at 0.2 and 08:00Z at 0.3 (2024-09-27). The shift sign is stable up to 0.2; at 0.3 advisory N gives no clock (fewer than a third of members reach it).
