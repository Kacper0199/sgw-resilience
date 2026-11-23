# Outage forecast (A2): model card

Audience: a reviewer or data scientist deciding how far to trust the county outage forecast, and how to rerun its tests. Every figure below is registered in `data/numbers/numbers.yaml` (keys `eval_outage_*`, label C, computed); the PRD and the briefing quote the same keys as macros.

## What the forecast is

| Item | Value |
| --- | --- |
| Headline method | Two-parameter wind-fragility curve: share of customers out per county as a lognormal function of the modelled peak gust, median and spread fitted on past storms (customer-weighted L1) |
| Output | Customers out per county and the storm total, with a range |
| Comparator | Fitted wind-threshold rule (threshold and coefficients fitted on the same training storms) |
| Data | 24 real storms in Georgia and South Carolina, 2016-2025, 123 footprint counties; NOAA HURDAT2 observed tracks, ORNL EAGLE-I county outages ([dataset reference](../04-data.md#dataset-reference)) |
| Test | Leave-one-storm-out hindcast: every storm is forecast by a curve fitted without it, on its observed track |
| Decisions it informs | D1 event type and risk, D2 crew pre-positioning. Crews are never sized on the forecast alone |

"Physics first, ML tested and fairly beaten": richer models were tested against the curve with a plan committed before any result ([outage-v3-preregistration.md](outage-v3-preregistration.md)) and did not beat it.

## Evidence

Source reports: `evals/reports/outage_loso_v2.json` (24-storm hindcast), `evals/reports/outage_loso_v3.json` (pre-registered test) and `data/artefacts/models/outage/loso_v3_detail.json`.

| Result | Value | Numbers key |
| --- | --- | --- |
| Storms where the curve beats the wind rule on county error | 21 of 24 | `eval_outage_storms_won`, `eval_outage_storms_n` |
| Median county error against the wind rule | 54% lower | `eval_outage_median_mae_reduction_pct` |
| Same, 2016-2017 storms dropped from training and testing | 15 of 19 storms, 31% lower | `eval_outage_storms_won_2018_on`, `eval_outage_median_mae_reduction_2018_on_pct` |
| Boosted model added to the curve | better on 4, worse on 3, same on 17 storms | `eval_outage_model_adds_*` |
| Pre-registered bars met (statistical model, machine learning) | none | `eval_outage_v3_curve_bar_met`, `eval_outage_v3_ml_bar_met` |
| County error of the statistical model with more drivers | 27 to 39% worse than the curve | `eval_outage_v3_glmw_county_error_change_pct`, `eval_outage_v3_glm_county_error_change_pct` |
| County error of the machine-learning residual models | 13 to 31% worse; better on 8 and 9 of 24 storms | `eval_outage_v3_ml*_county_error_change_pct`, `eval_outage_v3_ml*_storms_better` |
| Nested selection on training storms only | chose the plain curve for 23 of 24 storms | `eval_outage_v3_selection_picks_curve` |

An independent rerun reproduced the v2 and v3 outputs byte for byte, found no leakage, and confirmed that the leakage test fails when held-out labels or held-out wind records are let into training.

## Limitations

- **The curve under-calls large storms.** The storm total is below the observed total on 18 of 24 storms; pooled, the curve forecasts 41% of all observed outages and 30% for the eight largest storms. Helene: 0.4 M customers out forecast against 2.3 M observed, about one in six. Inland storms like Helene are the worst case. Registered as `eval_outage_storms_underpredicted`, `eval_outage_share_forecast_pct`, `eval_outage_v3_large8_share_pct`, `eval_outage_helene_forecast_m`, `eval_outage_helene_observed_m`.
- **The richer models do not fix the under-call.** They match the aggregate only by over-calling the 16 smaller storms about threefold (330% for the statistical model) while forecasting 43 to 49% of the eight largest. Their storm-total range covers 20 of 24 storms only because it is about 20.6 times wide, and it misses the three largest (Helene, Irma, Matthew, all above). Registered as `eval_outage_v3_glm_small16_share_pct`, `eval_outage_v3_glm_large8_share_pct`, `eval_outage_v3_richer_large8_share_max_pct`, `eval_outage_v3_glm_total_in_band_storms`, `eval_outage_v3_band_width`, `eval_outage_v3_band_misses`.
- **Gust calibration is descriptive only.** Calibrating the modelled wind against airport gust records (ASOS, label-free) reduced the curve's typical storm-total miss from a factor of 2.3 to 1.7, closer on 15 of 24 storms (one-sided Wilcoxon p 0.15). This was not a pre-registered test, and the calibrated curve still under-calls. Registered as `eval_outage_v3_curve_miss`, `eval_outage_v3_windcal_miss`, `eval_outage_v3_windcal_storms_closer`.
- **Ranking is not the problem.** The richer models ranked counties better than the curve on 18 to 19 of 24 storms; their loss is in the level, not the ranking (descriptive). Registered as `eval_outage_v3_glm_rank_better_storms`, `eval_outage_v3_ml_rank_better_storms`.
- **Labels.** Storm windows run 96 to 276 h and the target sums county peaks that need not coincide, so weak storms carry some non-tropical outages. EAGLE-I reporting before 2018 is sparser, which is why the 2018-on refit is quoted beside the headline.

## Replay model (unchanged)

The Helene replay still serves `a2-excl-helene` (`src/sgw/models/outage/backtest.py`, `SERVING_MODEL`): a gradient-boosted quantile model trained on Debby, Ian and Michael, with storm-grouped conformal ranges. It feeds the county ranges and risk shown in the replay. The PS-17 clock and its act-now share use the hazard-member fragility, not this model. On the four-storm WP-11 test it beat the wind rule on total error for 3 of 4 storms, missed 67% of Helene's outages, and its inner range held 29% of Helene counties (outer 57%). Registered as `eval_outage_replay_storms_won`, `eval_outage_helene_miss_pct`, `eval_outage_helene_cover_inner_pct`, `eval_outage_helene_cover_outer_pct`.

The replay model stays until a replacement is validated with its band, intervals and drivers. Switching it is a Stage 1 step.

## Stage 1 roadmap

1. Rainfall forecast input (NOAA WPC quantitative precipitation forecast). Observed rain is an upper bound on what a forecast adds, and it did not close the Helene gap in the v2 diagnostic.
2. A new pre-registered test on unseen storms only (the 2026 season, or Alabama, Florida and North Carolina storms outside the 24): county point from the calibrated-wind statistical model at its median residual, storm total from the calibrated-wind curve, storm-level band, with the v3 bars. On the 24 storms already used it is exploratory (0.945 times the curve's county error, 15 of 24 storms, p 0.19).

## Reproduce

```bash
make backtest-outage-v2   # 24-storm hindcast -> evals/reports/outage_loso_v2.json, about 6 min
make backtest-outage-v3   # pre-registered test -> evals/reports/outage_loso_v3.json, about 2 min
uv run sgw numbers --audit   # every registered value of four or more digits is quoted through a key
```

Both runs are deterministic: the prediction files (`loso_v2_predictions.csv`, `loso_v3_predictions.csv`) come out byte-identical; the reports differ only in `created_at` and `code_version`.
