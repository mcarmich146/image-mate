# Data-center construction animations — research and execution handoff

Prepared 9 September 2026. Repository: /Users/mark/.hermes/projects/image-mate, branch main, inspected commit 22316b6.

## 1. Outcome and scope

This is a researched plan, not an implemented feature or a completed animation project. Live Satellogic archive searches were performed through Image Mate's existing client. No source code or configuration was changed, no imagery-processing orders or new taskings were submitted, and no animations were generated.

The initial US shortlist contains seven OpenAI/Stargate campuses, three SpaceX/xAI facilities, Amazon's New Carlisle campus used by Anthropic, an Anthropic-linked Lake Mariner candidate, and a provisional search neighborhood for Hut 8's River Bend campus. This is a prioritized starter portfolio, not an exhaustive inventory of these companies' worldwide computing infrastructure.

Recommended first publication targets:

1. Abilene: eight metadata-screened existing L1D-SR captures, plus two August 2026 L1D captures worth considering for super-resolution processing.
2. Colossus 1: 33 metadata-screened existing L1D-SR captures during August–December 2025. The likely story is expansion/conversion, not the original 2024 build.
3. Colossus 2: three metadata-screened, full-search-area L1D-SR captures during one week in December 2025. Investigate additional raw captures to extend the story; a one-week sequence alone may show little change.
4. Colossus 3: existing December 2025 imagery provides a pre-announcement baseline, not proof of the 2026 data-center conversion. Later raw captures or new tasking are needed.
5. Future monitoring: prioritize New Carlisle, Port Washington, and Saline, where no usable archive coverage was established; also extend sparse construction sequences at Shackelford, Milam, Jupiter, and River Bend.

“Metadata-screened” means footprint coverage of at least 99.5% of the searched rectangle, mean scene/tile cloud metadata at most 20%, and raw STAC visual assets present. It does NOT mean the building is cloud-free, imagery downloads work, or the frame is publication-ready. No imagery binaries were downloaded or visually reviewed.

Evidence files:

- [Machine-readable archive inventory](data-center-imagery-2026-09-09.json): item/outcome IDs, dates, counts, coverage estimates, raw-footprint flags, exact search rectangles, and order audit.
- [Search AOIs](data-center-search-aois-2026-09-09.geojson): importable research rectangles, explicitly not approved tasking polygons.

## 2. Access findings — a refreshed key was not required for this investigation

The configured credentials successfully obtained OAuth access and listed contracts. The initially configured contract produced an archive authorization failure. Using the contract returned for this account fixed catalog and STAC access:

- Contract name: Sales - Showcase (provider display contains extra spacing).
- Contract ID: cont.eac744cc-2afe-4012-9621-35623feeb7a7.
- Explicitly pass this ID in Image Mate requests and the resulting X-Satellogic-Contract-Id header. Re-list contracts at execution time; do not assume access remains unchanged.
- Do not change a shared default contract without coordinating with the owner of the running application.
- OAuth without a usable contract returned 401 on archive collections; legacy key/secret mode returned 403. This was not evidence of an empty archive.
- The account advertised quickview-visual-thumb, quickview-visual, quickview-toa, l1c, l1d, l1d-sr, l0, l1a, gaia, and gaia-l1d-sr.
- Catalog visibility does not establish billing entitlement, processing eligibility, or permission to publish imagery.

No secrets or signed imagery URLs are included in these artifacts. Keep contract and order details in the internal handoff, not the blog.

## 3. Site inventory and location evidence

Coordinate order in this table is LATITUDE, LONGITUDE. GeoJSON and API positions use LONGITUDE, LATITUDE.

For the Epoch-mapped sites, the centers and rectangles were extracted from the public satellite explorer's embedded dataCenters records. These are more useful than a city centroid but are NOT surveyed property boundaries. The retained rectangles are reproducible search AOIs; verify construction parcels before spending tasking credits. See [Epoch's public satellite explorer](https://epoch.ai/data/ai-data-centers/directory/openai-stargate-abilene/satellite-explorer) and [downloadable directory data](https://epoch.ai/data/data_centers/data_centers.zip) for coordinate/address provenance.

| Site | Location reference, lat / lon | Public location and relationship | Location qualification |
| --- | --- | --- | --- |
| OpenAI — Abilene flagship | 32.501314, -99.785608 | 5502 Spinks Road, Abilene, TX. Crusoe/Lancium campus, Oracle infrastructure used by OpenAI. | Campus map center; distinguish flagship buildings from later separately tenanted expansion. |
| OpenAI — Frontier, Shackelford County | 32.543765, -99.548314 | PR 1604, near Abilene, TX. Vantage campus supporting Oracle/OpenAI. A specific building filing gives 246 PR 1604, Building 5; directory campus address is 175 PR 1604. | Different building/campus addresses, not necessarily a contradiction; use parcel geometry. |
| OpenAI — Freebird, Milam County | 30.996308, -97.010337 | County Road 133, Burlington, TX 76519. Milam County Data Center LLC / SB Energy–SoftBank project; filing identifies OpenAI tenancy. | The initial mapped rectangle is very small; expanded search also performed. Do not substitute Rockdale town center. |
| OpenAI — Project Jupiter | 31.820319, -106.684270 | Santa Teresa, Doña Ana County, NM. Oracle/BorderPlex campus associated with Stargate. | Broad project map rectangle; returned ortho strip covers only part of it. |
| OpenAI — Lighthouse | 43.430405, -87.856036 | Port Washington, WI. Vantage campus supporting Oracle/OpenAI. | Campus map center, not Mount Pleasant/Fairwater. |
| OpenAI — The Barn | 42.121227, -83.884173 | Saline Township, MI. Related Digital / Oracle / OpenAI. | Campus map center, not Saline town center. |
| OpenAI — Lordstown | 41.153112, -80.881228 | 2300 Hallock Young Road, Warren/Lordstown, OH. SoftBank Stargate site. | Verify which work is data-center construction versus server manufacturing/assembly; do not treat the entire former auto plant as compute halls. |
| Anthropic — AWS New Carlisle | 41.679359, -86.471226 | 55001 Larrison Boulevard, New Carlisle, IN; AWS campus within Project Rainier. A state filing also identifies an Amazon building at 55250 Walnut Road. | Multi-building campus. Expanded search included surrounding development area. |
| SpaceX/xAI — Colossus 1 | 35.060166, -90.155460 | Former Electrolux plant, 3231 Paul R. Lowry Road / Riverport Road, Memphis, TN. | Campus map center. Conversion/expansion story; original building predates AI use. |
| SpaceX/xAI — Colossus 2 | 34.999489, -90.042977 | 5420 Tulane Road, Memphis, TN 38109. | US Census street-address match, not building centroid. Separate facility search rectangle retained. |
| SpaceX/xAI — Colossus 3 | 34.991862, -90.034278 | Former GXO warehouse, 2400 Stateline Road W, Southaven, MS 38671. | US Census street-address match. Do not confuse with the gas plant at 2875 Stanton Road. |
| Anthropic / Fluidstack — River Bend | 30.716340, -91.309069 reference point ONLY | Hut 8 campus off LA-964 near US-61, West Feliciana Parish, LA. | PROVISIONAL: this coordinate is the geocoded neighboring commercial property at 2552 LA-964, NOT a verified campus center. A wider neighborhood was searched; obtain the campus parcel before ordering. |
| Lake Mariner — Anthropic candidate | 43.356428, -78.602038 | 7725 Lake Road, Barker/Somerset, NY. TeraWulf/Fluidstack development. | Physical campus identified; specific Anthropic building/tenant attribution remains provisional. Keep separate from Core42's facilities on the same campus. |

Primary and supporting relationship evidence:

- [OpenAI's September 2025 Stargate expansion announcement](https://openai.com/index/five-new-stargate-sites/) identifies Abilene, Shackelford, Doña Ana, Lordstown, Milam and, in its October update, Wisconsin.
- [Vantage's Frontier campus page](https://vantage-dc.com/data-center-locations/north-america/shackelford-county-tx) and [Texas building filing](https://www.tdlr.texas.gov/TABS/Search/Project/TABS2026024094) identify the campus and an individual building address. The filing's completion date is a plan, not proof of completion.
- [Freebird's Texas filing](https://www.tdlr.texas.gov/TABS/Search/Project/TABS2026017746) gives the Burlington location, October 2025 planned start, and OpenAI tenant identification.
- [Jupiter's project website](https://projectjupitertogether.com/) and [Oracle's April 2026 project announcement](https://www.oracle.com/news/announcement/oracle-borderplex-and-bloom-energy-to-power-project-jupiter-with-fuel-cell-technology-2026-04-27/) establish the project identity.
- [Vantage's Lighthouse page](https://vantage-dc.com/data-center-locations/north-america/port-washington-wisconsin) describes a four-building campus planned for completion in 2028.
- [OpenAI's Michigan announcement](https://openai.com/index/expanding-stargate-to-michigan/), [subsequent groundbreaking announcement](https://openai.com/index/stargate-michigan-data-center/), and [Related Digital's project page](https://www.related-digital.com/michigan) identify The Barn.
- [AWS's Rainier announcement](https://www.aboutamazon.com/news/aws/aws-project-rainier-ai-trainium-chips-compute-cluster) explicitly links Anthropic and the St. Joseph County campus; [the Indiana construction filing](https://oas.dhs.in.gov/reports/rwservlet?dfbsepnpdf=&p_form_id=1140442&report=plan_application_information.rdf) supplies a building address.
- [xAI's February 2, 2026 announcement](https://x.ai/news/xai-joins-spacex) explains the SpaceX connection. [Anthropic's May 6 announcement](https://www.anthropic.com/news/higher-limits-spacex) confirms its agreement to use Colossus 1 capacity. Label owner, operator, customer, and observation date separately.
- [Southaven's January 7, 2026 announcement](https://southaven.org/Blog.aspx?IID=227) identifies Colossus 3's former GXO building and separates it from the Stanton Road power plant. [Mississippi's announcement](https://mississippi.org/news/tech-leader-xai-investing-more-than-20-billion-in-southaven/) corroborates the project.
- [Hut 8's December 17, 2025 announcement](https://canada.hut8.com/resources/press-releases/hut-8-announces-ai-infrastructure-partnership-with-anthropic-and-fluidstack) explicitly links River Bend, Fluidstack, and Anthropic. [Local reporting](https://www.kplctv.com/2025/12/18/hut-8-facility-expected-generate-90-million-annually-local-government/) locates it on LA-964; [the adjacent-property brochure](https://images1.showcase.com/d2/-yYFZDLoXi4PVO5mH6UnYICsGuZMsJqkW7xnbeRZHy8/document.pdf) helped define a provisional search neighborhood.
- [Anthropic's infrastructure announcement](https://www.anthropic.com/news/anthropic-invests-50-billion-in-american-ai-infrastructure) names Texas and New York, but does not by itself prove a particular Lake Mariner hall is Anthropic's. Treat that attribution as a hypothesis.
- Address matches used the [US Census geocoder](https://geocoding.geo.census.gov/geocoder/), benchmark Public_AR_Current, on the research date. Address interpolation is not parcel surveying.

Excluded from the current archive audit: overseas campuses; generic partner data centers without a site-specific customer link; and further possible sites such as Microsoft Fairwater/Mount Pleasant, CoreWeave Helios, and newer Southaven proposals. Research and search them separately if the blog scope expands. Never repurpose a SpaceX launch facility as a data-center site.

## 4. Live archive results

Search interval: 2024-09-09 through 2026-09-09 UTC, inclusive of the end day; searches only return acquisitions present at query time. No cloud, satellite-generation, or GSD filters were applied to discovery. Different processing collections can assign slightly different sub-second timestamps to the same outcome; match outcomes, not exact timestamp strings.

Counts below are distinct capture outcome IDs intersecting the selected search AOI. They are not tile counts or distinct calendar days. The complete inventory contains tile IDs and supplementary collection searches.

| Site | QuickView captures | L1D captures | L1D-SR captures | Screened SR frames | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Abilene | 16 | 16 | 14 | 8 | Review existing Jan–Feb 2026 frames; process selected August dates to extend chronology. Sept 7 exists but has ~39% mean cloud. |
| Colossus 1 | 58 | 49 | 50 | 33 | Strongest existing sequence by count: Aug 6–Dec 29, 2025. Missing QuickViews are very cloudy; do not bulk-process them. |
| Colossus 2, facility AOI | 11 | 11 | 11 | 3 | Dec 3, 7, 10, 2025 pass metadata screen. Nov 30 is only ~20% coverage of this rectangle. |
| Colossus 3, separate AOI | 10 | 10 | 10 | 3 | Same three December captures provide a baseline. Need later observations for the conversion story. |
| Shackelford | 1 | 1 | 0 | 0 | Aug 8, 2026 is a processing candidate and only one date; also request future coverage after approval. |
| Milam, initial small AOI | 2 | 2 | 0 | 0 | Aug 6–7, 2026. Expanded AOI also finds two dates; process the better date first and acquire later stages. |
| Jupiter | 1 | 1 | 1 | 0 | Aug 20, 2026: ~18.77% of broad project rectangle. Verify whether a useful hall-level crop is covered. New full-project coverage needed. |
| Lordstown | 0 | 1 | 1 | 0 | June 24, 2025: ~91.31% rectangle coverage and ~29.5% cloud. Potential baseline only after pixel QC. |
| New Carlisle | 0 | 0 | 0 | 0 | No results in original or expanded searches, including L0/L1A/L1C. Highest-priority new-tasking candidate. |
| Port Washington | 0 | 0 | 0 | 0 | Only clearly implausible L0 intersections; no usable coverage established, including expanded AOI. |
| Saline | 0 | 0 | 0 | 0 | Only clearly implausible L0 intersections; no usable coverage established, including expanded AOI. |
| River Bend neighborhood | 4 | 4 | 0 | 0 | July 19–22, 2026. July 22 has 0% mean cloud. Verify the parcel, then process a campus crop. |
| Lake Mariner candidate | 0 | 0 | 0 | 0 | Only implausible L0 intersections; resolve tenant attribution before prioritizing new tasking. |

These are account/contract-scoped results. “No usable coverage established” is not a claim that Satellogic has never acquired the location or that another licensed archive has no imagery. None of the processed sequences discovered here provides a continuous two-year construction history. The blog must use the dates actually available, or expand the historical search with permission; future tasking will not fill past gaps.

### Raw archive caution and opportunity

Initial Colossus regional L0 results reached the 1,000-item client limit. A monthly re-query produced 1,193 unique raw items across 49 outcomes; 47 outcomes included at least one geometrically plausible raw tile. Other original-AOI raw searches did not reach the limit. The separately narrowed Colossus 2 L0 query still has a cap flag in the evidence; use the completed regional inventory as the starting set and resolve each against the verified building polygon.

Plausible is only a diagnostic heuristic, not a product-quality guarantee. Raw footprints can differ materially from ortho footprints. Do not equate 47 raw outcomes with 47 usable frames.

Examples requiring caution: raw outcomes 4838b264-45ec-482c-aa0f-4d565264dffa and 2b0da951-9a02-44a9-b559-fd5153cb179f appear over several unrelated campuses. Inspected Wisconsin records have GSD=1,000,000 and continent-spanning footprints beginning near 0,0; one reports negative sun elevation. Exclude these intersections from coverage and processing decisions unless Satellogic supplies corrected geolocation.

The archive audit searched nine of the ten catalog collections over the original sites; quickview-visual-thumb was not separately searched because it is a browse derivative. Supplementary/revised searches are recorded explicitly in the JSON. Before declaring a final provider-wide gap, confirm entitlements and check for any thumb-only or newly published records. Never convert HTTP errors or capped searches into zeros.

## 5. Processing queue — proposals, not submitted orders

Prefer real, correctly geolocated L1D-SR visual assets. The exact collection is l1d-sr and the order processing-level value in this codebase is L1D_SR. Do not silently substitute l1d, QuickView, or gaia-l1d-sr merely because the name looks similar.

First-pass proposals:

| Priority | Site / capture UTC date | outcome_id | Evidence and action |
| --- | --- | --- | --- |
| P1 | Abilene / 2026-08-02 | a16c15e5-ab8d-42ee-b321-55f4f062c461 | Existing L1D, four intersecting tiles, 0% mean cloud; no SR counterpart found. |
| P2 | Abilene / 2026-08-04 | 39ca13b8-c481-4012-afda-fe7de99d58b0 | Existing L1D, four tiles, ~9.7% cloud. Optional if little additional change beyond Aug 2. |
| P1 | Shackelford / 2026-08-08 | 84d62ef7-7ac6-467f-94f3-2dd9decbb446 | Existing L1D, two tiles, 0% cloud; creates a baseline, not a time series alone. |
| P1 | Milam / 2026-08-07 | fe64bdf2-0679-41e2-b331-623806549480 | Existing L1D, ~4.6% cloud on original AOI; use verified campus crop rather than tiny initial rectangle. |
| P2 | Milam / 2026-08-06 | 3be5c54d-04bb-4e58-b9d7-c9ffd338d33d | Existing L1D, ~20% mean cloud; adjacent-day comparison may add little. |
| P1, location gate | River Bend / 2026-07-22 | 7bbd45ce-5213-46b5-a11e-7160eeecf4a4 | Twelve L1D tiles cover the broad neighborhood, 0% mean cloud; order only the verified campus area. |
| Investigation | Colossus region / 2026-05-26 | 7a58ff9d-56c0-47aa-8e53-df5f600c61a9 | Plausible L0 coverage of regional AOI; no corresponding SR found. Ask provider to validate raw geolocation, quality, eligibility, and price before processing. |
| Investigation | Colossus region / 2026-09-02 | 497d270d-33b8-4d75-b7d1-df59a5d6ba0c | Plausible raw coverage of ~89% of regional rectangle. Check which individual buildings are actually imaged. |

Other River Bend L1D dates average ~28–31% cloud over the neighborhood. Recalculate cloud over the actual construction site before rejecting them. They remain secondary candidates, not automatic orders.

Execution through existing infrastructure:

1. Re-search l1d-sr for each outcome on the chosen AOI and capture date ±1 day. Products may have appeared since this audit.
2. Inspect the raw STAC asset definitions, media types, processing metadata, projection, transform and pixel dimensions. Image Mate's normalize_item can fill “visual” from analytic/preview/thumbnail when visual is missing; normalized names alone cannot certify ortho imagery.
3. Deduplicate by contract + outcome + processing level + requested geometry. One outcome may supply multiple sites; do not pay twice for the same product area.
4. Confirm processing SKU availability and price with the contract. The existing _archive_order_feature in backend/app/main.py uses a GeoJSON Feature with the requested geometry, properties.sku ARCIMG-M.NN.NN, and properties.parameters containing processing_level L1D_SR and outcome_id.
5. SatellogicClient.create_order is the existing provider submission method. The generic /api/tasking/orders route validates tasking SKUs and does NOT accept the archive-processing SKU.
6. Existing mosaic dependency handling includes _find_l1d_sr_products, _find_archive_order, /api/mosaics/jobs/{job_id}/request-products and /check-products. The product-request endpoint requires the exact confirmation REQUEST L1D-SR.
7. Do not create a multi-date mosaic merely to trigger orders: that workflow may queue/start a mosaic worker when products arrive. Reuse its dependency/deduplication pattern for per-capture products, or deliberately isolate a single-capture job if the workflow permits it. Any adaptation is work for the implementation agent, not already implemented here.
8. Reconcile ambiguous submission responses against existing orders before retrying. Record provider order IDs, then check status, deliverables, and the archive. “Order accepted” is not “orthos available.”
9. Download or tile only after verifying actual l1d-sr assets and AOI coverage. Preserve outcome/product lineage in the frame manifest.

## 6. Proposed tasking campaign

A complete read-only scan of 4,543 orders in the accessible contract found two spatially relevant orders, both closed:

- Stargate Data Center: provider task_id 340811, Jan 21–Feb 28, 2026, processing_level L1D_SR.
- xAI Data Center: provider task_id 313510, Aug 5–Dec 31, 2025, processing_level L1D_SR.

These task IDs are not asserted to be v2 order IDs. No active order intersected the research rectangles in that scan. Repeat the audit before submitting: active projects outside the exact rectangles or under another contract were not ruled out.

Suggested order of work after owner approval:

1. New Carlisle, Port Washington and Saline: verify final parcels, seek provider confirmation of archive gaps, then obtain a current baseline.
2. Shackelford, Milam and River Bend: pair the best processable historical baseline with a new observation. River Bend is held until location validation.
3. Jupiter: cover the full intended construction area or explicitly select a meaningful hall-level story.
4. Colossus 2/3: first inspect later raw candidates. New imagery is useful if processing cannot provide a recent usable observation.
5. Lordstown: verify what construction the imagery would depict; then acquire a recent comparison.
6. Colossus 1 and Abilene: refresh their older sequences if the selected story warrants it.
7. Lake Mariner: hold until Anthropic attribution and a defensible construction polygon are verified.

Planning assumption, not an approved spend: start with one acquisition per selected priority site, then aim for one usable observation every 2–4 weeks for three months, subject to budget, weather and active construction. A tasking attempt is not a guaranteed cloud-free acquisition. New tasking cannot reconstruct missing 2024–2025 observations.

Use existing Image Mate tasking routes:

- GET /api/contracts and /api/tasking/products. The latter is a local static SKU list, not a live price/entitlement quote.
- GET /api/tasking/orders; reconcile existing orders before creation.
- POST /api/tasking/orders/preview produces a read-only Feature preview and expected confirmation.
- POST /api/tasking/opportunities creates a provider feasibility analysis; it was not invoked during this investigation. Use it only when ready for the approved execution phase.
- POST /api/tasking/orders submits the order and requires confirmation equal to order_name.
- GET /api/tasking/orders/{order_id} and the lifecycle endpoint follow captures and deliverables.

TaskingOrderCreateRequest supports target_type, geometry, order_name, project_name, sku, start_date, end_date, contract_id, revisit_period/remapping_period, and additional_parameters. Point SKU TSKPOI-M and area SKU TSKARE-M exist in the code; revisit variants also exist. Confirm which SKU and schedule the contract permits rather than inferring cadence from its name. Large or elongated campuses should use a verified area polygon unless a point product's coverage guarantee is adequate.

Set processing_level L1D_SR in additional_parameters only if supported by the chosen product/contract. If the delivered acquisition lacks that format, follow the separate archive-processing workflow above.

Before any submission, show the user the final geometry, product, acquisition window, cadence, maximum spend, retry/cloud rules and publication license. Use deterministic order names and store returned IDs. No open-ended automatic reorder loop.

## 7. Animation workflow and code-specific limitations

The existing code is a useful starting point, but it does not by itself guarantee a rigorously co-registered ortho time series.

Relevant implementation locations:

| Existing component | Purpose / caveat |
| --- | --- |
| backend/app/satellogic_client.py:441 | Archive search. Has a 20-page and caller-limit ceiling; cloud filtering is client-side. |
| backend/app/main.py:3567 | POST /api/archive/search with geometry, dates, collection_id, contract_id and optional quality filters. |
| backend/app/main.py:3918 | Resolve l1d-sr products by outcome and footprint-union coverage. |
| backend/app/main.py:4276 | Existing archive-processing order Feature format. |
| backend/app/models.py:212 | MP4 tile/frame/request models. |
| backend/app/main.py:4886 | Create background MP4 job; GET status and download routes immediately follow. |
| backend/app/services.py:149 | make_selected_extent_mp4: fixed viewport, chronological sorting, date labels and H.264 encoding. |
| backend/app/services.py:493 | Frame composition uses Pillow and footprint-based projective/bounding-box placement, not raster CRS/affine reprojection. |
| frontend/app.js:6362 | Current carousel selection → MP4 payload. This file already contains user edits; preserve them. |

### Build a truthful frame manifest first

For every site retain: verified story polygon, fixed output viewport, source/collection, capture time in UTC, outcome_id, all contributing item IDs, original asset keys/types, product version, CRS/transform/GSD, footprint coverage, valid-pixel coverage, cloud/shadow/haze notes, viewing geometry, keep/reject decision, and any processing order ID.

Group all spatial tiles of one outcome into ONE frame. Two tiles are not two dates. Choose chronologically separated construction stages; do not let large tile counts or many same-day acquisitions create a misleadingly long animation.

Recommended minimum for a meaningful construction animation: 4–6 visibly distinct stages spanning months, with at least a baseline and a substantially later stage. This is an editorial target, not a property the current archive is guaranteed to satisfy. Shorter sequences should be described honestly as comparisons.

### Render using real ortho geometry

1. Choose north-up, fixed extent, fixed pixel grid and dimensions for all dates. Keep projection, crop and map rotation constant.
2. Read l1d-sr GeoTIFF/COG georeferencing with geospatial tooling or Image Mate's COG raster service, rather than treating the STAC footprint as the image affine transform.
3. The existing GET /api/raster/cog/tiles/{z}/{x}/{y} proxy accepts the COG URL, contract_id, tileMatrixSetId, band indices and render options. Keep zoom, tile grid, band selection and contrast consistent across dates. Account for pixel buffers when assigning image bounds.
4. For publication-grade registration, prepare each single-capture frame on an identical georeferenced grid before passing it to the MP4 compositor. This preparation is not presently guaranteed by the direct-asset MP4 path; the next agent should first test a small pilot and implement only the minimum missing preparation/validation.
5. Preserve nodata transparency/masks and reject incomplete construction areas. Never fill cloudy or missing areas with imagery from another date in a frame labeled with one acquisition date.
6. Avoid independently stretching every scene without review; lighting and seasonal differences can look like construction. Small documented alignment corrections may be necessary even with orthos. Never morph frames or synthesize construction.
7. Inspect stable road/building control points and roof edges at full output resolution. A passing software unit test is not proof of real-image alignment.

### Reuse the MP4 API after frame preparation

POST /api/archive/animate/mp4/jobs requires:

- frames: at least two frames; each has frame_id, datetime, and tiles.
- Each tile has url, geometry, optional item_id. URL must identify the intended real imagery/rendered frame, not a thumbnail fallback.
- viewport_geometry: one fixed GeoJSON extent.
- contract_id: the accessible Satellogic contract.
- seconds_per_frame: start around 0.8–1.2 seconds.
- filename_prefix: unique, site-specific prefix.

The implementation sorts frames chronologically, permits up to 120 frames and 2,400 tiles, prohibits mixed imagery sources in a run, caps the canvas at 8,192 pixels on its longest side, draws dates, and uses imageio/imageio-ffmpeg with H.264/yuv420p. Output resolution is inferred from imagery, not supplied as a 1080p/4K API setting. Start with a small frame set to manage memory.

Poll GET /api/archive/animate/mp4/jobs/{job_id}; download only after completed from /download. Jobs are held in application memory; preserve manifests and downloaded outputs outside transient job state.

The compositor can skip unreadable tiles/frames and still finish. Compare requested and rendered frame counts; visually check for blank areas. A completed status alone is insufficient QA.

The simpler /api/archive/animate uses preview-first GIFs. /api/archive/animate/search uses capture mosaics, but their framing is derived separately for each capture, with a fixed 1280×720 canvas and no rigorous raster reprojection. Neither should be the default for this blog.

Current frontend code sends a loop field, but the backend MP4 request model has no loop field. Implement looping in the blog's video player; do not assume it is baked into the MP4.

## 8. Publication plan and acceptance criteria

Suggested narrative: “Watching the AI infrastructure build-out from orbit,” with separate case studies for ground-up campuses and industrial-building conversions.

For each published case:

- Explain owner/operator versus AI customer, with dated sources.
- Show a paused poster frame, accessible play/pause controls and visible acquisition dates.
- Clearly mark long temporal gaps; equal frame duration does not imply equal time between observations.
- Include a compact before/after comparison and a sentence describing visible earthworks, foundations, roof completion or external site expansion.
- Do not infer model training activity, GPU counts, operational readiness, energy consumption or workforce identity from roofs and parking lots.
- Use provider-approved attribution and confirm redistribution/blog/video rights for the actual contract before publication. Do not reuse another research site's satellite images just because its map is public.
- Keep original frame files, product manifests, QA notes and citations with the publication archive.
- Do not expose provider credentials, signed URLs, internal contract IDs or order records in downloadable blog assets.

Completion requires: verified campus polygon; legitimate source assets; sufficient temporal coverage; consistent registration and rendering; no silent missing frames; date labels matching capture metadata; no multi-date cloud infill; publication permission; and explicit disclosure of any missing history.

Existing verification during this research: six tests passed with .venv/bin/python -m unittest backend.tests.test_mp4_geolocation -q. These tests cover geometry ordering/projective helpers and date-label behavior, not actual COG georeferencing, archive access end-to-end, or publication quality.

## 9. Execution sequence for the next agent

1. Read this document and the JSON; verify current repo status and preserve the three pre-existing modified frontend files.
2. Re-list contracts; use an explicitly authorized archive contract.
3. Validate parcels, especially River Bend, Milam and the separate Colossus facilities. Resolve Lake Mariner tenancy before presenting it as Anthropic-specific.
4. Refresh the archive, resolve cap flags, and perform real-pixel QC on selected candidates.
5. Present a small processing batch and proposed acquisition campaign with budget and license conditions.
6. After approval, submit/reconcile only the selected processing orders and taskings; track actual delivered products.
7. Make a two- or three-frame ortho pilot at Abilene and Colossus 1. Verify geometry before scaling up or changing the renderer.
8. Prepare full site sequences; identify which sites support a blog today and which belong to an ongoing follow-up.
9. Deliver MP4s, posters, manifests, evidence-backed captions, rejection logs, and a blog outline. Separate finished animations from planned monitoring.

The selected Analytics Dashboard spreadsheet template could not be produced in this session. Its [skill instructions](/Users/mark/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-analytics-dashboard/SKILL.md) require a preinstalled spreadsheet-authoring capability and state: “If no such capability can be identified and read, say it is unavailable and stop; do not recreate or install it.” The available Excel skill is for live Excel sessions, not standalone template workbooks. That template workflow was stopped; this Markdown/JSON/GeoJSON research package is not represented as the requested workbook.
