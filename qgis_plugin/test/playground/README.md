# Vessel DB Prototype Parser

This playground contains a prototype parser that ingests:

- `G:\My Drive\Vessel DB\Vessel DB.pdf`

and writes a normalized SQLite database.

## Script

- `qgis_plugin/test/playground/parse_vessel_db_prototype.py`

## Run

From repo root:

```powershell
py qgis_plugin\test\playground\parse_vessel_db_prototype.py --force
```

Or with the venv interpreter:

```powershell
.\.venv\Scripts\python.exe qgis_plugin\test\playground\parse_vessel_db_prototype.py --force
```

## Output

Default DB output path:

- `qgis_plugin/test/playground/asset_intel_prototype.sqlite`
- optional legacy path: `qgis_plugin/test/playground/vessel_db_prototype.sqlite`

## Notes

- The parser auto-detects whole-file concatenation duplicates and parses only the unique block.
- It stores both normalized fields and raw text/URLs to avoid losing source detail.
- It now emits normalized tables for:
  - `asset_profile`
  - `asset_dimension` (length/width/draft/tonnage, plus normalized metric values)
  - `asset_system` + `asset_system_attribute` (per-system parsed rows)
  - `analyst_note` (empty table scaffold for plugin-side notes)
