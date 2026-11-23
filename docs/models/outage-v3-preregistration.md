# Outage forecast v3: pre-registration

Fixed 2026-11-20 14:40 CET, before any outcome run of a v3 variant. Source plan: RX-6 deep dive, section 4
(copied below) with sections 3 and 6. Everything under "Implementation choices fixed now" resolves details that
RX-6 left open; they are fixed here, before any v3 model has been scored on outages.

Disclosure: the RX-6 diagnostics (storm-scale ratio of B3, ASOS gust bias of 6 storms, power) were run on the
committed v2 predictions and shaped this plan (garden-of-forking-paths risk). That is why the bars are
strict and the variant budget is fixed. A variant added after outer results are seen is labelled exploratory
and cannot be the headline.

## Data and frame
- Frame: `extended_frame(rain=True)`: 24 storms (2016-2025), 123 GA/SC footprint counties, labels L1
  (current: peak excess over the 600 km / +72 h window, MCC denominator). LOSO on observed HURDAT2 tracks.
- Servable features only: track features from `point_features`, static county data, `rain_antecedent_14d_mm`
  (known before landfall). `rain_window_mm` is excluded from every v3 variant.
- Static county table (new, `data/open/eaglei/county_static.csv`): land area (TIGER cb 2023 5m `ALAND`, public
  domain), customer density = `customers_mcc` / land km2, distance to the coast (km, from the boundary of the
  union of the contiguous-US counties of the same file, EPSG:5070), SVI 2022 `EP_MOBILE` (CDC/ATSDR).
- ASOS (new, label-free): IEM ASOS archive, networks GA_ASOS and SC_ASOS, all stations, each storm's L1
  window; observed peak = max of `gust`, `peak_wind_gust`, `sknt` (kt to m/s).

## Baselines (refit in every outer and inner fold)
- B1 wind threshold (as v2).
- B3 fragility, lognormal on gust, median and beta on the grid by customer-weighted L1 on counts (as now). B3
  stays the headline comparator.
- B3m fragility by binomial likelihood (mean curve): probit GLM on ln(gust), customer weights, no storm effect.
- B3w: B3 refit on the calibrated gust (counts as a baseline, so wind calibration is credited separately).

## Variants (8, fixed hyperparameters, all reported)
- F1 composite fragility: probit eta = a + b ln(gust) + u_storm, u ~ N(0, tau^2).
- F2 generalised GLM: eta = a + b ln(gust) + c ln(1 + hours_gust_ge_20) + d z(rain_antecedent_14d_mm)
  + e ln(customer density) + u_storm.
- M1 GBM residual on F2 (the single "ML" arm).
- F1w, F2w, M1w: the same with the calibrated wind (`peak_gust_cal_ms`, `hours_gust_cal_ge_20`); the
  correction is fitted on the training storms' ASOS only.
- S5 nested selection among {B3, B3m, F1, F2, M1, F1w, F2w, M1w}: the honest "procedure" score.

Selection rule (inner folds only, training storms only): minimise the mean over inner storms of
[ln(county MAE) + |ln(P_total / O_total)|]. Ties: pool order above.

## Implementation choices fixed now
1. GLM fit (B3m, F1, F2): statsmodels GLM, Binomial family with probit link (quasi-binomial: point estimates
   are the binomial MLE, standard errors scaled by the Pearson dispersion), response `peak_frac`,
   `var_weights` = customers / mean customers of the training rows. F1/F2 carry one indicator per training
   storm and no global intercept (storm effects as fixed effects). Then a DerSimonian-Laird random-effects
   step on the storm coefficients (estimate u_s, quasi-binomial variance se_s^2): tau^2 =
   max(0, (Q - (k - 1)) / (sum w - sum w^2 / sum w)), population intercept a = sum w*_s u_s / sum w*_s with
   w*_s = 1 / (se_s^2 + tau^2).
2. Sign rule: b, c, d must be > 0 (more wind, longer wind, wetter soil never lower outages); the density
   coefficient is free (an exposure control). A coefficient <= 0 in a fit drops that covariate and the fit is
   repeated (that fold only); drops are counted and reported. z-scoring uses the training rows' mean and sd.
3. Outputs of F1/F2: county point = Phi(a + x b) (the median storm, u = 0), used for county MAE, Spearman and
   the worst miss; storm total = sum customers x Phi((a + x b) / sqrt(1 + tau^2)) (the marginal mean). B1, B3,
   B3m, B3w: point and total from the same curve.
4. Intervals. County 80% / 95%: probit residuals r = Phi^-1(clip(y, 1e-5, 1 - 1e-5)) - eta_0 over all
   training rows (eta_0 = the variant's u = 0 linear predictor), interval [Phi(eta_0 + r_q), Phi(eta_0 + r_1-q)]
   with q = 0.10 / 0.025; computed for every probit-shaped method (B3, B3m, B3w, F*, M*). Storm-total 80%:
   totals at u = -1.2816 tau and +1.2816 tau (F*, M* only).
5. M1: LightGBM `cross_entropy` on `peak_frac`, sample_weight = customers / mean, init_score =
   logit(clip(Phi(eta_F2 + u_s), 1e-6, 1 - 1e-6)) with each training storm's own estimated u_s (the conditional
   mean), features ln(gust), ln(1 + h20), z(ante 14 d), ln(density), `vmax_ms_closest`, `speed_kmh_closest`,
   `ep_mobile`; monotone +1 on the first three; num_leaves 3, 100 trees, learning_rate 0.05,
   min_child_samples 50, no bagging, deterministic, seed 20241. Prediction: p0 = sigmoid(logit(Phi(eta_F2))
   + g(x)) at u = 0 (county point); total: Phi(Phi^-1(p0) / sqrt(1 + tau_F2^2)) summed with customers.
6. Wind calibration (label-free): per station-storm pair, keep when hourly reports cover >= 75% of the hours of
   [closest approach - 24 h, + 24 h] and the modelled peak gust is >= 13 m/s. OLS of ln(obs / model peak gust)
   on 1, ln(model gust), log1p(distance to coast km), `vmax_ms_closest`, `speed_kmh_closest` (all at the
   station), equal weight per pair. Applied at county centroids with each covariate clamped to its training
   range; factor clipped to [0.25, 2.0]. `peak_gust_cal_ms` = factor x modelled peak gust;
   `hours_gust_cal_ge_20` = hours with factor x modelled gust >= 20 m/s (from the same Holland-profile series;
   `field.py` untouched).
7. Metrics per storm: county MAE (customers, county point); storm-total |ln(P/O)| and signed ln(P/O) (P from
   the total output); relative total error |P - O| / O; Spearman; worst miss; county 80% coverage; storm-total
   80% interval hit (F*, M*). Summaries: strict wins, median MAE ratio, one-sided Wilcoxon on per-storm log
   ratios, median |ln(P/O)|, storms under-predicted, pooled P/O, large-8 subset (Dorian, Helene, Ian,
   Idalia, Irma, Matthew, Michael, Zeta: the v2 list), 2018-on refit (colin_2016, hermine, julia,
   matthew, irma dropped from training and testing, full rerun).

## Confirmatory contrasts (3, Holm at family alpha 0.05)
One-sided Wilcoxon signed-rank on the 24 per-storm ln(county MAE_a / county MAE_b) (H1: a better):
- C1: F2 vs B3, "the curve with covariates".
- C2: M1 vs F2, "ML adds".
- C3: F2w vs F2, "wind calibration".
Everything else is descriptive.

## Bars
"ML genuinely helps" (M1 vs F2 and B3; M1w vs the wind-matched F2w and B3w, so ML is not credited for the
wind calibration; M1w vs F2 and B3 also reported). All must hold:
- county MAE median ratio <= 0.90 and wins >= 18/24 against both comparators; one-sided Wilcoxon p: Holm-adjusted
  C2 < 0.05 against F2 (for M1w its own test against F2w, Holm-adjusted as C2's step), p x 3 < 0.05 against B3;
- median |ln(P/O)| no worse than the comparator + 0.05, and pooled P/O in [0.67, 1.5];
- large 8: pooled P/O >= the comparator's and county MAE better on >= 5/8;
- 2018-on refit: same direction, median ratio <= 0.95.

"The statistical curve beats B3" (F2 vs B3; F2w vs B3w): median |ln(P/O)| at least 0.2 lower, closer on
>= 17/24 storms, pooled P/O in [0.67, 1.5], AND county MAE non-inferior (median ratio <= 1.10).

Headline rule: the ML arm if its bar passes; else F2 (or F2w if C3 is significant after Holm) if its bar passes;
else the fitted curve B3 stays, with the fixed loss wording.

Fixed loss wording: "Against a two-parameter fragility curve fitted on the other storms, [M1] changed county
error by [x]% (better on [a], worse on [b] of 24; p = [p]) and storm-total error by [y]; this does not meet the
pre-registered bar, so the serving forecast stays [B3/F2]."

## Quick wins (RX-6 section 6), applied to every method
1. Loss aligned with the metric: customer weights everywhere; totals from the marginal mean, the county view
   from the median storm (choice 3); B3m is the mean-calibrated fragility curve.
2. `rain_antecedent_14d_mm` servable (in F2, M1). A 30-day antecedent total (IEMRE, same endpoint) is fetched
   and reported only as a sensitivity: F2 with 30 d in place of 14 d (outer LOSO only, not in the pool).
3. L2 labels (sensitivity only): per county, window from the first time the modelled gust reaches 13 m/s
   minus 6 h to the last time plus 48 h (counties never at 13 m/s: closest approach - 6 h to + 48 h); the
   pre-storm level stays L1's. Every method reported on L1 and L2 (outer LOSO).
4. Gap-aware labels: a missing 15-min slot inside the L1 window is a gap when the nearest reported values
   before and after it both exceed 0.5% of MCC customers (an ongoing outage cannot read zero in between).
   Gap share per county-storm; rows above 20% flagged; sensitivity without them (training and testing, outer
   LOSO). Pre-2018 has no DQI: the 2018-on refit stands.
5. Exposure: customer density beside log customers (F2, M1).
6. Per-storm wind-input bias (geometric mean model/obs over kept ASOS stations) in the detail file.

## Outer-only sensitivities and budget
Sensitivities (L2, gap, ante 30 d) run outer LOSO only, no nested selection, never selected on. Variant budget:
the 8 above plus S5. Approach 4 (neighbouring states) is day 2 and exploratory if run at all.

## Serving candidate (assessment only, not activated)
The headline method refit on the storms that ended before Helene's window (`serving_storms`), its Helene row,
its storm-scale band from tau (exp of the u quantiles mapped to totals) beside the current band
[0.453, 2.209], county intervals and drivers (GLM coefficients). Nothing is saved as the active model.
