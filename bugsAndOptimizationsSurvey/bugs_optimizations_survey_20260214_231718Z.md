# Image-Mate Bugs and Optimizations Survey

Generated (UTC): 2026-02-14
Workspace: `/Users/mark/Documents/dev/spotlite-2026/image-mate`

## Scope and Method
- Reviewed backend and frontend source paths end-to-end (`backend/app/*.py`, `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`, tests, scripts).
- Ran static sanity checks:
  - `python3 -m compileall -q backend/app` (pass)
  - `node --check frontend/app.js` (pass)
- Ran unit tests:
  - `../.venv/bin/python -m unittest discover -q backend/tests` (pass, 43 tests)
  - `pytest` unavailable in current venv (`No module named pytest`).

## Executive Summary
The platform is feature-rich, but there are several high-impact risks for production-grade stability/performance/security:
- Critical request-proxy security exposure (SSRF class) in download/proxy endpoints.
- Multiple frontend DOM injection/XSS vectors from unsanitized API-derived fields.
- A real regex bug in Satellogic capture grouping logic that can degrade cloud-filter correctness.
- Memory/perf scaling issues (unbounded caches + large in-memory responses + heavy state persistence writes).
- Automation gaps (no CI pipeline, no lint/type gates, no pytest dependency in environment).

## Prioritized Findings

### 1) High: SSRF risk in backend URL proxy/download endpoints
- Files:
  - `backend/app/main.py:1196`
  - `backend/app/main.py:1254`
  - `backend/app/main.py:1141`
  - `backend/app/main.py:1167`
- Problem:
  - `/api/assets/proxy` and `/api/download/zip` fetch user-supplied URLs with minimal validation (scheme + host present), enabling server-side requests to arbitrary destinations.
- Impact:
  - If deployed in any networked environment, internal services/metadata endpoints can be probed/exfiltrated.
- Recommendation:
  - Enforce strict allowlist by domain/provider.
  - Resolve DNS and block private/link-local/loopback ranges post-resolution.
  - Add signed URL policy or backend-issued asset tokens instead of raw passthrough URLs.

### 2) High: Multiple frontend XSS injection vectors via `innerHTML`
- Files:
  - `frontend/app.js:2685`
  - `frontend/app.js:2849`
  - `frontend/app.js:3650`
  - `frontend/app.js:5165`
  - `frontend/app.js:5201`
  - `frontend/app.js:5216`
- Problem:
  - API-derived values are interpolated directly into HTML templates.
  - `escapeHtml` does not escape quotes, but is used inside HTML attributes.
- Impact:
  - Malicious or malformed upstream metadata can execute script in browser context.
- Recommendation:
  - Replace template-string HTML injection with DOM API (`textContent`, `setAttribute`).
  - Upgrade escaping for attribute contexts (`& < > " '`).
  - Add unit tests for sanitizer edge cases.

### 3) High: Regex bug breaks capture-pattern fallback grouping
- File:
  - `backend/app/satellogic_client.py:452`
  - `backend/app/satellogic_client.py:465`
- Problem:
  - Raw regex strings use doubled slashes (`r"_SN\\d+_"`, `r"(\\d{8}_...)"`) so `\d` is treated literally, not as digit class.
- Impact:
  - Capture key fallback fails when `outcome_id` is missing; cloud-average grouping can become incorrect/inconsistent.
- Recommendation:
  - Fix to `r"_SN\d+_"` and `r"(\d{8}_\d{6}_\d+_SN\d+)"`.
  - Add targeted tests for capture grouping without `outcome_id`.

### 4) Medium: Unbounded `item_cache` growth in backend
- File:
  - `backend/app/main.py:81`
  - `backend/app/main.py:1810`
  - `backend/app/main.py:1879`
- Problem:
  - `app.state.item_cache` is never evicted/TTL-pruned.
- Impact:
  - Long sessions or high traffic can accumulate large objects (`raw` STAC payloads), increasing memory and GC overhead.
- Recommendation:
  - Add bounded LRU+TTL cache (size configurable).
  - Store minimal normalized item payload instead of full raw unless explicitly requested.

### 5) Medium: Large in-memory ZIP assembly can cause OOM under heavy use
- File:
  - `backend/app/main.py:1153`
  - `backend/app/main.py:1186`
- Problem:
  - `/api/download/zip` builds entire archive in `BytesIO` before response; request permits up to 500 assets with no aggregate-byte guardrail.
- Impact:
  - Memory spikes and process instability.
- Recommendation:
  - Stream ZIP output to temp file/streaming response.
  - Enforce max total bytes and per-asset size budget.

### 6) Medium: Workbench persistence design scales poorly with run volume
- File:
  - `backend/app/workbench.py:393`
  - `backend/app/workbench.py:951`
  - `backend/app/workbench.py:960`
  - `backend/app/workbench.py:1025`
- Problem:
  - Full state JSON rewrite on frequent updates (logs/stage status/cache). `stage_cache` and run metadata keep growing.
- Impact:
  - I/O contention, larger pause times, startup/load slowdown, and eventual state-file bloat.
- Recommendation:
  - Move run/event/stage cache to SQLite/Postgres.
  - Apply retention windows and max-entry caps.

### 7) Medium: UI stale-data race during rapid map interactions
- File:
  - `frontend/app.js:4268`
  - `frontend/app.js:4271`
  - `frontend/app.js:4408`
- Problem:
  - Debounced refresh exists, but in-flight requests are not cancelled or sequence-guarded; slower old responses can overwrite newer viewport state.
- Impact:
  - Flicker, incorrect overlays, reduced perceived quality under heavy pan/zoom.
- Recommendation:
  - Add `AbortController` for search requests.
  - Track request token/version and discard late responses.

### 8) Medium: `run.sh` always starts backend with `--reload`
- File:
  - `backend/run.sh:21`
- Problem:
  - Hot-reload mode is always enabled.
- Impact:
  - Unnecessary overhead and reloader process in non-dev runtime.
- Recommendation:
  - Gate reload by env flag (e.g., `IMAGE_MATE_DEV_RELOAD=true`).

### 9) Medium: Quality automation gaps (CI/lint/type/perf gates)
- Evidence:
  - No `.github` workflow present.
  - `backend/requirements.txt` does not include `pytest` despite test suite expectations.
  - No lint/type tooling config discovered for backend/frontend gates.
- Impact:
  - Regressions are easier to ship; performance/security drift harder to catch early.
- Recommendation:
  - Add CI pipeline for tests, lint, type checks, and minimal smoke/perf checks.
  - Add reproducible dev/test commands and lockfile strategy.

## Optimization Opportunities (Platform-Grade UX)
1. Replace synchronous `requests` fanout with pooled clients and controlled concurrency for tile/asset fetch paths.
2. Split/organize `frontend/app.js` (currently ~7k lines) into modules; add build-time minification and tree-shaking.
3. Add request-level telemetry and budgets (p95 tile latency, cache hit-rate, dropped frame overlays).
4. Promote cache strategy to layered design:
   - client-side tile cache + server LRU/TTL + optional CDN edge caching.
5. Introduce progressive rendering strategy for detail mode with cancellation and priority queues.

## Test and Verification Notes
- Passing checks:
  - Syntax and compile checks passed.
  - `unittest` suite passed (`43 tests`).
- Gaps:
  - `pytest` execution unavailable in venv (`No module named pytest`).
  - No tests found for high-risk endpoints (`/api/assets/proxy`, `/api/download/zip`) security behavior.

## Recommended Next Sequence
1. Security hardening first: SSRF + XSS + regex fix.
2. Stability/perf second: cache bounds, streaming ZIP, stale-request cancellation.
3. Platform hardening third: CI + lint/type/perf gates + observability SLO dashboard.
