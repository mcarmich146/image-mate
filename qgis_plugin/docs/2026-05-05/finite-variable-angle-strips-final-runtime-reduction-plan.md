# Finite Variable Angle Strips Final - Runtime Reduction

Date: 2026-05-05
Owner: Codex

## Goal

Reduce optimization runtime per run while keeping full AOI coverage behavior.

## Changes Applied

1. Bounded local search per strip step
- Replaced unbounded repeated failed picks with `--seed-tries-per-strip` (default `6`).
- At each strip step, sample a fixed number of random seeds and keep the locally best placement by `new_area_m2`.

2. Bounded trial stagnation
- Added `--max-failed-steps` (default `25`) to stop a trial after consecutive no-progress strip steps.

3. Trial-level pruning against current best
- Added `best_length_cap_m` pruning in `run_single_trial`.
- If current trial cumulative length already exceeds current global best feasible total length, stop that trial early.

4. Faster chord angle search
- Updated shortest-chord search to two-stage evaluation:
  - coarse pass at `2 * chord_angle_step`
  - local refine pass around the best coarse angle at `chord_angle_step`

## Why This Speeds Up

- Prevents thousands of expensive no-progress seed/chord attempts.
- Reduces angle evaluations per seed with coarse/refine chord search.
- Stops losing trials early once they cannot beat the incumbent best KPI.

## Validation

Executed with `.venv` Python:

- Baseline-style command (before optimization, same 10-trial config) previously observed ~1702s runtime.
- After optimization (same 10-trial config): ~54.81s runtime.
- Coverage remains full on fixture (`linear_polygon.geojson`):
  - effective output coverage gap `0.000000 km2`
  - written effective output coverage gap `0.000000 km2`

Smoke test:

- `qgis_plugin/test/finite_variable_angle_strips_final_smoke.py` passed.

## Notes

- Runtime improved significantly, but solution quality (total strip length) can vary with trial count and randomness.
- If needed later, tune `--seed-tries-per-strip` and `--trials` for quality/speed tradeoff.
