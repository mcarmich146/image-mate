"""Manual smoke runner for Simulation point revisit worker.

Run inside a QGIS Python environment after installing:
    skyfield==1.54
"""

from datetime import datetime, timedelta, timezone
import json

from image_mate_qgis_plugin.simulation.revisit_worker import PointRevisitSimulationWorker


def _payload():
    start = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=12)
    return {
        "scenario_id": "point_revisit_analysis",
        "selection_mode": "top_n",
        "satellite_count": 1,
        "selected_satellite_ids": [],
        "off_nadir_deg": 30.0,
        "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_step_sec": 120,
        "target": {
            "lat": -34.603722,
            "lon": -58.381592,
            "source": "manual",
            "label": "Buenos Aires",
        },
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
    worker = PointRevisitSimulationWorker(_payload())
    result = worker._execute()
    print("Point revisit smoke result:")
    print(json.dumps(result, indent=2)[:4000])
    print(
        "Summary:",
        f"events={int(result.get('total_collection_events', 0) or 0)},",
        f"first={result.get('first_access_utc')},",
        f"last={result.get('last_access_utc')},",
        f"longest_gap_min={float(result.get('longest_gap_min', 0.0) or 0.0):.2f}",
    )


if __name__ == "__main__":
    main()
