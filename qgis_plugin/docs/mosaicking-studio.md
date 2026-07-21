# Mosaicking Studio

Mosaicking Studio creates a local GeoTIFF mosaic from raster layers already
loaded in the QGIS project. It is available under **Geoprocessing → Mosaicking →
Mosaicking Studio**.

## Runtime requirements

The mosaicking engine requires Python 3.10 or newer and these packages in the
Python environment used by QGIS:

- NumPy 1.24 or newer
- Rasterio 1.3.9 or newer
- SciPy 1.10 or newer
- OpenCV (`opencv-python-headless`) 4.8 or newer
- Shapely 2.0 or newer
- Affine 2.4 or newer

Install packages into the QGIS Python environment, not a separate system Python
environment. The exact interpreter/installation command varies by QGIS package
and operating system. Missing dependencies affect Mosaicking Studio execution
only; Image Mate continues to load and reports the import error when a mosaic is
started.

## Create a mosaic

1. Add at least two local raster files to the QGIS project.
2. Open **Geoprocessing** and click **Mosaicking Studio**.
3. On the **Inputs** tab, select the raster layers to include and click **Next**.
4. On the **Output** tab, choose a `.tif` or `.tiff` output. Enable replacement
   only when an existing file should be overwritten. Enable **Include debug
   information** when troubleshooting to include detailed request, task,
   dependency-loading, engine, and output-verification messages. Click **Next**.
5. On the **Review** tab, confirm the request and click **Finish**.
6. Keep the studio open on **Processing Results**. Its progress bar and live,
   timestamped log show planning, source analysis, seam generation, tile writing,
   overview creation, and the final result. The studio prevents accidental closing
   while the task is running.
7. When processing succeeds, Image Mate adds the output to the Image Mate layer
   group and enables **Close**. Failures remain visible in the same results tab.

If progress appears stalled, rerun with **Include debug information** enabled and
use the last `DEBUG:` message to distinguish task submission, worker startup,
dependency loading, engine execution, and output verification.

Task states are logged by name and number. A task that terminates before its
normal completion callback now reports QGIS's stored exception in Processing
Results and enables **Close** instead of remaining stuck.

The engine also writes `<output>.analysis.json` beside the mosaic. It contains
the grid plan, radiometric transforms, cloud statistics, seam statistics, and
processing settings.

## Current engine behavior

This lift-and-shift integration preserves the `Mosaicker_v2` defaults:

- global gain-and-offset radiometric balancing;
- automatic sensor-agnostic cloud scoring;
- graph-cut seam planning with deterministic fallback;
- 64-pixel cosine feathering;
- tiled, bounded-memory GeoTIFF writing with DEFLATE compression; and
- internal overviews and a validity mask.

Selected inputs must resolve to existing local files and must use compatible
band meanings/order. Remote WMS/WMTS/XYZ layers are not accepted by this MVP.

## Deferred studio capabilities

- Create, import, and edit cutlines.
- Change seam ownership interactively.
- Adjust feathering and cloud detection/removal parameters.
- Assign external cloud masks or per-input priorities.
- Save and reopen a studio session.

## Source and license

The engine was copied without algorithm changes from local project
`Mosaicker_v2`, version 1.0.0. Its MIT license is stored at
`image_mate_qgis_plugin/vendor/mosaicker/LICENSE`.
