const apiBase = "";

const state = {
  items: [],
  overviewItems: [],
  detailItems: [],
  mapVectorLayer: null,
  mapThumbOverlayLayer: null,
  mapThumbMarkerLayer: null,
  compareBlendLayer: null,
  activeFrameOverlay: null,
  playTimer: null,
  currentAoi: null,
  lastDrawnGeometry: null,
  mapMode: "overview",
  searchParams: null,
  mapRefreshTimer: null,
  lastDetailRequestKey: null,
  pendingAnimationDraw: false,
  animationGeometry: null,
  selectedCarouselId: null,
  selectedCarouselIds: new Set(),
  compareMode: false,
  compareFrames: [],
  lastDetailFetchAt: 0,
  contextMenuLatLng: null,
  lastDetailCoverageBounds: null,
  lastDetailCoverageZoom: null,
  lastDetailContextKey: null,
  prefetchTileUrlSeen: new Set(),
  useCogTileProxy: true,
  tileProxyWarned: false,
  carouselQuickviewCount: 0,
  carouselFilterActive: false,
  skipMapRefreshEvents: 0,
  locationHistory: [],
  mp4JobId: null,
  mp4JobTimer: null,
  mp4JobDownloading: false,
};

const DETAIL_ZOOM_THRESHOLD = 13;
const DETAIL_COG_HIGHRES_ZOOM = 16;
const DETAIL_FETCH_DEBOUNCE_MS = 700;
const DETAIL_FETCH_COOLDOWN_MS = 1800;
const DETAIL_MAX_VECTOR_TILES = 120;
const DETAIL_FULLRES_VISIBLE_LIMIT = 1;
const DETAIL_FETCH_PADDING = 0.35;
const DETAIL_MAX_QUERY_LIMIT = 400;
const DETAIL_TILE_BUFFER_PAD = 0.12;
const COMPARE_PREFETCH_NEIGHBORS = 1;
const COMPARE_PREFETCH_TILES_PER_FRAME = 3;
const LOCATION_HISTORY_KEY = "imageMate.locationHistory.v1";
const LOCATION_HISTORY_LIMIT = 80;

const DEBUG_NET = new URLSearchParams(window.location.search).has("debugNet");

function debugLog(message, meta = null) {
  if (!DEBUG_NET) return;
  if (meta) console.debug(`[GeoDebug] ${message}`, meta);
  else console.debug(`[GeoDebug] ${message}`);
}

const map = L.map("map", { zoomControl: true }).setView([37.6188, -122.375], 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 20,
}).addTo(map);
window.addEventListener("resize", () => {
  map.invalidateSize();
  if (animateSeriesPopoverEl?.classList.contains("open")) positionAnimateSeriesPopover();
});
setTimeout(() => map.invalidateSize(), 80);

const drawnItems = new L.FeatureGroup().addTo(map);
const drawControl = new L.Control.Draw({
  draw: {
    rectangle: true,
    polygon: false,
    circle: false,
    circlemarker: false,
    marker: false,
    polyline: false,
  },
  edit: {
    featureGroup: drawnItems,
  },
});
map.addControl(drawControl);

map.on(L.Draw.Event.CREATED, (evt) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(evt.layer);
  const geometry = normalizeGeometryLongitudes(evt.layer.toGeoJSON().geometry);
  if (state.pendingAnimationDraw) {
    state.animationGeometry = geometry;
    state.pendingAnimationDraw = false;
    openAnimationDialog();
    toast("Animation AOI captured");
    return;
  }

  state.currentAoi = geometry;
  state.lastDrawnGeometry = geometry;
  updateSearchFieldsFromGeometry(geometry);
  toast("AOI updated from drawn search box");
});

map.on(L.Draw.Event.EDITED, (evt) => {
  evt.layers.eachLayer((layer) => {
    const geometry = normalizeGeometryLongitudes(layer.toGeoJSON().geometry);
    state.currentAoi = geometry;
    state.lastDrawnGeometry = geometry;
    updateSearchFieldsFromGeometry(geometry);
  });
  toast("AOI edited");
});

map.on(L.Draw.Event.DELETED, () => {
  state.currentAoi = null;
  toast("Drawn AOI cleared; center/width search will be used");
});

const latEl = document.getElementById("lat");
const lonEl = document.getElementById("lon");
const widthKmEl = document.getElementById("widthKm");
const startDateEl = document.getElementById("startDate");
const endDateEl = document.getElementById("endDate");
const maxCloudEl = document.getElementById("maxCloud");
const satelliteNameEl = document.getElementById("satelliteName");
const minGsdEl = document.getElementById("minGsd");
const maxGsdEl = document.getElementById("maxGsd");
const limitEl = document.getElementById("limit");
const collectionEl = document.getElementById("collection");
const contractSelectEl = document.getElementById("contractSelect");
const searchMetaEl = document.getElementById("searchMeta");
const frameSelectEl = document.getElementById("frameSelect");
const timelineEl = document.getElementById("timeline");
const framePreviewEl = document.getElementById("framePreview");
const beforeSelectEl = document.getElementById("beforeSelect");
const afterSelectEl = document.getElementById("afterSelect");
const beforeImgEl = document.getElementById("beforeImg");
const afterImgEl = document.getElementById("afterImg");
const beforeClipEl = document.getElementById("beforeClip");
const compareSliderEl = document.getElementById("compareSlider");
const geoPromptEl = document.getElementById("geoPrompt");
const reportOutEl = document.getElementById("reportOut");
const annotationNoteEl = document.getElementById("annotationNote");
const timeCarouselListEl = document.getElementById("timeCarouselList");
const searchResultsCountEl = document.getElementById("searchResultsCount");
const searchResultsFilterMetaEl = document.getElementById("searchResultsFilterMeta");
const mapStatusEl = document.getElementById("mapStatus");
const mapDebugStatsEl = document.getElementById("mapDebugStats");
const mapLocateEl = document.getElementById("mapLocate");
const mapLocateFormEl = document.getElementById("mapLocateForm");
const mapLocateInputEl = document.getElementById("mapLocateInput");
const mapLocateHistoryBtnEl = document.getElementById("mapLocateHistoryBtn");
const mapLocateHistoryEl = document.getElementById("mapLocateHistory");
const mapContextMenuEl = document.getElementById("mapContextMenu");
const ctxCopyLatLonEl = document.getElementById("ctxCopyLatLon");
const ctxCreateAnimationEl = document.getElementById("ctxCreateAnimation");
const ctxTaskImageEl = document.getElementById("ctxTaskImage");
const animationDialogEl = document.getElementById("animationDialog");
const animationFormEl = document.getElementById("animationForm");
const animStartDateEl = document.getElementById("animStartDate");
const animEndDateEl = document.getElementById("animEndDate");
const animMaxCloudEl = document.getElementById("animMaxCloud");
const animSatelliteEl = document.getElementById("animSatellite");
const animMinGsdEl = document.getElementById("animMinGsd");
const animMaxGsdEl = document.getElementById("animMaxGsd");
const animMaxFramesEl = document.getElementById("animMaxFrames");
const animSecPerFrameEl = document.getElementById("animSecPerFrame");
const lockSelectionBtnEl = document.getElementById("lockSelectionBtn");
const compareModeBtnEl = document.getElementById("compareModeBtn");
const compareRailEl = document.getElementById("compareRail");
const compareRangeEl = document.getElementById("compareRange");
const compareDateTagEl = document.getElementById("compareDateTag");
const compareStepUpBtnEl = document.getElementById("compareStepUpBtn");
const compareStepDownBtnEl = document.getElementById("compareStepDownBtn");
const animateSeriesBtnEl = document.getElementById("animateSeriesBtn");
const animateSeriesPopoverEl = document.getElementById("animateSeriesPopover");
const animateSeriesSecondsEl = document.getElementById("animateSeriesSeconds");
const animateSeriesRunBtnEl = document.getElementById("animateSeriesRunBtn");
const animateSeriesCloseBtnEl = document.getElementById("animateSeriesCloseBtn");
const animateSeriesStatusEl = document.getElementById("animateSeriesStatus");
const downloadMenuBtnEl = document.getElementById("downloadMenuBtn");
const downloadPopoverEl = document.getElementById("downloadPopover");
const downloadOutcomeCsvBtnEl = document.getElementById("downloadOutcomeCsvBtn");
const downloadVisibleQuickviewBtnEl = document.getElementById("downloadVisibleQuickviewBtn");
const downloadVisibleL1dBtnEl = document.getElementById("downloadVisibleL1dBtn");
const downloadCopiedTipEl = document.getElementById("downloadCopiedTip");
const lockIconEl = lockSelectionBtnEl?.querySelector(".lock-icon");

const today = new Date();
const sixMonthsAgo = new Date();
sixMonthsAgo.setDate(today.getDate() - 180);
startDateEl.value = sixMonthsAgo.toISOString().slice(0, 10);
endDateEl.value = today.toISOString().slice(0, 10);

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

function isoDate(dateValue) {
  return `${dateValue}T00:00:00Z`;
}

function selectedContractId() {
  const value = (contractSelectEl.value || "").trim();
  return value || null;
}

function parseOptionalNumber(value) {
  const v = (value || "").toString().trim();
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function compactObject(input) {
  const out = {};
  Object.entries(input).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") out[key] = value;
  });
  return out;
}

function normalizeLongitude(lon) {
  const value = Number(lon);
  if (!Number.isFinite(value)) return lon;
  return ((((value + 180) % 360) + 360) % 360) - 180;
}

function clampLatitude(lat) {
  const value = Number(lat);
  if (!Number.isFinite(value)) return lat;
  return Math.max(-90, Math.min(90, value));
}

function normalizeLngLatPair(pair) {
  if (!Array.isArray(pair) || pair.length < 2) return pair;
  return [normalizeLongitude(pair[0]), clampLatitude(pair[1]), ...pair.slice(2)];
}

function normalizeGeometryLongitudes(geometry) {
  if (!geometry || typeof geometry !== "object") return geometry;
  const type = geometry.type;
  const coords = geometry.coordinates;

  if (type === "Point" && Array.isArray(coords)) {
    return { ...geometry, coordinates: normalizeLngLatPair(coords) };
  }
  if (type === "MultiPoint" || type === "LineString") {
    if (!Array.isArray(coords)) return geometry;
    return { ...geometry, coordinates: coords.map((pair) => normalizeLngLatPair(pair)) };
  }
  if (type === "MultiLineString" || type === "Polygon") {
    if (!Array.isArray(coords)) return geometry;
    return { ...geometry, coordinates: coords.map((line) => (Array.isArray(line) ? line.map((pair) => normalizeLngLatPair(pair)) : line)) };
  }
  if (type === "MultiPolygon") {
    if (!Array.isArray(coords)) return geometry;
    return {
      ...geometry,
      coordinates: coords.map((poly) => (
        Array.isArray(poly)
          ? poly.map((line) => (Array.isArray(line) ? line.map((pair) => normalizeLngLatPair(pair)) : line))
          : poly
      )),
    };
  }
  if (type === "GeometryCollection" && Array.isArray(geometry.geometries)) {
    return {
      ...geometry,
      geometries: geometry.geometries.map((g) => normalizeGeometryLongitudes(g)),
    };
  }
  return geometry;
}

function bboxFromCenter(lat, lon, widthKm) {
  const centerLat = clampLatitude(lat);
  const centerLon = normalizeLongitude(lon);
  const halfLatDelta = (widthKm / 2) / 111.0;
  const halfLonDelta = (widthKm / 2) / (111.0 * Math.cos((centerLat * Math.PI) / 180));
  const minLat = centerLat - halfLatDelta;
  const maxLat = centerLat + halfLatDelta;
  const minLon = centerLon - halfLonDelta;
  const maxLon = centerLon + halfLonDelta;

  return normalizeGeometryLongitudes({
    type: "Polygon",
    coordinates: [[
      [minLon, minLat],
      [maxLon, minLat],
      [maxLon, maxLat],
      [minLon, maxLat],
      [minLon, minLat],
    ]],
  });
}

function geometryFromMapBounds() {
  const b = map.getBounds();
  return geometryFromBounds(b);
}

function geometryFromBounds(bounds) {
  const b = bounds || map.getBounds();
  return normalizeGeometryLongitudes({
    type: "Polygon",
    coordinates: [[
      [b.getWest(), b.getSouth()],
      [b.getEast(), b.getSouth()],
      [b.getEast(), b.getNorth()],
      [b.getWest(), b.getNorth()],
      [b.getWest(), b.getSouth()],
    ]],
  });
}

function updateSearchFieldsFromGeometry(geometry) {
  const bounds = boundsFromGeometry(geometry);
  if (!bounds) return;
  const center = bounds.getCenter();
  const west = bounds.getWest();
  const east = bounds.getEast();
  const widthDeg = Math.abs(east - west);
  const widthKm = widthDeg * 111.0 * Math.cos((center.lat * Math.PI) / 180);

  latEl.value = clampLatitude(center.lat).toFixed(6);
  lonEl.value = normalizeLongitude(center.lng).toFixed(6);
  widthKmEl.value = Math.max(0.1, widthKm).toFixed(2);
}

function buildSearchPayload(geometry, collectionOverride = null, limitOverride = null) {
  const normalizedGeometry = normalizeGeometryLongitudes(geometry);
  return compactObject({
    geometry: normalizedGeometry,
    start_date: isoDate(startDateEl.value),
    end_date: isoDate(endDateEl.value),
    collection_id: collectionOverride || collectionEl.value.trim() || "l1d-sr",
    contract_id: selectedContractId(),
    limit: limitOverride || Number(limitEl.value),
    max_cloud_cover: parseOptionalNumber(maxCloudEl.value),
    satellite_name: (satelliteNameEl.value || "").trim() || null,
    min_gsd: parseOptionalNumber(minGsdEl.value),
    max_gsd: parseOptionalNumber(maxGsdEl.value),
  });
}

function formatCaptureDate(value) {
  if (!value) return "no datetime";
  try {
    const dt = new Date(value);
    return dt.toISOString().replace("T", " ").slice(0, 19) + "Z";
  } catch (_) {
    return value;
  }
}

function timestampTag() {
  const d = new Date();
  const p = (v) => String(v).padStart(2, "0");
  return `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}_${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}`;
}

function sanitizeFilePart(value, fallback = "item") {
  const cleaned = (value || "").toString().trim().replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[_\.]+|[_\.]+$/g, "");
  return cleaned || fallback;
}

function extensionFromUrl(url, fallback = ".tif") {
  try {
    const parsed = new URL(url);
    const filename = parsed.pathname.split("/").pop() || "";
    const dot = filename.lastIndexOf(".");
    if (dot > 0) return filename.slice(dot);
  } catch (_) {
    // ignore
  }
  return fallback;
}

function csvCell(value) {
  const s = (value ?? "").toString();
  return `"${s.replace(/"/g, "\"\"")}"`;
}

function showCopiedTooltip() {
  if (!downloadCopiedTipEl) return;
  downloadCopiedTipEl.classList.add("show");
  window.setTimeout(() => {
    downloadCopiedTipEl.classList.remove("show");
  }, 1600);
}

function hideDownloadPopover() {
  downloadPopoverEl?.classList.remove("open");
}

function toggleDownloadPopover() {
  if (!downloadPopoverEl) return;
  downloadPopoverEl.classList.toggle("open");
}

function setAnimateSeriesStatus(message, isError = false) {
  if (!animateSeriesStatusEl) return;
  animateSeriesStatusEl.textContent = message;
  animateSeriesStatusEl.style.color = isError ? "#9f2f1e" : "";
}

function positionAnimateSeriesPopover() {
  if (!animateSeriesPopoverEl || !animateSeriesBtnEl) return;
  const host = animateSeriesPopoverEl.offsetParent || animateSeriesBtnEl.offsetParent || animateSeriesBtnEl.parentElement;
  if (!host) return;
  const hostRect = host.getBoundingClientRect();
  const btnRect = animateSeriesBtnEl.getBoundingClientRect();
  const top = btnRect.bottom - hostRect.top + 6;
  const desiredRight = hostRect.right - btnRect.right;
  const maxRight = Math.max(0, host.clientWidth - 16);
  const clampedRight = Math.max(0, Math.min(maxRight, desiredRight));
  animateSeriesPopoverEl.style.top = `${Math.max(0, top)}px`;
  animateSeriesPopoverEl.style.left = "auto";
  animateSeriesPopoverEl.style.right = `${clampedRight}px`;
}

function hideAnimateSeriesPopover() {
  animateSeriesPopoverEl?.classList.remove("open");
}

function toggleAnimateSeriesPopover() {
  if (!animateSeriesPopoverEl) return;
  const willOpen = !animateSeriesPopoverEl.classList.contains("open");
  animateSeriesPopoverEl.classList.toggle("open");
  if (willOpen) {
    setAnimateSeriesStatus("Select 2+ images in the carousel, then render.");
    positionAnimateSeriesPopover();
  }
}

function loadLocationHistory() {
  try {
    const raw = window.localStorage.getItem(LOCATION_HISTORY_KEY);
    if (!raw) {
      state.locationHistory = [];
      return;
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      state.locationHistory = [];
      return;
    }
    state.locationHistory = parsed
      .map((entry) => ({
        label: (entry?.label || "").toString(),
        query: (entry?.query || "").toString(),
        lat: Number(entry?.lat),
        lon: Number(entry?.lon),
      }))
      .filter((entry) => Number.isFinite(entry.lat) && Number.isFinite(entry.lon))
      .slice(0, LOCATION_HISTORY_LIMIT);
  } catch (_) {
    state.locationHistory = [];
  }
}

function saveLocationHistory() {
  try {
    window.localStorage.setItem(LOCATION_HISTORY_KEY, JSON.stringify(state.locationHistory.slice(0, LOCATION_HISTORY_LIMIT)));
  } catch (_) {
    // Storage is optional; ignore failures (private mode / quota).
  }
}

function addLocationHistory(entry) {
  const lat = clampLatitude(entry?.lat);
  const lon = normalizeLongitude(entry?.lon);
  if (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon))) return;
  const label = (entry?.label || "").toString().trim() || `${formatCoord(lat)}, ${formatCoord(lon)}`;
  const query = (entry?.query || "").toString().trim();
  const key = `${Number(lat).toFixed(6)},${Number(lon).toFixed(6)}`;
  const next = [{ label, query, lat: Number(lat), lon: Number(lon) }];
  state.locationHistory.forEach((item) => {
    const itemKey = `${Number(item.lat).toFixed(6)},${Number(item.lon).toFixed(6)}`;
    if (itemKey === key) return;
    next.push(item);
  });
  state.locationHistory = next.slice(0, LOCATION_HISTORY_LIMIT);
  saveLocationHistory();
}

function renderLocationHistoryMenu() {
  if (!mapLocateHistoryEl) return;
  const filter = (mapLocateInputEl?.value || "").trim().toLowerCase();
  const rows = state.locationHistory.filter((item) => {
    if (!filter) return true;
    const bag = `${item.label || ""} ${item.query || ""}`.toLowerCase();
    return bag.includes(filter);
  });

  mapLocateHistoryEl.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "map-locate-history-empty";
    empty.textContent = "No previous searches.";
    mapLocateHistoryEl.appendChild(empty);
    return;
  }

  rows.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "map-locate-history-item";
    const primary = document.createElement("span");
    primary.className = "map-locate-history-primary";
    primary.textContent = item.label;
    const secondary = document.createElement("span");
    secondary.className = "map-locate-history-secondary";
    secondary.textContent = `${formatCoord(item.lat)}, ${formatCoord(item.lon)}`;
    button.append(primary, secondary);
    button.addEventListener("click", () => {
      hideLocationHistoryMenu();
      jumpToLocation(item.lat, item.lon, { zoom: Math.max(11, map.getZoom()) });
      if (mapLocateInputEl) mapLocateInputEl.value = item.query || item.label;
    });
    mapLocateHistoryEl.appendChild(button);
  });
}

function showLocationHistoryMenu() {
  if (!mapLocateHistoryEl) return;
  renderLocationHistoryMenu();
  mapLocateHistoryEl.classList.add("open");
  mapLocateHistoryBtnEl?.setAttribute("aria-expanded", "true");
}

function hideLocationHistoryMenu() {
  mapLocateHistoryEl?.classList.remove("open");
  mapLocateHistoryBtnEl?.setAttribute("aria-expanded", "false");
}

function toggleLocationHistoryMenu() {
  if (!mapLocateHistoryEl) return;
  const nextOpen = !mapLocateHistoryEl.classList.contains("open");
  if (nextOpen) showLocationHistoryMenu();
  else hideLocationHistoryMenu();
}

function splitCoordinatePairs(rawText) {
  const text = rawText.trim();
  const pairs = [];
  const commaParts = text.split(/[;,]/).map((x) => x.trim()).filter(Boolean);
  if (commaParts.length >= 2) pairs.push([commaParts[0], commaParts[1]]);

  const tokens = text.split(/\s+/).filter(Boolean);
  for (let i = 1; i < tokens.length; i += 1) {
    const left = tokens.slice(0, i).join(" ");
    const right = tokens.slice(i).join(" ");
    if (!left || !right) continue;
    pairs.push([left, right]);
  }
  return pairs;
}

function parseCoordinatePart(part) {
  const raw = (part || "").trim();
  if (!raw) return null;
  const upper = raw.toUpperCase();
  const hemisphereMatch = upper.match(/[NSEW]/);
  const hemisphere = hemisphereMatch ? hemisphereMatch[0] : null;

  const decimalMatch = upper.match(/^([NSEW])?\s*([+-]?\d+(?:\.\d+)?)\s*([NSEW])?$/);
  if (decimalMatch) {
    const dir = decimalMatch[1] || decimalMatch[3] || hemisphere;
    let value = Number(decimalMatch[2]);
    if (!Number.isFinite(value)) return null;
    if (dir === "S" || dir === "W") value = -Math.abs(value);
    if (dir === "N" || dir === "E") value = Math.abs(value);
    return { value, hemisphere: dir || null };
  }

  const numeric = upper
    .replace(/[NSEW]/g, " ")
    .replace(/[°º]/g, " ")
    .replace(/[′']/g, " ")
    .replace(/[″"]/g, " ")
    .replace(/,/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((x) => Number(x))
    .filter((x) => Number.isFinite(x));
  if (!numeric.length) return null;

  const sign = numeric[0] < 0 ? -1 : 1;
  const deg = Math.abs(numeric[0]);
  const min = Math.abs(numeric[1] || 0);
  const sec = Math.abs(numeric[2] || 0);
  let value = sign * (deg + (min / 60) + (sec / 3600));
  if (hemisphere === "S" || hemisphere === "W") value = -Math.abs(value);
  if (hemisphere === "N" || hemisphere === "E") value = Math.abs(value);
  return { value, hemisphere };
}

function resolveCoordinatePair(first, second) {
  if (!first || !second) return null;
  const firstHem = first.hemisphere;
  const secondHem = second.hemisphere;

  const combine = (lat, lon) => {
    const normalized = {
      lat: Number(clampLatitude(lat)),
      lon: Number(normalizeLongitude(lon)),
    };
    if (!Number.isFinite(normalized.lat) || !Number.isFinite(normalized.lon)) return null;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return normalized;
  };

  if ((firstHem === "N" || firstHem === "S") && (secondHem === "E" || secondHem === "W")) {
    return combine(first.value, second.value);
  }
  if ((firstHem === "E" || firstHem === "W") && (secondHem === "N" || secondHem === "S")) {
    return combine(second.value, first.value);
  }

  const direct = combine(first.value, second.value);
  if (direct) return direct;
  return combine(second.value, first.value);
}

function parseLatLonInput(rawText) {
  const raw = (rawText || "").trim();
  if (!raw) return null;
  const pairs = splitCoordinatePairs(raw);
  for (const [left, right] of pairs) {
    const first = parseCoordinatePart(left);
    const second = parseCoordinatePart(right);
    const resolved = resolveCoordinatePair(first, second);
    if (resolved) return resolved;
  }

  const numericPair = raw.match(/[-+]?\d+(?:\.\d+)?/g);
  if (numericPair && numericPair.length === 2 && !/[NSEW]/i.test(raw)) {
    const lat = Number(numericPair[0]);
    const lon = Number(numericPair[1]);
    if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
      return { lat: Number(clampLatitude(lat)), lon: Number(normalizeLongitude(lon)) };
    }
  }
  return null;
}

function jumpToLocation(lat, lon, options = {}) {
  const targetLat = Number(clampLatitude(lat));
  const targetLon = Number(normalizeLongitude(lon));
  if (!Number.isFinite(targetLat) || !Number.isFinite(targetLon)) {
    throw new Error("Invalid location");
  }
  const zoom = Number.isFinite(Number(options.zoom)) ? Number(options.zoom) : Math.max(11, map.getZoom());
  map.flyTo([targetLat, targetLon], zoom, {
    animate: true,
    duration: 0.65,
  });
}

async function geocodeLocation(query) {
  const endpoint = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`;
  const res = await fetch(endpoint, {
    headers: {
      "Accept-Language": "en",
    },
  });
  if (!res.ok) throw new Error(`Location search failed (${res.status})`);
  const rows = await res.json();
  if (!Array.isArray(rows) || !rows.length) throw new Error("Location not found");
  const first = rows[0];
  const lat = Number(first.lat);
  const lon = Number(first.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error("Location result is invalid");
  return {
    lat: Number(clampLatitude(lat)),
    lon: Number(normalizeLongitude(lon)),
    label: (first.display_name || query).toString(),
  };
}

async function runLocationSearch(rawQuery = null) {
  const query = (rawQuery ?? mapLocateInputEl?.value ?? "").trim();
  if (!query) {
    showLocationHistoryMenu();
    return;
  }

  const parsed = parseLatLonInput(query);
  if (parsed) {
    jumpToLocation(parsed.lat, parsed.lon);
    addLocationHistory({
      query,
      label: `${formatCoord(parsed.lat)}, ${formatCoord(parsed.lon)}`,
      lat: parsed.lat,
      lon: parsed.lon,
    });
    hideLocationHistoryMenu();
    toast(`Moved to ${formatCoord(parsed.lat)}, ${formatCoord(parsed.lon)}`);
    return;
  }

  const geo = await geocodeLocation(query);
  jumpToLocation(geo.lat, geo.lon);
  addLocationHistory({
    query,
    label: geo.label,
    lat: geo.lat,
    lon: geo.lon,
  });
  hideLocationHistoryMenu();
  toast(`Moved to ${geo.label}`);
}

function buildVisibleSearchPayload(collectionId) {
  const geometry = geometryFromBounds(map.getBounds());
  if (state.searchParams) {
    return {
      ...state.searchParams,
      geometry,
      collection_id: collectionId,
      limit: 1000,
    };
  }
  return buildSearchPayload(geometry, collectionId, 1000);
}

function looksLikeThumbnailOrPreview(url) {
  const lower = (url || "").toLowerCase();
  return lower.includes("thumbnail") || lower.includes("quickview_visual_thumbnail") || lower.includes("_preview") || lower.endsWith(".png");
}

function fullVisualAssetUrl(item) {
  const candidates = [item?.assets?.visual, item?.assets?.analytic].filter(Boolean);
  for (const url of candidates) {
    if (!looksLikeThumbnailOrPreview(url)) return url;
  }
  return "";
}

function triggerBlobDownload(blob, filename) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

function buildZipAssets(items, prefix) {
  return items
    .map((item) => {
      const url = fullVisualAssetUrl(item);
      if (!url) return null;
      const idPart = sanitizeFilePart(item.id || item.outcome_id || "tile");
      const dtPart = sanitizeFilePart((item.datetime || "").replace(/[:T\-]/g, "").replace(/Z$/i, ""), "nodate");
      const ext = extensionFromUrl(url, ".tif");
      return {
        url,
        item_id: item.id || null,
        outcome_id: item.outcome_id || null,
        filename: `${prefix}_${dtPart}_${idPart}${ext}`,
      };
    })
    .filter(Boolean);
}

async function fetchVisibleIntersectingItems(collectionId) {
  const payload = buildVisibleSearchPayload(collectionId);
  const items = await fetchArchiveItems(payload);
  return filterItemsToViewport(items, map.getBounds());
}

async function requestZipDownload(assets, bundleName) {
  if (!assets.length) {
    toast("No downloadable visible tiles found.");
    return;
  }
  const res = await fetch(`${apiBase}/api/download/zip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      assets,
      contract_id: selectedContractId(),
      bundle_name: bundleName,
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "ZIP download failed");
  }
  const blob = await res.blob();
  triggerBlobDownload(blob, `${bundleName}.zip`);
}

async function downloadSelectedOutcomeCsv() {
  const selected = selectedOverviewItems();
  if (!selected.length) {
    toast("Select one or more images in the carousel first.");
    return;
  }
  const outcomeIds = Array.from(
    new Set(selected.map((item) => item.outcome_id || item.id).filter(Boolean)),
  );
  const csv = ["outcome_id", ...outcomeIds.map((v) => csvCell(v))].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  triggerBlobDownload(blob, `selected_outcome_ids_${timestampTag()}.csv`);
  try {
    await navigator.clipboard.writeText(csv);
    showCopiedTooltip();
  } catch (_) {
    toast("CSV downloaded. Clipboard copy unavailable.");
  }
}

async function downloadVisibleQuickviewTiles() {
  const items = await fetchVisibleIntersectingItems("quickview-visual");
  const assets = buildZipAssets(items, "quickview_visual");
  await requestZipDownload(assets, `visible_quickview_visual_${timestampTag()}`);
  toast(`Downloaded ${assets.length} visible L1B Quickview tiles.`);
}

async function downloadVisibleL1dSrTiles() {
  const items = await fetchVisibleIntersectingItems("l1d-sr");
  const assets = buildZipAssets(items, "l1d_sr_visual");
  await requestZipDownload(assets, `visible_l1d_sr_visual_${timestampTag()}`);
  toast(`Downloaded ${assets.length} visible L1D-SR tiles.`);
}

function formatGsdMeters(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "n/a";
  return n.toFixed(2).replace(/\.?0+$/, "");
}

function collectionGsdForOverviewItem(overviewItem) {
  if (!overviewItem) return null;
  const collectionItems = Array.isArray(state.items) ? state.items : [];
  if (!collectionItems.length) return null;
  const matches = tilesForOverviewItem(collectionItems, overviewItem, false);
  const gsds = matches
    .map((item) => Number(item?.gsd))
    .filter((gsd) => Number.isFinite(gsd) && gsd > 0);
  if (!gsds.length) return null;
  return Math.min(...gsds);
}

function formatCarouselMeta(item) {
  const captureDate = formatCaptureDate(item?.datetime);
  const gsd = collectionGsdForOverviewItem(item);
  const gsdText = formatGsdMeters(gsd);
  return `${captureDate}, GSD=${gsdText === "n/a" ? gsdText : `${gsdText}m`}`;
}

function assetProxyUrl(rawUrl, options = {}) {
  if (!rawUrl) return "";
  const params = new URLSearchParams({ url: rawUrl });
  const contractId = selectedContractId();
  if (contractId) params.set("contract_id", contractId);
  if (options.render === true) params.set("render", "true");
  return `${apiBase}/api/assets/proxy?${params.toString()}`;
}

function hideContextMenu() {
  mapContextMenuEl.style.display = "none";
}

function formatCoord(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return n.toFixed(6);
}

function formatLatLon(latlng) {
  if (!latlng) return "--, --";
  return `${formatCoord(clampLatitude(latlng.lat))}, ${formatCoord(normalizeLongitude(latlng.lng))}`;
}

function updateMapStatus() {
  const center = map.getCenter();
  mapStatusEl.textContent = `Zoom ${map.getZoom()} | Lat ${formatCoord(clampLatitude(center.lat))} | Lon ${formatCoord(normalizeLongitude(center.lng))}`;
}

async function updateDebugStats() {
  if (!DEBUG_NET || !mapDebugStatsEl) return;
  try {
    const res = await fetch(`${apiBase}/api/debug/stats`, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const searchTotal = Number(data?.archive_search?.total || 0);
    const byCollection = data?.archive_search?.by_collection || {};
    const l1dCount = Number(byCollection["l1d-sr"] || 0);
    const quickviewCount = Number(byCollection["quickview-visual-thumb"] || 0);
    const tileTotal = Number(data?.tile_proxy?.total || 0);
    const tileHitPct = Math.round(Number(data?.tile_proxy?.hit_rate || 0) * 100);
    mapDebugStatsEl.textContent = `Search ${searchTotal} (l1d ${l1dCount}, qv ${quickviewCount}) | Tiles ${tileTotal} (hit ${tileHitPct}%)`;
  } catch (_) {
    // Keep previous debug line if stats endpoint is unavailable.
  }
}

function showContextMenu(x, y, latlng = null) {
  if (latlng) {
    state.contextMenuLatLng = {
      lat: clampLatitude(latlng.lat),
      lng: normalizeLongitude(latlng.lng),
    };
    ctxCopyLatLonEl.textContent = `Lat/Lon: ${formatLatLon(latlng)}`;
  }
  mapContextMenuEl.style.left = `${x}px`;
  mapContextMenuEl.style.top = `${y}px`;
  mapContextMenuEl.style.display = "block";
}

function openAnimationDialog() {
  animStartDateEl.value = startDateEl.value;
  animEndDateEl.value = endDateEl.value;
  animMaxCloudEl.value = maxCloudEl.value;
  animSatelliteEl.value = satelliteNameEl.value;
  animMinGsdEl.value = minGsdEl.value;
  animMaxGsdEl.value = maxGsdEl.value;
  if (typeof animationDialogEl.showModal === "function") {
    animationDialogEl.showModal();
  }
}

function openAnimationWindow(gifBase64, filename = "capture_animation.gif") {
  const popup = window.open("", "_blank");
  if (!popup) {
    toast("Popup blocked by browser");
    return;
  }

  const dataUrl = `data:image/gif;base64,${gifBase64}`;
  popup.document.write(`
    <html>
      <head>
        <title>Animation Preview</title>
        <style>
          body { font-family: sans-serif; background: #111; color: #eee; margin: 20px; }
          img { max-width: 96vw; border: 1px solid #444; border-radius: 8px; }
          .actions { margin: 12px 0; }
          a { color: #9cd6ff; text-decoration: none; margin-right: 16px; }
        </style>
      </head>
      <body>
        <div class="actions">
          <a href="${dataUrl}" download="${filename}">Download GIF</a>
          <a href="${dataUrl}" target="_blank" rel="noopener">Open Raw GIF</a>
        </div>
        <img src="${dataUrl}" alt="Animation" />
      </body>
    </html>
  `);
  popup.document.close();
}

function updateSearchResultsHeader(visibleCount) {
  if (searchResultsCountEl) searchResultsCountEl.textContent = `${visibleCount} Products Found`;
  if (!searchResultsFilterMetaEl) return;
  if (!state.carouselFilterActive) {
    searchResultsFilterMetaEl.style.display = "none";
    searchResultsFilterMetaEl.textContent = "";
    return;
  }
  const total = Math.max(0, Number(state.carouselQuickviewCount || 0));
  searchResultsFilterMetaEl.textContent = `Showing quickviews backed by l1d-sr: ${visibleCount} of ${total}`;
  searchResultsFilterMetaEl.style.display = "block";
}

function renderTimeCarousel(items) {
  timeCarouselListEl.innerHTML = "";
  if (!items.length) {
    updateSearchResultsHeader(0);
    timeCarouselListEl.innerHTML = `<div class="meta">No quickview thumbnails for current search.</div>`;
    updateLockButtonState();
    return;
  }

  const sorted = [...items].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
  updateSearchResultsHeader(sorted.length);
  sorted.forEach((item, idx) => {
    const thumb = assetProxyUrl(thumbnailUrl(item), { render: false });
    const card = document.createElement("button");
    card.className = "carousel-card";
    card.type = "button";
    card.dataset.itemId = item.id;
    card.innerHTML = `
      <div class="carousel-card-head">
        <label class="check-wrap">
          <input type="checkbox" data-select-id="${item.id}" />
          show
        </label>
      </div>
      <img data-src="${thumb}" loading="lazy" alt="thumbnail ${idx + 1}" />
      <div class="card-date">${formatCarouselMeta(item)}</div>
    `;
    card.addEventListener("click", (evt) => {
      const target = evt.target;
      if (target instanceof HTMLInputElement) return;
      state.selectedCarouselIds.add(item.id);
      setActiveCarouselCard(item.id);
      syncCarouselCheckboxes();
      if (state.compareMode) updateCompareModeState(item.id);
      focusFromCarousel(item).catch((err) => toast(err.message));
    });

    const checkbox = card.querySelector('input[type="checkbox"]');
    if (checkbox) {
      checkbox.checked = state.selectedCarouselIds.has(item.id);
      checkbox.addEventListener("click", (evt) => evt.stopPropagation());
      checkbox.addEventListener("change", async (evt) => {
        const checked = evt.target.checked;
        if (checked) {
          state.selectedCarouselIds.add(item.id);
          setActiveCarouselCard(item.id);
        } else {
          state.selectedCarouselIds.delete(item.id);
          if (state.selectedCarouselId === item.id) {
            const next = mostRecentSelectedOverviewItem();
            state.selectedCarouselId = next ? next.id : null;
          }
        }
        syncCarouselCheckboxes();
        if (state.compareMode) updateCompareModeState(item.id);
        await refreshMapMode(false);
      });
    }
    timeCarouselListEl.appendChild(card);
    const img = card.querySelector("img[data-src]");
    if (img) lazyLoadCarouselImage(img);
  });
  syncCarouselCheckboxes();
}

const carouselImageObserver = typeof IntersectionObserver === "function"
  ? new IntersectionObserver((entries, observer) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const img = entry.target;
      const src = img.getAttribute("data-src");
      if (src && !img.getAttribute("src")) img.setAttribute("src", src);
      observer.unobserve(img);
    });
  }, {
    root: timeCarouselListEl,
    rootMargin: "120px 0px",
    threshold: 0.01,
  })
  : null;

function lazyLoadCarouselImage(imgEl) {
  if (!(imgEl instanceof HTMLImageElement)) return;
  if (imgEl.getAttribute("src")) return;
  const src = imgEl.getAttribute("data-src");
  if (!carouselImageObserver) {
    if (src) imgEl.setAttribute("src", src);
    return;
  }
  carouselImageObserver.observe(imgEl);
}

function setActiveCarouselCard(itemId) {
  state.selectedCarouselId = itemId;
  const cards = Array.from(timeCarouselListEl.querySelectorAll(".carousel-card"));
  cards.forEach((card) => {
    const selected = state.selectedCarouselIds.has(card.dataset.itemId);
    if (card.dataset.itemId === itemId) {
      card.classList.add("active");
      card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else {
      card.classList.toggle("active", selected);
    }
  });
}

function updateLockButtonState() {
  const selectedCount = state.selectedCarouselIds.size;
  const locked = selectedCount > 0;
  lockSelectionBtnEl.classList.toggle("active", locked);
  lockSelectionBtnEl.setAttribute("aria-pressed", locked ? "true" : "false");
  if (lockIconEl) {
    lockIconEl.classList.toggle("locked", locked);
    lockIconEl.classList.toggle("unlocked", !locked);
  }
}

function syncCarouselCheckboxes() {
  const cards = Array.from(timeCarouselListEl.querySelectorAll(".carousel-card"));
  cards.forEach((card) => {
    const id = card.dataset.itemId;
    const input = card.querySelector('input[type="checkbox"]');
    if (input) input.checked = state.selectedCarouselIds.has(id);
    card.classList.toggle("active", state.selectedCarouselIds.has(id) || state.selectedCarouselId === id);
  });
  updateLockButtonState();
}

function overviewSourceItems() {
  return state.overviewItems.length ? state.overviewItems : state.items;
}

function selectedOverviewItems() {
  if (state.selectedCarouselIds.size === 0) return [];
  return overviewSourceItems().filter((item) => state.selectedCarouselIds.has(item.id));
}

function sortNewestFirst(items) {
  return [...items].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
}

function captureKey(item) {
  const candidate = [item?.outcome_id, item?.id]
    .filter((v) => typeof v === "string" && v.length > 0)
    .join(" ");
  const match = candidate.match(/\d{8}_\d{6}_\d+_SN\d+/);
  return match ? match[0] : "";
}

function tilesForOverviewItem(source, overviewItem, allowNearest = true) {
  if (!overviewItem || !source?.length) return [];
  if (overviewItem.outcome_id) {
    const sameOutcome = source.filter((item) => item.outcome_id && item.outcome_id === overviewItem.outcome_id);
    if (sameOutcome.length) return sameOutcome;
  }

  const key = captureKey(overviewItem);
  if (key) {
    const sameCapture = source.filter((item) => captureKey(item) === key);
    if (sameCapture.length) return sameCapture;
  }

  if (!allowNearest) return [];
  return nearestCaptureTiles(source, overviewItem.datetime);
}

function normalizeCollectionId(value) {
  return (value || "").toString().trim().toLowerCase().replace(/_/g, "-");
}

function shouldRestrictCarouselToL1dSr(collectionId) {
  return normalizeCollectionId(collectionId) === "l1d-sr";
}

function filterOverviewItemsByPrimaryAvailability(overviewItems, primaryItems, collectionId) {
  const overview = Array.isArray(overviewItems) ? overviewItems : [];
  const primary = Array.isArray(primaryItems) ? primaryItems : [];
  if (!overview.length) return [];
  if (!primary.length) return [];
  if (!shouldRestrictCarouselToL1dSr(collectionId)) return overview;

  const outcomeIds = new Set(
    primary
      .map((item) => item?.outcome_id)
      .filter((value) => typeof value === "string" && value.length > 0),
  );
  const captureKeys = new Set(
    primary
      .map((item) => captureKey(item))
      .filter((value) => typeof value === "string" && value.length > 0),
  );

  return overview.filter((item) => {
    const outcomeId = item?.outcome_id;
    if (typeof outcomeId === "string" && outcomeId && outcomeIds.has(outcomeId)) return true;
    const key = captureKey(item);
    return Boolean(key && captureKeys.has(key));
  });
}

function mostRecentSelectedOverviewItem() {
  const selected = sortNewestFirst(selectedOverviewItems());
  return selected[0] || null;
}

function orderedOverviewDisplayItems() {
  const selected = sortNewestFirst(selectedOverviewItems());
  if (selected.length) return selected;
  const all = sortNewestFirst(overviewSourceItems());
  return all.length ? [all[0]] : [];
}

function detailTilesForOverviewItem(overviewItem, baseItems = []) {
  if (!overviewItem) return [];
  const source = dedupeById([...(baseItems || []), ...state.items]);
  return tilesForOverviewItem(source, overviewItem, state.selectedCarouselIds.size === 0);
}

function detailTilesForOverviewItems(overviewItems, baseItems = []) {
  if (!overviewItems?.length) return [];
  const chronological = [...overviewItems].sort((a, b) => (a.datetime || "").localeCompare(b.datetime || ""));
  const merged = [];
  chronological.forEach((overviewItem) => {
    merged.push(...detailTilesForOverviewItem(overviewItem, baseItems));
  });
  return dedupeById(merged);
}

function buildCompareFrames() {
  const source = selectedOverviewItems().length ? selectedOverviewItems() : overviewSourceItems();
  return [...source].sort((a, b) => (a.datetime || "").localeCompare(b.datetime || ""));
}

function updateCompareDateTag() {
  if (!state.compareMode) return;
  const frames = state.compareFrames;
  if (!frames.length) {
    compareDateTagEl.textContent = "No image";
    compareDateTagEl.style.top = "50%";
    return;
  }
  const min = Number(compareRangeEl.min || 0);
  const max = Number(compareRangeEl.max || 0);
  const value = Math.round(Math.max(min, Math.min(max, Number(compareRangeEl.value || 0))));
  const pct = max > min ? (value - min) / (max - min) : 0;
  compareDateTagEl.style.top = `${(1 - pct) * 100}%`;
  compareDateTagEl.textContent = formatCaptureDate(frames[value]?.datetime);
}

function clearMapLayers() {
  if (state.mapVectorLayer) map.removeLayer(state.mapVectorLayer);
  if (state.mapThumbOverlayLayer) map.removeLayer(state.mapThumbOverlayLayer);
  if (state.mapThumbMarkerLayer) map.removeLayer(state.mapThumbMarkerLayer);
  if (state.compareBlendLayer) map.removeLayer(state.compareBlendLayer);
  if (state.activeFrameOverlay) map.removeLayer(state.activeFrameOverlay);
  state.mapVectorLayer = null;
  state.mapThumbOverlayLayer = null;
  state.mapThumbMarkerLayer = null;
  state.compareBlendLayer = null;
  state.activeFrameOverlay = null;
}

function thumbnailUrl(item) {
  return item.assets?.thumbnail || item.assets?.preview || item.assets?.visual || "";
}

function previewUrl(item) {
  return item.assets?.preview || item.assets?.thumbnail || item.assets?.visual || "";
}

function detailVisualUrl(item) {
  return item.assets?.visual || item.assets?.analytic || item.assets?.preview || item.assets?.thumbnail || "";
}

function detailCogAssetUrl(item) {
  return item.assets?.visual || item.assets?.analytic || item.assets?.preview || item.assets?.thumbnail || "";
}

function extractCogSourceUrl(rawUrl) {
  if (!rawUrl) return "";
  if (rawUrl.startsWith("s3://")) return rawUrl;
  try {
    const parsed = new URL(rawUrl);
    const source = parsed.searchParams.get("s");
    if (source && source.startsWith("s3://")) return source;
    return rawUrl;
  } catch (_) {
    return rawUrl;
  }
}

function detailTileTemplateUrl(item, zoomLevel = map.getZoom()) {
  const raw = detailCogAssetUrl(item);
  const source = extractCogSourceUrl(raw);
  if (!source) return "";
  const params = new URLSearchParams();
  params.set("url", source);
  const contractId = selectedContractId();
  if (contractId) params.set("contract_id", contractId);
  const scale = Number(zoomLevel) >= DETAIL_COG_HIGHRES_ZOOM ? 2 : 1;
  params.set("scale", String(scale));
  params.set("tileMatrixSetId", "WebMercatorQuad");
  params.set("format", "png");
  params.append("bidx", "1");
  params.append("bidx", "2");
  params.append("bidx", "3");
  return `${apiBase}/api/raster/cog/tiles/{z}/{x}/{y}?${params.toString()}`;
}

function modeSourceUrl(item, mode) {
  if (mode === "detail") return detailVisualUrl(item);
  return thumbnailUrl(item);
}

function compareOverlaySource(item, mode, overlayIndex = 0) {
  if (mode !== "detail") return { raw: modeSourceUrl(item, mode), render: false };
  const useFullRes = overlayIndex < DETAIL_FULLRES_VISIBLE_LIMIT;
  if (useFullRes) return { raw: detailVisualUrl(item), render: true };
  return { raw: previewUrl(item) || thumbnailUrl(item) || detailVisualUrl(item), render: false };
}

function itemCenterDistance(item, centerLatLng) {
  const bounds = boundsFromGeometry(item?.geometry);
  if (!bounds || !centerLatLng) return Number.POSITIVE_INFINITY;
  return map.distance(centerLatLng, bounds.getCenter());
}

function prioritizeClosestToCenter(items, maxItems = null) {
  const center = map.getCenter();
  const sorted = [...items].sort((a, b) => itemCenterDistance(a, center) - itemCenterDistance(b, center));
  if (maxItems && maxItems > 0) return sorted.slice(0, maxItems);
  return sorted;
}

function boundsFromGeometry(geometry) {
  if (!geometry) return null;
  try {
    const layer = L.geoJSON({ type: "Feature", geometry });
    const bounds = layer.getBounds();
    return bounds.isValid() ? bounds : null;
  } catch (_) {
    return null;
  }
}

function updateActiveFrameOverlay(item) {
  if (state.activeFrameOverlay) {
    map.removeLayer(state.activeFrameOverlay);
    state.activeFrameOverlay = null;
  }

  // Detail mode already renders its own visible tile overlays.
  // Avoid downloading a duplicate image layer on top.
  if (state.mapMode === "detail") return;

  if (!item || !item.geometry) return;
  const raw = state.mapMode === "detail" ? detailVisualUrl(item) : previewUrl(item);
  const src = assetProxyUrl(raw, { render: state.mapMode === "detail" });
  const bounds = boundsFromGeometry(item.geometry);
  if (!src || !bounds) return;

  state.activeFrameOverlay = L.imageOverlay(src, bounds, {
    opacity: state.mapMode === "detail" ? 1.0 : 0.72,
    crossOrigin: true,
    className: "active-frame-overlay",
  }).addTo(map);
}

function drawResults(items, mode = "overview", fitToBounds = false, options = {}) {
  clearMapLayers();

  const selectedOverview = selectedOverviewItems();
  const selectedIds = new Set(selectedOverview.map((item) => item?.id).filter(Boolean));
  const selectedOutcomes = new Set(selectedOverview.map((item) => item?.outcome_id).filter(Boolean));
  const selectedCaptures = new Set(selectedOverview.map((item) => captureKey(item)).filter(Boolean));
  const selectedDatetimes = new Set(selectedOverview.map((item) => item?.datetime).filter(Boolean));
  const isSelectedItem = (item) => {
    if (!item || selectedOverview.length === 0) return false;
    if (item.id && selectedIds.has(item.id)) return true;
    if (item.outcome_id && selectedOutcomes.has(item.outcome_id)) return true;
    const key = captureKey(item);
    if (key && selectedCaptures.has(key)) return true;
    if (item.datetime && selectedDatetimes.has(item.datetime)) return true;
    return false;
  };

  const features = items
    .filter((item) => item.geometry)
    .map((item, itemIndex) => ({
      type: "Feature",
      geometry: item.geometry,
      properties: {
        itemIndex,
        id: item.id,
        datetime: item.datetime,
        cloud_cover: item.cloud_cover,
        thumbnail: assetProxyUrl(mode === "detail" ? (previewUrl(item) || thumbnailUrl(item) || detailVisualUrl(item)) : modeSourceUrl(item, mode), { render: false }),
        satellite_name: item.satellite_name || "n/a",
        gsd: item.gsd,
        selected: isSelectedItem(item),
      },
    }));

  state.mapVectorLayer = L.geoJSON(features, {
    style: (feature) => {
      const selected = Boolean(feature?.properties?.selected);
      if (mode === "detail" && !selected) {
        return {
          color: "transparent",
          weight: 0,
          fillOpacity: 0,
          opacity: 0,
        };
      }
      const baseColor = selected ? "#2d6bff" : "#f28f3b";
      return {
        color: baseColor,
        weight: mode === "detail" ? 2.1 : 1.2,
        fillOpacity: mode === "detail" ? 0.0 : (selected ? 0.1 : 0.07),
        opacity: 1,
      };
    },
    onEachFeature: (feature, layer) => {
      const props = feature.properties || {};
      const thumb = props.thumbnail
        ? `<img src="${props.thumbnail}" alt="thumbnail" />`
        : "<div>No thumbnail</div>";
      layer.bindPopup(`
        <div class="thumb-popup">
          ${thumb}
          <div class="meta">
            <strong>${props.id}</strong><br/>
            ${props.datetime || "no datetime"}<br/>
            cloud: ${props.cloud_cover ?? "n/a"}<br/>
            sat: ${props.satellite_name}<br/>
            gsd: ${props.gsd ?? "n/a"}
          </div>
        </div>
      `);
    },
  }).addTo(map);

  state.mapThumbOverlayLayer = L.layerGroup().addTo(map);
  state.mapThumbMarkerLayer = L.layerGroup().addTo(map);

  const overlaySourceItems = Array.isArray(options.overlayItems) ? options.overlayItems : items;
  const withThumbnailsRaw = overlaySourceItems.filter((item) => item.geometry && (mode === "detail" ? (previewUrl(item) || detailVisualUrl(item)) : modeSourceUrl(item, mode)));
  const withThumbnails = mode === "detail"
    ? [...withThumbnailsRaw].sort((a, b) => (a.datetime || "").localeCompare(b.datetime || ""))
    : withThumbnailsRaw;
  const maxOverlays = mode === "detail" ? withThumbnails.length : 0;
  const maxMarkers = mode === "detail" ? 0 : 40;
  const overlayOpacity = mode === "detail" ? 1.0 : 0.32;
  const overlayItems = mode === "detail"
    ? withThumbnails.slice(Math.max(0, withThumbnails.length - maxOverlays))
    : withThumbnails.slice(0, maxOverlays);
  const overlayEntries = overlayItems.map((item, index) => ({
    item,
    visualIndex: index,
    zIndex: 400 + index,
  }));
  const loadEntries = mode === "detail"
    ? [...overlayEntries].reverse()
    : overlayEntries;

  if (mode === "detail" && state.useCogTileProxy && loadEntries.length) {
    const topTemplate = detailTileTemplateUrl(loadEntries[0].item, map.getZoom());
    if (topTemplate) {
      const center = map.getCenter();
      const tileCenter = latLngToTileXY(center.lat, center.lng, map.getZoom());
      const url = resolveTileTemplate(topTemplate, tileCenter.z, tileCenter.x, tileCenter.y);
      queuePrefetchUrl(url);
    }
  }

  loadEntries.forEach(({ item, visualIndex, zIndex }) => {
    const bounds = boundsFromGeometry(item.geometry);
    if (!bounds) return;

    if (mode === "detail" && state.useCogTileProxy) {
      const tileTemplate = detailTileTemplateUrl(item, map.getZoom());
      if (tileTemplate) {
        const tileLayer = L.tileLayer(tileTemplate, {
          opacity: overlayOpacity,
          bounds,
          tileSize: 256,
          maxZoom: 22,
          updateWhenIdle: true,
          updateWhenZooming: false,
          keepBuffer: 0,
          zIndex,
          crossOrigin: true,
        });
        tileLayer.on("tileerror", () => {
          if (!state.useCogTileProxy) return;
          state.useCogTileProxy = false;
          if (!state.tileProxyWarned) {
            state.tileProxyWarned = true;
            toast("COG tile API not authorized; using fallback rendering");
          }
          refreshMapMode(true).catch(() => {});
        });
        tileLayer.addTo(state.mapThumbOverlayLayer);
        return;
      }
    }

    const srcCfg = compareOverlaySource(item, mode, visualIndex);
    const src = assetProxyUrl(srcCfg.raw, { render: srcCfg.render });
    if (!src) return;
    L.imageOverlay(src, bounds, {
      opacity: overlayOpacity,
      crossOrigin: true,
      interactive: false,
      zIndex,
      className: "thumb-footprint-overlay",
    }).addTo(state.mapThumbOverlayLayer);
  });

  withThumbnails.slice(0, maxMarkers).forEach((item) => {
    const bounds = boundsFromGeometry(item.geometry);
    const src = assetProxyUrl(modeSourceUrl(item, mode), { render: false });
    if (!bounds || !src) return;
    const marker = L.circleMarker(bounds.getCenter(), {
      radius: 4,
      color: "#0c7b63",
      weight: 2,
      fillOpacity: 0.95,
    });
    marker.bindPopup(`
      <div class="thumb-popup">
        <img src="${src}" alt="thumbnail" />
        <div class="meta">
          <strong>${item.id}</strong><br/>
          ${item.datetime || "no datetime"}<br/>
          cloud: ${item.cloud_cover ?? "n/a"}<br/>
          sat: ${item.satellite_name || "n/a"}<br/>
          gsd: ${item.gsd ?? "n/a"}
        </div>
      </div>
    `);
    marker.addTo(state.mapThumbMarkerLayer);
  });

  if (state.mapVectorLayer) state.mapVectorLayer.bringToFront();

  if (fitToBounds && features.length > 0) {
    map.fitBounds(state.mapVectorLayer.getBounds(), { maxZoom: 13 });
  }
}

function setItemSelectors(items) {
  frameSelectEl.innerHTML = "";
  beforeSelectEl.innerHTML = "";
  afterSelectEl.innerHTML = "";

  items.forEach((item, idx) => {
    const label = `${idx + 1}. ${item.datetime || "n/a"} (${item.id.slice(0, 10)})`;
    [frameSelectEl, beforeSelectEl, afterSelectEl].forEach((sel) => {
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = label;
      sel.appendChild(opt);
    });
  });

  if (items.length > 0) {
    beforeSelectEl.selectedIndex = Math.min(items.length - 1, 1);
    afterSelectEl.selectedIndex = 0;
  }

  timelineEl.max = String(Math.max(0, items.length - 1));
  timelineEl.value = "0";
  showFrame(0);
}

function showFrame(index) {
  const item = state.items[index];
  if (!item) return;
  const src = assetProxyUrl(previewUrl(item));
  framePreviewEl.src = src || "";
  timelineEl.value = String(index);
  updateActiveFrameOverlay(item);
}

function selectedFrameIds() {
  const selected = Array.from(frameSelectEl.selectedOptions).map((opt) => opt.value);
  if (selected.length > 0) return selected;
  return state.items.slice(0, 12).map((item) => item.id);
}

async function fetchArchiveItems(payload) {
  const started = performance.now();
  debugLog("archive search request", {
    collection: payload.collection_id,
    limit: payload.limit,
  });
  const res = await fetch(`${apiBase}/api/archive/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Search failed");
  }
  debugLog("archive search response", {
    collection: payload.collection_id,
    count: (data.items || []).length,
    ms: Math.round(performance.now() - started),
  });
  return data.items || [];
}

function latestCaptureTiles(items) {
  if (!items.length) return [];
  const sorted = [...items].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
  const first = sorted[0];
  if (first.outcome_id) {
    const byOutcome = sorted.filter((item) => item.outcome_id === first.outcome_id);
    if (byOutcome.length) return byOutcome;
  }
  const latestDt = first.datetime;
  return sorted.filter((item) => item.datetime === latestDt);
}

function nearestCaptureTiles(items, targetDatetime) {
  if (!items.length) return [];
  if (!targetDatetime) return latestCaptureTiles(items);
  const t = new Date(targetDatetime).getTime();
  let best = null;
  let bestDelta = Number.POSITIVE_INFINITY;
  items.forEach((item) => {
    const dt = item.datetime ? new Date(item.datetime).getTime() : NaN;
    if (!Number.isFinite(dt)) return;
    const delta = Math.abs(dt - t);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = item;
    }
  });
  if (!best) return latestCaptureTiles(items);
  if (best.outcome_id) return items.filter((item) => item.outcome_id === best.outcome_id);
  return items.filter((item) => item.datetime === best.datetime);
}

function renderTilesForFrame(frame, bounds = null) {
  if (!frame) return [];
  const source = dedupeById([...(state.detailItems || []), ...state.items]);
  let tiles = tilesForOverviewItem(source, frame, false);
  if (!tiles.length) tiles = tilesForOverviewItem(source, frame, true);
  const viewport = bounds || map.getBounds().pad(DETAIL_TILE_BUFFER_PAD);
  const visibleTiles = filterItemsToViewport(tiles, viewport);
  const useTiles = visibleTiles.length ? visibleTiles : tiles;
  return useTiles;
}

function queuePrefetchUrl(url) {
  if (!url || state.prefetchTileUrlSeen.has(url)) return;
  state.prefetchTileUrlSeen.add(url);
  fetch(url, { cache: "force-cache" }).catch(() => {});
}

function latLngToTileXY(lat, lon, zoom) {
  const z = Math.max(0, Math.floor(zoom));
  const n = 2 ** z;
  const wrappedLon = normalizeLongitude(lon);
  const mercatorLat = Math.max(-85.05112878, Math.min(85.05112878, clampLatitude(lat)));
  let x = Math.floor(((wrappedLon + 180) / 360) * n);
  x = ((x % n) + n) % n;
  const latRad = (mercatorLat * Math.PI) / 180;
  const y = Math.floor(((1 - Math.log(Math.tan(latRad) + (1 / Math.cos(latRad))) / Math.PI) / 2) * n);
  return { z, x, y };
}

function resolveTileTemplate(template, z, x, y) {
  return template
    .replace("{z}", String(z))
    .replace("{x}", String(x))
    .replace("{y}", String(y));
}

function prefetchCompareTilesAroundIndex(index) {
  if (!state.useCogTileProxy || !state.compareMode || map.getZoom() < DETAIL_ZOOM_THRESHOLD) return;
  const frames = state.compareFrames;
  if (!frames.length) return;

  const base = Math.max(0, Math.min(frames.length - 1, Math.round(index)));
  const bufferedBounds = map.getBounds().pad(DETAIL_TILE_BUFFER_PAD);
  for (let delta = 1; delta <= COMPARE_PREFETCH_NEIGHBORS; delta += 1) {
    [base - delta, base + delta].forEach((i) => {
      if (i < 0 || i >= frames.length) return;
      const tiles = renderTilesForFrame(frames[i], bufferedBounds).slice(0, COMPARE_PREFETCH_TILES_PER_FRAME);
      const center = map.getCenter();
      const tileCenter = latLngToTileXY(center.lat, center.lng, map.getZoom());
      const offsets = [
        [0, 0],
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ];
      tiles.forEach((tile, overlayIndex) => {
        if (overlayIndex >= DETAIL_FULLRES_VISIBLE_LIMIT) return;
        const tileTemplate = detailTileTemplateUrl(tile, map.getZoom());
        if (!tileTemplate) return;
        offsets.forEach(([dx, dy]) => {
          const url = resolveTileTemplate(tileTemplate, tileCenter.z, tileCenter.x + dx, tileCenter.y + dy);
          queuePrefetchUrl(url);
        });
      });
    });
  }
}

async function focusFromCarousel(overviewItem) {
  if (!overviewItem) return;
  setActiveCarouselCard(overviewItem.id);
  if (state.compareMode && state.compareFrames.length) {
    const idx = state.compareFrames.findIndex((item) => item.id === overviewItem.id);
    if (idx >= 0) {
      compareRangeEl.value = String(idx);
      updateCompareDateTag();
    }
  }

  let tiles = [];
  if (overviewItem.outcome_id) {
    tiles = state.items.filter((item) => item.outcome_id === overviewItem.outcome_id);
  }
  if (!tiles.length) {
    tiles = nearestCaptureTiles(state.items, overviewItem.datetime);
  }

  if (!tiles.length) {
    const geom = overviewItem.geometry || state.currentAoi || geometryFromMapBounds();
    const centerDt = overviewItem.datetime ? new Date(overviewItem.datetime) : new Date();
    const start = new Date(centerDt.getTime() - (3 * 24 * 3600 * 1000)).toISOString();
    const end = new Date(centerDt.getTime() + (3 * 24 * 3600 * 1000)).toISOString();

    const detailPayload = {
      ...buildSearchPayload(geom, "l1d-sr", DETAIL_MAX_QUERY_LIMIT),
      start_date: start,
      end_date: end,
    };
    const fetched = await fetchArchiveItems(detailPayload);
    tiles = overviewItem.outcome_id
      ? fetched.filter((item) => item.outcome_id === overviewItem.outcome_id)
      : nearestCaptureTiles(fetched, overviewItem.datetime);
  }

  if (!tiles.length) {
    toast("No matching l1d-sr tiles found for this thumbnail");
    return;
  }

  if (map.getZoom() < DETAIL_ZOOM_THRESHOLD) {
    state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
    map.setZoom(DETAIL_ZOOM_THRESHOLD);
  }

  state.detailItems = dedupeById(tiles);
  state.mapMode = "detail";
  const visibleTiles = filterItemsToViewport(state.detailItems);
  const renderTiles = topCaptureOnly(visibleTiles);
  drawResults(renderTiles, "detail", false);
  updateActiveFrameOverlay(renderTiles[0]);

  const bounds = boundsFromGeometry(overviewItem.geometry || state.detailItems[0].geometry);
  if (bounds) {
    state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
    map.panTo(bounds.getCenter(), { animate: true, duration: 0.4 });
  }
}

function buildDetailRequestKey(payload) {
  const b = map.getBounds();
  return JSON.stringify({
    z: map.getZoom(),
    bbox: [
      b.getWest().toFixed(3),
      b.getSouth().toFixed(3),
      b.getEast().toFixed(3),
      b.getNorth().toFixed(3),
    ],
    start: payload.start_date,
    end: payload.end_date,
    contract: payload.contract_id || "",
    sat: payload.satellite_name || "",
    gsdMin: payload.min_gsd ?? "",
    gsdMax: payload.max_gsd ?? "",
    cloud: payload.max_cloud_cover ?? "",
  });
}

function buildDetailContextKey(payload) {
  return JSON.stringify({
    start: payload.start_date,
    end: payload.end_date,
    contract: payload.contract_id || "",
    sat: payload.satellite_name || "",
    gsdMin: payload.min_gsd ?? "",
    gsdMax: payload.max_gsd ?? "",
    cloud: payload.max_cloud_cover ?? "",
  });
}

function dedupeById(items) {
  const seen = new Set();
  const out = [];
  items.forEach((item) => {
    if (!item?.id || seen.has(item.id)) return;
    seen.add(item.id);
    out.push(item);
  });
  return out;
}

function selectedDetailItems(baseDetailItems) {
  const selected = selectedOverviewItems();
  const base = dedupeById(baseDetailItems || []);
  if (!selected.length) return base;

  const source = dedupeById([...base, ...state.items]);

  const merged = [];
  selected.forEach((ov) => {
    merged.push(...tilesForOverviewItem(source, ov, false));
  });
  const unique = dedupeById(merged);
  return unique;
}

function itemIntersectsBounds(item, bounds) {
  if (!item?.geometry || !bounds) return false;
  const itemBounds = boundsFromGeometry(item.geometry);
  return Boolean(itemBounds && bounds.intersects(itemBounds));
}

function filterItemsToViewport(items, bounds = map.getBounds()) {
  return items.filter((item) => itemIntersectsBounds(item, bounds));
}

function topCaptureOnly(items) {
  if (!items.length) return [];
  const sorted = [...items].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
  const top = sorted[0];
  if (top?.outcome_id) {
    const sameOutcome = sorted.filter((item) => item.outcome_id === top.outcome_id);
    if (sameOutcome.length) return sameOutcome;
  }
  const topDt = top?.datetime;
  return sorted.filter((item) => item.datetime === topDt);
}

function stripAreaKey(item) {
  const candidate = [item?.id, item?.outcome_id]
    .filter((v) => typeof v === "string" && v.length > 0)
    .join(" ");
  const areaMatch = candidate.match(/(\d+[NS]_\d+_\d+)(?=[^0-9]|$)/i);
  if (areaMatch) return areaMatch[1].toUpperCase();
  const bounds = boundsFromGeometry(item?.geometry);
  if (bounds) {
    const center = bounds.getCenter();
    const spanLat = Math.abs(bounds.getNorth() - bounds.getSouth());
    const spanLon = Math.abs(bounds.getEast() - bounds.getWest());
    return `${center.lat.toFixed(4)}_${center.lng.toFixed(4)}_${spanLat.toFixed(4)}_${spanLon.toFixed(4)}`;
  }
  return (item?.id || item?.outcome_id || "").toString();
}

function latestStripPerArea(items) {
  if (!Array.isArray(items) || !items.length) return [];
  const chosen = new Map();
  items.forEach((item) => {
    const key = stripAreaKey(item);
    if (!key) return;
    const prior = chosen.get(key);
    if (!prior) {
      chosen.set(key, item);
      return;
    }
    const prevDt = prior.datetime || "";
    const nextDt = item.datetime || "";
    if (nextDt > prevDt) chosen.set(key, item);
  });
  return [...chosen.values()].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
}

async function refreshMapMode(force = false) {
  if (!state.searchParams) return;
  const viewportBounds = map.getBounds();

  if (map.getZoom() >= DETAIL_ZOOM_THRESHOLD) {
    const paddedBounds = viewportBounds.pad(DETAIL_FETCH_PADDING);
    const detailPayload = {
      ...state.searchParams,
      geometry: geometryFromBounds(paddedBounds),
      collection_id: "l1d-sr",
      limit: DETAIL_MAX_QUERY_LIMIT,
    };
    const requestKey = buildDetailRequestKey(detailPayload);
    const contextKey = buildDetailContextKey(detailPayload);
    const coverageValid = (
      !force &&
      Boolean(state.lastDetailCoverageBounds) &&
      state.lastDetailCoverageZoom === map.getZoom() &&
      state.lastDetailContextKey === contextKey &&
      state.lastDetailCoverageBounds.contains(viewportBounds)
    );
    const needFetch = force || requestKey !== state.lastDetailRequestKey;
    const canFetchNow = force || (Date.now() - state.lastDetailFetchAt >= DETAIL_FETCH_COOLDOWN_MS);
    if (needFetch && !coverageValid && canFetchNow) {
      debugLog("detail fetch", { zoom: map.getZoom(), requestKey });
      const items = await fetchArchiveItems(detailPayload);
      state.detailItems = dedupeById(items);
      state.lastDetailRequestKey = requestKey;
      state.lastDetailFetchAt = Date.now();
      state.lastDetailCoverageBounds = paddedBounds;
      state.lastDetailCoverageZoom = map.getZoom();
      state.lastDetailContextKey = contextKey;
      debugLog("detail fetch result", { fetched: items.length, detailItems: state.detailItems.length });
    } else if (coverageValid) {
      debugLog("detail fetch skipped (coverage cache)");
    } else if (!canFetchNow) {
      debugLog("detail fetch skipped (cooldown)");
    }

    state.mapMode = "detail";
    let detailCandidates = dedupeById(state.detailItems.length ? state.detailItems : state.items);
    if (!detailCandidates.length) detailCandidates = latestCaptureTiles(state.items);
    let detailVisible = filterItemsToViewport(detailCandidates, viewportBounds);
    if (!detailVisible.length) {
      detailVisible = filterItemsToViewport(detailCandidates, viewportBounds.pad(DETAIL_TILE_BUFFER_PAD));
    }
    let overlayItems = latestStripPerArea(detailVisible);
    const selectedOverviews = selectedOverviewItems();
    if (selectedOverviews.length) {
      const selectedTiles = detailTilesForOverviewItems(selectedOverviews, detailCandidates);
      const selectedVisible = filterItemsToViewport(dedupeById(selectedTiles), viewportBounds);
      if (selectedVisible.length) overlayItems = selectedVisible;
    }
    drawResults(detailVisible, "detail", false, { overlayItems });
    const sel = state.selectedCarouselIds.size;
    searchMetaEl.textContent = `Mode: detail (zoom ${map.getZoom()}) • strips: ${detailVisible.length} • overlays: ${overlayItems.length}${sel ? ` • selected: ${sel}` : ""}`;
    syncCarouselCheckboxes();
    updateCompareModeState();
    return;
  }

  state.mapMode = "overview";
  const overview = orderedOverviewDisplayItems();
  const overviewVisible = filterItemsToViewport(overview, viewportBounds);
  drawResults(overviewVisible, "overview", false);
  const mapReadyThumbs = overviewVisible.filter((item) => Boolean(item.geometry && thumbnailUrl(item))).length;
  const sel = state.selectedCarouselIds.size;
  searchMetaEl.textContent = `Mode: overview • ${overviewVisible.length} visible (${mapReadyThumbs} thumbnails) • zoom to ${DETAIL_ZOOM_THRESHOLD}+ for detail${sel ? ` • selected: ${sel}` : ""}`;
  syncCarouselCheckboxes();
  updateCompareModeState();
}

function applyCompareFrameAt(index) {
  if (!state.compareMode) return;
  const frames = state.compareFrames;
  if (!frames.length) return;
  const idx = Math.max(0, Math.min(frames.length - 1, Math.round(Number(index || 0))));
  compareRangeEl.value = String(idx);
  const frame = frames[idx];
  setActiveCarouselCard(frame.id);

  if (state.compareBlendLayer) {
    map.removeLayer(state.compareBlendLayer);
    state.compareBlendLayer = null;
  }

  if (map.getZoom() >= DETAIL_ZOOM_THRESHOLD) {
    const renderTiles = renderTilesForFrame(frame);
    drawResults(renderTiles, "detail", false);
  } else {
    drawResults([frame], "overview", false);
  }
  updateCompareDateTag();
  prefetchCompareTilesAroundIndex(idx);
}

function updateCompareModeState(preferredItemId = null) {
  if (!state.compareMode) return;
  const currentIdx = Math.round(Number(compareRangeEl.value || 0));
  const currentItemId = preferredItemId || state.compareFrames[currentIdx]?.id || state.selectedCarouselId || null;
  state.compareFrames = buildCompareFrames();
  const max = Math.max(0, state.compareFrames.length - 1);
  compareRangeEl.max = String(max);
  let nextIdx = state.compareFrames.findIndex((item) => item.id === currentItemId);
  if (nextIdx < 0) nextIdx = Math.max(0, Math.min(max, currentIdx));
  compareRangeEl.value = String(nextIdx);
  updateCompareDateTag();
  applyCompareFrameAt(nextIdx);
}

function setCompareMode(enabled) {
  state.compareMode = enabled;
  compareRailEl.classList.toggle("visible", enabled);
  compareModeBtnEl.classList.toggle("active", enabled);
  if (!enabled && state.compareBlendLayer) {
    map.removeLayer(state.compareBlendLayer);
    state.compareBlendLayer = null;
  }
  if (!enabled) {
    refreshMapMode(false).catch((err) => toast(err.message));
    return;
  }
  state.compareFrames = buildCompareFrames();
  compareRangeEl.min = "0";
  compareRangeEl.max = String(Math.max(0, state.compareFrames.length - 1));
  compareRangeEl.value = "0";
  updateCompareDateTag();
  applyCompareFrameAt(0);
}

function scheduleMapRefresh() {
  if (state.mapRefreshTimer) clearTimeout(state.mapRefreshTimer);
  state.mapRefreshTimer = setTimeout(() => {
    refreshMapMode(false).catch((err) => toast(err.message));
  }, DETAIL_FETCH_DEBOUNCE_MS);
}

function stepCompareBy(delta) {
  if (!state.compareMode || !state.compareFrames.length) return;
  const current = Math.round(Number(compareRangeEl.value || 0));
  const next = Math.max(0, Math.min(state.compareFrames.length - 1, current + delta));
  applyCompareFrameAt(next);
}

async function searchArchive() {
  const geometry = normalizeGeometryLongitudes(geometryFromBounds(map.getBounds()));
  updateSearchFieldsFromGeometry(geometry);
  state.currentAoi = geometry;

  state.searchParams = buildSearchPayload(geometry);
  state.lastDetailRequestKey = null;
  state.lastDetailCoverageBounds = null;
  state.lastDetailCoverageZoom = null;
  state.lastDetailContextKey = null;
  state.prefetchTileUrlSeen.clear();
  state.useCogTileProxy = true;
  state.tileProxyWarned = false;
  state.detailItems = [];
  state.selectedCarouselIds.clear();
  state.selectedCarouselId = null;
  if (state.compareMode) setCompareMode(false);

  const primaryItems = await fetchArchiveItems(state.searchParams);
  const overviewPayload = {
    ...state.searchParams,
    collection_id: "quickview-visual-thumb",
    limit: Math.max(Number(limitEl.value), 300),
  };
  let overviewItems = [];
  try {
    overviewItems = await fetchArchiveItems(overviewPayload);
  } catch (_) {
    overviewItems = [];
  }
  const filteredOverviewItems = filterOverviewItemsByPrimaryAvailability(
    overviewItems,
    primaryItems,
    state.searchParams.collection_id,
  );

  state.items = primaryItems;
  state.carouselQuickviewCount = overviewItems.length;
  state.carouselFilterActive = shouldRestrictCarouselToL1dSr(state.searchParams.collection_id);
  if (shouldRestrictCarouselToL1dSr(state.searchParams.collection_id)) {
    state.overviewItems = filteredOverviewItems;
  } else {
    state.overviewItems = overviewItems.length ? overviewItems : primaryItems;
  }
  renderTimeCarousel(state.overviewItems);
  updateLockButtonState();

  // Keep analyst viewport stable; do not auto-fit search results.
  drawResults(orderedOverviewDisplayItems(), "overview", false);
  setItemSelectors(state.items);
  await refreshMapMode(true);
  toast(`Loaded ${state.items.length} timeline items, ${state.overviewItems.length} overview items`);
}

async function discoverStacks() {
  const geometry = normalizeGeometryLongitudes(geometryFromBounds(map.getBounds()));
  updateSearchFieldsFromGeometry(geometry);
  state.currentAoi = geometry;

  const payload = buildSearchPayload(geometry);

  const res = await fetch(`${apiBase}/api/archive/stacks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Stack discovery failed");

  const totalCaptures = data.stacks.reduce((sum, s) => sum + s.count, 0);
  searchMetaEl.textContent = `${data.count} stacks, ${totalCaptures} tiles total`;
  toast(`Stacks discovered: ${data.count}`);
}

async function buildGif() {
  const payload = {
    item_ids: selectedFrameIds(),
    contract_id: selectedContractId(),
    seconds_per_frame: 0.8,
    max_frames: 30,
  };

  const res = await fetch(`${apiBase}/api/archive/animate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Animation failed");

  if (data.created && data.gif_base64) {
    framePreviewEl.src = `data:image/gif;base64,${data.gif_base64}`;
    toast(`GIF ready (${data.frame_count} frames)`);
  } else {
    throw new Error(data.reason || "GIF not created");
  }
}

function clearMp4JobPolling() {
  if (state.mp4JobTimer) {
    clearInterval(state.mp4JobTimer);
    state.mp4JobTimer = null;
  }
}

function buildSelectedMp4AnimationPayload() {
  const selectedFrames = sortNewestFirst(selectedOverviewItems()).reverse();
  if (selectedFrames.length < 2) {
    throw new Error("Select at least two images in the carousel.");
  }

  const viewportBounds = map.getBounds();
  const viewportGeometry = normalizeGeometryLongitudes(geometryFromBounds(viewportBounds));
  const sourceTiles = dedupeById([...(state.detailItems || []), ...state.items]);

  const frames = [];
  selectedFrames.forEach((overviewItem) => {
    let tiles = tilesForOverviewItem(sourceTiles, overviewItem, false);
    if (!tiles.length) tiles = tilesForOverviewItem(sourceTiles, overviewItem, true);
    if (!tiles.length) return;

    const visibleTiles = filterItemsToViewport(tiles, viewportBounds);
    if (!visibleTiles.length) return;

    const frameTiles = dedupeById(visibleTiles)
      .map((tile) => ({
        item_id: tile.id || null,
        geometry: normalizeGeometryLongitudes(tile.geometry),
        url: fullVisualAssetUrl(tile) || detailVisualUrl(tile),
      }))
      .filter((tile) => tile.geometry && tile.url);

    if (!frameTiles.length) return;
    frames.push({
      frame_id: overviewItem.id || overviewItem.outcome_id || null,
      datetime: overviewItem.datetime || null,
      tiles: frameTiles,
    });
  });

  if (frames.length < 2) {
    throw new Error("Need 2+ selected images with visible full-resolution coverage in the current map view.");
  }

  const inputValue = Number(animateSeriesSecondsEl?.value || 0.8);
  const secondsPerFrame = Number.isFinite(inputValue) ? Math.min(10, Math.max(0.1, inputValue)) : 0.8;
  if (animateSeriesSecondsEl) animateSeriesSecondsEl.value = secondsPerFrame.toFixed(1);

  return {
    viewport_geometry: viewportGeometry,
    contract_id: selectedContractId(),
    seconds_per_frame: secondsPerFrame,
    filename_prefix: "selected_extent_animation",
    frames,
  };
}

async function pollMp4AnimationJob(jobId) {
  const res = await fetch(`${apiBase}/api/archive/animate/mp4/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "MP4 animation job status failed");

  const progress = `${Number(data.progress_current || 0)}/${Number(data.progress_total || 0)}`;
  const status = (data.status || "").toLowerCase();
  if (status === "queued") {
    setAnimateSeriesStatus(data.message || `Queued (${progress})`);
    return data;
  }
  if (status === "running") {
    setAnimateSeriesStatus(data.message || `Rendering ${progress}...`);
    return data;
  }
  if (status === "failed") {
    clearMp4JobPolling();
    state.mp4JobId = null;
    const reason = data.error || data.message || "MP4 render failed";
    setAnimateSeriesStatus(reason, true);
    throw new Error(reason);
  }
  if (status === "completed") {
    clearMp4JobPolling();
    setAnimateSeriesStatus(`MP4 ready (${Number(data.frame_count || 0)} frames). Downloading...`);
    return data;
  }
  return data;
}

async function downloadMp4AnimationJob(jobId, fileName = "") {
  const res = await fetch(`${apiBase}/api/archive/animate/mp4/jobs/${encodeURIComponent(jobId)}/download`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "MP4 download failed");
  }
  const blob = await res.blob();
  const fallback = `selected_extent_animation_${timestampTag()}.mp4`;
  triggerBlobDownload(blob, fileName || fallback);
}

async function startSelectedMp4Animation() {
  const payload = buildSelectedMp4AnimationPayload();
  setAnimateSeriesStatus(`Submitting ${payload.frames.length} frames...`);
  hideDownloadPopover();

  const res = await fetch(`${apiBase}/api/archive/animate/mp4/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Failed to queue MP4 animation");
  }

  state.mp4JobId = data.job_id;
  state.mp4JobDownloading = false;
  clearMp4JobPolling();
  setAnimateSeriesStatus(data.message || "Queued for rendering...");

  state.mp4JobTimer = window.setInterval(async () => {
    if (!state.mp4JobId) return;
    try {
      const job = await pollMp4AnimationJob(state.mp4JobId);
      if ((job.status || "").toLowerCase() === "completed" && !state.mp4JobDownloading) {
        state.mp4JobDownloading = true;
        await downloadMp4AnimationJob(state.mp4JobId, job.file_name || "");
        state.mp4JobId = null;
        setAnimateSeriesStatus("MP4 downloaded.");
        toast("Selected animation MP4 ready");
      }
    } catch (err) {
      clearMp4JobPolling();
      state.mp4JobId = null;
      state.mp4JobDownloading = false;
      setAnimateSeriesStatus(err.message || "MP4 animation failed", true);
      toast(err.message || "MP4 animation failed");
    }
  }, 1800);

  const first = await pollMp4AnimationJob(state.mp4JobId);
  if ((first.status || "").toLowerCase() === "completed" && !state.mp4JobDownloading) {
    state.mp4JobDownloading = true;
    await downloadMp4AnimationJob(state.mp4JobId, first.file_name || "");
    clearMp4JobPolling();
    state.mp4JobId = null;
    setAnimateSeriesStatus("MP4 downloaded.");
    toast("Selected animation MP4 ready");
  } else {
    toast("MP4 render started in background");
  }
}

async function compareSelection() {
  const payload = {
    before_item_id: beforeSelectEl.value,
    after_item_id: afterSelectEl.value,
    contract_id: selectedContractId(),
  };

  const res = await fetch(`${apiBase}/api/archive/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Comparison failed");

  beforeImgEl.src = assetProxyUrl(data.before.url || "");
  afterImgEl.src = assetProxyUrl(data.after.url || "");
  toast("Comparison pair loaded");
}

async function generateReport() {
  if (!state.currentAoi) {
    state.currentAoi = bboxFromCenter(Number(latEl.value), Number(lonEl.value), Number(widthKmEl.value));
  }
  state.currentAoi = normalizeGeometryLongitudes(state.currentAoi);

  const payload = {
    geometry: state.currentAoi,
    start_date: isoDate(startDateEl.value),
    end_date: isoDate(endDateEl.value),
    prompt: geoPromptEl.value.trim() || "Summarize notable temporal activity in this AOI.",
    latest_item_id: afterSelectEl.value || null,
    collection_id: collectionEl.value.trim() || "l1d-sr",
    contract_id: selectedContractId(),
    satellite_name: (satelliteNameEl.value || "").trim() || null,
    min_gsd: parseOptionalNumber(minGsdEl.value),
    max_gsd: parseOptionalNumber(maxGsdEl.value),
    max_frames: 12,
  };

  reportOutEl.textContent = "Generating report...";
  const res = await fetch(`${apiBase}/api/geoagent/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();

  if (!res.ok) {
    reportOutEl.textContent = data.detail || "Geoagent failed.";
    throw new Error(data.detail || "Geoagent failed");
  }

  reportOutEl.textContent = data.report_markdown;
  toast(`Report generated with ${data.frame_count} frames`);
}

async function runSearchAnimation() {
  if (!state.animationGeometry) {
    throw new Error("Animation AOI missing. Draw a rectangle first.");
  }
  state.animationGeometry = normalizeGeometryLongitudes(state.animationGeometry);

  const payload = compactObject({
    geometry: state.animationGeometry,
    start_date: isoDate(animStartDateEl.value),
    end_date: isoDate(animEndDateEl.value),
    collection_id: "l1d-sr",
    contract_id: selectedContractId(),
    max_cloud_cover: parseOptionalNumber(animMaxCloudEl.value),
    satellite_name: (animSatelliteEl.value || "").trim() || null,
    min_gsd: parseOptionalNumber(animMinGsdEl.value),
    max_gsd: parseOptionalNumber(animMaxGsdEl.value),
    max_frames: Number(animMaxFramesEl.value || 20),
    seconds_per_frame: Number(animSecPerFrameEl.value || 0.8),
  });

  const res = await fetch(`${apiBase}/api/archive/animate/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Animation generation failed");
  }
  if (!data.created || !data.gif_base64) {
    throw new Error(data.reason || "Animation was not created");
  }

  openAnimationWindow(data.gif_base64, "satellogic_capture_animation.gif");
  toast(`Animation created (${data.frame_count} frames)`);
}

async function saveAnnotation() {
  const note = annotationNoteEl.value.trim();
  if (!note) {
    toast("Add a note before saving annotation");
    return;
  }

  const geometry = state.lastDrawnGeometry || state.currentAoi;
  if (!geometry) {
    toast("Draw a geometry or run a search first");
    return;
  }

  const payload = {
    note,
    geometry: normalizeGeometryLongitudes(geometry),
    label: "analyst-note",
    aoi_name: "default",
  };

  const res = await fetch(`${apiBase}/api/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Annotation save failed");

  toast("Annotation saved");
}

async function loadAnnotations() {
  const res = await fetch(`${apiBase}/api/annotations`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Failed to load annotations");

  const geo = L.geoJSON(data, {
    style: { color: "#0c7b63", weight: 2, fillOpacity: 0.1 },
    pointToLayer: (_, latlng) => L.circleMarker(latlng, { radius: 5, color: "#0c7b63", fillOpacity: 0.8 }),
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindPopup(`<strong>${p.label || "annotation"}</strong><br/>${p.note || ""}`);
    },
  });
  geo.addTo(map);
  toast("Annotations loaded");
}

async function loadContracts() {
  contractSelectEl.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Default contract";
  contractSelectEl.appendChild(placeholder);

  try {
    const res = await fetch(`${apiBase}/api/contracts`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load contracts");

    (data.contracts || []).forEach((contract) => {
      const opt = document.createElement("option");
      opt.value = contract.id;
      opt.textContent = contract.name ? `${contract.name} (${contract.id})` : contract.id;
      contractSelectEl.appendChild(opt);
    });

    if (data.default_contract_id) {
      contractSelectEl.value = data.default_contract_id;
    }
    toast(`Contracts loaded: ${data.count}`);
  } catch (err) {
    toast(`Contracts unavailable: ${err.message}`);
  }
}

async function loadCollections() {
  const previous = (collectionEl.value || "").trim();
  collectionEl.innerHTML = "";
  try {
    const params = new URLSearchParams();
    const contractId = selectedContractId();
    if (contractId) params.set("contract_id", contractId);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const res = await fetch(`${apiBase}/api/collections${suffix}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load collections");

    const collections = Array.isArray(data.collections) ? data.collections : [];
    collections.forEach((collection) => {
      const opt = document.createElement("option");
      opt.value = collection.id;
      const title = (collection.title || "").trim();
      opt.textContent = title && title !== collection.id ? `${title} (${collection.id})` : collection.id;
      collectionEl.appendChild(opt);
    });

    const fallbackId = data.default_collection_id || "l1d-sr";
    const candidate = previous || fallbackId;
    const hasCandidate = collections.some((c) => c.id === candidate);
    if (hasCandidate) collectionEl.value = candidate;
    else if (collections.length) collectionEl.value = collections[0].id;
    else {
      const opt = document.createElement("option");
      opt.value = fallbackId;
      opt.textContent = fallbackId;
      collectionEl.appendChild(opt);
      collectionEl.value = fallbackId;
    }
  } catch (err) {
    const fallbackId = previous || "l1d-sr";
    const opt = document.createElement("option");
    opt.value = fallbackId;
    opt.textContent = fallbackId;
    collectionEl.appendChild(opt);
    collectionEl.value = fallbackId;
    toast(`Collections unavailable: ${err.message}`);
  }
}

mapLocateFormEl?.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  try {
    await runLocationSearch();
  } catch (err) {
    toast(err.message || "Location search failed");
  }
});

mapLocateHistoryBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  toggleLocationHistoryMenu();
});

mapLocateInputEl?.addEventListener("input", () => {
  if (!mapLocateHistoryEl?.classList.contains("open")) return;
  renderLocationHistoryMenu();
});

mapLocateInputEl?.addEventListener("focus", () => {
  if ((mapLocateInputEl.value || "").trim()) return;
  showLocationHistoryMenu();
});

mapLocateInputEl?.addEventListener("keydown", (evt) => {
  if (evt.key === "ArrowDown") {
    evt.preventDefault();
    showLocationHistoryMenu();
    const first = mapLocateHistoryEl?.querySelector(".map-locate-history-item");
    if (first instanceof HTMLElement) first.focus();
  }
});

mapLocateHistoryEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
});

document.getElementById("searchBtn").addEventListener("click", async () => {
  try {
    await searchArchive();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("stackBtn").addEventListener("click", async () => {
  try {
    await discoverStacks();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("gifBtn").addEventListener("click", async () => {
  try {
    await buildGif();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("compareBtn").addEventListener("click", async () => {
  try {
    await compareSelection();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("reportBtn").addEventListener("click", async () => {
  try {
    await generateReport();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("saveAnnotationBtn").addEventListener("click", async () => {
  try {
    await saveAnnotation();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("loadAnnotationBtn").addEventListener("click", async () => {
  try {
    await loadAnnotations();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("playBtn").addEventListener("click", () => {
  if (!state.items.length) return;
  if (state.playTimer) clearInterval(state.playTimer);
  state.playTimer = setInterval(() => {
    const next = (Number(timelineEl.value) + 1) % state.items.length;
    showFrame(next);
  }, 900);
});

document.getElementById("pauseBtn").addEventListener("click", () => {
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
});

compareSliderEl.addEventListener("input", () => {
  beforeClipEl.style.width = `${compareSliderEl.value}%`;
});

timelineEl.addEventListener("input", () => {
  showFrame(Number(timelineEl.value));
});

frameSelectEl.addEventListener("change", () => {
  const selected = Array.from(frameSelectEl.selectedOptions);
  if (selected.length) {
    const id = selected[selected.length - 1].value;
    const idx = state.items.findIndex((item) => item.id === id);
    if (idx >= 0) showFrame(idx);
  }
});

map.on("zoomend moveend", () => {
  if (!state.searchParams) return;
  if (state.skipMapRefreshEvents > 0) {
    state.skipMapRefreshEvents -= 1;
    return;
  }
  scheduleMapRefresh();
});

map.on("move zoom", () => {
  updateMapStatus();
});

compareRangeEl.addEventListener("input", () => {
  applyCompareFrameAt(Math.round(Number(compareRangeEl.value || 0)));
});

compareStepUpBtnEl?.addEventListener("click", () => {
  stepCompareBy(1);
});

compareStepDownBtnEl?.addEventListener("click", () => {
  stepCompareBy(-1);
});

lockSelectionBtnEl.addEventListener("click", async () => {
  if (state.selectedCarouselIds.size === 0) {
    updateLockButtonState();
    return;
  }
  state.selectedCarouselIds.clear();
  state.selectedCarouselId = null;
  syncCarouselCheckboxes();
  if (state.compareMode) setCompareMode(false);
  await refreshMapMode(false);
  toast("Selections cleared");
});

compareModeBtnEl.addEventListener("click", () => {
  if (!state.overviewItems.length) {
    toast("Run a search first");
    return;
  }
  setCompareMode(!state.compareMode);
});

animateSeriesBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideDownloadPopover();
  toggleAnimateSeriesPopover();
});

animateSeriesRunBtnEl?.addEventListener("click", async (evt) => {
  evt.stopPropagation();
  try {
    await startSelectedMp4Animation();
  } catch (err) {
    setAnimateSeriesStatus(err.message || "MP4 animation failed", true);
    toast(err.message || "MP4 animation failed");
  }
});

animateSeriesCloseBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideAnimateSeriesPopover();
});

animateSeriesPopoverEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
});

downloadMenuBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideAnimateSeriesPopover();
  toggleDownloadPopover();
});

downloadOutcomeCsvBtnEl?.addEventListener("click", async (evt) => {
  evt.stopPropagation();
  try {
    await downloadSelectedOutcomeCsv();
  } catch (err) {
    toast(err.message);
  } finally {
    hideDownloadPopover();
  }
});

downloadVisibleQuickviewBtnEl?.addEventListener("click", async (evt) => {
  evt.stopPropagation();
  try {
    await downloadVisibleQuickviewTiles();
  } catch (err) {
    toast(err.message);
  } finally {
    hideDownloadPopover();
  }
});

downloadVisibleL1dBtnEl?.addEventListener("click", async (evt) => {
  evt.stopPropagation();
  try {
    await downloadVisibleL1dSrTiles();
  } catch (err) {
    toast(err.message);
  } finally {
    hideDownloadPopover();
  }
});

map.on("contextmenu", (evt) => {
  const p = evt.containerPoint;
  showContextMenu(p.x, p.y, evt.latlng);
});

map.on("click", () => {
  hideContextMenu();
  hideLocationHistoryMenu();
  hideAnimateSeriesPopover();
  hideDownloadPopover();
});

document.addEventListener("click", (evt) => {
  if (mapLocateEl && !mapLocateEl.contains(evt.target)) hideLocationHistoryMenu();
  if (!mapContextMenuEl.contains(evt.target)) hideContextMenu();
  if (animateSeriesPopoverEl && animateSeriesBtnEl) {
    const target = evt.target;
    if (!animateSeriesPopoverEl.contains(target) && !animateSeriesBtnEl.contains(target)) hideAnimateSeriesPopover();
  }
  if (downloadPopoverEl && downloadMenuBtnEl) {
    const target = evt.target;
    if (!downloadPopoverEl.contains(target) && !downloadMenuBtnEl.contains(target)) hideDownloadPopover();
  }
});

document.addEventListener("keydown", (evt) => {
  if (evt.key === "Escape") {
    hideLocationHistoryMenu();
    hideAnimateSeriesPopover();
    hideDownloadPopover();
  }
});

ctxCreateAnimationEl.addEventListener("click", () => {
  hideContextMenu();
  state.pendingAnimationDraw = true;
  toast("Draw a rectangle AOI for animation");
});

ctxCopyLatLonEl.addEventListener("click", async () => {
  hideContextMenu();
  if (!state.contextMenuLatLng) {
    toast("No map coordinate to copy");
    return;
  }
  const value = formatLatLon(state.contextMenuLatLng);
  try {
    await navigator.clipboard.writeText(value);
    toast(`Copied ${value}`);
  } catch (_) {
    toast(`Clipboard unavailable: ${value}`);
  }
});

ctxTaskImageEl.addEventListener("click", () => {
  hideContextMenu();
  toast("Task New Image: coming next");
});

animationFormEl.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  try {
    await runSearchAnimation();
    animationDialogEl.close();
  } catch (err) {
    toast(err.message);
  }
});

contractSelectEl.addEventListener("change", () => {
  loadCollections().catch((err) => toast(err.message));
  if (!state.searchParams) return;
  state.lastDetailRequestKey = null;
  state.lastDetailCoverageBounds = null;
  state.lastDetailCoverageZoom = null;
  state.lastDetailContextKey = null;
  state.prefetchTileUrlSeen.clear();
  state.useCogTileProxy = true;
  state.tileProxyWarned = false;
  refreshMapMode(true).catch((err) => toast(err.message));
});

updateLockButtonState();
updateMapStatus();
loadLocationHistory();
if (DEBUG_NET) {
  if (mapDebugStatsEl) mapDebugStatsEl.style.display = "block";
  updateDebugStats();
  setInterval(() => {
    updateDebugStats();
  }, 4000);
} else if (mapDebugStatsEl) {
  mapDebugStatsEl.style.display = "none";
}

(async () => {
  await loadContracts();
  await loadCollections();
})();
