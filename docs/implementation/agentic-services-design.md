# Image-Mate Agentic Services — Phase 1 Design

**Revision:** 2026-09-18
**Decision source:** User design answers in the Hermes session on 2026-09-18.

## Goal

Make Image-Mate useful as a backend-independent agentic tool set: the agent can create and maintain durable projects, sites, and context while the browser UI remains an optional projection of the same state. When the UI is started later, agent-created work must be visible without an import step.

## Confirmed decisions

- **Execution model:** shared Python agent services with SQLite state; the UI is optional.
- **Durable state:** reuse Image-Mate SQLite stores and add a shared workflow database only where a later phase needs it.
- **Phase 1 scope:** project, site, and context management only.
- **Autonomy:** the agent may prepare and execute non-provider work automatically, but must ask the user to confirm the final plan immediately before provider tasking.
- **Task naming:** every provider-facing tasking order name is normalized idempotently to `Mark - <original name>`, including grid, successor, retask, extension, and remaining-AOI orders.

## Architecture

```text
Agent CLI / future Hermes service
          |
          +-- AgentProjectService (pure local orchestration)
          |       +-- project/site validation
          |       +-- context versioning and history
          |       +-- geometry derivation from site registries
          |
          +-- MonitoringStore (shared monitoring.sqlite3)
                  +-- monitoring_projects
                  +-- monitoring_project_sites
                  +-- monitoring_project_context
                  +-- monitoring_project_context_history

Optional FastAPI backend/UI
          |
          +-- existing monitoring project routes read the same store
          +-- UI lists draft/disabled agent-created projects
          +-- site/context summaries are available for later detail views
```

The Phase 1 agent path must not import `backend.app.main`, start Uvicorn, refresh provider credentials, or call Satellogic. It may import the lightweight configuration and store/service modules. Provider search, opportunity analysis, and tasking remain later adapters with their existing confirmation gates.

## Durable data model

Extend the existing monitoring SQLite store with:

- `monitoring_project_sites`: stable `project_id` + `site_id`, display name, WGS84 latitude/longitude, footprint, optional GeoJSON geometry, provenance/notes, and active state.
- `monitoring_project_context`: current Markdown/text, source ledger, version, and update timestamp.
- `monitoring_project_context_history`: append-only prior context versions for auditability.
- `monitoring_projects.lifecycle_status`: `draft`, `approved`, `active`, `paused`, or `archived`; existing API-created enabled projects remain active, while disabled agent-created projects default to draft.

All migrations must be additive and safe against an existing database. No signed URLs, credentials, or authorization headers may enter these tables.

## Phase 1 interfaces

### Agent service

`backend/app/agent_projects.py` exposes a backend-independent `AgentProjectService` with:

- `create_project(project, sites, context=None)`;
- `list_projects()` and `get_project(project_id)`;
- `replace_sites(project_id, sites)` and `list_sites(project_id)`;
- `upsert_context(project_id, text, sources)` and `get_context(project_id)`;
- deterministic site validation and optional site-centered geometry derivation.

### CLI

`backend/scripts/image_mate_agent.py` provides local commands for project creation/list/show, site replacement/listing, and context import. Commands operate directly on the shared SQLite store and never require the FastAPI server.

### UI/API projection

Existing monitoring project reads expose lifecycle status, site count, and context freshness. The UI lists all projects, including draft/disabled projects, while only enabled projects are offered as tasking links. Detailed site/context routes are read-only in Phase 1.

## Safety and naming

- New agent projects default to `draft` and `enabled=false`.
- No provider call occurs during project/site/context operations.
- Tasking plan generation may be automatic in a later phase, but the final provider payload requires user confirmation.
- The final provider-facing name, not the user’s unprefixed draft, is used for preview, confirmation, exact-name reconciliation, and submission.
- `Mark -` normalization is idempotent and canonicalizes prior `Mark —`/`Mark:` variants rather than stacking prefixes.

## Acceptance criteria

1. The Phase 1 CLI creates a project, 13 sites, and versioned context while the backend is stopped.
2. A fresh read of the shared SQLite database returns the project, all sites, and current context without importing files into the UI.
3. Existing monitoring API reads expose the agent-created project and site/context summaries.
4. The UI lists draft/disabled projects without making them eligible for tasking links.
5. Existing project/monitoring tests remain green.
6. Tasking preview and submission use `Mark - <name>` and require confirmation of the final normalized name.
7. Grid and successor tasking names are normalized exactly once.
8. No provider endpoint is called by Phase 1 operations.

## Deferred work

- Generic workflow queue and worker process.
- Archive search/monitor refresh from the backend-independent agent.
- Report generation and context retrieval automation.
- Provider opportunities and tasking execution from the agent.
- UI editing of sites and context; Phase 1 UI is a durable-state projection and inspection surface.
