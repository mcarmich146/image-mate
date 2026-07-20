# Vessel Training Scripts (Scaffold)

This folder contains the initial local CLI scaffolding for vessel model lifecycle steps:

- `export.py`
- `train.py`
- `evaluate.py`
- `promote.py`

Current state:

- Phase-0/Phase-1 scaffolding only.
- CLI contracts and artifact shapes are stabilized.
- Full QA dataset conversion, Ultralytics training execution, and metric computation are intentionally incremental and not fully implemented in this first coding slice.

Recommended flow (current scaffold):

1. Run `export.py` to initialize dataset structure and metadata.
2. Run `train.py` to initialize a training run folder and run contract.
3. Run `evaluate.py` to write an evaluation artifact skeleton.
4. Run `promote.py` to evaluate candidate-vs-production metrics against conservative gate and update registry.
