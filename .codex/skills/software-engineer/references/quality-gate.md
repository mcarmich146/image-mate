# Implementation Quality Gate

Run this gate before marking a requirement-driven change complete.

## Architecture

- Module boundaries are clear and aligned with domain responsibilities.
- Dependency direction is controlled and intentional.
- Public interfaces are stable and minimal.
- New abstractions are justified by repeated need, not speculation.

## Code Quality

- Naming is domain-oriented and intention-revealing.
- Functions/classes are cohesive and sized for readability.
- Error handling is explicit and actionable.
- Dead code and temporary scaffolding are removed.

## Testing

- Every acceptance criterion maps to automated verification.
- Core logic has unit tests.
- Cross-boundary behavior has integration/contract tests where needed.
- Regression tests exist for bug fixes and high-risk paths.

## Operations

- Logs and metrics support diagnosis of critical failures.
- Backward compatibility/migration behavior is verified where relevant.
- Rollout and rollback strategy is defined for risky changes.

## Traceability and Documentation

- Requirement ID -> code -> test mapping is documented.
- Key design decisions and tradeoffs are documented.
- User-facing or operator-facing docs are updated if behavior changed.

## Release Readiness

- Build, lint, type checks, and tests pass in expected environments.
- No known critical defects remain without explicit sign-off.
