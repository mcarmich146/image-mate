"""Manual smoke runner for Simulation coverage worker.

Run this inside a QGIS Python environment after installing:
    skyfield==1.54
"""

from datetime import datetime, timedelta, timezone
import json

from image_mate_qgis_plugin.simulation.coverage_worker import CoverageSimulationWorker


def _aoi_geojson():
    # Small AOI near Buenos Aires for smoke checks.
    min_lon = -58.55
    min_lat = -34.75
    max_lon = -58.20
    max_lat = -34.45
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lon, min_lat],
            [max_lon, min_lat],
            [max_lon, max_lat],
            [min_lon, max_lat],
            [min_lon, min_lat],
        ]],
    }


def _payload():
    start = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=12)
    return {
        "scenario_id": "coverage_analysis",
        "selection_mode": "top_n",
        "satellite_count": 1,
        "selected_satellite_ids": [],
        "off_nadir_deg": 30.0,
        "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_step_sec": 120,
        "aoi_source": "map_extent",
        "aoi_layer_id": "",
        "aoi_geojson": _aoi_geojson(),
        "satellites": [
            {
                "satellite_id": "ISS",
                "name": "ISS",
                "priority": 1,
                "enabled": True,
                "tle": {
                    "line1": "1 25544U 98067A   26050.52916667  .00006753  00000+0  12574-3 0  9992",
                    "line2": "2 25544  51.6432 302.5030 0004970  56.8578  45.6498 15.50009812399999",
                },
            }
        ],
    }


def main():
    worker = CoverageSimulationWorker(_payload())
    result = worker._execute()
    print("Simulation smoke result:")
    print(json.dumps(result, indent=2)[:4000])
    print(
        "Summary:",
        f"unique={result.get('total_unique_area_km2', 0.0):.2f} km2,",
        f"total={result.get('total_area_imaged_km2', 0.0):.2f} km2,",
        f"passes={int(result.get('total_collection_passes', 0) or 0)}",
    )


if __name__ == "__main__":
    main()

