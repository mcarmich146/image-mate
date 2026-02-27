# QGIS Plugin Module Map

Use this map to keep logic in backend modules and keep UI modules thin.

## Backend-First Ownership

- `qgis_plugin/image_mate_qgis_plugin/services/`
  Implement business rules, orchestration, persistence wiring, and integration calls.
- `qgis_plugin/image_mate_qgis_plugin/simulation/`
  Implement simulation computation and domain workflows.
- `qgis_plugin/image_mate_qgis_plugin/workflow_execution/`
  Implement execution engines, workers, and workflow orchestration state.
- `qgis_plugin/image_mate_qgis_plugin/workflow_plugins/`
  Implement reusable processing plugins and pure operations where possible.
- `qgis_plugin/image_mate_qgis_plugin/controllers/`
  Implement input validation and request-to-service delegation.
- `qgis_plugin/image_mate_qgis_plugin/clients/`
  Implement external API adapters and source configuration logic.
- `qgis_plugin/image_mate_qgis_plugin/mixins/`
  Implement shared backend behaviors that are reused across plugin entry points.

## UI Ownership (Keep Dumb)

- `qgis_plugin/image_mate_qgis_plugin/ui/`
  Restrict to:
  - Widget construction
  - Signal-slot connections
  - Reading UI state and passing it to backend services
  - Displaying backend outputs and progress

Do not place heavy business logic, data processing loops, or integration behavior here unless there is no alternative. If unavoidable, extract quickly into backend modules.

## Out-of-Scope Directories

Do not change these when using this skill:

- `backend/`
- `frontend/`
- `ml/`
- Any path outside `qgis_plugin/`

Run `scripts/check_scope.py` before completion to enforce this boundary.
