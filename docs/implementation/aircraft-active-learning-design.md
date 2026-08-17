# Aircraft Active-Learning Review and Fine-Tuning Design

**Revision:** 2026-08-15, initial design confirmation
**Source:** User-directed follow-up to the Bamako-Sénou L1D-SR detector run

## Goal

Improve aircraft/ helicopter detection on high-resolution Satellogic L1D-SR imagery through a human-in-the-loop review loop that works from Mark's phone over Telegram. Preserve the current detector as a baseline, collect auditable labels, and fine-tune only after a scene-separated validation set exists.

## User-visible first phase

This workflow is deliberately restricted to Satellogic `l1d-sr` / L1D-SR products. QuickView, Sentinel-2, provider analytics, and products without explicit WGS84 bounds are rejected. L1D-SR is the only imagery source included in reports or fine-tuning data because the workflow needs the highest available resolution and reliable image-to-map alignment.

1. Run one L1D-SR tile at a low confidence threshold to produce a broad candidate pool.
2. Deduplicate overlapping proposals for review, while preserving the original model boxes and scores.
3. Generate small image chips centered on candidates, with enough context to distinguish plane, helicopter, and background.
4. Send chips through Telegram in manageable batches. Mark replies:
   - `1` = plane / fixed-wing aircraft
   - `2` = helicopter
   - `3` = background / no detection
   - `0` = unsure / skip
5. Persist every label with candidate ID, source scene, model version, threshold, crop geometry, and timestamp.
6. Run a second systematic overlapping grid pass so objects absent from the detector's proposal set can be discovered.

## Training intent

The labels support two complementary improvements:

- **Detector fine-tuning:** accepted proposals retain their current OBB geometry as a starting annotation. Manually confirmed missed objects must eventually receive a box annotation before they can become true detector-training examples.
- **Candidate reranking/subclassification:** plane/helicopter/background chips can train a lightweight crop classifier or reranker, improving precision and subclass decisions without requiring a new detector for the first iteration.

The pipeline must not imply that candidate-only labels can recover completely missed objects. Grid-review positives are retained as discovery evidence and can be promoted to detector labels after box annotation.

## Confirmed repository assumptions

- `backend/app/aircraft_detector.py` already produces normalized pixel boxes and OBB polygons from one image tile.
- `backend/scripts/detect_aircraft.py` already supports adjustable confidence, IoU, provider, bounds, and output path.
- The tracked model is YOLO11n-OBB/DOTAv1 with `plane` and `helicopter` classes; current output is model evidence, not ground truth.
- The current detector uses class-aware NMS, so cross-class duplicate proposals are possible and must be deduplicated for review and later evaluation.
- The repository uses Python `unittest`-style tests under `backend/tests` and has no existing active-learning/training pipeline.
- The existing Hermes skill runs one-tile inference and preserves result artifacts; the review workflow should extend that procedure rather than change provider analytics routes.

## Implementation adaptations

- The first review transport is a Hermes/Telegram-driven CLI workflow, with a local Model Lab UI for archive selection and polygon annotation. The public API persists analyst geometry but never accepts arbitrary provider URLs or credentials.
- Labels are stored as append-only JSONL plus a manifest, matching the artifact-oriented workflows already used for detector provenance.
- Chip generation is deterministic and records source coordinates, padding, context scale, and the original proposal. This makes labels reproducible and exportable to later YOLO/classifier formats.
- A class-agnostic spatial deduplication pass is used for review candidates, while the raw detector output remains unchanged for auditability.
- Luna is used as a few-shot reviewer through the Hermes-managed `gpt-5.6-luna` route. Confirmed human examples prime each evaluation prompt; Luna output is stored as review evidence and never replaces a human label.
- Batch inference and batch chip preparation preserve a per-scene manifest so a series of downloaded L1D-SR tiles can be resumed from Telegram.

## Planned components

- `backend/app/aircraft_review.py`: pure candidate deduplication, chip geometry, manifest, and label-state helpers.
- `backend/scripts/aircraft_review.py`: `prepare`, `label`, `grid`, and dataset-export commands.
- `backend/app/luna_aircraft.py`: confirmed-example packets, Luna prompt construction, and append-only evaluation records.
- `backend/scripts/detect_aircraft_batch.py`: host-side batch inference over sidecar-provenanced L1D-SR tiles.
- `backend/app/main.py` and the Model Lab UI: local annotation persistence, model/dataset catalog, detector review actions, and map polygon capture.
- `backend/tests/test_aircraft_review.py`: deterministic unit tests for geometry, deduplication, state transitions, and safe label validation.
- `image-mate-local-aircraft-detection` Hermes skill: phone review procedure and absolute-path/CPU-GPU caveats.

## Requirements and acceptance criteria

- **AL-001:** `prepare` accepts one detector JSON and source image, produces deterministic chips and a review manifest.
- **AL-002:** Overlapping cross-class predictions for one object produce one review candidate with alternative proposals retained.
- **AL-003:** Chips never exceed source bounds; edge chips are padded deterministically and record the source crop box.
- **AL-004:** Only `plane`, `helicopter`, `background`, and `skip` labels are accepted; duplicate relabeling is idempotent and conflicting relabels are rejected unless explicitly overridden.
- **AL-005:** Labels contain no credentials, signed URLs, or arbitrary remote paths.
- **AL-006:** `grid` produces an overlapping full-image discovery manifest distinct from detector candidate labels.
- **AL-007:** Dataset export preserves scene IDs and supports grouping/splitting by scene, preventing chips from one source scene leaking into validation.
- **AL-008:** Existing detector tests and full backend tests remain green.
- **AL-009:** Luna evaluations preserve human labels and produce a separate JSONL audit trail.
- **AL-010:** An explicit held-out manifest produces `images/val` and `val: images/val`; training refuses to call a run scene-validated without independent validation data unless `--allow-single-scene` is explicit.

## Blocking decisions deferred until the first labeled batch

- Whether to train a two-class OBB detector from the current YOLO11n-OBB weights or add a classifier/reranker first.
- Exact chip size/context and candidate volume after Mark sees the first batch.
- Whether missed-object box annotation should be done with a small web panel or a later manual annotation pass.
- Host-side CoreML/MPS training environment; the Hermes Docker runtime cannot verify or use the laptop GPU.
