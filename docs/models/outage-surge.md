# Outage-surge detector (G1): model card

Audience: a reviewer or data scientist deciding how far to trust the "surge detected" flags, and how to rerun the test. Headline figures are registered in `data/numbers/numbers.yaml` (keys `eval_surge_*`, `eval_batadal_*`); every figure comes from `evals/reports/outage_surge.json` (K17) and `data/artefacts/surge/eval_detail.json`, label C (computed on public data; not utility or DOE figures).

## What it is

| Item | Value |
| --- | --- |
| Question | Has the number of customers out in a county started to rise abnormally, and since when? |
| Method | Robust one-sided CUSUM: residual of log1p(customers out) against the median of the previous 7 days, scaled by the rolling IQR (floored), accumulated with allowance k; a surge starts when the statistic reaches h, the excess over the baseline passes a magnitude gate (customers and share of customers), and at least N other footprint counties started within the last 3 h (spatial corroboration). Causal: a slot is used only after its 15-min run ended |
| Output | Per county: onset (estimated change point), detection time, status, customers out, peak, baseline, share of customers out, confidence and data-quality flags |
| Baselines | (1) fixed share of customers out; (2) rolling z-score against the previous 7 days with the same magnitude gate. Each gets its own search on the training seasons. The canonical forms (1% of customers out; z >= 4) are also reported |
| Ablations | the model without corroboration; the fixed-share baseline with the model's corroboration |
| Data | EAGLE-I 15-min county customers out (ORNL, CC BY 4.0), GA + SC May-Nov 2016-2025 (2024: Aug-Oct, the only extract on disk); 123 footprint counties; denominator EAGLE-I modelled customers (`MCC.csv`) |
| Labels | NOAA NCEI Storm Events (public domain), wind-driven episodes per county: thunderstorm wind, tornado, tropical storm, hurricane, tropical depression, high and strong wind. Zone events are mapped to the county of the same name (all names matched). Other weather that cuts power (hail, lightning, flood, heavy rain, coastal flood, surge, winter, wildfire, heat) explains a surge but is not counted for recall |
| Split | Time split: every setting chosen on 2016-2021 only; 2022-2025 scored once with the chosen settings (Ian, Idalia, Debby, Helene in test) |
| Serving | `sgw.models.surge.read.list_outage_surges(as_of)` runs the fitted detector on the committed Helene series cut at `as_of`; copilot tool `list_outage_surges`; pipeline asset `surge.outages` |

Why CUSUM and not a Bayesian online change-point detector (BOCPD): the question is one-sided (a rise), CUSUM is the quickest detector of a sustained shift for a given false-alarm rate (Lorden; Page 1954), its state is one number per county, so a replay at any `as_of` recomputes in milliseconds, and its settings read as "how many robust standard deviations, for how long". BOCPD detects changes in both directions, needs a hazard rate and an observation model for zero-heavy, heavy-tailed counts, and costs O(run length) per step on 123 x 20,000 slots per season; with labels this incomplete its extra modelling would not be measurable. The search showed what carries the signal: the magnitude gate and the spatial corroboration, which a BOCPD would also need.

## Evidence

Test seasons 2022-2025, 123 counties, 1,456 NCEI wind episodes, 2,917 county-months. Each method uses its own setting chosen on 2016-2021 at a budget of 0.25 false alarms per county-month (about one unexplained alert a day across the footprint, fixed before any search). Intervals are 95% bootstraps that resample whole event days.

| Method (setting chosen on train) | Recall | False alarms per county-month | Precision (lower bound) | Median delay after NCEI begin |
| --- | --- | --- | --- | --- |
| **Model**: robust CUSUM, k 0.5, h 16, gate 250 customers and 1%, corroboration by 6 counties | **0.48** (0.40-0.55), `eval_surge_test_recall` | 0.41 | 0.39 | 0.6 h |
| Baseline 1: fixed share, 8% of customers out | 0.26, `eval_surge_test_recall_fixed_share` | 0.35 | 0.27 | 0.6 h |
| Baseline 2: rolling z >= 6, gate 1,500 customers and 1% | 0.32, `eval_surge_test_recall_rolling_z` | 0.37 | 0.31 | 0.65 h |
| Ablation: CUSUM without corroboration | 0.332 | 0.37 | 0.33 | 0.75 h |
| Ablation: fixed share 2% with the model's corroboration | 0.44, `eval_surge_test_recall_neighbour_ablation` | 0.43 | 0.35 | 0.6 h |
| Canonical 1% of customers out (untuned) | 0.607 | 2.73 | 0.11 | 0.4 h |
| Canonical rolling z >= 4 (untuned) | 0.606 | 2.88 | 0.11 | 0.4 h |

**Verdict against the pre-registered rule: the model does not beat the baselines.** The rule needed a recall gain with an interval above zero *and* test false alarms no higher than the baseline's. The recall gain is clear: +0.22 (0.15 to 0.28) over the fixed share and +0.16 (0.11 to 0.21) over the rolling z. But the model's test false-alarm rate is 0.41 against 0.35 and 0.37, so the second condition fails. Every method overshoots the 0.25 training budget on test (0.35 to 0.43): the later seasons have more unexplained surges for all of them.

What the evidence does support (descriptive, not a registered claim):
- At a stricter operating point (budget 0.10 on train), the model detects 0.37 of test episodes at 0.154 false alarms per county-month. The fixed share detects 0.18 at 0.15, and no rolling-z setting meets that budget.
- Spatial corroboration carries most of the gain: CUSUM without it reaches 0.33, the fixed share with it 0.44. The CUSUM adds +0.04 (0.02 to 0.06) over the corroborated fixed share, at fewer false alarms (0.41 against 0.43).
- By tier on test, the model detects tropical episodes 0.80 (n 238), tornado 0.49 (n 37) and thunderstorm wind 0.42 (n 1,161). By test year, recall is 0.41 (2022), 0.45 (2023), 0.68 (2024, Aug-Oct) and 0.48 (2025).
- 15% of detected episodes are flagged before the NCEI begin time.
- The untuned canonical baselines detect more episodes but raise about 7 times more false alarms. A fixed 1% threshold would page the footprint about 11 times a day.

Confidence score on test surges (n 1,935): Brier 0.203 against 0.237 for the training base rate, AUC 0.73. Surges in the high band match an NCEI event 67% of the time, medium 29% and low 19%.

### Helene replay (2024, a test season)

Serving path `list_outage_surges(as_of)` on the committed series. Its counts equal the evaluation run, and a test fails if they ever differ.

| Scenario time (ET) | Counties surging | Note |
| --- | --- | --- |
| 26 Sep 09:15 | 1 | first surge (Burke, GA) |
| 26 Sep 14:00 | 13 | |
| 26 Sep 23:10 (landfall in Florida) | 22 | |
| 27 Sep 02:00 | 68 | |
| 27 Sep 05:00 | 106 | 90% of the surging counties detected by 05:00 ET |
| 27 Sep 10:00 | 121 of 123 | |

Of Helene's NCEI tropical county episodes in the footprint, the model detected 0.81 (n 109), with a median delay of 0.27 h after the NCEI begin time. **On Helene the tuned fixed share (8%) scores higher on this metric: 0.97 (n 109; rolling z 0.87).** It is slower, though: median delay 0.75 h, and 90% of its surging counties by 06:30 ET against 05:00 ET for the model. Twenty of the model's 21 missed episodes are counties it had already flagged more than 3 h before the NCEI begin time (zone begin times for tropical storms are often late), and the registered match window counts those as misses. The window stays as registered. Read the Helene figure as "flags counties early", not "misses more counties".

## Limitations

- **The labels are incomplete.** NCEI lists severe reports (about 50 kt winds, damage), not every storm that cuts power, and outages also have non-weather causes. Precision and false alarms are therefore lower and upper bounds. Equal for every method, so the comparison stays fair.
- **Event-level recall on all NCEI wind episodes is low for every method** because most single thunderstorm-wind reports (one tree down) do not move a county's customers-out count. Tropical episodes are the relevant tier for this platform.
- **One footprint, one data source.** Thresholds are in customers and shares of EAGLE-I modelled customers for GA and SC; another utility needs a refit on its own OMS counts.
- **EAGLE-I gaps.** A slot with no county reporting is a feed gap (NaN, the CUSUM holds); a county missing from a reported slot counts as zero (the descriptor does not tell zero from a county gap). A surge within 4 h after a feed gap carries `after_feed_gap`; a peak above the modelled customers carries `exceeds_mcc`.
- **Confidence** is a logistic score on two causal features (excess share at detection, number of other counties surging within 3 h), fitted on training surges against the same incomplete labels: it ranks surges; it is not the probability that a storm caused the surge. In replay it is recomputed at `as_of` and can rise as more counties surge.
- **Replay uses real 2024 data.** The Helene series is the observed EAGLE-I record, not the synthetic family-A outages; the platform's synthetic counts and these flags will not match county by county.

## Rerun

```
uv run python -m sgw.models.surge.fit --raw-dir raw/data      # about 25 min
uv run pytest tests/unit/models/surge -q
```
Inputs: `raw/data/eaglei/` (figshare files listed in `data/open/eaglei/SOURCE.md`, plus `MCC.csv`) and `raw/data/storm_events/StormEvents_details-ftp_v1.0_d{2016..2025}_c*.csv.gz`; their SHA-256 are in `eval_detail.json`.

## External check of the water anomaly family (BATADAL, G3)

`evals/reports/anomaly_batadal.json`, detail `data/artefacts/surge/batadal_detail.json`; `uv run python -m sgw.models.anomaly.batadal --raw-dir raw/data/bench_water`. BATADAL (Taormina et al. 2018) C-Town hourly SCADA: fit on dataset03 (one attack-free year), scored on dataset04 (4,177 h, five labelled attacks, 219 attack hours; two more attacks are unlabelled, so TNR is a lower bound). Research-use data: not committed.

The A7/A8 detectors need the zone twin's station streams, which BATADAL lacks. The test therefore covers their family with the settings from `detector.yaml`: a PCA consistency residual over 31 sensors, the same two-sided CUSUM (k 0.5, h 10), and the A8 frozen and replay signatures.

| Method | BATADAL score S | TPR | TNR (lower bound) | Attacks detected |
| --- | --- | --- | --- | --- |
| A7/A8 family as is | 0.75, `eval_batadal_family_score` | 1.00 | 0.002 | 5 of 5 |
| Residual CUSUM, h recalibrated on dataset03 (94.8 sigma, 0% alarms there) | 0.758 | 1.00 | 0.032 | 5 of 5 |
| Static SCADA limits from dataset03 (baseline) | **0.79**, `eval_batadal_limits_score` | 0.55 | 0.80 | 5 of 5 |
| z-score >= 4 (baseline) | 0.625 | 0.41 | 0.99 | 4 of 5 |

**The family does not transfer.** As configured it alarms almost all the time. The h of 10 sigma assumes white noise on 15-min twin residuals, and real hourly SCADA residuals are autocorrelated. The A8 signatures also fire on 57% of the attack-free hours, because readings quantised to two decimals repeat. Recalibrating h on the attack-free year does not help either. Dataset04 runs the network in another regime (even the static limits fire on 20% of its normal hours), so a residual model fitted on one year does not carry over. Only these two variants were defined and run against the labels. The A7/A8 numbers on the synthetic bench (`anomaly_dev.json`) stay as they are, but they should not be read as evidence about real SCADA.
