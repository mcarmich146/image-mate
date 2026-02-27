# Terminal-Only Test Patterns

Design tests as if only terminal access is available and bandwidth is limited.

## Core Principles

- Prefer deterministic checks over visual checks.
- Validate contracts (inputs, outputs, side effects) rather than rendered imagery.
- Use tiny fixtures and minimal network dependencies.
- Make each check scriptable with clear exit codes.

## Derive Tests From Behavior

For each changed behavior, capture:

1. Input contract
2. Expected output contract
3. Side effects (files, DB rows, log events, emitted payloads)
4. Failure path and error messaging

Translate each into a CLI-verifiable assertion.

## Suggested Check Types

- Input validation:
  - Invalid AOI, missing config keys, unsupported modes
  - Assert explicit error type/message and non-zero exit code
- Deterministic transformations:
  - Assert output schema, field ranges, and stable ordering
  - Assert no hidden dependency on GUI state
- Integration seams:
  - Stub/mock external clients
  - Assert request payload shape and retry behavior from logs or counters
- Persistence and cache:
  - Assert created/updated records using lightweight SQL or JSON checks
  - Assert idempotence for repeated runs
- Worker execution:
  - Run short smoke paths that complete quickly
  - Assert progress/report fields and completion status

## Existing Test Entrypoints

- `qgis_plugin/test/simulation_smoke_runner.py`
- `qgis_plugin/test/point_revisit_smoke_runner.py`
- `qgis_plugin/test/streaming_gap_probe.py`
- `qgis_plugin/test/wms_tester/outcome_gap_check.py`

Prefer extending these patterns with lightweight probes before creating new heavy test harnesses.

## Terminal Test Definition of Done

- Tests run without opening the QGIS GUI.
- Tests avoid downloading large imagery unless explicitly required.
- Tests produce machine-readable outputs (JSON/text) and non-zero exit on failure.
- Tests isolate backend behavior even when UI files are touched.
