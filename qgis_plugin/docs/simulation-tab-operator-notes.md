# Simulation Tab Operator Notes

## Runtime Dependency
The Simulation tab coverage analysis requires Skyfield in the QGIS Python runtime.

Recommended install:

```powershell
python -m pip install skyfield==1.54
```

If Skyfield is missing, simulation start will fail with an explicit error message.

## Default Constellation Seed
New/empty simulation configs are seeded with one enabled default entry:
`Simulation SSO 475km` (`SIM-SSO-475`) using a synthetic ~475 km sun-synchronous style TLE.

## Supported MVP Workflow
1. Open `Simulation` tab.
2. Configure constellation satellites with TLEs.
3. Choose selection mode:
- `Top N by Priority` or
- `Manual Selection` using the `Include` column.
4. Choose AOI source:
- `Current Map Extent`, or
- `Selected Polygon Layer`.
5. Set off-nadir, UTC time window, and timestep.
6. Click `Start Simulation`.
7. Navigate daily outputs with left/right arrows.

## Metric Semantics
1. A pass is counted as a collection only when pass footprint intersects AOI.
2. Per-pass imaged area is `intersection(pass_footprint, AOI)`.
3. `Total unique area covered` is the union of all pass-imaged AOI geometries.
4. `Total area imaged` is the sum of all per-pass imaged areas (overlap counted multiple times).

## Output Layers
Day navigation renders:
1. `Image Mate Simulation - Day Imaged`
2. `Image Mate Simulation - Cumulative Unique`

Both layers are created in the `Image Mate` layer group.
