const apiBase = "";

const state = {
  items: [],
  overviewItems: [],
  detailItems: [],
  outlineItems: [],
  mapVectorLayer: null,
  mapThumbOverlayLayer: null,
  mapThumbMarkerLayer: null,
  stackOutlineLayer: null,
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
  contextMenuPoint: null,
  lastDetailCoverageBounds: null,
  lastDetailCoverageZoom: null,
  lastDetailContextKey: null,
  prefetchTileUrlSeen: new Set(),
  useCogTileProxy: true,
  tileProxyWarned: false,
  tileProxyErrorCount: 0,
  lastMapRenderSignature: "",
  detailLayerMode: "natural",
  carouselQuickviewCount: 0,
  carouselFilterActive: false,
  carouselVisibleItems: [],
  carouselRenderItems: [],
  carouselRenderNextIndex: 0,
  skipMapRefreshEvents: 0,
  locationHistory: [],
  mp4JobId: null,
  mp4JobTimer: null,
  mp4JobDownloading: false,
  reportRunId: null,
  reportRunTimer: null,
  reportRunDownloading: false,
  activeTab: "explore",
  taskingMode: "idle",
  taskingTargetType: null,
  taskingTargetGeometry: null,
  taskingDrawPoints: [],
  taskingSketchLine: null,
  taskingSketchFill: null,
  taskingRestoreDblClickZoom: false,
  taskingProducts: [],
  taskingProjects: [],
  taskingOrders: [],
  taskingRefreshAt: null,
  workflows: [],
  skills: [],
  providers: [],
  runs: [],
  schedules: [],
  poiSets: [],
  subscriptions: [],
  events: [],
  selectedRunId: null,
  selectedScheduleId: null,
  workflowGraph: {
    nodes: [],
    selectedNodeId: null,
    dragNodeId: null,
    dragOffsetX: 0,
    dragOffsetY: 0,
    dirty: false,
  },
  workflowBuilder: {
    popoutWindow: null,
    isDetached: false,
  },
  satellogicContractMemory: null,
  layerControl: {
    sentinelBaseEnabled: true,
    satellogicOverlayEnabled: true,
    sentinelFramesEnabled: true,
    satellogicFramesEnabled: true,
    sentinelWmtsEnabled: true,
    sentinelStacOverlayEnabled: false,
    sentinelBaseCollectionId: "sentinel-2-l2a",
    sentinelAnalyticCollections: [],
  },
  layerSearchResults: {
    sentinelBase: {
      collectionId: null,
      items: [],
      overviewItems: [],
    },
    satellogicOverlay: {
      collectionId: null,
      items: [],
      overviewItems: [],
    },
    satellogicQuickviewVisual: {
      collectionId: "quickview-visual",
      items: [],
    },
    sentinelAnalytics: {},
  },
  satellogicStripGsdByKey: new Map(),
  satellogicStripGsdCacheSig: "",
  sentinelWmtsConfig: null,
  sentinelWmtsLayer: null,
  sentinelWmtsLayerTemplate: "",
  sentinelWmtsOverlayLayers: {},
  sentinelWmtsOverlayLayerTemplates: {},
  sentinelWmtsConfigByLayerId: {},
  sentinelWmtsPlayback: {
    anchorDate: "",
    offsetWeeks: 0,
    windowDays: 7,
    refreshRevision: 0,
    lastAppliedTimeParam: "",
    lastAppliedAtMs: 0,
  },
  sourcePickerOpen: false,
  preferredActionSource: "satellogic",
  enabledSources: {
    "merlin-s2": true,
    satellogic: true,
  },
  perSourceCollections: {
    "merlin-s2": "__none__",
    satellogic: "quickview-visual",
  },
  browseTilePolicy: "latest_visible_capture_per_source",
  sourceLayerStatus: {},
  timeline: {
    centerMs: null,
    spanMs: 90 * 24 * 60 * 60 * 1000,
    events: [],
    renderedEvents: [],
    hoverX: null,
    hoverMs: null,
    hoverEvent: null,
    userAdjusted: false,
    wmtsDrag: null,
    wmtsApplyTimer: null,
  },
};

const DETAIL_ZOOM_THRESHOLD = 13;
const STACK_DISCOVERY_COLLECTION_ID = "quickview-visual-thumb";
const ZOOMED_OUT_SEARCH_MAX_ZOOM = 12;
const DETAIL_COG_HIGHRES_ZOOM = 17;
const DETAIL_COG_TILE_BUFFER = 1;
const DETAIL_FETCH_DEBOUNCE_MS = 700;
const DETAIL_FETCH_COOLDOWN_MS = 1800;
const DETAIL_MAX_VECTOR_TILES = 120;
const DETAIL_FULLRES_VISIBLE_LIMIT = 6;
const DETAIL_FETCH_PADDING = 0.35;
const DETAIL_MAX_QUERY_LIMIT = 400;
const DETAIL_TILE_BUFFER_PAD = 0.12;
const DETAIL_VISIBLE_MOSAIC_MAX_TILE_CELLS = 900;
const DETAIL_VISIBLE_MOSAIC_MAX_CLIP_BOUNDS_PER_ITEM = 24;
const DETAIL_TILE_PROXY_ERROR_THRESHOLD = 12;
const SENTINEL_WMTS_MIN_ZOOM = 10;
const COMPARE_PREFETCH_NEIGHBORS = 1;
const COMPARE_PREFETCH_TILES_PER_FRAME = 3;
const CAROUSEL_BATCH_SIZE = 24;
const CAROUSEL_SCROLL_THRESHOLD_PX = 240;
const DAY_MS = 24 * 60 * 60 * 1000;
const TIMELINE_MIN_SPAN_MS = 3 * DAY_MS;
const TIMELINE_MAX_SPAN_MS = 3650 * DAY_MS;
const TIMELINE_DEFAULT_SPAN_MS = 90 * DAY_MS;
const TIMELINE_HIT_PX = 5;
const WMTS_BAND_EDGE_HIT_PX = 8;
const WMTS_BAND_MIN_WINDOW_MS = DAY_MS;
const MP4_JOB_POLL_MS = 2500;
const REPORT_RUN_POLL_MS = 3000;
const LOCATION_HISTORY_KEY = "imageMate.locationHistory.v1";
const LOCATION_HISTORY_LIMIT = 80;
const DETAIL_LAYER_LABELS = {
  natural: "Natural Colour",
  false_color: "False Colour",
  ndvi: "NDVI",
  cloud_mask: "Cloud Mask",
};
const COLLECTION_NONE_VALUE = "__none__";

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
if (L?.drawLocal?.edit?.toolbar?.buttons) {
  L.drawLocal.edit.toolbar.buttons.edit = "Select Layers";
  L.drawLocal.edit.toolbar.buttons.editDisabled = "Select Layers";
}
window.addEventListener("resize", () => {
  map.invalidateSize();
  ensureLayerEditorControlAnchor();
  if (animateSeriesPopoverEl?.classList.contains("open")) positionAnimateSeriesPopover();
  if (generateSeriesReportPopoverEl?.classList.contains("open")) positionGenerateSeriesReportPopover();
  if (layerEditorPopoverEl?.classList.contains("open")) positionLayerEditorPopover();
  renderMapTimebar();
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
const taskingDrawLayer = L.layerGroup().addTo(map);

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

const startDateEl = document.getElementById("startDate");
const endDateEl = document.getElementById("endDate");
const maxCloudEl = document.getElementById("maxCloud");
const satelliteNameEl = document.getElementById("satelliteName");
const minGsdEl = document.getElementById("minGsd");
const maxGsdEl = document.getElementById("maxGsd");
const limitEl = document.getElementById("limit");
const sourceSelectEl = document.getElementById("sourceSelect");
const sentinelCollectionEl = document.getElementById("sentinelCollection");
const collectionEl = document.getElementById("collection");
const contractSelectEl = document.getElementById("contractSelect");
const layerSentinelBaseToggleEl = document.getElementById("layerSentinelBaseToggle");
const layerSatellogicToggleEl = document.getElementById("layerSatellogicToggle");
const layerSentinelFramesToggleEl = document.getElementById("layerSentinelFramesToggle");
const layerSatellogicFramesToggleEl = document.getElementById("layerSatellogicFramesToggle");
const layerSentinelWmtsToggleEl = document.getElementById("layerSentinelWmtsToggle");
const layerSentinelStacToggleEl = document.getElementById("layerSentinelStacToggle");
const sourcePickerBtnEl = document.getElementById("sourcePickerBtn");
const sourcePickerLabelEl = document.getElementById("sourcePickerLabel");
const sourcePickerMenuEl = document.getElementById("sourcePickerMenu");
const sentinelWmtsMetaEl = document.getElementById("sentinelWmtsMeta");
const wmtsWeekWindowMetaEl = document.getElementById("wmtsWeekWindowMeta");
const sentinelAnalyticsLayersEl = document.getElementById("sentinelAnalyticsLayers");
const sentinelAnalyticsCountEl = document.getElementById("sentinelAnalyticsCount");
const searchMetaEl = document.getElementById("searchMeta");
const frameSelectEl = document.getElementById("frameSelect");
const timelineEl = document.getElementById("timeline");
const framePreviewEl = document.getElementById("framePreview");
const beforeSelectEl = document.getElementById("beforeSelect");
const afterSelectEl = document.getElementById("afterSelect");
const beforeClipEl = document.getElementById("beforeClip");
const compareSliderEl = document.getElementById("compareSlider");
const timeCarouselListEl = document.getElementById("timeCarouselList");
const searchResultsCountEl = document.getElementById("searchResultsCount");
const searchResultsFilterMetaEl = document.getElementById("searchResultsFilterMeta");
const mapStatusEl = document.getElementById("mapStatus");
const mapDebugStatsEl = document.getElementById("mapDebugStats");
const mapTimebarEl = document.getElementById("mapTimebar");
const mapTimebarCanvasEl = document.getElementById("mapTimebarCanvas");
const mapTimebarTooltipEl = document.getElementById("mapTimebarTooltip");
const mapTimebarPageBackBtnEl = document.getElementById("mapTimebarPageBackBtn");
const mapTimebarDayBackBtnEl = document.getElementById("mapTimebarDayBackBtn");
const mapTimebarDayForwardBtnEl = document.getElementById("mapTimebarDayForwardBtn");
const mapTimebarPageForwardBtnEl = document.getElementById("mapTimebarPageForwardBtn");
const mapTimebarCenterInputEl = document.getElementById("mapTimebarCenterInput");
const mapTimebarCenterBtnEl = document.getElementById("mapTimebarCenterBtn");
const tilePerfHudEl = document.getElementById("tilePerfHud");
const tilePerfNewSatEl = document.getElementById("tilePerfNewSat");
const tilePerfMerlinEl = document.getElementById("tilePerfMerlin");
const mapLocateEl = document.getElementById("mapLocate");
const mapLocateFormEl = document.getElementById("mapLocateForm");
const mapLocateInputEl = document.getElementById("mapLocateInput");
const mapLocateHistoryBtnEl = document.getElementById("mapLocateHistoryBtn");
const mapLocateHistoryEl = document.getElementById("mapLocateHistory");
const mapContextMenuEl = document.getElementById("mapContextMenu");
const ctxCopyLatLonEl = document.getElementById("ctxCopyLatLon");
const ctxCreateAnimationEl = document.getElementById("ctxCreateAnimation");
const ctxTaskImageEl = document.getElementById("ctxTaskImage");
const taskingTypeMenuEl = document.getElementById("taskingTypeMenu");
const taskingTypePointEl = document.getElementById("taskingTypePoint");
const taskingTypeAreaEl = document.getElementById("taskingTypeArea");
const taskingFormPopoverEl = document.getElementById("taskingFormPopover");
const taskingFormTitleEl = document.getElementById("taskingFormTitle");
const taskingGeometryHintEl = document.getElementById("taskingGeometryHint");
const taskingFormEl = document.getElementById("taskingForm");
const taskingOrderNameEl = document.getElementById("taskingOrderName");
const taskingProjectNameEl = document.getElementById("taskingProjectName");
const taskingProductEl = document.getElementById("taskingProduct");
const taskingStartEl = document.getElementById("taskingStart");
const taskingEndEl = document.getElementById("taskingEnd");
const taskingCadenceLabelEl = document.getElementById("taskingCadenceLabel");
const taskingCadenceEl = document.getElementById("taskingCadence");
const taskingCancelBtnEl = document.getElementById("taskingCancelBtn");
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
let layerEditorBtnEl = null;
const layerEditorPopoverEl = document.getElementById("layerEditorPopover");
const layerEditorSelectEl = document.getElementById("layerEditorSelect");
const compareRailEl = document.getElementById("compareRail");
const compareRangeEl = document.getElementById("compareRange");
const compareDateTagEl = document.getElementById("compareDateTag");
const compareStepUpBtnEl = document.getElementById("compareStepUpBtn");
const compareStepDownBtnEl = document.getElementById("compareStepDownBtn");
const animateSeriesBtnEl = document.getElementById("animateSeriesBtn");
const animateSeriesPopoverEl = document.getElementById("animateSeriesPopover");
const animateSeriesSecondsEl = document.getElementById("animateSeriesSeconds");
const animateSeriesLoopEl = document.getElementById("animateSeriesLoop");
const animateSeriesRunBtnEl = document.getElementById("animateSeriesRunBtn");
const animateSeriesCloseBtnEl = document.getElementById("animateSeriesCloseBtn");
const animateSeriesStatusEl = document.getElementById("animateSeriesStatus");
const generateSeriesReportBtnEl = document.getElementById("generateSeriesReportBtn");
const generateSeriesReportPopoverEl = document.getElementById("generateSeriesReportPopover");
const generateSeriesReportWorkflowEl = document.getElementById("generateSeriesReportWorkflow");
const generateSeriesReportPromptEl = document.getElementById("generateSeriesReportPrompt");
const generateSeriesReportRunBtnEl = document.getElementById("generateSeriesReportRunBtn");
const generateSeriesReportCloseBtnEl = document.getElementById("generateSeriesReportCloseBtn");
const generateSeriesReportStatusEl = document.getElementById("generateSeriesReportStatus");
const downloadMenuBtnEl = document.getElementById("downloadMenuBtn");
const downloadPopoverEl = document.getElementById("downloadPopover");
const downloadOutcomeCsvBtnEl = document.getElementById("downloadOutcomeCsvBtn");
const downloadVisibleQuickviewBtnEl = document.getElementById("downloadVisibleQuickviewBtn");
const downloadVisibleL1dBtnEl = document.getElementById("downloadVisibleL1dBtn");
const downloadCopiedTipEl = document.getElementById("downloadCopiedTip");
const lockIconEl = lockSelectionBtnEl?.querySelector(".lock-icon");
const rightPanelTitleEl = document.getElementById("rightPanelTitle");
const workbenchTabsEl = document.getElementById("workbenchTabs");
const leftExploreViewEl = document.getElementById("leftExploreView");
const leftTaskingViewEl = document.getElementById("leftTaskingView");
const leftWorkflowsViewEl = document.getElementById("leftWorkflowsView");
const leftSchedulesViewEl = document.getElementById("leftSchedulesView");
const leftRunsViewEl = document.getElementById("leftRunsView");
const taskingRefreshBtnEl = document.getElementById("taskingRefreshBtn");
const taskingOrdersMetaEl = document.getElementById("taskingOrdersMeta");
const taskingOrdersListEl = document.getElementById("taskingOrdersList");
const taskingProjectSuggestionsEl = document.getElementById("taskingProjectSuggestions");
const workflowSelectEl = document.getElementById("workflowSelect");
const workflowUseViewportEl = document.getElementById("workflowUseViewport");
const workflowUseSelectedEl = document.getElementById("workflowUseSelected");
const workflowPoiSetSelectEl = document.getElementById("workflowPoiSetSelect");
const workflowParamsJsonEl = document.getElementById("workflowParamsJson");
const workflowRunBtnEl = document.getElementById("workflowRunBtn");
const workflowRefreshBtnEl = document.getElementById("workflowRefreshBtn");
const workflowMetaEl = document.getElementById("workflowMeta");
const workflowBuilderHostEl = document.getElementById("workflowBuilderHost");
const workflowBuilderDockEl = document.getElementById("workflowBuilderDock");
const workflowBuilderPopoutBtnEl = document.getElementById("workflowBuilderPopoutBtn");
const workflowBuilderDockBtnEl = document.getElementById("workflowBuilderDockBtn");
const workflowBuilderIdEl = document.getElementById("workflowBuilderId");
const workflowBuilderVersionEl = document.getElementById("workflowBuilderVersion");
const workflowBuilderDefaultsEl = document.getElementById("workflowBuilderDefaults");
const workflowBuilderSkillSelectEl = document.getElementById("workflowBuilderSkillSelect");
const workflowBuilderNodeIdEl = document.getElementById("workflowBuilderNodeId");
const workflowBuilderAddNodeBtnEl = document.getElementById("workflowBuilderAddNodeBtn");
const workflowBuilderAutoLayoutBtnEl = document.getElementById("workflowBuilderAutoLayoutBtn");
const workflowBuilderRemoveNodeBtnEl = document.getElementById("workflowBuilderRemoveNodeBtn");
const workflowBuilderEdgeFromEl = document.getElementById("workflowBuilderEdgeFrom");
const workflowBuilderEdgeToEl = document.getElementById("workflowBuilderEdgeTo");
const workflowBuilderAddEdgeBtnEl = document.getElementById("workflowBuilderAddEdgeBtn");
const workflowBuilderRemoveEdgeBtnEl = document.getElementById("workflowBuilderRemoveEdgeBtn");
const workflowBuilderCanvasWrapEl = document.getElementById("workflowBuilderCanvasWrap");
const workflowBuilderEdgesEl = document.getElementById("workflowBuilderEdges");
const workflowBuilderCanvasEl = document.getElementById("workflowBuilderCanvas");
const workflowBuilderJsonEl = document.getElementById("workflowBuilderJson");
const workflowBuilderApplyJsonBtnEl = document.getElementById("workflowBuilderApplyJsonBtn");
const workflowBuilderLoadSelectedBtnEl = document.getElementById("workflowBuilderLoadSelectedBtn");
const workflowBuilderSaveBtnEl = document.getElementById("workflowBuilderSaveBtn");
const workflowBuilderMetaEl = document.getElementById("workflowBuilderMeta");
const workflowBuilderSelectedNodeIdEl = document.getElementById("workflowBuilderSelectedNodeId");
const workflowBuilderSelectedNodeSkillEl = document.getElementById("workflowBuilderSelectedNodeSkill");
const workflowBuilderApplyNodeBtnEl = document.getElementById("workflowBuilderApplyNodeBtn");
const scheduleTypeEl = document.getElementById("scheduleType");
const scheduleWorkflowSelectEl = document.getElementById("scheduleWorkflowSelect");
const scheduleCronEl = document.getElementById("scheduleCron");
const scheduleIntervalSecondsEl = document.getElementById("scheduleIntervalSeconds");
const scheduleSubscriptionSelectEl = document.getElementById("scheduleSubscriptionSelect");
const scheduleMaxScenesEl = document.getElementById("scheduleMaxScenes");
const scheduleCreateBtnEl = document.getElementById("scheduleCreateBtn");
const scheduleRefreshBtnEl = document.getElementById("scheduleRefreshBtn");
const scheduleSelectEl = document.getElementById("scheduleSelect");
const scheduleEnableBtnEl = document.getElementById("scheduleEnableBtn");
const scheduleDisableBtnEl = document.getElementById("scheduleDisableBtn");
const scheduleListOutEl = document.getElementById("scheduleListOut");
const poiSetNameEl = document.getElementById("poiSetName");
const poiSetGeoJsonEl = document.getElementById("poiSetGeoJson");
const poiSetCreateBtnEl = document.getElementById("poiSetCreateBtn");
const subscriptionPoiSetSelectEl = document.getElementById("subscriptionPoiSetSelect");
const subscriptionGeometryEl = document.getElementById("subscriptionGeometry");
const subscriptionCreateBtnEl = document.getElementById("subscriptionCreateBtn");
const runsRefreshBtnEl = document.getElementById("runsRefreshBtn");
const runsSelectEl = document.getElementById("runsSelect");
const runInspectorOutEl = document.getElementById("runInspectorOut");
const runEventsOutEl = document.getElementById("runEventsOut");

const today = new Date();
const oneMonthAgo = new Date(today);
const originalDay = oneMonthAgo.getDate();
oneMonthAgo.setDate(1);
oneMonthAgo.setMonth(oneMonthAgo.getMonth() - 1);
const daysInTargetMonth = new Date(oneMonthAgo.getFullYear(), oneMonthAgo.getMonth() + 1, 0).getDate();
oneMonthAgo.setDate(Math.min(originalDay, daysInTargetMonth));
startDateEl.value = oneMonthAgo.toISOString().slice(0, 10);
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

function normalizeSourceId(value) {
  const source = (value || "").toString().trim().toLowerCase();
  if (!source) return "satellogic";
  if (source === "satl") return "satellogic";
  if (source === "merlin" || source === "s2" || source === "sentinel-2" || source === "cdse") return "merlin-s2";
  return source;
}

function sourceSelectForId(sourceId) {
  return normalizeSourceId(sourceId) === "merlin-s2" ? sentinelCollectionEl : collectionEl;
}

function defaultCollectionForSource(sourceId) {
  return normalizeSourceId(sourceId) === "merlin-s2" ? "sentinel-2-l2a" : "quickview-visual";
}

function syncEnabledSourcesFromLayerControl() {
  state.enabledSources = {
    ...state.enabledSources,
    "merlin-s2": Boolean(state.layerControl.sentinelBaseEnabled),
    satellogic: Boolean(state.layerControl.satellogicOverlayEnabled),
  };
}

function isSourceEnabled(sourceId) {
  const normalized = normalizeSourceId(sourceId);
  syncEnabledSourcesFromLayerControl();
  return Boolean(state.enabledSources[normalized]);
}

function enabledSourceIds() {
  syncEnabledSourcesFromLayerControl();
  return ["merlin-s2", "satellogic"].filter((sourceId) => Boolean(state.enabledSources[sourceId]));
}

function setPreferredActionSource(sourceId) {
  const normalized = normalizeSourceId(sourceId);
  state.preferredActionSource = normalized;
  if (sourceSelectEl) sourceSelectEl.value = normalized;
}

function selectedSourceId() {
  const preferred = normalizeSourceId(state.preferredActionSource || sourceSelectEl?.value || "satellogic");
  if (isSourceEnabled(preferred)) return preferred;
  const enabled = enabledSourceIds();
  if (enabled.length) return enabled[0];
  return preferred || "satellogic";
}

function isSatellogicSource() {
  return selectedSourceId() === "satellogic";
}

function collectionForSource(sourceId, options = {}) {
  const allowNone = Boolean(options.allowNone);
  const normalized = normalizeSourceId(sourceId);
  const selectEl = sourceSelectForId(normalized);
  const uiValue = (selectEl?.value || "").trim();
  if (uiValue) {
    state.perSourceCollections[normalized] = uiValue;
    if (uiValue === COLLECTION_NONE_VALUE) return allowNone ? "" : defaultCollectionForSource(normalized);
    if (normalized === "merlin-s2") state.layerControl.sentinelBaseCollectionId = uiValue;
    return uiValue;
  }
  const stored = (state.perSourceCollections[normalized] || "").trim();
  if (stored) {
    if (stored === COLLECTION_NONE_VALUE) return allowNone ? "" : defaultCollectionForSource(normalized);
    return stored;
  }
  if (normalized === "merlin-s2") {
    const base = (state.layerControl.sentinelBaseCollectionId || "").trim();
    if (base) return base;
  }
  return defaultCollectionForSource(normalized);
}

function setCollectionForSource(sourceId, collectionId, updateUi = true) {
  const normalized = normalizeSourceId(sourceId);
  const fallback = defaultCollectionForSource(normalized);
  const requested = (collectionId || "").toString().trim();
  const value = requested === COLLECTION_NONE_VALUE ? COLLECTION_NONE_VALUE : (requested || fallback);
  state.perSourceCollections[normalized] = value;
  if (normalized === "merlin-s2" && value !== COLLECTION_NONE_VALUE) state.layerControl.sentinelBaseCollectionId = value;
  if (updateUi) {
    const selectEl = sourceSelectForId(normalized);
    if (selectEl) selectEl.value = value;
  }
}

function selectedSatellogicContractId() {
  if (isSourceEnabled("satellogic")) {
    const value = (contractSelectEl?.value || "").trim();
    if (value) {
      state.satellogicContractMemory = value;
      return value;
    }
  }
  return state.satellogicContractMemory || null;
}

function sourceIdForItem(item) {
  const rawExplicit = (item?.source_id || "").toString().trim();
  if (rawExplicit) return normalizeSourceId(rawExplicit);
  const itemId = (item?.id || "").toString();
  const colon = itemId.indexOf(":");
  if (colon > 0) {
    const prefix = itemId.slice(0, colon);
    return normalizeSourceId(prefix);
  }
  const collectionId = (item?.collection || "").toString().trim().toLowerCase();
  if (collectionId.startsWith("sentinel-2")) return "merlin-s2";
  const visual = (item?.assets?.visual || "").toString().toLowerCase();
  if (visual.includes("copernicus") || visual.includes("dataspace")) return "merlin-s2";
  return "satellogic";
}

function isSatellogicItem(item) {
  return sourceIdForItem(item) === "satellogic";
}

function isSentinelItem(item) {
  return sourceIdForItem(item) === "merlin-s2";
}

function isSentinelAnalyticItem(item) {
  if (!isSentinelItem(item)) return false;
  const collectionId = (item?.collection || "").toString().trim().toLowerCase();
  const baseId = (state.layerControl.sentinelBaseCollectionId || "").toString().trim().toLowerCase();
  return Boolean(collectionId && baseId && collectionId !== baseId);
}

function overlayPriority(item) {
  if (isSatellogicItem(item)) return 30;
  if (isSentinelAnalyticItem(item)) return 20;
  if (isSentinelItem(item)) return 10;
  return 0;
}

function activeCollectionId() {
  return collectionForSource(selectedSourceId());
}

function selectedContractId() {
  if (!isSourceEnabled("satellogic")) return null;
  return selectedSatellogicContractId();
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
}

function buildSearchPayloadForSource(geometry, sourceId, collectionOverride = null, limitOverride = null) {
  const normalizedGeometry = normalizeGeometryLongitudes(geometry);
  const normalizedSource = normalizeSourceId(sourceId);
  const fallbackCollection = defaultCollectionForSource(normalizedSource);
  const parsedLimit = Number(limitOverride ?? limitEl.value);
  const limit = Number.isFinite(parsedLimit) && parsedLimit > 0 ? Math.floor(parsedLimit) : 250;
  const collectionId = (collectionOverride || collectionForSource(normalizedSource) || fallbackCollection).toString().trim() || fallbackCollection;
  return compactObject({
    geometry: normalizedGeometry,
    start_date: isoDate(startDateEl.value),
    end_date: isoDate(endDateEl.value),
    source_id: normalizedSource,
    collection_id: collectionId,
    contract_id: normalizedSource === "satellogic" ? selectedSatellogicContractId() : null,
    limit,
    max_cloud_cover: parseOptionalNumber(maxCloudEl.value),
    satellite_name: (satelliteNameEl.value || "").trim() || null,
    min_gsd: parseOptionalNumber(minGsdEl.value),
    max_gsd: parseOptionalNumber(maxGsdEl.value),
  });
}

function buildSearchPayload(geometry, collectionOverride = null, limitOverride = null) {
  return buildSearchPayloadForSource(geometry, selectedSourceId(), collectionOverride || activeCollectionId(), limitOverride);
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

function normalizeDetailLayerMode(value) {
  const mode = (value || "").toString().trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(DETAIL_LAYER_LABELS, mode) ? mode : "natural";
}

function detailLayerLabel(mode = state.detailLayerMode) {
  const normalized = normalizeDetailLayerMode(mode);
  return DETAIL_LAYER_LABELS[normalized] || DETAIL_LAYER_LABELS.natural;
}

function resetLayerSearchResults() {
  state.layerSearchResults = {
    sentinelBase: {
      collectionId: state.layerControl.sentinelBaseCollectionId || null,
      items: [],
      overviewItems: [],
    },
    satellogicOverlay: {
      collectionId: "l1d-sr",
      items: [],
      overviewItems: [],
    },
    satellogicQuickviewVisual: {
      collectionId: "quickview-visual",
      items: [],
    },
    sentinelAnalytics: {},
  };
  state.satellogicStripGsdByKey = new Map();
  state.satellogicStripGsdCacheSig = "";
}

function enabledSentinelAnalyticCollectionIds() {
  return (state.layerControl.sentinelAnalyticCollections || [])
    .filter((row) => row?.enabled)
    .map((row) => row.id)
    .filter(Boolean);
}

function sentinelWmtsAnalyticTitle(layerId) {
  const raw = (layerId || "").toString().trim();
  if (!raw) return "";
  return raw
    .toLowerCase()
    .split("-")
    .map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : ""))
    .join(" ");
}

function setSentinelWmtsAnalyticLayers(config) {
  const priorEnabled = new Set(enabledSentinelAnalyticCollectionIds());
  const available = Array.isArray(config?.available_layers) ? config.available_layers : [];
  const baseLayerId = (config?.layer_id || "").trim();
  const rows = available
    .map((row) => (row || "").toString().trim())
    .filter(Boolean)
    .filter((row) => row !== baseLayerId)
    .map((row) => ({
      id: row,
      title: sentinelWmtsAnalyticTitle(row),
      enabled: priorEnabled.has(row),
    }));
  state.layerControl.sentinelAnalyticCollections = rows;
}

function isoDayStringUTC(dateObj) {
  const d = dateObj instanceof Date ? dateObj : new Date(dateObj);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function normalizeIsoDay(value) {
  const raw = (value || "").toString().trim();
  if (!raw) return "";
  const day = raw.slice(0, 10);
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "";
  return isoDayStringUTC(parsed);
}

function shiftIsoDayByDays(isoDay, days) {
  const normalized = normalizeIsoDay(isoDay);
  if (!normalized) return "";
  const parsed = new Date(`${normalized}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + Number(days || 0));
  return isoDayStringUTC(parsed);
}

function wmtsPlaybackAnchorDay() {
  const fromState = normalizeIsoDay(state.sentinelWmtsPlayback?.anchorDate || "");
  if (fromState) return fromState;
  const fromConfig = normalizeIsoDay(state.sentinelWmtsConfig?.default_time || "");
  if (fromConfig) return fromConfig;
  return isoDayStringUTC(new Date());
}

function wmtsPlaybackWindow() {
  const anchor = wmtsPlaybackAnchorDay();
  const offsetWeeks = Math.max(0, Number(state.sentinelWmtsPlayback?.offsetWeeks || 0));
  const end = shiftIsoDayByDays(anchor, -(offsetWeeks * 7));
  const days = Math.max(1, Number(state.sentinelWmtsPlayback?.windowDays || 7));
  const start = shiftIsoDayByDays(end, -(days - 1));
  const rangeParam = `${start}/${end}`;
  // Use latest day only for WMTS tile requests (test mode).
  const timeParam = end;
  return { anchor, start, end, timeParam, rangeParam, offsetWeeks };
}

function wmtsPlaybackWindowMs() {
  const { start, end } = wmtsPlaybackWindow();
  const startMs = toValidMs(`${start}T00:00:00Z`);
  const endInclusiveMs = toValidMs(`${end}T00:00:00Z`);
  const endExclusiveMs = Number.isFinite(endInclusiveMs) ? endInclusiveMs + DAY_MS : Number.NaN;
  return { startMs, endExclusiveMs };
}

function scheduleWmtsLayerRefresh() {
  if (state.timeline.wmtsApplyTimer) clearTimeout(state.timeline.wmtsApplyTimer);
  state.timeline.wmtsApplyTimer = setTimeout(() => {
    state.timeline.wmtsApplyTimer = null;
    applySentinelWmtsLayer();
    applySentinelWmtsAnalyticLayers().catch((err) => toast(err.message || "WMTS playback update failed"));
  }, 80);
}

function setWmtsPlaybackWindowFromMs(startMs, endExclusiveMs) {
  if (!Number.isFinite(startMs) || !Number.isFinite(endExclusiveMs)) return;
  const safeEndExclusive = Math.max(startMs + WMTS_BAND_MIN_WINDOW_MS, endExclusiveMs);
  const startDay = utcDayStartMs(startMs);
  const endExclusiveDay = utcDayStartMs(safeEndExclusive);
  const minEndExclusiveDay = startDay + DAY_MS;
  const normalizedEndExclusive = Math.max(minEndExclusiveDay, endExclusiveDay);
  const currentWindow = wmtsPlaybackWindowMs();
  if (
    Number.isFinite(currentWindow.startMs)
    && Number.isFinite(currentWindow.endExclusiveMs)
    && currentWindow.startMs === startDay
    && currentWindow.endExclusiveMs === normalizedEndExclusive
  ) {
    renderMapTimebar();
    return;
  }
  const windowDays = Math.max(1, Math.round((normalizedEndExclusive - startDay) / DAY_MS));
  const endInclusiveDayMs = normalizedEndExclusive - 1;
  state.sentinelWmtsPlayback.windowDays = windowDays;
  state.sentinelWmtsPlayback.anchorDate = isoDayStringUTC(new Date(endInclusiveDayMs));
  state.sentinelWmtsPlayback.offsetWeeks = 0;
  state.sentinelWmtsPlayback.refreshRevision = Number(state.sentinelWmtsPlayback.refreshRevision || 0) + 1;
  updateSentinelWmtsPlaybackUi();
  renderMapTimebar();
  scheduleWmtsLayerRefresh();
}

function wmtsTemplateWithPlaybackTime(templateUrl) {
  if (!templateUrl) return "";
  const { timeParam } = wmtsPlaybackWindow();
  const cleaned = templateUrl
    .replace(/([?&])TIME=[^&]*/ig, "$1")
    .replace(/([?&])time=[^&]*/g, "$1")
    .replace(/([?&])wmts_rev=[^&]*/g, "$1")
    .replace(/[?&]$/, "");
  const joiner = cleaned.includes("?") ? "&" : "?";
  const encodedTime = encodeURIComponent(timeParam).replace(/%2F/gi, "/");
  const timeKey = cleaned.includes("/api/layers/sentinel/wmts/tiles/") ? "time" : "TIME";
  const revision = Number(state.sentinelWmtsPlayback?.refreshRevision || 0);
  return `${cleaned}${joiner}${timeKey}=${encodedTime}&wmts_rev=${revision}`;
}

function updateSentinelWmtsPlaybackUi() {
  const { start, end, timeParam } = wmtsPlaybackWindow();
  if (wmtsWeekWindowMetaEl) {
    const applied = (state.sentinelWmtsPlayback?.lastAppliedTimeParam || "").trim();
    const appliedSuffix = applied
      ? (applied === timeParam ? " • applied" : ` • applied ${applied}`)
      : "";
    wmtsWeekWindowMetaEl.textContent = `S-2 Window: ${start} to ${end}${appliedSuffix}`;
  }
}

function sentinelWmtsStatusText(cfg = state.sentinelWmtsConfig) {
  const layerId = cfg?.layer_id || "layer";
  const zoomHint = ` • visible at zoom ${SENTINEL_WMTS_MIN_ZOOM}+`;
  return `WMTS status: active (${layerId})${zoomHint}`;
}

function hasSearchableCollection(sourceId) {
  return Boolean((collectionForSource(sourceId, { allowNone: true }) || "").trim());
}

function hasAnyEnabledSearchLayer() {
  return Boolean(
    (state.layerControl.sentinelBaseEnabled && hasSearchableCollection("merlin-s2"))
      || (state.layerControl.satellogicOverlayEnabled && hasSearchableCollection("satellogic"))
  );
}

function applyLayerSearchResultsToState() {
  const mergedItems = [];
  const mergedOverview = [];

  if (state.layerControl.sentinelBaseEnabled) {
    mergedItems.push(...(state.layerSearchResults.sentinelBase.items || []));
    mergedOverview.push(...(state.layerSearchResults.sentinelBase.overviewItems || []));
  }

  if (state.layerControl.satellogicOverlayEnabled) {
    mergedItems.push(...(state.layerSearchResults.satellogicOverlay.items || []));
    mergedOverview.push(...(state.layerSearchResults.satellogicOverlay.overviewItems || []));
  }

  const items = dedupeById(mergedItems);
  const overviewItems = dedupeById(mergedOverview.length ? mergedOverview : mergedItems);
  state.items = items;
  state.overviewItems = overviewItems;
  state.outlineItems = dedupeById(overviewItems.length ? overviewItems : items);
  state.carouselQuickviewCount = state.layerSearchResults.satellogicOverlay.overviewItems.length;
  state.carouselFilterActive = false;
  refreshSatellogicStripGsdCache();
  refreshMapTimebarData();
}

function renderSentinelAnalyticsLayerChecklist() {
  if (sentinelAnalyticsCountEl) {
    sentinelAnalyticsCountEl.textContent = String((state.layerControl.sentinelAnalyticCollections || []).length);
  }
  if (!sentinelAnalyticsLayersEl) return;
  const rows = state.layerControl.sentinelAnalyticCollections || [];
  if (!rows.length) {
    sentinelAnalyticsLayersEl.innerHTML = `<p class="meta">No additional Sentinel WMTS analytic layers available.</p>`;
    return;
  }
  const wmtsReady = Boolean(state.sentinelWmtsConfig?.available && state.layerControl.sentinelWmtsEnabled);
  sentinelAnalyticsLayersEl.innerHTML = "";
  rows.forEach((row) => {
    const label = document.createElement("label");
    label.className = "layer-check";
    label.innerHTML = `
      <span class="layer-check-main">
        <input type="checkbox" data-layer-id="${row.id}" ${row.enabled ? "checked" : ""} ${wmtsReady ? "" : "disabled"} />
        <span class="layer-check-text">${row.title || row.id}</span>
      </span>
      <span class="layer-check-id">${row.id}</span>
    `;
    sentinelAnalyticsLayersEl.appendChild(label);
  });
}

function sourcePickerLabelText() {
  const selected = [];
  if (state.layerControl.sentinelBaseEnabled) selected.push("Merlin");
  if (state.layerControl.satellogicOverlayEnabled) selected.push("NewSat");
  if (!selected.length) return "None selected";
  if (selected.length === 2) return "Merlin + NewSat";
  return selected[0];
}

function setSourcePickerOpen(open) {
  state.sourcePickerOpen = Boolean(open);
  sourcePickerBtnEl?.setAttribute("aria-expanded", state.sourcePickerOpen ? "true" : "false");
  sourcePickerBtnEl?.closest(".source-picker")?.classList.toggle("open", state.sourcePickerOpen);
}

function applyLayerControlUiState() {
  syncEnabledSourcesFromLayerControl();
  if (layerSentinelBaseToggleEl) layerSentinelBaseToggleEl.checked = Boolean(state.layerControl.sentinelBaseEnabled);
  if (layerSatellogicToggleEl) layerSatellogicToggleEl.checked = Boolean(state.layerControl.satellogicOverlayEnabled);
  if (layerSentinelFramesToggleEl) layerSentinelFramesToggleEl.checked = Boolean(state.layerControl.sentinelFramesEnabled);
  if (layerSatellogicFramesToggleEl) layerSatellogicFramesToggleEl.checked = Boolean(state.layerControl.satellogicFramesEnabled);
  if (layerSentinelWmtsToggleEl) {
    layerSentinelWmtsToggleEl.checked = Boolean(state.layerControl.sentinelWmtsEnabled);
    layerSentinelWmtsToggleEl.disabled = !Boolean(state.sentinelWmtsConfig?.available);
  }
  if (layerSentinelStacToggleEl) layerSentinelStacToggleEl.checked = Boolean(state.layerControl.sentinelStacOverlayEnabled);
  if (sourceSelectEl) sourceSelectEl.value = selectedSourceId();
  if (contractSelectEl) contractSelectEl.disabled = !isSourceEnabled("satellogic");
  if (sourcePickerLabelEl) sourcePickerLabelEl.textContent = sourcePickerLabelText();
  renderSentinelAnalyticsLayerChecklist();
  updateSentinelWmtsPlaybackUi();
}

function sentinelCollectionLabel(collection) {
  const title = (collection?.title || "").toString().trim();
  const collectionId = (collection?.id || "").toString().trim();
  return title && title !== collectionId ? `${title}` : collectionId;
}

function setSentinelCollectionCatalog(collections) {
  const previousRaw = (state.perSourceCollections["merlin-s2"] || "").trim();
  const previous = previousRaw || collectionForSource("merlin-s2");
  const rows = (collections || [])
    .filter((row) => row && row.id)
    .filter((row) => String(row.id).toLowerCase().startsWith("sentinel-2"))
    .map((row) => ({
      id: String(row.id),
      title: sentinelCollectionLabel(row),
    }))
    .sort((a, b) => a.id.localeCompare(b.id));

  if (!rows.length) {
    if (sentinelCollectionEl) {
      sentinelCollectionEl.innerHTML = "";
      const noneOpt = document.createElement("option");
      noneOpt.value = COLLECTION_NONE_VALUE;
      noneOpt.textContent = "None (do not search)";
      sentinelCollectionEl.appendChild(noneOpt);
      if (previous === COLLECTION_NONE_VALUE) {
        setCollectionForSource("merlin-s2", COLLECTION_NONE_VALUE, false);
        sentinelCollectionEl.value = COLLECTION_NONE_VALUE;
      }
    }
    renderSentinelAnalyticsLayerChecklist();
    return;
  }

  const priorBaseId = state.layerControl.sentinelBaseCollectionId;
  const hasPriorBase = rows.some((row) => row.id === priorBaseId);
  const preferredBase = rows.find((row) => row.id.toLowerCase() === "sentinel-2-l2a")?.id;
  state.layerControl.sentinelBaseCollectionId = hasPriorBase
    ? priorBaseId
    : (preferredBase || rows[0].id);

  if (sentinelCollectionEl) {
    sentinelCollectionEl.innerHTML = "";
    const noneOpt = document.createElement("option");
    noneOpt.value = COLLECTION_NONE_VALUE;
    noneOpt.textContent = "None (do not search)";
    sentinelCollectionEl.appendChild(noneOpt);
    rows.forEach((row) => {
      const opt = document.createElement("option");
      opt.value = row.id;
      opt.textContent = row.title && row.title !== row.id ? `${row.title} (${row.id})` : row.id;
      sentinelCollectionEl.appendChild(opt);
    });
    const hasPrevious = previous === COLLECTION_NONE_VALUE || rows.some((row) => row.id === previous);
    const selected = hasPrevious ? previous : state.layerControl.sentinelBaseCollectionId;
    setCollectionForSource("merlin-s2", selected, false);
    sentinelCollectionEl.value = state.perSourceCollections["merlin-s2"] || collectionForSource("merlin-s2");
  } else {
    setCollectionForSource("merlin-s2", state.layerControl.sentinelBaseCollectionId, false);
  }

  renderSentinelAnalyticsLayerChecklist();
}

async function loadSentinelCollectionCatalog() {
  try {
    const params = new URLSearchParams();
    params.set("source_id", "merlin-s2");
    params.set("sentinel_only", "true");
    const res = await fetch(`${apiBase}/api/collections?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Sentinel collections unavailable");
    setSentinelCollectionCatalog(Array.isArray(data.collections) ? data.collections : []);
  } catch (err) {
    if (sentinelCollectionEl && sentinelCollectionEl.options.length === 0) {
      const noneOpt = document.createElement("option");
      noneOpt.value = COLLECTION_NONE_VALUE;
      noneOpt.textContent = "None (do not search)";
      sentinelCollectionEl.appendChild(noneOpt);
      const fallback = collectionForSource("merlin-s2") || "sentinel-2-l2a";
      const opt = document.createElement("option");
      opt.value = fallback;
      opt.textContent = fallback;
      sentinelCollectionEl.appendChild(opt);
      const desired = (state.perSourceCollections["merlin-s2"] || "").trim();
      if (desired === COLLECTION_NONE_VALUE) {
        sentinelCollectionEl.value = COLLECTION_NONE_VALUE;
        setCollectionForSource("merlin-s2", COLLECTION_NONE_VALUE, false);
      } else {
        sentinelCollectionEl.value = fallback;
        setCollectionForSource("merlin-s2", fallback, false);
      }
    }
    renderSentinelAnalyticsLayerChecklist();
    toast(`Sentinel layers unavailable: ${err.message}`);
  }
}

function clearSentinelWmtsLayer() {
  if (state.sentinelWmtsLayer) {
    map.removeLayer(state.sentinelWmtsLayer);
    state.sentinelWmtsLayer = null;
  }
  state.sentinelWmtsLayerTemplate = "";
}

function clearSentinelWmtsAnalyticLayers() {
  Object.values(state.sentinelWmtsOverlayLayers || {}).forEach((layer) => {
    if (layer) map.removeLayer(layer);
  });
  state.sentinelWmtsOverlayLayers = {};
  state.sentinelWmtsOverlayLayerTemplates = {};
}

async function loadSentinelWmtsLayerConfig(layerId) {
  const id = (layerId || "").toString().trim();
  if (!id) return null;
  if (id === (state.sentinelWmtsConfig?.layer_id || "")) return state.sentinelWmtsConfig;
  const cached = state.sentinelWmtsConfigByLayerId[id];
  if (cached) return cached;
  const params = new URLSearchParams();
  params.set("layer_id", id);
  const res = await fetch(`${apiBase}/api/layers/sentinel/wmts?${params.toString()}`, { cache: "no-store" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `WMTS config unavailable for ${id}`);
  state.sentinelWmtsConfigByLayerId[id] = data;
  return data;
}

function applySentinelWmtsLayer() {
  const cfg = state.sentinelWmtsConfig;
  if (!state.layerControl.sentinelWmtsEnabled || !cfg?.available || !cfg.template_url) {
    clearSentinelWmtsLayer();
    updateSentinelWmtsPlaybackUi();
    return;
  }
  const templateUrl = wmtsTemplateWithPlaybackTime(cfg.template_url);
  if (state.sentinelWmtsLayer && state.sentinelWmtsLayerTemplate === templateUrl) {
    state.sentinelWmtsPlayback.lastAppliedTimeParam = wmtsPlaybackWindow().timeParam;
    state.sentinelWmtsPlayback.lastAppliedAtMs = Date.now();
    updateSentinelWmtsPlaybackUi();
    return;
  }
  clearSentinelWmtsLayer();
  const paneId = "sentinelWmtsPane";
  if (!map.getPane(paneId)) {
    const pane = map.createPane(paneId);
    pane.style.zIndex = "260";
    pane.style.pointerEvents = "none";
  }
  state.sentinelWmtsLayer = L.tileLayer(templateUrl, {
    pane: paneId,
    opacity: 1.0,
    crossOrigin: true,
    minZoom: SENTINEL_WMTS_MIN_ZOOM,
    maxZoom: 19,
    noWrap: true,
    attribution: cfg.attribution || "",
  }).addTo(map);
  state.sentinelWmtsLayerTemplate = templateUrl;
  state.sentinelWmtsPlayback.lastAppliedTimeParam = wmtsPlaybackWindow().timeParam;
  state.sentinelWmtsPlayback.lastAppliedAtMs = Date.now();
  updateSentinelWmtsPlaybackUi();
}

async function applySentinelWmtsAnalyticLayers() {
  const selected = (state.layerControl.sentinelAnalyticCollections || [])
    .filter((row) => row?.enabled)
    .map((row) => (row.id || "").toString().trim())
    .filter(Boolean);
  const selectedSet = new Set(selected);

  Object.entries(state.sentinelWmtsOverlayLayers || {}).forEach(([layerId, layer]) => {
    if (!selectedSet.has(layerId) || !state.layerControl.sentinelWmtsEnabled || !state.sentinelWmtsConfig?.available) {
      if (layer) map.removeLayer(layer);
      delete state.sentinelWmtsOverlayLayers[layerId];
      delete state.sentinelWmtsOverlayLayerTemplates[layerId];
    }
  });

  if (!state.layerControl.sentinelWmtsEnabled || !state.sentinelWmtsConfig?.available || !selected.length) {
    updateSentinelWmtsPlaybackUi();
    return;
  }

  for (const layerId of selected) {
    try {
      const cfg = await loadSentinelWmtsLayerConfig(layerId);
      if (!cfg?.available || !cfg.template_url) continue;
      const templateUrl = wmtsTemplateWithPlaybackTime(cfg.template_url);
      const currentTemplate = state.sentinelWmtsOverlayLayerTemplates[layerId] || "";
      const existingLayer = state.sentinelWmtsOverlayLayers[layerId] || null;
      if (existingLayer && currentTemplate === templateUrl) continue;
      if (existingLayer) {
        map.removeLayer(existingLayer);
        delete state.sentinelWmtsOverlayLayers[layerId];
        delete state.sentinelWmtsOverlayLayerTemplates[layerId];
      }
      const paneId = `sentinelWmtsAnalyticPane_${layerId.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
      if (!map.getPane(paneId)) {
        const pane = map.createPane(paneId);
        pane.style.zIndex = "265";
        pane.style.pointerEvents = "none";
      }
      const layer = L.tileLayer(templateUrl, {
        pane: paneId,
        opacity: 0.72,
        crossOrigin: true,
        minZoom: SENTINEL_WMTS_MIN_ZOOM,
        maxZoom: 19,
        noWrap: true,
        attribution: cfg.attribution || "",
      }).addTo(map);
      state.sentinelWmtsOverlayLayers[layerId] = layer;
      state.sentinelWmtsOverlayLayerTemplates[layerId] = templateUrl;
    } catch (err) {
      console.warn(`Sentinel WMTS analytic layer '${layerId}' unavailable:`, err?.message || err);
    }
  }
  updateSentinelWmtsPlaybackUi();
}

async function loadSentinelWmtsConfig() {
  if (sentinelWmtsMetaEl) sentinelWmtsMetaEl.textContent = "Loading WMTS configuration...";
  try {
    const res = await fetch(`${apiBase}/api/layers/sentinel/wmts`, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "WMTS config unavailable");
    state.sentinelWmtsConfig = data;
    state.sentinelWmtsPlayback.anchorDate = normalizeIsoDay(data.default_time || wmtsPlaybackAnchorDay());
    state.sentinelWmtsPlayback.offsetWeeks = Math.max(0, Number(state.sentinelWmtsPlayback.offsetWeeks || 0));
    state.sentinelWmtsConfigByLayerId = {};
    if (data.layer_id) state.sentinelWmtsConfigByLayerId[data.layer_id] = data;
    setSentinelWmtsAnalyticLayers(data);
    if (!data.available) {
      state.layerControl.sentinelWmtsEnabled = false;
      clearSentinelWmtsLayer();
      clearSentinelWmtsAnalyticLayers();
      if (sentinelWmtsMetaEl) {
        sentinelWmtsMetaEl.textContent = `WMTS status: outlines-only fallback${data.reason ? ` (${data.reason})` : ""}`;
      }
    } else if (sentinelWmtsMetaEl) {
      sentinelWmtsMetaEl.textContent = sentinelWmtsStatusText(data);
    }
  } catch (err) {
    state.sentinelWmtsConfig = { available: false };
    state.sentinelWmtsConfigByLayerId = {};
    state.layerControl.sentinelAnalyticCollections = [];
    state.layerControl.sentinelWmtsEnabled = false;
    clearSentinelWmtsLayer();
    clearSentinelWmtsAnalyticLayers();
    if (sentinelWmtsMetaEl) sentinelWmtsMetaEl.textContent = `WMTS status: outlines-only fallback (${err.message})`;
  } finally {
    applyLayerControlUiState();
    applySentinelWmtsLayer();
    applySentinelWmtsAnalyticLayers().catch((err) => console.warn("Sentinel WMTS analytic layer update failed:", err?.message || err));
  }
}

async function refreshSearchForLayerControls() {
  applyLayerControlUiState();
  applySentinelWmtsLayer();
  await applySentinelWmtsAnalyticLayers();
  if (!hasAnyEnabledSearchLayer()) {
    state.items = [];
    state.overviewItems = [];
    state.detailItems = [];
    state.outlineItems = [];
    state.searchParams = null;
    state.lastDetailRequestKey = null;
    state.lastDetailCoverageBounds = null;
    state.lastDetailCoverageZoom = null;
    state.lastDetailContextKey = null;
    if (state.compareMode) setCompareMode(false);
    state.lastMapRenderSignature = "";
    drawResults([], "overview", false, { vectorItems: [], showOutlines: true });
    renderTimeCarouselForViewport();
    setItemSelectors([]);
    refreshMapTimebarData();
    searchMetaEl.textContent = "No active imagery layers. Enable Sentinel-2 or Satellogic.";
    return;
  }
  if (!state.searchParams && !state.currentAoi) return;
  await searchArchive();
}

function hideLayerEditorPopover() {
  layerEditorPopoverEl?.classList.remove("open");
  layerEditorBtnEl?.classList.remove("active");
}

function ensureLayerEditorControlAnchor() {
  const mapEl = map.getContainer();
  const editBtn = mapEl.querySelector(".leaflet-draw-edit-edit");
  if (!(editBtn instanceof HTMLElement)) return null;
  layerEditorBtnEl = editBtn;
  layerEditorBtnEl.title = "Select Layers";
  layerEditorBtnEl.setAttribute("aria-label", "Select Layers");
  layerEditorBtnEl.classList.remove("leaflet-disabled");
  if (layerEditorBtnEl.dataset.layerEditorBound !== "1") {
    layerEditorBtnEl.dataset.layerEditorBound = "1";
    layerEditorBtnEl.addEventListener("click", (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      if (typeof evt.stopImmediatePropagation === "function") evt.stopImmediatePropagation();
      hideAnimateSeriesPopover();
      hideDownloadPopover();
      toggleLayerEditorPopover();
    }, true);
  }
  return layerEditorBtnEl;
}

function positionLayerEditorPopover() {
  const anchorBtn = ensureLayerEditorControlAnchor();
  if (!layerEditorPopoverEl || !anchorBtn) return;
  const host = layerEditorPopoverEl.offsetParent || anchorBtn.offsetParent || anchorBtn.parentElement;
  if (!host) return;
  const hostRect = host.getBoundingClientRect();
  const btnRect = anchorBtn.getBoundingClientRect();
  const top = btnRect.bottom - hostRect.top + 6;
  const desiredRight = hostRect.right - btnRect.right;
  const maxRight = Math.max(0, host.clientWidth - 16);
  const clampedRight = Math.max(0, Math.min(maxRight, desiredRight));
  layerEditorPopoverEl.style.top = `${Math.max(0, top)}px`;
  layerEditorPopoverEl.style.bottom = "auto";
  layerEditorPopoverEl.style.left = "auto";
  layerEditorPopoverEl.style.right = `${clampedRight}px`;
}

function toggleLayerEditorPopover() {
  const anchorBtn = ensureLayerEditorControlAnchor();
  if (!layerEditorPopoverEl || !anchorBtn) return;
  const willOpen = !layerEditorPopoverEl.classList.contains("open");
  layerEditorPopoverEl.classList.toggle("open");
  anchorBtn.classList.toggle("active", willOpen);
  if (willOpen) {
    if (layerEditorSelectEl) layerEditorSelectEl.value = normalizeDetailLayerMode(state.detailLayerMode);
    positionLayerEditorPopover();
  }
}

async function applyDetailLayerMode(nextMode, refresh = true) {
  const normalized = normalizeDetailLayerMode(nextMode);
  const changed = normalized !== state.detailLayerMode;
  state.detailLayerMode = normalized;
  if (layerEditorSelectEl && layerEditorSelectEl.value !== normalized) {
    layerEditorSelectEl.value = normalized;
  }
  if (!refresh || !changed || !state.searchParams) return;
  await refreshMapMode(false);
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
    setAnimateSeriesStatus("Select 2+ visible images in the carousel, then press OK.");
    positionAnimateSeriesPopover();
  }
}

function setGenerateSeriesReportStatus(message, isError = false) {
  if (!generateSeriesReportStatusEl) return;
  generateSeriesReportStatusEl.textContent = message;
  generateSeriesReportStatusEl.style.color = isError ? "#d17569" : "";
}

function positionGenerateSeriesReportPopover() {
  if (!generateSeriesReportPopoverEl || !generateSeriesReportBtnEl) return;
  const host = generateSeriesReportPopoverEl.offsetParent || generateSeriesReportBtnEl.offsetParent || generateSeriesReportBtnEl.parentElement;
  if (!host) return;
  const hostRect = host.getBoundingClientRect();
  const btnRect = generateSeriesReportBtnEl.getBoundingClientRect();
  const top = btnRect.bottom - hostRect.top + 6;
  const desiredRight = hostRect.right - btnRect.right;
  const maxRight = Math.max(0, host.clientWidth - 16);
  const clampedRight = Math.max(0, Math.min(maxRight, desiredRight));
  generateSeriesReportPopoverEl.style.top = `${Math.max(0, top)}px`;
  generateSeriesReportPopoverEl.style.left = "auto";
  generateSeriesReportPopoverEl.style.right = `${clampedRight}px`;
}

function hideGenerateSeriesReportPopover() {
  generateSeriesReportPopoverEl?.classList.remove("open");
}

function toggleGenerateSeriesReportPopover() {
  if (!generateSeriesReportPopoverEl) return;
  const willOpen = !generateSeriesReportPopoverEl.classList.contains("open");
  generateSeriesReportPopoverEl.classList.toggle("open");
  if (willOpen) {
    setGenerateSeriesReportStatus("Uses selected images and current viewport extent.");
    positionGenerateSeriesReportPopover();
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
  if (state.searchParams && normalizeSourceId(state.searchParams.source_id) === "satellogic") {
    return {
      ...state.searchParams,
      geometry,
      source_id: "satellogic",
      collection_id: collectionId,
      limit: 1000,
    };
  }
  return buildSearchPayloadForSource(geometry, "satellogic", collectionId, 1000);
}

function looksLikeThumbnailOrPreview(url) {
  const lower = (url || "").toLowerCase();
  return lower.includes("thumbnail") || lower.includes("quickview_visual_thumbnail") || lower.includes("_preview") || lower.endsWith(".png");
}

function fullVisualAssetUrl(item) {
  const candidates = [item?.assets?.visual, item?.assets?.analytic, item?.assets?.data].filter(Boolean);
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

function positiveNumberOrNull(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function captureStripToken(item) {
  const candidate = [item?.outcome_id, item?.id]
    .filter((v) => typeof v === "string" && v.length > 0)
    .join(" ");
  const match = candidate.match(/\d{8}_\d{6}(?:_\d+)?_SN\d+/);
  if (!match) return "";
  return match[0].replace(/_\d+_SN/, "_SN");
}

function satellogicStripKey(item) {
  if (!item || normalizeSourceId(sourceIdForItem(item)) !== "satellogic") return "";
  const outcomeId = (item?.outcome_id || "").toString().trim();
  if (outcomeId) return `outcome:${outcomeId}`;
  const token = captureStripToken(item);
  if (token) return `capture:${token}`;
  const itemId = (item?.id || "").toString().trim();
  if (itemId) return `id:${itemId}`;
  return "";
}

function quickviewVisualRows() {
  return Array.isArray(state.layerSearchResults?.satellogicQuickviewVisual?.items)
    ? state.layerSearchResults.satellogicQuickviewVisual.items
    : [];
}

function quickviewVisualGsdSignature(rows) {
  return rows
    .map((row) => `${row?.id || ""}|${row?.outcome_id || ""}|${row?.gsd ?? ""}`)
    .join("~");
}

function refreshSatellogicStripGsdCache() {
  const rows = quickviewVisualRows();
  const nextSig = quickviewVisualGsdSignature(rows);
  if (nextSig === state.satellogicStripGsdCacheSig) return;
  const stripGsdMap = new Map();
  rows.forEach((row) => {
    const key = satellogicStripKey(row);
    const gsd = positiveNumberOrNull(row?.gsd);
    if (!key || gsd === null || stripGsdMap.has(key)) return;
    stripGsdMap.set(key, gsd);
  });
  state.satellogicStripGsdByKey = stripGsdMap;
  state.satellogicStripGsdCacheSig = nextSig;
}

function sampledSatellogicStripGsd(item) {
  const key = satellogicStripKey(item);
  if (!key) return null;
  refreshSatellogicStripGsdCache();
  const value = state.satellogicStripGsdByKey.get(key);
  return positiveNumberOrNull(value);
}

function collectionGsdForOverviewItem(overviewItem) {
  if (!overviewItem) return null;
  if (normalizeSourceId(sourceIdForItem(overviewItem)) === "satellogic") {
    const stripGsd = sampledSatellogicStripGsd(overviewItem);
    if (stripGsd !== null) return stripGsd;
    if (quickviewVisualRows().length) return null;
  }
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
  const sourceHint = normalizeSourceId(options.sourceHint || selectedSourceId());
  const contractId = sourceHint === "satellogic" ? selectedSatellogicContractId() : selectedContractId();
  if (contractId) params.set("contract_id", contractId);
  params.set("source_hint", sourceHint);
  if (options.render === true) params.set("render", "true");
  return `${apiBase}/api/assets/proxy?${params.toString()}`;
}

function hideContextMenu() {
  mapContextMenuEl.style.display = "none";
  state.contextMenuPoint = null;
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

function timelineSourceLabel(sourceId) {
  const normalized = normalizeSourceId(sourceId);
  if (normalized === "merlin-s2") return "Sentinel-2";
  if (normalized === "satellogic") return "Satellogic";
  return normalized || "Unknown";
}

function timelineLineColor(sourceId, isFuture = false) {
  const normalized = normalizeSourceId(sourceId);
  if (normalized === "merlin-s2") return isFuture ? "#9eb9ff" : "#4e7bff";
  if (normalized === "satellogic") return isFuture ? "#7edfd1" : "#26c0a5";
  return isFuture ? "#b6c7de" : "#89a3c6";
}

function toValidMs(value) {
  if (!value) return Number.NaN;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : Number.NaN;
}

function clampTimelineSpan(spanMs) {
  const value = Number(spanMs);
  if (!Number.isFinite(value)) return TIMELINE_DEFAULT_SPAN_MS;
  return Math.max(TIMELINE_MIN_SPAN_MS, Math.min(TIMELINE_MAX_SPAN_MS, value));
}

function ensureTimelineWindowState() {
  const now = Date.now();
  state.timeline.spanMs = clampTimelineSpan(state.timeline.spanMs || TIMELINE_DEFAULT_SPAN_MS);
  if (!Number.isFinite(state.timeline.centerMs)) {
    state.timeline.centerMs = now - (state.timeline.spanMs / 2);
  }
}

function timelineWindow() {
  ensureTimelineWindowState();
  const span = clampTimelineSpan(state.timeline.spanMs);
  const center = Number(state.timeline.centerMs);
  return {
    span,
    center,
    start: center - (span / 2),
    end: center + (span / 2),
  };
}

function timelineMsToX(ms, startMs, endMs, width) {
  if (!Number.isFinite(ms) || !Number.isFinite(startMs) || !Number.isFinite(endMs) || width <= 0 || endMs <= startMs) return Number.NaN;
  return ((ms - startMs) / (endMs - startMs)) * width;
}

function timelineXToMs(x, startMs, endMs, width) {
  if (!Number.isFinite(x) || !Number.isFinite(startMs) || !Number.isFinite(endMs) || width <= 0 || endMs <= startMs) return Number.NaN;
  return startMs + ((x / width) * (endMs - startMs));
}

function utcDayStartMs(ms) {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function utcMonthStartMs(ms) {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
}

function chooseDayTickStep(spanMs) {
  if (spanMs <= 14 * DAY_MS) return 1;
  if (spanMs <= 45 * DAY_MS) return 2;
  if (spanMs <= 120 * DAY_MS) return 5;
  if (spanMs <= 240 * DAY_MS) return 10;
  return 30;
}

function imageryTimelineEvents() {
  const viewportRows = Array.isArray(state.carouselVisibleItems) && state.carouselVisibleItems.length
    ? state.carouselVisibleItems
    : viewportFilteredCarouselItems(map.getBounds());
  const rows = dedupeById(viewportRows);
  const now = Date.now();
  return rows
    .map((item) => {
      const ms = toValidMs(item?.datetime);
      if (!Number.isFinite(ms)) return null;
      const sourceId = sourceIdForItem(item);
      return {
        kind: "image",
        ms,
        sourceId,
        isFuture: ms > now,
        item,
      };
    })
    .filter(Boolean);
}

function taskingTimelineEvents() {
  const now = Date.now();
  const rows = Array.isArray(state.taskingOrders) ? state.taskingOrders : [];
  return rows
    .map((order) => {
      const ms = toValidMs(order?.start || order?.start_date || order?.window_start);
      if (!Number.isFinite(ms) || ms <= now) return null;
      const sku = (order?.sku || "").toString().toLowerCase();
      const sourceId = normalizeSourceId(order?.source_id || (sku.includes("sentinel") ? "merlin-s2" : "satellogic"));
      return {
        kind: "tasking",
        ms,
        sourceId,
        isFuture: true,
        order,
      };
    })
    .filter(Boolean);
}

function refreshMapTimebarData() {
  if (!mapTimebarCanvasEl) return;
  const events = [...imageryTimelineEvents(), ...taskingTimelineEvents()].sort((a, b) => a.ms - b.ms);
  state.timeline.events = events;

  if (!state.timeline.userAdjusted) {
    const now = Date.now();
    if (events.length) {
      const earliest = events[0].ms;
      const naturalSpan = Math.max(30 * DAY_MS, now - earliest);
      state.timeline.spanMs = clampTimelineSpan(Math.min(TIMELINE_DEFAULT_SPAN_MS * 2, naturalSpan));
    } else {
      state.timeline.spanMs = TIMELINE_DEFAULT_SPAN_MS;
    }
    state.timeline.centerMs = now - (state.timeline.spanMs / 2);
  }

  renderMapTimebar();
}

function timelineSensorName(sourceId) {
  const normalized = normalizeSourceId(sourceId);
  if (normalized === "satellogic") return "Satellogic NewSat";
  if (normalized === "merlin-s2") return "Sentinel-2";
  return timelineSourceLabel(sourceId);
}

function matchQuickviewVisualItem(item) {
  if (!item || normalizeSourceId(sourceIdForItem(item)) !== "satellogic") return null;
  const rows = quickviewVisualRows();
  if (!rows.length) return null;

  if (item.outcome_id) {
    const byOutcome = rows.find((row) => row?.outcome_id && row.outcome_id === item.outcome_id);
    if (byOutcome) return byOutcome;
  }

  const stripKey = satellogicStripKey(item);
  if (stripKey) {
    const byStrip = rows.find((row) => satellogicStripKey(row) === stripKey);
    if (byStrip) return byStrip;
  }

  const key = captureKey(item);
  if (key) {
    const byCapture = rows.find((row) => captureKey(row) === key);
    if (byCapture) return byCapture;
  }

  if (item.id) {
    const byId = rows.find((row) => row?.id && row.id === item.id);
    if (byId) return byId;
  }

  if (item.datetime) {
    const byDatetime = rows.find((row) => row?.datetime && row.datetime === item.datetime);
    if (byDatetime) return byDatetime;
  }
  return null;
}

function timelineMetadataItem(event) {
  const item = event?.item;
  if (!item) return null;
  const matched = matchQuickviewVisualItem(item);
  const stripGsd = sampledSatellogicStripGsd(item);
  if (matched && stripGsd !== null) return { ...matched, gsd: stripGsd };
  if (matched) return matched;
  if (stripGsd !== null) return { ...item, gsd: stripGsd };
  return item;
}

function timelineHoverHtml(ms, event) {
  const iso = Number.isFinite(ms) ? new Date(ms).toISOString() : "";
  let html = `<div class="time">Datetime: ${formatCaptureDate(iso)}</div>`;
  if (!event) return html;
  if (event.kind === "image") {
    const item = timelineMetadataItem(event) || event.item || {};
    const cloud = item.cloud_cover === null || item.cloud_cover === undefined ? "n/a" : String(item.cloud_cover);
    const gsd = item.gsd === null || item.gsd === undefined ? "n/a" : String(item.gsd);
    const satelliteName = ((item.satellite_name || "").toString().trim() || timelineSensorName(event.sourceId));
    const datetimeValue = item.datetime || iso;
    html = `<div class="title">Sensor: ${escapeHtml(satelliteName)}</div>`;
    html += [
      `<div class="time">Datetime: ${escapeHtml(formatCaptureDate(datetimeValue))}</div>`,
      `<div>GSD: ${escapeHtml(gsd)}, Cloud Cover: ${escapeHtml(cloud)}</div>`,
    ].join("");
    return html;
  }

  const order = event.order || {};
  html += [
    `<div class="title">${timelineSourceLabel(event.sourceId)} Planned Tasking</div>`,
    `<div>Order: ${escapeHtml((order.order_name || order.id || "n/a").toString())}</div>`,
    `<div>Project: ${escapeHtml((order.project_name || "n/a").toString())}</div>`,
    `<div>Product: ${escapeHtml((order.sku || "n/a").toString())}</div>`,
    `<div>Window: ${escapeHtml(formatTaskingDate(order.start || order.start_date || ""))} → ${escapeHtml(formatTaskingDate(order.end || order.end_date || ""))}</div>`,
    `<div>Status: ${escapeHtml((order.status || "n/a").toString())}</div>`,
  ].join("");
  return html;
}

function nearestTimelineRenderedEntry(x, hitPx = TIMELINE_HIT_PX) {
  const rendered = Array.isArray(state.timeline.renderedEvents) ? state.timeline.renderedEvents : [];
  let nearest = null;
  rendered.forEach((entry) => {
    const dist = Math.abs(entry.x - x);
    if (dist > hitPx) return;
    if (!nearest || dist < nearest.dist) nearest = { entry, dist };
  });
  return nearest?.entry || null;
}

function findOverviewItemForTimelineItem(item) {
  if (!item) return null;
  const overview = overviewSourceItems();
  if (!overview.length) return null;

  if (item.id) {
    const byId = overview.find((row) => row.id === item.id);
    if (byId) return byId;
  }
  if (item.outcome_id) {
    const byOutcome = overview.find((row) => row?.outcome_id && row.outcome_id === item.outcome_id);
    if (byOutcome) return byOutcome;
  }
  const key = captureKey(item);
  if (key) {
    const byCapture = overview.find((row) => captureKey(row) === key);
    if (byCapture) return byCapture;
  }
  if (item.datetime) {
    const byDatetime = overview.find((row) => row?.datetime && row.datetime === item.datetime);
    if (byDatetime) return byDatetime;
  }
  return null;
}

async function focusTimelineImageEvent(event) {
  if (!event || event.kind !== "image") return;
  const overviewItem = findOverviewItemForTimelineItem(event.item);
  if (!overviewItem || !overviewItem.id) {
    toast("Could not match timeline image to current carousel item.");
    return;
  }
  state.selectedCarouselIds.add(overviewItem.id);
  setActiveCarouselCard(overviewItem.id, { autoScroll: true });
  syncCarouselCheckboxes();
  if (state.compareMode) updateCompareModeState(overviewItem.id);
  await focusFromCarousel(overviewItem, { fitToFrame: false, preserveViewport: true });
}

function setTimelineHoverFromClientPoint(clientX, clientY) {
  if (!mapTimebarCanvasEl || !mapTimebarTooltipEl) return;
  const rect = mapTimebarCanvasEl.getBoundingClientRect();
  const width = rect.width;
  if (width <= 0) return;

  const x = Math.max(0, Math.min(width, clientX - rect.left));
  const { start, end } = timelineWindow();
  const ms = timelineXToMs(x, start, end, width);
  state.timeline.hoverX = x;
  state.timeline.hoverMs = ms;

  const nearest = nearestTimelineRenderedEntry(x, TIMELINE_HIT_PX);
  state.timeline.hoverEvent = nearest?.event || null;

  mapTimebarTooltipEl.innerHTML = timelineHoverHtml(ms, state.timeline.hoverEvent);
  const tooltipWidth = Math.min(360, Math.max(180, mapTimebarTooltipEl.offsetWidth || 220));
  const left = Math.max(6, Math.min((mapTimebarEl.clientWidth - tooltipWidth - 6), x + 8));
  mapTimebarTooltipEl.style.left = `${left}px`;
  mapTimebarTooltipEl.classList.add("open");
  renderMapTimebar();
}

function hideMapTimebarTooltip() {
  state.timeline.hoverX = null;
  state.timeline.hoverMs = null;
  state.timeline.hoverEvent = null;
  mapTimebarTooltipEl?.classList.remove("open");
  renderMapTimebar();
}

function drawMapTimebarAxis(ctx, width, height, start, end) {
  const span = end - start;
  const monthTop = 18;
  const dayBaseline = height - 16;
  const dayStep = chooseDayTickStep(span);

  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.textBaseline = "top";

  ctx.strokeStyle = "rgba(110, 143, 183, 0.26)";
  ctx.lineWidth = 1;
  let dayTick = utcDayStartMs(start) - DAY_MS;
  while (dayTick <= end + DAY_MS) {
    const day = Math.floor(dayTick / DAY_MS);
    if (dayStep <= 1 || (day % dayStep) === 0) {
      const x = timelineMsToX(dayTick, start, end, width);
      if (Number.isFinite(x)) {
        ctx.beginPath();
        ctx.moveTo(x + 0.5, dayBaseline - 8);
        ctx.lineTo(x + 0.5, dayBaseline + 4);
        ctx.stroke();
        if (span <= 120 * DAY_MS) {
          const dd = new Date(dayTick).getUTCDate();
          ctx.fillStyle = "rgba(156, 181, 214, 0.9)";
          ctx.fillText(String(dd).padStart(2, "0"), x + 2, dayBaseline + 5);
        }
      }
    }
    dayTick += DAY_MS;
  }

  let monthTick = utcMonthStartMs(start) - (31 * DAY_MS);
  while (monthTick <= end + (31 * DAY_MS)) {
    const d = new Date(monthTick);
    const normalized = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
    const x = timelineMsToX(normalized, start, end, width);
    if (Number.isFinite(x) && x >= -80 && x <= width + 80) {
      ctx.strokeStyle = "rgba(133, 168, 213, 0.42)";
      ctx.beginPath();
      ctx.moveTo(x + 0.5, monthTop);
      ctx.lineTo(x + 0.5, height - 6);
      ctx.stroke();
      ctx.fillStyle = "rgba(204, 222, 244, 0.96)";
      ctx.fillText(d.toLocaleString("en-US", { month: "short", year: "numeric", timeZone: "UTC" }), x + 4, 2);
    }
    monthTick = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  }
}

function isWmtsBandInteractive() {
  return Boolean(state.sentinelWmtsConfig?.available && state.layerControl.sentinelWmtsEnabled);
}

function wmtsBandRectForTimeline(width, height, start, end) {
  if (!isWmtsBandInteractive()) return null;
  const { startMs, endExclusiveMs } = wmtsPlaybackWindowMs();
  if (!Number.isFinite(startMs) || !Number.isFinite(endExclusiveMs)) return null;
  const rawX0 = timelineMsToX(startMs, start, end, width);
  const rawX1 = timelineMsToX(endExclusiveMs, start, end, width);
  if (!Number.isFinite(rawX0) || !Number.isFinite(rawX1)) return null;
  const x0 = Math.min(rawX0, rawX1);
  const x1 = Math.max(rawX0, rawX1);
  const y = 22;
  const h = Math.max(22, height - 42);
  return { x0, x1, y, h, startMs, endExclusiveMs };
}

function wmtsBandHitMode(x, bandRect) {
  if (!bandRect) return null;
  const leftDist = Math.abs(x - bandRect.x0);
  const rightDist = Math.abs(x - bandRect.x1);
  if (leftDist <= WMTS_BAND_EDGE_HIT_PX) return "resize-left";
  if (rightDist <= WMTS_BAND_EDGE_HIT_PX) return "resize-right";
  if (x >= bandRect.x0 && x <= bandRect.x1) return "move";
  return null;
}

function updateMapTimebarCursor(clientX = null) {
  if (!mapTimebarCanvasEl) return;
  if (state.timeline.wmtsDrag?.mode) {
    const dragMode = state.timeline.wmtsDrag.mode;
    mapTimebarCanvasEl.style.cursor = dragMode === "move" ? "grab" : "ew-resize";
    return;
  }
  const rect = mapTimebarCanvasEl.getBoundingClientRect();
  const width = rect.width;
  if (!Number.isFinite(clientX) || width <= 0) {
    mapTimebarCanvasEl.style.cursor = "crosshair";
    return;
  }
  const x = Math.max(0, Math.min(width, clientX - rect.left));
  const { start, end } = timelineWindow();
  const bandRect = wmtsBandRectForTimeline(width, mapTimebarCanvasEl.clientHeight, start, end);
  const mode = wmtsBandHitMode(x, bandRect);
  if (mode === "move") {
    mapTimebarCanvasEl.style.cursor = "grab";
    return;
  }
  if (mode === "resize-left" || mode === "resize-right") {
    mapTimebarCanvasEl.style.cursor = "ew-resize";
    return;
  }
  mapTimebarCanvasEl.style.cursor = "crosshair";
}

function renderMapTimebar() {
  if (!mapTimebarCanvasEl) return;
  const widthCss = mapTimebarCanvasEl.clientWidth;
  const heightCss = mapTimebarCanvasEl.clientHeight;
  if (widthCss <= 0 || heightCss <= 0) return;
  const dpr = window.devicePixelRatio || 1;
  const widthPx = Math.max(1, Math.round(widthCss * dpr));
  const heightPx = Math.max(1, Math.round(heightCss * dpr));
  if (mapTimebarCanvasEl.width !== widthPx || mapTimebarCanvasEl.height !== heightPx) {
    mapTimebarCanvasEl.width = widthPx;
    mapTimebarCanvasEl.height = heightPx;
  }

  const ctx = mapTimebarCanvasEl.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, widthCss, heightCss);

  const { start, end, span } = timelineWindow();
  drawMapTimebarAxis(ctx, widthCss, heightCss, start, end);

  const wmtsBand = wmtsBandRectForTimeline(widthCss, heightCss, start, end);
  if (wmtsBand) {
    const drawX0 = Math.max(0, Math.min(widthCss, wmtsBand.x0));
    const drawX1 = Math.max(0, Math.min(widthCss, wmtsBand.x1));
    const bandWidth = Math.max(0, drawX1 - drawX0);
    if (bandWidth > 0) {
      ctx.fillStyle = "rgba(128, 188, 255, 0.22)";
      ctx.strokeStyle = "rgba(149, 206, 255, 0.78)";
      ctx.lineWidth = 1.5;
      ctx.fillRect(drawX0, wmtsBand.y, bandWidth, wmtsBand.h);
      ctx.strokeRect(drawX0 + 0.5, wmtsBand.y + 0.5, Math.max(0, bandWidth - 1), Math.max(0, wmtsBand.h - 1));

      const handleW = 4;
      ctx.fillStyle = "rgba(179, 224, 255, 0.92)";
      ctx.fillRect(drawX0 - (handleW / 2), wmtsBand.y + 2, handleW, Math.max(0, wmtsBand.h - 4));
      ctx.fillRect(drawX1 - (handleW / 2), wmtsBand.y + 2, handleW, Math.max(0, wmtsBand.h - 4));

      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.fillStyle = "rgba(183, 194, 209, 0.95)";
      const label = "S-2 Window";
      const labelX = Math.min(widthCss - 80, Math.max(4, drawX0 + 6));
      ctx.fillText(label, labelX, wmtsBand.y + 4);
    }
  }

  const nowMs = Date.now();
  const nowX = timelineMsToX(nowMs, start, end, widthCss);
  if (Number.isFinite(nowX) && nowX >= 0 && nowX <= widthCss) {
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = "rgba(255, 185, 102, 0.95)";
    ctx.beginPath();
    ctx.moveTo(nowX + 0.5, 0);
    ctx.lineTo(nowX + 0.5, heightCss);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = '11px "IBM Plex Mono", monospace';
    ctx.fillStyle = "rgba(255, 206, 140, 0.98)";
    ctx.fillText("Now", Math.min(widthCss - 30, nowX + 4), heightCss - 30);
  }

  const events = Array.isArray(state.timeline.events) ? state.timeline.events : [];
  const rendered = [];
  const sentinelBins = new Map();
  events.forEach((event) => {
    const x = timelineMsToX(event.ms, start, end, widthCss);
    if (!Number.isFinite(x) || x < -2 || x > widthCss + 2) return;
    rendered.push({ x, event });
    if (event.kind === "image" && normalizeSourceId(event.sourceId) === "merlin-s2") {
      const key = Math.round(x);
      const prior = sentinelBins.get(key) || { x: key, count: 0 };
      prior.count += 1;
      sentinelBins.set(key, prior);
    }
    const isHovered = state.timeline.hoverEvent && event.kind === state.timeline.hoverEvent.kind
      && ((event.kind === "image" && event.item?.id === state.timeline.hoverEvent.item?.id)
      || (event.kind === "tasking" && event.order?.id === state.timeline.hoverEvent.order?.id));
    ctx.strokeStyle = timelineLineColor(event.sourceId, Boolean(event.isFuture));
    ctx.globalAlpha = isHovered ? 1.0 : 0.9;
    ctx.lineWidth = isHovered ? 2.6 : (event.kind === "tasking" ? 2.2 : 1.7);
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, heightCss);
    ctx.stroke();
    ctx.globalAlpha = 1.0;
  });
  state.timeline.renderedEvents = rendered;

  if (wmtsBand && sentinelBins.size) {
    const drawX0 = Math.max(0, Math.min(widthCss, wmtsBand.x0));
    const drawX1 = Math.max(0, Math.min(widthCss, wmtsBand.x1));
    const baselineY = wmtsBand.y + wmtsBand.h - 4;
    const rows = Array.from(sentinelBins.values()).sort((a, b) => a.x - b.x);
    const maxCount = rows.reduce((mx, row) => Math.max(mx, Number(row.count || 0)), 1);
    let inWindow = 0;
    let overlapBins = 0;
    rows.forEach((row) => {
      const x = Math.max(0, Math.min(widthCss, row.x));
      const inBand = x >= drawX0 && x <= drawX1;
      if (inBand) inWindow += Number(row.count || 0);
      if ((row.count || 0) > 1 && inBand) overlapBins += 1;
      const scale = maxCount > 1 ? (row.count / maxCount) : 1;
      const tickHeight = Math.max(4, Math.round(4 + (scale * 10)));
      ctx.strokeStyle = (row.count || 0) > 1
        ? "rgba(131, 255, 182, 0.95)"
        : "rgba(128, 236, 255, 0.78)";
      ctx.lineWidth = (row.count || 0) > 1 ? 2 : 1.2;
      ctx.beginPath();
      ctx.moveTo(x + 0.5, baselineY + 0.5);
      ctx.lineTo(x + 0.5, baselineY - tickHeight);
      ctx.stroke();
    });
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = "rgba(178, 207, 229, 0.94)";
    const captureLabel = `S-2 captures in window: ${inWindow}${overlapBins ? ` (${overlapBins} overlap bins)` : ""}`;
    const labelX = Math.min(widthCss - 220, Math.max(4, drawX0 + 6));
    ctx.fillText(captureLabel, labelX, wmtsBand.y + 16);
  }

  if (Number.isFinite(state.timeline.hoverX)) {
    ctx.strokeStyle = "rgba(226, 240, 255, 0.55)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(state.timeline.hoverX + 0.5, 0);
    ctx.lineTo(state.timeline.hoverX + 0.5, heightCss);
    ctx.stroke();
  }

  if (mapTimebarCenterInputEl && document.activeElement !== mapTimebarCenterInputEl && Number.isFinite(state.timeline.centerMs)) {
    mapTimebarCenterInputEl.value = toDateTimeLocalInput(new Date(state.timeline.centerMs).toISOString());
  }

  if (mapTimebarPageForwardBtnEl) {
    const forwardMax = nowMs + (365 * DAY_MS);
    mapTimebarPageForwardBtnEl.disabled = (start + span) > forwardMax;
  }
}

function shiftMapTimebarBy(deltaMs) {
  ensureTimelineWindowState();
  state.timeline.centerMs += Number(deltaMs || 0);
  state.timeline.userAdjusted = true;
  renderMapTimebar();
}

function centerMapTimebarAt(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value)) return;
  ensureTimelineWindowState();
  state.timeline.centerMs = value;
  state.timeline.userAdjusted = true;
  renderMapTimebar();
}

function zoomMapTimebarAt(anchorClientX, zoomIn) {
  if (!mapTimebarCanvasEl) return;
  const rect = mapTimebarCanvasEl.getBoundingClientRect();
  const width = rect.width;
  if (width <= 0) return;
  const x = Math.max(0, Math.min(width, anchorClientX - rect.left));
  const { start, span } = timelineWindow();
  const anchorMs = timelineXToMs(x, start, start + span, width);
  const factor = zoomIn ? 0.84 : 1.18;
  const nextSpan = clampTimelineSpan(span * factor);
  const ratio = (anchorMs - start) / span;
  const nextStart = anchorMs - (ratio * nextSpan);
  state.timeline.centerMs = nextStart + (nextSpan / 2);
  state.timeline.spanMs = nextSpan;
  state.timeline.userAdjusted = true;
  renderMapTimebar();
}

async function updateDebugStats() {
  try {
    const res = await fetch(`${apiBase}/api/debug/stats`, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const tileDelivery = data?.tile_delivery || {};
    const newsat = tileDelivery.newsat || {};
    const merlin = tileDelivery.merlin || {};
    const formatPerfChip = (label, row) => {
      const mbps = Number(row?.mbps_avg || 0);
      const mbTotal = Number(row?.mb_total || 0);
      const req = Number(row?.requests || 0);
      const err = Number(row?.errors || 0);
      return `${label} ${mbps.toFixed(2)} MB/s | ${mbTotal.toFixed(1)} MB | req ${req}${err ? ` • err ${err}` : ""}`;
    };
    if (tilePerfNewSatEl) tilePerfNewSatEl.textContent = formatPerfChip("NewSat", newsat);
    if (tilePerfMerlinEl) tilePerfMerlinEl.textContent = formatPerfChip("Merlin", merlin);

    if (DEBUG_NET && mapDebugStatsEl) {
      const searchTotal = Number(data?.archive_search?.total || 0);
      const byCollection = data?.archive_search?.by_collection || {};
      const l1dCount = Number(byCollection["l1d-sr"] || 0);
      const quickviewCount = Number(byCollection["quickview-visual-thumb"] || 0);
      const tileTotal = Number(data?.tile_proxy?.total || 0);
      const tileHitPct = Math.round(Number(data?.tile_proxy?.hit_rate || 0) * 100);
      mapDebugStatsEl.textContent = `Search ${searchTotal} (l1d ${l1dCount}, qv ${quickviewCount}) | Tiles ${tileTotal} (hit ${tileHitPct}%)`;
    }
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
  state.contextMenuPoint = { x, y };
  mapContextMenuEl.style.left = `${x}px`;
  mapContextMenuEl.style.top = `${y}px`;
  mapContextMenuEl.style.display = "block";
}

function toDateTimeLocalInput(isoValue) {
  if (!isoValue) return "";
  const parsed = new Date(isoValue);
  if (Number.isNaN(parsed.getTime())) return "";
  const pad = (v) => String(v).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function toUtcIsoFromLocalInput(rawValue) {
  const text = (rawValue || "").trim();
  if (!text) return "";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString();
}

function taskingDateTag() {
  const now = new Date();
  const pad = (v) => String(v).padStart(2, "0");
  return `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}`;
}

function updateTaskingCursor() {
  const mapEl = map.getContainer();
  if (!mapEl) return;
  const pointMode = state.taskingMode === "point-await-click";
  const areaMode = state.taskingMode === "area-drawing";
  mapEl.classList.toggle("tasking-point-pick", pointMode);
  mapEl.classList.toggle("tasking-area-draw", areaMode);
}

function defaultTaskingOrderName(targetType) {
  return targetType === "area" ? `area_task_${taskingDateTag()}` : `point_task_${taskingDateTag()}`;
}

function hideTaskingTypeMenu() {
  if (!taskingTypeMenuEl) return;
  taskingTypeMenuEl.style.display = "none";
}

function showTaskingTypeMenu(x, y) {
  if (!taskingTypeMenuEl) return;
  taskingTypeMenuEl.style.left = `${x}px`;
  taskingTypeMenuEl.style.top = `${y}px`;
  taskingTypeMenuEl.style.display = "block";
}

function hideTaskingForm() {
  taskingFormPopoverEl?.classList.remove("open");
}

function renderTaskingProductOptions(targetType) {
  if (!taskingProductEl) return;
  taskingProductEl.innerHTML = "";
  const filtered = (state.taskingProducts || []).filter((row) => {
    const supported = Array.isArray(row?.target_types) ? row.target_types : [];
    return supported.includes(targetType);
  });
  filtered.forEach((row) => {
    const opt = document.createElement("option");
    opt.value = row.sku;
    opt.textContent = `${row.sku} - ${row.label || row.sku}`;
    taskingProductEl.appendChild(opt);
  });
  if (!taskingProductEl.value && filtered.length) {
    taskingProductEl.value = filtered[0].sku;
  }
}

function renderTaskingProjectSuggestions() {
  if (!taskingProjectSuggestionsEl) return;
  taskingProjectSuggestionsEl.innerHTML = "";
  (state.taskingProjects || []).forEach((project) => {
    if (!project) return;
    const opt = document.createElement("option");
    opt.value = project;
    taskingProjectSuggestionsEl.appendChild(opt);
  });
}

function taskingGeometryHint(targetType, geometry) {
  if (!geometry || typeof geometry !== "object") return "Target geometry not selected.";
  if (targetType === "point" && geometry.type === "Point" && Array.isArray(geometry.coordinates)) {
    const lat = geometry.coordinates[1];
    const lon = geometry.coordinates[0];
    return `Point: ${formatCoord(lat)}, ${formatCoord(lon)}`;
  }
  if (targetType === "area" && geometry.type === "Polygon") {
    const points = Array.isArray(geometry.coordinates?.[0]) ? geometry.coordinates[0].length - 1 : 0;
    return `Polygon vertices: ${Math.max(0, points)}`;
  }
  return `Geometry: ${geometry.type || "unknown"}`;
}

function openTaskingForm({ targetType, geometry, containerPoint }) {
  state.taskingTargetType = targetType;
  state.taskingTargetGeometry = geometry;
  if (!taskingFormPopoverEl) return;
  const cadenceLabel = targetType === "area" ? "Remapping Period (optional, ISO-8601)" : "Revisit Period (optional, ISO-8601)";
  if (taskingCadenceLabelEl) {
    const input = taskingCadenceLabelEl.querySelector("input");
    taskingCadenceLabelEl.textContent = cadenceLabel;
    if (input) taskingCadenceLabelEl.appendChild(input);
  }
  if (taskingFormTitleEl) {
    taskingFormTitleEl.textContent = targetType === "area" ? "Task Image - Area" : "Task Image - Point Target";
  }
  if (taskingGeometryHintEl) {
    taskingGeometryHintEl.textContent = taskingGeometryHint(targetType, geometry);
  }

  renderTaskingProductOptions(targetType);
  renderTaskingProjectSuggestions();

  if (taskingOrderNameEl) taskingOrderNameEl.value = defaultTaskingOrderName(targetType);
  if (taskingCadenceEl) taskingCadenceEl.value = "";
  if (taskingProjectNameEl && !taskingProjectNameEl.value && state.taskingProjects.length) {
    taskingProjectNameEl.value = state.taskingProjects[0];
  }
  if (taskingStartEl && !taskingStartEl.value) {
    taskingStartEl.value = toDateTimeLocalInput(new Date().toISOString());
  }
  if (taskingEndEl && !taskingEndEl.value) {
    const plusDay = new Date(Date.now() + (24 * 60 * 60 * 1000));
    taskingEndEl.value = toDateTimeLocalInput(plusDay.toISOString());
  }

  const mapEl = map.getContainer();
  const anchorX = Number.isFinite(Number(containerPoint?.x)) ? Number(containerPoint.x) : Math.floor(mapEl.clientWidth / 2);
  const anchorY = Number.isFinite(Number(containerPoint?.y)) ? Number(containerPoint.y) : Math.floor(mapEl.clientHeight / 2);
  const maxX = Math.max(8, mapEl.clientWidth - 400);
  const maxY = Math.max(8, mapEl.clientHeight - 370);
  const x = Math.max(8, Math.min(maxX, anchorX));
  const y = Math.max(8, Math.min(maxY, anchorY));
  taskingFormPopoverEl.style.left = `${x}px`;
  taskingFormPopoverEl.style.top = `${y}px`;
  taskingFormPopoverEl.classList.add("open");
}

function restoreTaskingDoubleClickZoom() {
  if (!state.taskingRestoreDblClickZoom) return;
  map.doubleClickZoom.enable();
  state.taskingRestoreDblClickZoom = false;
}

function resetTaskingDrawState() {
  state.taskingMode = "idle";
  state.taskingDrawPoints = [];
  state.taskingSketchLine = null;
  state.taskingSketchFill = null;
  taskingDrawLayer.clearLayers();
  restoreTaskingDoubleClickZoom();
  updateTaskingCursor();
}

function updateTaskingAreaSketch() {
  taskingDrawLayer.clearLayers();
  if (!state.taskingDrawPoints.length) return;
  const path = state.taskingDrawPoints.map((pt) => [pt.lat, pt.lng]);
  state.taskingSketchLine = L.polyline(path, {
    color: "#ffd166",
    weight: 2,
    opacity: 0.95,
    dashArray: "4 4",
  }).addTo(taskingDrawLayer);
  if (path.length >= 3) {
    state.taskingSketchFill = L.polygon(path, {
      color: "#ffd166",
      weight: 2,
      fillColor: "#ffd166",
      fillOpacity: 0.18,
    }).addTo(taskingDrawLayer);
  }
}

function cancelTaskingInteraction() {
  hideTaskingTypeMenu();
  hideTaskingForm();
  state.taskingTargetType = null;
  state.taskingTargetGeometry = null;
  resetTaskingDrawState();
}

function beginPointTaskingFlow() {
  hideTaskingTypeMenu();
  hideTaskingForm();
  resetTaskingDrawState();
  state.taskingMode = "point-await-click";
  updateTaskingCursor();
  toast("Point target: click once on the map.");
}

function beginAreaTaskingFlow() {
  hideTaskingTypeMenu();
  hideTaskingForm();
  resetTaskingDrawState();
  state.taskingMode = "area-drawing";
  state.taskingTargetType = "area";
  state.taskingDrawPoints = [];
  if (map.doubleClickZoom.enabled()) {
    state.taskingRestoreDblClickZoom = true;
    map.doubleClickZoom.disable();
  }
  updateTaskingCursor();
  toast("Area target: click to add polygon vertices, double-click to finish.");
}

function onTaskingPointSelected(latlng, containerPoint) {
  const target = {
    type: "Point",
    coordinates: [normalizeLongitude(latlng.lng), clampLatitude(latlng.lat)],
  };
  resetTaskingDrawState();
  L.circleMarker([target.coordinates[1], target.coordinates[0]], {
    radius: 5,
    color: "#ffd166",
    fillColor: "#ffd166",
    fillOpacity: 0.8,
    weight: 1,
  }).addTo(taskingDrawLayer);
  openTaskingForm({ targetType: "point", geometry: target, containerPoint });
}

function onTaskingAreaVertex(latlng) {
  state.taskingDrawPoints.push({
    lat: clampLatitude(latlng.lat),
    lng: normalizeLongitude(latlng.lng),
  });
  updateTaskingAreaSketch();
}

function finishTaskingArea(containerPoint) {
  const points = [...state.taskingDrawPoints];
  if (points.length > 1) {
    const last = points[points.length - 1];
    const prev = points[points.length - 2];
    const same = Math.abs(Number(last.lat) - Number(prev.lat)) < 1e-8 && Math.abs(Number(last.lng) - Number(prev.lng)) < 1e-8;
    if (same) points.pop();
  }
  if (points.length < 3) {
    toast("Need at least 3 vertices for an area target.");
    return;
  }
  const ring = points.map((pt) => [pt.lng, pt.lat]);
  ring.push([points[0].lng, points[0].lat]);
  const geometry = normalizeGeometryLongitudes({
    type: "Polygon",
    coordinates: [ring],
  });
  restoreTaskingDoubleClickZoom();
  state.taskingMode = "idle";
  updateTaskingCursor();
  openTaskingForm({ targetType: "area", geometry, containerPoint });
}

function formatTaskingDate(value) {
  if (!value) return "n/a";
  try {
    const dt = new Date(value);
    return dt.toISOString().replace("T", " ").slice(0, 19) + "Z";
  } catch (_) {
    return value;
  }
}

function renderTaskingOrdersList() {
  if (!taskingOrdersListEl || !taskingOrdersMetaEl) return;
  const rows = Array.isArray(state.taskingOrders) ? state.taskingOrders : [];
  taskingOrdersListEl.innerHTML = "";
  if (!rows.length) {
    taskingOrdersListEl.innerHTML = `<div class="meta">No tasking orders found.</div>`;
    taskingOrdersMetaEl.textContent = "No tasking orders loaded.";
    return;
  }
  taskingOrdersMetaEl.textContent = `Loaded ${rows.length} tasking order${rows.length === 1 ? "" : "s"}.`;
  rows.forEach((order) => {
    const card = document.createElement("div");
    card.className = "tasking-order-card";
    const status = (order.status || "unknown").toString();
    card.innerHTML = `
      <div class="row-main">
        <strong>${order.order_name || "(unnamed order)"}</strong>
        <span class="status-chip">${status}</span>
      </div>
      <div class="row-meta">Project: ${order.project_name || "-"}</div>
      <div class="row-meta">Product: ${order.sku || "-"}</div>
      <div class="row-meta">Window: ${formatTaskingDate(order.start)} to ${formatTaskingDate(order.end)}</div>
      <div class="row-meta">Geometry: ${order.geometry_type || "-"}</div>
      <div class="row-id">${order.id || "-"}</div>
    `;
    taskingOrdersListEl.appendChild(card);
  });
}

async function refreshTaskingOrders() {
  const params = new URLSearchParams({ limit: "120" });
  const contractId = selectedContractId();
  if (contractId) params.set("contract_id", contractId);
  const data = await apiJson(`/api/tasking/orders?${params.toString()}`);
  state.taskingOrders = Array.isArray(data.orders) ? data.orders : [];
  state.taskingRefreshAt = new Date().toISOString();
  renderTaskingOrdersList();
  refreshMapTimebarData();
}

async function refreshTaskingProjects() {
  const params = new URLSearchParams({ limit: "120" });
  const contractId = selectedContractId();
  if (contractId) params.set("contract_id", contractId);
  const data = await apiJson(`/api/tasking/projects?${params.toString()}`);
  state.taskingProjects = Array.isArray(data.projects) ? data.projects.filter(Boolean) : [];
  renderTaskingProjectSuggestions();
}

async function loadTaskingProducts() {
  const data = await apiJson("/api/tasking/products");
  state.taskingProducts = Array.isArray(data.products) ? data.products : [];
}

async function refreshTaskingPanel() {
  await Promise.all([
    refreshTaskingOrders(),
    refreshTaskingProjects(),
  ]);
}

async function submitTaskingOrder() {
  if (!state.taskingTargetGeometry || !state.taskingTargetType) {
    throw new Error("Select a target geometry first.");
  }
  const orderName = (taskingOrderNameEl?.value || "").trim();
  const projectName = (taskingProjectNameEl?.value || "").trim();
  const sku = (taskingProductEl?.value || "").trim();
  const startDate = toUtcIsoFromLocalInput(taskingStartEl?.value || "");
  const endDate = toUtcIsoFromLocalInput(taskingEndEl?.value || "");
  const cadence = (taskingCadenceEl?.value || "").trim();
  if (!orderName || !projectName || !sku || !startDate || !endDate) {
    throw new Error("Order name, project, product, start, and end are required.");
  }
  if (new Date(endDate).getTime() <= new Date(startDate).getTime()) {
    throw new Error("End date must be after start date.");
  }

  const payload = {
    target_type: state.taskingTargetType,
    geometry: state.taskingTargetGeometry,
    order_name: orderName,
    project_name: projectName,
    sku,
    start_date: startDate,
    end_date: endDate,
    revisit_period: state.taskingTargetType === "point" ? (cadence || null) : null,
    remapping_period: state.taskingTargetType === "area" ? (cadence || null) : null,
    contract_id: selectedContractId(),
  };
  const data = await apiJson("/api/tasking/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const order = data?.order || {};
  await refreshTaskingPanel();
  hideTaskingForm();
  resetTaskingDrawState();
  state.taskingTargetGeometry = null;
  state.taskingTargetType = null;
  toast(`Task accepted: ${order.id || "created"}`);
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

function updateSearchResultsHeader(visibleCount, totalCount = null) {
  const total = Number.isFinite(Number(totalCount)) ? Number(totalCount) : Number(visibleCount);
  if (searchResultsCountEl) searchResultsCountEl.textContent = `${visibleCount} Frames in View (${total} total)`;
  if (!searchResultsFilterMetaEl) return;
  if (!state.carouselFilterActive) {
    searchResultsFilterMetaEl.textContent = `Viewport filter active: showing ${visibleCount} of ${total}.`;
    searchResultsFilterMetaEl.style.display = "block";
    return;
  }
  const quickviewTotal = Math.max(0, Number(state.carouselQuickviewCount || 0));
  searchResultsFilterMetaEl.textContent = `Viewport filter active: showing ${visibleCount} of ${total}. Quickviews backed by l1d-sr: ${visibleCount} of ${quickviewTotal}.`;
  searchResultsFilterMetaEl.style.display = "block";
}

function resetCarouselLazyState() {
  state.carouselRenderItems = [];
  state.carouselRenderNextIndex = 0;
}

function makeCarouselCard(item, idx) {
  const thumb = assetProxyUrl(thumbnailUrl(item), {
    render: false,
    sourceHint: sourceIdForItem(item),
  });
  const card = document.createElement("button");
  card.className = "carousel-card";
  card.type = "button";
  card.dataset.itemId = item.id;
  const imageMarkup = thumb
    ? `<img data-src="${thumb}" loading="lazy" alt="thumbnail ${idx + 1}" />`
    : `<div class="thumb-missing">No preview available</div>`;
  card.innerHTML = `
    <div class="carousel-card-head">
      <label class="check-wrap">
        <input type="checkbox" data-select-id="${item.id}" />
        show
      </label>
    </div>
    ${imageMarkup}
    <div class="card-date">${formatCarouselMeta(item)}</div>
  `;
  card.addEventListener("click", (evt) => {
    const target = evt.target;
    if (target instanceof HTMLInputElement) return;
    state.selectedCarouselIds.add(item.id);
    setActiveCarouselCard(item.id);
    syncCarouselCheckboxes();
    if (state.compareMode) updateCompareModeState(item.id);
    focusFromCarousel(item, { preserveViewport: true }).catch((err) => toast(err.message));
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
      await refreshMapMode(false, { renderCarousel: false });
    });
  }
  const img = card.querySelector("img[data-src]");
  if (img) {
    img.addEventListener("error", () => {
      const fallback = document.createElement("div");
      fallback.className = "thumb-missing";
      fallback.textContent = "Preview unavailable";
      img.replaceWith(fallback);
    }, { once: true });
    lazyLoadCarouselImage(img);
  }
  return card;
}

function appendCarouselBatch() {
  if (!timeCarouselListEl || state.activeTab !== "explore") return;
  const items = state.carouselRenderItems || [];
  if (!items.length || state.carouselRenderNextIndex >= items.length) return;
  const start = state.carouselRenderNextIndex;
  const end = Math.min(items.length, start + CAROUSEL_BATCH_SIZE);
  for (let idx = start; idx < end; idx += 1) {
    const card = makeCarouselCard(items[idx], idx);
    timeCarouselListEl.appendChild(card);
  }
  state.carouselRenderNextIndex = end;
  syncCarouselCheckboxes();
}

function fillCarouselViewport() {
  if (!timeCarouselListEl || state.activeTab !== "explore") return;
  let safety = 0;
  while (
    state.carouselRenderNextIndex < (state.carouselRenderItems || []).length
    && timeCarouselListEl.scrollHeight <= (timeCarouselListEl.clientHeight + 8)
    && safety < 25
  ) {
    appendCarouselBatch();
    safety += 1;
  }
}

function maybeLoadMoreCarouselOnScroll() {
  if (!timeCarouselListEl || state.activeTab !== "explore") return;
  let remaining = timeCarouselListEl.scrollHeight - (timeCarouselListEl.scrollTop + timeCarouselListEl.clientHeight);
  let guard = 0;
  while (remaining <= CAROUSEL_SCROLL_THRESHOLD_PX && state.carouselRenderNextIndex < (state.carouselRenderItems || []).length && guard < 8) {
    appendCarouselBatch();
    remaining = timeCarouselListEl.scrollHeight - (timeCarouselListEl.scrollTop + timeCarouselListEl.clientHeight);
    guard += 1;
  }
}

function renderTimeCarousel(items, totalCount = null) {
  resetCarouselLazyState();
  timeCarouselListEl.innerHTML = "";
  state.carouselVisibleItems = [];
  if (!items.length) {
    updateSearchResultsHeader(0, totalCount);
    timeCarouselListEl.innerHTML = `<div class="meta">No frames intersect the current viewport.</div>`;
    updateLockButtonState();
    return;
  }

  const sorted = [...items].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
  state.carouselVisibleItems = sorted;
  updateSearchResultsHeader(sorted.length, totalCount);
  state.carouselRenderItems = sorted;
  state.carouselRenderNextIndex = 0;
  appendCarouselBatch();
  fillCarouselViewport();
}

function overviewItemsForCarousel() {
  return dedupeById(state.overviewItems.length ? state.overviewItems : state.items);
}

function viewportFilteredCarouselItems(bounds = map.getBounds()) {
  const source = overviewItemsForCarousel();
  if (!source.length) return [];
  return dedupeById(filterItemsToViewport(source, bounds));
}

function renderTimeCarouselForViewport(bounds = map.getBounds()) {
  if (state.activeTab !== "explore") return;
  const total = overviewItemsForCarousel().length;
  const visible = viewportFilteredCarouselItems(bounds);
  renderTimeCarousel(visible, total);
  refreshMapTimebarData();
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

function findRenderedCarouselCard(itemId) {
  if (!timeCarouselListEl) return null;
  return Array.from(timeCarouselListEl.querySelectorAll(".carousel-card")).find((card) => card.dataset.itemId === itemId) || null;
}

function setActiveCarouselCard(itemId, options = {}) {
  const autoScroll = Boolean(options.autoScroll);
  state.selectedCarouselId = itemId;
  if (state.activeTab === "explore" && itemId && !findRenderedCarouselCard(itemId)) {
    let guard = 0;
    while (!findRenderedCarouselCard(itemId) && state.carouselRenderNextIndex < (state.carouselRenderItems || []).length && guard < 80) {
      appendCarouselBatch();
      guard += 1;
    }
  }
  const cards = Array.from(timeCarouselListEl.querySelectorAll(".carousel-card"));
  cards.forEach((card) => {
    const selected = state.selectedCarouselIds.has(card.dataset.itemId);
    if (card.dataset.itemId === itemId) {
      card.classList.add("active");
      if (autoScroll) {
        card.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
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

function selectedVisibleOverviewItems() {
  const visibleIds = new Set((state.carouselVisibleItems || []).map((item) => item?.id).filter(Boolean));
  if (!visibleIds.size) return [];
  return selectedOverviewItems().filter((item) => visibleIds.has(item?.id));
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

function clearStackOutlines() {
  if (state.stackOutlineLayer) {
    map.removeLayer(state.stackOutlineLayer);
    state.stackOutlineLayer = null;
  }
}

function stackOutlineColor(index) {
  const hue = (index * 67) % 360;
  return `hsl(${hue}, 72%, 48%)`;
}

function renderDiscoveredStackOutlines(stacks) {
  clearStackOutlines();
  if (!Array.isArray(stacks) || !stacks.length) return;

  const seenIds = new Set();
  const features = [];
  stacks.forEach((stack, stackIndex) => {
    const stackItems = Array.isArray(stack?.items) ? stack.items : [];
    stackItems.forEach((item) => {
      if (!item?.geometry) return;
      const itemId = item.id || "";
      if (itemId && seenIds.has(itemId)) return;
      if (itemId) seenIds.add(itemId);
      features.push({
        type: "Feature",
        geometry: item.geometry,
        properties: {
          stack_id: stack.stack_id || `stack-${stackIndex + 1}`,
          stack_index: stackIndex,
          datetime: item.datetime || "",
          item_id: itemId,
        },
      });
    });
  });
  if (!features.length) return;

  state.stackOutlineLayer = L.geoJSON(
    {
      type: "FeatureCollection",
      features,
    },
    {
      interactive: false,
      style: (feature) => ({
        color: stackOutlineColor(Number(feature?.properties?.stack_index || 0)),
        weight: 2,
        opacity: 0.9,
        fillOpacity: 0,
      }),
    },
  ).addTo(map);
  state.stackOutlineLayer.bringToFront();
}

function thumbnailUrl(item) {
  return item.assets?.thumbnail || item.assets?.preview || item.assets?.visual || "";
}

function previewUrl(item) {
  return item.assets?.preview || item.assets?.thumbnail || item.assets?.visual || "";
}

function detailVisualUrl(item) {
  return item.assets?.visual_fullres || item.assets?.visual || item.assets?.preview || item.assets?.thumbnail || "";
}

function detailCloudMaskUrl(item) {
  return item.assets?.cloud_mask || "";
}

function detailCogAssetUrl(item, mode = state.detailLayerMode) {
  const layerMode = normalizeDetailLayerMode(mode);
  if (layerMode === "cloud_mask") {
    return detailCloudMaskUrl(item) || item.assets?.visual || "";
  }
  return item.assets?.visual || "";
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
  if (!isSatellogicItem(item)) return "";
  const layerMode = normalizeDetailLayerMode(state.detailLayerMode);
  const raw = detailCogAssetUrl(item, layerMode);
  const source = extractCogSourceUrl(raw);
  if (!source) return "";
  const params = new URLSearchParams();
  params.set("url", source);
  const contractId = selectedSatellogicContractId();
  if (contractId) params.set("contract_id", contractId);
  const scale = Number(zoomLevel) >= DETAIL_COG_HIGHRES_ZOOM ? 2 : 1;
  params.set("scale", String(scale));
  if (DETAIL_COG_TILE_BUFFER > 0) params.set("buffer", String(DETAIL_COG_TILE_BUFFER));
  params.set("render_layer", layerMode === "natural" ? "raw" : layerMode);
  const cloudMaskRaw = detailCloudMaskUrl(item);
  const cloudMaskSource = extractCogSourceUrl(cloudMaskRaw);
  if (cloudMaskSource) params.set("cloud_mask_url", cloudMaskSource);
  params.set("tileMatrixSetId", "WebMercatorQuad");
  params.set("format", "png");
  const modeBands = {
    natural: [1, 2, 3],
    false_color: [4, 1, 2],
    ndvi: [3, 4],
    cloud_mask: [1],
  };
  const bands = modeBands[layerMode] || [1, 2, 3];
  bands.forEach((band) => params.append("bidx", String(band)));
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

function mapBoundsSignature(bounds = map.getBounds()) {
  return [
    bounds.getWest().toFixed(5),
    bounds.getSouth().toFixed(5),
    bounds.getEast().toFixed(5),
    bounds.getNorth().toFixed(5),
  ].join(",");
}

function renderItemSignature(items = []) {
  return items
    .map((item) => {
      const id = (item?.id || item?.outcome_id || item?.datetime || "").toString();
      return `${id}:${normalizeCollectionId(item?.collection)}:${normalizeSourceId(sourceIdForItem(item))}`;
    })
    .join("|");
}

function detailRenderSignature(detailVisible, overlayItems, vectorItems) {
  return [
    "detail",
    `z:${map.getZoom()}`,
    `layer:${normalizeDetailLayerMode(state.detailLayerMode)}`,
    `cog:${state.useCogTileProxy ? 1 : 0}`,
    `b:${mapBoundsSignature()}`,
    `vis:${renderItemSignature(detailVisible)}`,
    `ov:${renderItemSignature(overlayItems)}`,
    `vec:${renderItemSignature(vectorItems)}`,
    `sel:${Array.from(state.selectedCarouselIds).sort().join(",")}`,
  ].join(";");
}

function overviewRenderSignature(overviewVisible, vectorItems) {
  return [
    "overview",
    `z:${map.getZoom()}`,
    `b:${mapBoundsSignature()}`,
    `vis:${renderItemSignature(overviewVisible)}`,
    `vec:${renderItemSignature(vectorItems)}`,
    `sel:${Array.from(state.selectedCarouselIds).sort().join(",")}`,
  ].join(";");
}

function overlayBoundsFromItem(item) {
  const raw = item?.__overlayBounds;
  if (!Array.isArray(raw) || raw.length !== 2) return null;
  const sw = raw[0];
  const ne = raw[1];
  if (!Array.isArray(sw) || !Array.isArray(ne) || sw.length < 2 || ne.length < 2) return null;
  try {
    const bounds = L.latLngBounds([Number(sw[0]), Number(sw[1])], [Number(ne[0]), Number(ne[1])]);
    return bounds.isValid() ? bounds : null;
  } catch (_) {
    return null;
  }
}

function overlayBoundsListFromItem(item) {
  const rawList = item?.__overlayBoundsList;
  if (Array.isArray(rawList) && rawList.length) {
    const parsed = rawList
      .map((raw) => {
        if (!Array.isArray(raw) || raw.length !== 2) return null;
        const sw = raw[0];
        const ne = raw[1];
        if (!Array.isArray(sw) || !Array.isArray(ne) || sw.length < 2 || ne.length < 2) return null;
        try {
          const bounds = L.latLngBounds([Number(sw[0]), Number(sw[1])], [Number(ne[0]), Number(ne[1])]);
          return bounds.isValid() ? bounds : null;
        } catch (_) {
          return null;
        }
      })
      .filter(Boolean);
    if (parsed.length) return parsed;
  }
  const single = overlayBoundsFromItem(item);
  return single ? [single] : [];
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
  if (isSatellogicItem(item)) return;
  if (isSentinelItem(item) && !state.layerControl.sentinelStacOverlayEnabled) return;
  const raw = state.mapMode === "detail" ? detailVisualUrl(item) : previewUrl(item);
  const src = assetProxyUrl(raw, {
    render: state.mapMode === "detail",
    sourceHint: sourceIdForItem(item),
  });
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

  const showOutlines = Boolean(options.showOutlines ?? true);
  const showOutlinesForItem = (item) => {
    if (!showOutlines) return false;
    const sourceId = sourceIdForItem(item);
    if (sourceId === "merlin-s2") return Boolean(state.layerControl.sentinelFramesEnabled);
    if (sourceId === "satellogic") return Boolean(state.layerControl.satellogicFramesEnabled);
    return true;
  };
  const vectorSource = Array.isArray(options.vectorItems) && options.vectorItems.length ? options.vectorItems : items;
  const features = vectorSource
    .filter((item) => {
      const geomType = (item?.geometry?.type || "").toString().toLowerCase();
      return item?.geometry && (geomType === "polygon" || geomType === "multipolygon");
    })
    .map((item, itemIndex) => ({
      type: "Feature",
      geometry: item.geometry,
      properties: {
        itemIndex,
        id: item.id,
        datetime: item.datetime,
        cloud_cover: item.cloud_cover,
        thumbnail: assetProxyUrl(
          mode === "detail" ? (previewUrl(item) || thumbnailUrl(item) || detailVisualUrl(item)) : modeSourceUrl(item, mode),
          { render: false, sourceHint: sourceIdForItem(item) },
        ),
        satellite_name: item.satellite_name || "n/a",
        gsd: item.gsd,
        selected: isSelectedItem(item),
        outlines_enabled: showOutlinesForItem(item),
      },
    }));

  state.mapVectorLayer = L.geoJSON(features, {
    interactive: false,
    style: (feature) => {
      const selected = Boolean(feature?.properties?.selected);
      const outlinesEnabled = Boolean(feature?.properties?.outlines_enabled);
      if (!outlinesEnabled) {
        return {
          color: "transparent",
          weight: 0,
          fillOpacity: 0,
          opacity: 0,
        };
      }
      return {
        color: selected ? "#1e63d8" : "#ff8a00",
        weight: selected ? 2.4 : 1.8,
        fillOpacity: 0,
        opacity: selected ? 0.98 : 0.84,
      };
    },
  }).addTo(map);

  if (features.some((feature) => Boolean(feature?.properties?.outlines_enabled))) {
    state.mapVectorLayer.bringToFront();
  }

  state.mapThumbOverlayLayer = L.layerGroup().addTo(map);
  state.mapThumbMarkerLayer = L.layerGroup().addTo(map);

  const overlayItemsProvided = Array.isArray(options.overlayItems);
  let overlaySourceItems = overlayItemsProvided ? options.overlayItems : items;
  if (mode === "detail" && !overlayItemsProvided && selectedOverview.length === 0) {
    overlaySourceItems = latestStripPerArea(overlaySourceItems);
  }
  const shouldRenderOverlayForItem = (item) => {
    if (isSatellogicItem(item)) {
      // Never render Satellogic thumbnail/preview overlays on map.
      // Satellogic map imagery must come from COG tiles in detail mode.
      return mode === "detail";
    }
    if (!isSentinelItem(item)) return true;
    if (!state.layerControl.sentinelStacOverlayEnabled) return false;
    return isSelectedItem(item);
  };
  const withThumbnailsRaw = overlaySourceItems.filter((item) => (
    item.geometry
    && shouldRenderOverlayForItem(item)
    && (mode === "detail" ? (previewUrl(item) || detailVisualUrl(item)) : modeSourceUrl(item, mode))
  ));
  const withThumbnails = mode === "detail"
    ? [...withThumbnailsRaw].sort((a, b) => {
      const layerDelta = overlayPriority(a) - overlayPriority(b);
      if (layerDelta !== 0) return layerDelta;
      return (a.datetime || "").localeCompare(b.datetime || "");
    })
    : withThumbnailsRaw;
  const maxOverlays = mode === "detail" ? withThumbnails.length : Math.min(12, withThumbnails.length);
  const maxMarkers = mode === "detail" ? 0 : 40;
  const overlayOpacity = mode === "detail" ? 1.0 : 0.32;
  const overlayItems = mode === "detail"
    ? withThumbnails.slice(Math.max(0, withThumbnails.length - maxOverlays))
    : withThumbnails.slice(0, maxOverlays);
  const overlayEntries = overlayItems.map((item, index) => ({
    item,
    visualIndex: index,
    zIndex: 300 + overlayPriority(item) + index,
  }));
  const loadEntries = mode === "detail"
    ? [...overlayEntries].reverse()
    : overlayEntries;

  const effectiveLoadEntries = (mode === "detail" && state.useCogTileProxy)
    ? loadEntries.slice(0, Math.max(1, DETAIL_FULLRES_VISIBLE_LIMIT))
    : loadEntries;

  const ensureSourceOverlayPane = (item) => {
    const sourceId = sourceIdForItem(item);
    const paneId = sourceId === "satellogic" ? "newSatOverlayPane" : "merlinOverlayPane";
    const zIndex = sourceId === "satellogic" ? "285" : "270";
    if (!map.getPane(paneId)) {
      const pane = map.createPane(paneId);
      pane.style.zIndex = zIndex;
      pane.style.pointerEvents = "none";
    }
    return paneId;
  };

  if (mode === "detail" && state.useCogTileProxy && effectiveLoadEntries.length) {
    const prefetchTemplate = effectiveLoadEntries
      .map((entry) => detailTileTemplateUrl(entry.item, map.getZoom()))
      .find((value) => Boolean(value));
    const topTemplate = prefetchTemplate || "";
    if (topTemplate) {
      const center = map.getCenter();
      const tileCenter = latLngToTileXY(center.lat, center.lng, map.getZoom());
      const url = resolveTileTemplate(topTemplate, tileCenter.z, tileCenter.x, tileCenter.y);
      queuePrefetchUrl(url);
    }
  }

  effectiveLoadEntries.forEach(({ item, visualIndex, zIndex }) => {
    const overlayPaneId = ensureSourceOverlayPane(item);
    // For Satellogic detail rendering, avoid fragmented viewport clipping bounds.
    // Those fragments can occasionally omit edge tile rows/columns and create
    // visible vertical/horizontal gaps. Use full frame bounds for stable coverage.
    const overlayBoundsList = (mode === "detail" && isSatellogicItem(item))
      ? (() => {
        const full = boundsFromGeometry(item.geometry);
        return full ? [full] : [];
      })()
      : overlayBoundsListFromItem(item);
    if (!overlayBoundsList.length) {
      const fallbackBounds = boundsFromGeometry(item.geometry);
      if (fallbackBounds) overlayBoundsList.push(fallbackBounds);
    }
    if (!overlayBoundsList.length) return;

    overlayBoundsList.forEach((bounds) => {
      if (mode === "detail" && state.useCogTileProxy) {
        const tileTemplate = detailTileTemplateUrl(item, map.getZoom());
        if (tileTemplate) {
          const tileLayer = L.tileLayer(tileTemplate, {
            pane: overlayPaneId,
            opacity: overlayOpacity,
            bounds,
            tileSize: 256,
            className: "cog-tile-layer",
            maxZoom: 22,
            updateWhenIdle: true,
            updateWhenZooming: false,
            keepBuffer: 2,
            zIndex,
            crossOrigin: true,
          });
          tileLayer.on("tileerror", () => {
            if (!state.useCogTileProxy) return;
            const itemSourceId = sourceIdForItem(item);
            if (itemSourceId === "satellogic") {
              if (!state.tileProxyWarned) {
                state.tileProxyWarned = true;
                toast("Satellogic COG tiles unavailable for this frame; thumbnail fallback is disabled.");
              }
              return;
            }
            state.tileProxyErrorCount += 1;
            if (state.tileProxyErrorCount < DETAIL_TILE_PROXY_ERROR_THRESHOLD) return;
            state.useCogTileProxy = false;
            if (!state.tileProxyWarned) {
              state.tileProxyWarned = true;
              toast("COG tile API unstable; using fallback rendering");
            }
            refreshMapMode(true).catch(() => {});
          });
          tileLayer.on("tileload", () => {
            if (state.tileProxyErrorCount > 0) state.tileProxyErrorCount -= 1;
          });
          tileLayer.addTo(state.mapThumbOverlayLayer);
          return;
        }
      }

      if (mode === "detail" && isSatellogicItem(item)) {
        return;
      }
      const srcCfg = compareOverlaySource(item, mode, visualIndex);
      const src = assetProxyUrl(srcCfg.raw, {
        render: srcCfg.render,
        sourceHint: sourceIdForItem(item),
      });
      if (!src) return;
      L.imageOverlay(src, bounds, {
        pane: overlayPaneId,
        opacity: overlayOpacity,
        crossOrigin: true,
        interactive: false,
        zIndex,
        className: "thumb-footprint-overlay",
      }).addTo(state.mapThumbOverlayLayer);
    });
  });

  withThumbnails.slice(0, maxMarkers).forEach((item) => {
    const bounds = boundsFromGeometry(item.geometry);
    const src = assetProxyUrl(modeSourceUrl(item, mode), {
      render: false,
      sourceHint: sourceIdForItem(item),
    });
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
  if (frameSelectEl) frameSelectEl.innerHTML = "";
  if (beforeSelectEl) beforeSelectEl.innerHTML = "";
  if (afterSelectEl) afterSelectEl.innerHTML = "";

  items.forEach((item, idx) => {
    const label = `${idx + 1}. ${item.datetime || "n/a"} (${item.id.slice(0, 10)})`;
    [frameSelectEl, beforeSelectEl, afterSelectEl].filter(Boolean).forEach((sel) => {
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = label;
      sel.appendChild(opt);
    });
  });

  if (beforeSelectEl && afterSelectEl && items.length > 0) {
    beforeSelectEl.selectedIndex = Math.min(items.length - 1, 1);
    afterSelectEl.selectedIndex = 0;
  }

  if (timelineEl) {
    timelineEl.max = String(Math.max(0, items.length - 1));
    timelineEl.value = "0";
  }
  showFrame(0);
}

function showFrame(index) {
  const item = state.items[index];
  if (!item) return;
  const src = assetProxyUrl(previewUrl(item), { sourceHint: sourceIdForItem(item) });
  if (framePreviewEl) framePreviewEl.src = src || "";
  if (timelineEl) timelineEl.value = String(index);
  updateActiveFrameOverlay(item);
}

function selectedFrameIds() {
  const selected = frameSelectEl ? Array.from(frameSelectEl.selectedOptions).map((opt) => opt.value) : [];
  if (selected.length > 0) return selected;
  return state.items.slice(0, 12).map((item) => item.id);
}

async function fetchArchiveItems(payload) {
  const started = performance.now();
  debugLog("archive search request", {
    source: payload.source_id,
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
    source: payload.source_id,
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

async function focusFromCarousel(overviewItem, options = {}) {
  if (!overviewItem) return;
  const fitToFrame = Boolean(options.fitToFrame);
  const preserveViewport = Boolean(options.preserveViewport);
  const sourceId = sourceIdForItem(overviewItem);
  const isSatellogicFocus = sourceId === "satellogic";
  const targetSatellogicCollection = isSatellogicFocus
    ? ((collectionForSource("satellogic") || "l1d-sr").toString().trim() || "l1d-sr")
    : "";
  const targetSatellogicCollectionNorm = normalizeCollectionId(targetSatellogicCollection);
  if (isSatellogicFocus) {
    state.useCogTileProxy = true;
  }
  setActiveCarouselCard(overviewItem.id);
  if (state.compareMode && state.compareFrames.length) {
    const idx = state.compareFrames.findIndex((item) => item.id === overviewItem.id);
    if (idx >= 0) {
      compareRangeEl.value = String(idx);
      updateCompareDateTag();
    }
  }

  if (isSentinelItem(overviewItem) && state.layerControl.sentinelWmtsEnabled && !state.layerControl.sentinelStacOverlayEnabled) {
    const bounds = boundsFromGeometry(overviewItem.geometry || state.currentAoi || null);
    if (bounds) {
      if (fitToFrame) {
        state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
        map.fitBounds(bounds, { padding: [20, 20], maxZoom: 17 });
      } else if (!preserveViewport && map.getZoom() < DETAIL_ZOOM_THRESHOLD) {
        state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
        map.setZoom(DETAIL_ZOOM_THRESHOLD);
        state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
        map.panTo(bounds.getCenter(), { animate: true, duration: 0.35 });
      }
    }
    await refreshMapMode(false, { renderCarousel: false });
    toast("Sentinel-2 STAC selected. Enable step 2 overlay toggle to render STAC imagery.");
    return;
  }

  const sourceItems = isSatellogicFocus
    ? (state.items || []).filter((item) => (
      isSatellogicItem(item)
      && normalizeCollectionId(item.collection) === targetSatellogicCollectionNorm
    ))
    : (state.items || []);

  let tiles = [];
  if (overviewItem.outcome_id) {
    tiles = sourceItems.filter((item) => item.outcome_id === overviewItem.outcome_id);
  }
  if (!tiles.length) {
    tiles = nearestCaptureTiles(sourceItems, overviewItem.datetime);
  }

  if (!tiles.length) {
    const geom = overviewItem.geometry || state.currentAoi || geometryFromMapBounds();
    const centerDt = overviewItem.datetime ? new Date(overviewItem.datetime) : new Date();
    const start = new Date(centerDt.getTime() - (3 * 24 * 3600 * 1000)).toISOString();
    const end = new Date(centerDt.getTime() + (3 * 24 * 3600 * 1000)).toISOString();
    const collectionId = sourceId === "satellogic"
      ? targetSatellogicCollection
      : ((overviewItem.collection || state.layerControl.sentinelBaseCollectionId || "sentinel-2-l2a").toString().trim() || "sentinel-2-l2a");

    const detailPayload = {
      ...buildSearchPayloadForSource(geom, sourceId, collectionId, DETAIL_MAX_QUERY_LIMIT),
      start_date: start,
      end_date: end,
    };
    const fetched = await fetchArchiveItems(detailPayload);
    const fetchedForCollection = sourceId === "satellogic"
      ? fetched.filter((item) => normalizeCollectionId(item.collection) === targetSatellogicCollectionNorm)
      : fetched;
    tiles = overviewItem.outcome_id
      ? fetchedForCollection.filter((item) => item.outcome_id === overviewItem.outcome_id)
      : nearestCaptureTiles(fetchedForCollection, overviewItem.datetime);
  }

  if (!tiles.length) {
    toast("No matching source tiles found for this thumbnail");
    return;
  }

  if (!preserveViewport && map.getZoom() < DETAIL_ZOOM_THRESHOLD) {
    state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
    map.setZoom(DETAIL_ZOOM_THRESHOLD);
  }

  state.detailItems = dedupeById(tiles);
  state.mapMode = "detail";
  const visibleTiles = filterItemsToViewport(state.detailItems);
  const renderTiles = topCaptureOnly(visibleTiles);
  drawResults(renderTiles, "detail", false, {
    vectorItems: stripOutlineVectorItems(renderTiles),
    showOutlines: true,
  });
  updateActiveFrameOverlay(renderTiles[0]);

  const bounds = boundsFromGeometry(overviewItem.geometry || state.detailItems[0].geometry);
  if (bounds) {
    if (fitToFrame) {
      state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
      map.fitBounds(bounds, { padding: [20, 20], maxZoom: 17 });
    } else if (!preserveViewport) {
      state.skipMapRefreshEvents = Math.min(6, state.skipMapRefreshEvents + 2);
      map.panTo(bounds.getCenter(), { animate: true, duration: 0.4 });
    }
  }
}

function buildDetailRequestKey(payload) {
  const b = map.getBounds();
  return JSON.stringify({
    source: payload.source_id || "",
    collection: payload.collection_id || "",
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
    source: payload.source_id || "",
    collection: payload.collection_id || "",
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

function clipBoundsListFromTileCells(cellSet, zoom, tileSize = 256) {
  const rows = new Map();
  cellSet.forEach((key) => {
    const [xRaw, yRaw] = key.split(":");
    const x = Number(xRaw);
    const y = Number(yRaw);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (!rows.has(y)) rows.set(y, []);
    rows.get(y).push(x);
  });

  const yValues = Array.from(rows.keys()).sort((a, b) => a - b);
  const segmentsByY = new Map();
  yValues.forEach((y) => {
    const xs = Array.from(new Set(rows.get(y))).sort((a, b) => a - b);
    const segments = [];
    let start = null;
    let prev = null;
    xs.forEach((x, idx) => {
      if (start === null) {
        start = x;
        prev = x;
        if (idx === xs.length - 1) segments.push({ x0: start, x1: prev });
        return;
      }
      if (x === prev + 1) {
        prev = x;
        if (idx === xs.length - 1) segments.push({ x0: start, x1: prev });
      } else {
        segments.push({ x0: start, x1: prev });
        start = x;
        prev = x;
        if (idx === xs.length - 1) segments.push({ x0: start, x1: prev });
      }
    });
    segmentsByY.set(y, segments);
  });

  const finalized = [];
  let activeByKey = new Map();
  yValues.forEach((y) => {
    const nextActive = new Map();
    const segments = segmentsByY.get(y) || [];
    segments.forEach((segment) => {
      const key = `${segment.x0}:${segment.x1}`;
      const active = activeByKey.get(key);
      if (active && active.y1 === y - 1) {
        active.y1 = y;
        nextActive.set(key, active);
      } else {
        nextActive.set(key, { x0: segment.x0, x1: segment.x1, y0: y, y1: y });
      }
    });
    activeByKey.forEach((rect, key) => {
      if (!nextActive.has(key)) finalized.push(rect);
    });
    activeByKey = nextActive;
  });
  activeByKey.forEach((rect) => finalized.push(rect));

  const rects = finalized
    .sort((a, b) => ((a.y0 - b.y0) || (a.x0 - b.x0)));
  if (rects.length > DETAIL_VISIBLE_MOSAIC_MAX_CLIP_BOUNDS_PER_ITEM) {
    // Avoid truncating complex fragment lists, which can drop edge tile columns.
    // Caller will fall back to full geometry bounds for this item.
    return [];
  }

  return rects.map((rect) => {
    const nw = map.unproject(L.point(rect.x0 * tileSize, rect.y0 * tileSize), zoom);
    const se = map.unproject(L.point((rect.x1 + 1) * tileSize, (rect.y1 + 1) * tileSize), zoom);
    const bounds = L.latLngBounds(nw, se);
    return [
      [bounds.getSouth(), bounds.getWest()],
      [bounds.getNorth(), bounds.getEast()],
    ];
  });
}

function stripOutlineVectorItems(fallbackItems = []) {
  const fromQuickview = dedupeById(Array.isArray(state.outlineItems) ? state.outlineItems : []);
  if (fromQuickview.length) return fromQuickview;
  const fromOverview = dedupeById(Array.isArray(state.overviewItems) ? state.overviewItems : []);
  if (fromOverview.length) return fromOverview;
  const fromFallback = dedupeById(Array.isArray(fallbackItems) ? fallbackItems : []);
  if (fromFallback.length) return fromFallback;
  return dedupeById(Array.isArray(state.items) ? state.items : []);
}

function latestVisibleStripMosaic(items) {
  if (!Array.isArray(items) || !items.length) return [];

  const sortedNewest = [...items].sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));
  const prepared = sortedNewest
    .map((item, idx) => ({
      item,
      key: item?.id || item?.outcome_id || `${item?.datetime || "n/a"}-${idx}`,
      bounds: boundsFromGeometry(item?.geometry),
    }))
    .filter((entry) => entry.bounds);
  if (!prepared.length) return [];

  const pixelBounds = map.getPixelBounds();
  const tileSize = 256;
  const minTileX = Math.floor(pixelBounds.min.x / tileSize);
  const maxTileX = Math.floor((pixelBounds.max.x - 1) / tileSize);
  const minTileY = Math.floor(pixelBounds.min.y / tileSize);
  const maxTileY = Math.floor((pixelBounds.max.y - 1) / tileSize);
  const tileCount = Math.max(0, (maxTileX - minTileX + 1) * (maxTileY - minTileY + 1));
  if (!tileCount || tileCount > DETAIL_VISIBLE_MOSAIC_MAX_TILE_CELLS) {
    return latestStripPerArea(prepared.map((entry) => entry.item));
  }

  const selected = new Set();
  const selectedCellSets = new Map();
  const zoom = map.getZoom();
  for (let tx = minTileX; tx <= maxTileX; tx += 1) {
    for (let ty = minTileY; ty <= maxTileY; ty += 1) {
      const nw = map.unproject(L.point(tx * tileSize, ty * tileSize), zoom);
      const se = map.unproject(L.point((tx + 1) * tileSize, (ty + 1) * tileSize), zoom);
      const tileBounds = L.latLngBounds(nw, se);
      for (let i = 0; i < prepared.length; i += 1) {
        const entry = prepared[i];
        if (entry.bounds.intersects(tileBounds)) {
          selected.add(entry.key);
          const cellKey = `${tx}:${ty}`;
          const prior = selectedCellSets.get(entry.key) || new Set();
          prior.add(cellKey);
          selectedCellSets.set(entry.key, prior);
          break;
        }
      }
    }
  }

  if (!selected.size) return latestStripPerArea(prepared.map((entry) => entry.item));
  return prepared
    .filter((entry) => selected.has(entry.key))
    .map((entry) => {
      const cellSet = selectedCellSets.get(entry.key);
      if (!cellSet || !cellSet.size) return entry.item;
      const boundsList = clipBoundsListFromTileCells(cellSet, zoom, tileSize);
      if (!boundsList.length) return entry.item;
      return {
        ...entry.item,
        __overlayBoundsList: boundsList,
        __overlayBounds: boundsList[0],
      };
    });
}

function latestVisibleStripMosaicPerSource(items) {
  if (!Array.isArray(items) || !items.length) return [];
  const grouped = new Map();
  items.forEach((item) => {
    const sourceId = sourceIdForItem(item);
    const prior = grouped.get(sourceId) || [];
    prior.push(item);
    grouped.set(sourceId, prior);
  });
  const merged = [];
  grouped.forEach((rows) => {
    merged.push(...latestVisibleStripMosaic(rows));
  });
  return dedupeById(merged).sort((a, b) => {
    const priorityDelta = overlayPriority(a) - overlayPriority(b);
    if (priorityDelta !== 0) return priorityDelta;
    return (a.datetime || "").localeCompare(b.datetime || "");
  });
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

async function refreshMapMode(force = false, options = {}) {
  const renderCarousel = options.renderCarousel !== false;
  if (!state.searchParams && !state.items.length) return;
  const viewportBounds = map.getBounds();

  if (map.getZoom() >= DETAIL_ZOOM_THRESHOLD) {
    const paddedBounds = viewportBounds.pad(DETAIL_FETCH_PADDING);
    const detailSourceId = normalizeSourceId(state.searchParams?.source_id || selectedSourceId());
    const detailCollectionId = detailSourceId === "satellogic"
      ? "l1d-sr"
      : ((state.searchParams?.collection_id || state.layerControl.sentinelBaseCollectionId || "sentinel-2-l2a").toString().trim() || "sentinel-2-l2a");
    const detailPayload = {
      ...state.searchParams,
      source_id: detailSourceId,
      geometry: geometryFromBounds(paddedBounds),
      collection_id: detailCollectionId,
      contract_id: detailSourceId === "satellogic" ? selectedSatellogicContractId() : null,
      limit: DETAIL_MAX_QUERY_LIMIT,
    };
    const skipSentinelDetailFetch = (
      detailSourceId === "merlin-s2"
      && state.layerControl.sentinelWmtsEnabled
      && !state.layerControl.sentinelStacOverlayEnabled
    );
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
    if (needFetch && !coverageValid && canFetchNow && !skipSentinelDetailFetch) {
      debugLog("detail fetch", { zoom: map.getZoom(), requestKey });
      try {
        const items = await fetchArchiveItems(detailPayload);
        state.detailItems = dedupeById(items);
      } catch (err) {
        debugLog("detail fetch failed", {
          source: detailSourceId,
          collection: detailCollectionId,
          error: err?.message || String(err),
        });
        state.detailItems = [];
      }
      state.lastDetailRequestKey = requestKey;
      state.lastDetailFetchAt = Date.now();
      state.lastDetailCoverageBounds = paddedBounds;
      state.lastDetailCoverageZoom = map.getZoom();
      state.lastDetailContextKey = contextKey;
      debugLog("detail fetch result", { detailItems: state.detailItems.length });
    } else if (skipSentinelDetailFetch) {
      state.lastDetailRequestKey = requestKey;
      state.lastDetailFetchAt = Date.now();
      state.lastDetailCoverageBounds = paddedBounds;
      state.lastDetailCoverageZoom = map.getZoom();
      state.lastDetailContextKey = contextKey;
      state.detailItems = [];
      debugLog("detail fetch skipped (Sentinel WMTS baseline mode)");
    } else if (coverageValid) {
      debugLog("detail fetch skipped (coverage cache)");
    } else if (!canFetchNow) {
      debugLog("detail fetch skipped (cooldown)");
    }

    state.mapMode = "detail";
    let detailCandidates = dedupeById([...(state.detailItems || []), ...(state.items || [])]);
    if (!detailCandidates.length) detailCandidates = latestCaptureTiles(state.items);
    let detailVisible = filterItemsToViewport(detailCandidates, viewportBounds);
    if (!detailVisible.length) {
      detailVisible = filterItemsToViewport(detailCandidates, viewportBounds.pad(DETAIL_TILE_BUFFER_PAD));
    }
    let overlayItems = latestVisibleStripMosaicPerSource(detailVisible);
    const selectedOverviews = selectedOverviewItems();
    if (selectedOverviews.length) {
      const selectedTiles = detailTilesForOverviewItems(selectedOverviews, detailCandidates);
      const selectedVisible = filterItemsToViewport(dedupeById(selectedTiles), viewportBounds);
      if (selectedVisible.length) overlayItems = selectedVisible;
    }
    const vectorItems = stripOutlineVectorItems(detailCandidates);
    const renderSig = detailRenderSignature(detailVisible, overlayItems, vectorItems);
    if (renderSig !== state.lastMapRenderSignature) {
      drawResults(detailVisible, "detail", false, {
        overlayItems,
        vectorItems,
        showOutlines: true,
      });
      state.lastMapRenderSignature = renderSig;
    }
    if (renderCarousel) renderTimeCarouselForViewport(viewportBounds);
    const sel = state.selectedCarouselIds.size;
    searchMetaEl.textContent = `Mode: detail (zoom ${map.getZoom()}) • strips: ${detailVisible.length} • overlays(latest-visible per source): ${overlayItems.length} • policy: ${state.browseTilePolicy} • layer: ${detailLayerLabel()}${sel ? ` • selected: ${sel}` : ""}`;
    syncCarouselCheckboxes();
    updateCompareModeState();
    return;
  }

  state.mapMode = "overview";
  const overview = orderedOverviewDisplayItems();
  const overviewVisible = filterItemsToViewport(overview, viewportBounds);
  const overviewVectorItems = stripOutlineVectorItems(overviewVisible);
  const overviewSig = overviewRenderSignature(overviewVisible, overviewVectorItems);
  if (overviewSig !== state.lastMapRenderSignature) {
    drawResults(overviewVisible, "overview", false, {
      vectorItems: overviewVectorItems,
      showOutlines: true,
    });
    state.lastMapRenderSignature = overviewSig;
  }
  if (renderCarousel) renderTimeCarouselForViewport(viewportBounds);
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
    drawResults(renderTiles, "detail", false, {
      vectorItems: stripOutlineVectorItems(renderTiles),
      showOutlines: true,
    });
  } else {
    drawResults([frame], "overview", false, {
      vectorItems: stripOutlineVectorItems([frame]),
      showOutlines: true,
    });
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
  clearStackOutlines();
  const geometry = normalizeGeometryLongitudes(geometryFromBounds(map.getBounds()));
  updateSearchFieldsFromGeometry(geometry);
  state.currentAoi = geometry;

  const zoomedOutSatellogicCollectionId = map.getZoom() <= ZOOMED_OUT_SEARCH_MAX_ZOOM
    ? STACK_DISCOVERY_COLLECTION_ID
    : null;
  const layerWarnings = new Set();
  const successfulSearchParams = [];
  state.sourceLayerStatus = {};

  resetLayerSearchResults();
  state.lastDetailRequestKey = null;
  state.lastDetailCoverageBounds = null;
  state.lastDetailCoverageZoom = null;
  state.lastDetailContextKey = null;
  state.lastMapRenderSignature = "";
  state.prefetchTileUrlSeen.clear();
  state.useCogTileProxy = Boolean(state.layerControl.satellogicOverlayEnabled);
  state.tileProxyWarned = false;
  state.tileProxyErrorCount = 0;
  state.detailItems = [];
  state.outlineItems = [];
  state.timeline.userAdjusted = false;
  state.selectedCarouselIds.clear();
  state.selectedCarouselId = null;
  if (state.compareMode) setCompareMode(false);

  const runLayerSearch = async (label, payload) => {
    try {
      const items = await fetchArchiveItems(payload);
      const sourceId = normalizeSourceId(payload.source_id);
      state.sourceLayerStatus[`${sourceId}:${payload.collection_id}`] = "active";
      return items;
    } catch (err) {
      const sourceId = normalizeSourceId(payload.source_id);
      state.sourceLayerStatus[`${sourceId}:${payload.collection_id}`] = "degraded";
      layerWarnings.add(`${label}: ${err.message}`);
      return [];
    }
  };

  const tasks = [];

  if (state.layerControl.sentinelBaseEnabled) {
    const sentinelBaseCollectionId = collectionForSource("merlin-s2", { allowNone: true });
    if (!sentinelBaseCollectionId) {
      layerWarnings.add("Sentinel-2 base: skipped (collection=None)");
      state.sourceLayerStatus["merlin-s2:base"] = "disabled";
    } else {
      const payload = buildSearchPayloadForSource(geometry, "merlin-s2", sentinelBaseCollectionId);
      tasks.push((async () => {
        const items = await runLayerSearch("Sentinel-2", payload);
        state.layerSearchResults.sentinelBase = {
          collectionId: sentinelBaseCollectionId,
          items,
          overviewItems: items,
        };
        if (items.length) successfulSearchParams.push(payload);
      })());
    }
  }

  if (state.layerControl.satellogicOverlayEnabled) {
    const requestedSatellogicCollection = collectionForSource("satellogic", { allowNone: true });
    if (!requestedSatellogicCollection) {
      layerWarnings.add("Satellogic overlay: skipped (collection=None)");
      state.sourceLayerStatus["satellogic:overlay"] = "disabled";
    } else {
      const primarySatellogicCollection = zoomedOutSatellogicCollectionId || requestedSatellogicCollection;
      const payload = buildSearchPayloadForSource(geometry, "satellogic", primarySatellogicCollection);
      tasks.push((async () => {
        const items = await runLayerSearch("Satellogic overlay", payload);
        let quickviewVisualItems = [];
        if (primarySatellogicCollection === "quickview-visual") {
          quickviewVisualItems = items;
        } else {
          const quickviewVisualPayload = buildSearchPayloadForSource(
            geometry,
            "satellogic",
            "quickview-visual",
            Math.max(Number(limitEl.value || 250), 300),
          );
          quickviewVisualItems = await runLayerSearch("Satellogic quickview visual", quickviewVisualPayload);
        }
        let overviewItems = items;
        if (primarySatellogicCollection !== STACK_DISCOVERY_COLLECTION_ID) {
          const overviewPayload = buildSearchPayloadForSource(
            geometry,
            "satellogic",
            STACK_DISCOVERY_COLLECTION_ID,
            Math.max(Number(limitEl.value || 250), 300),
          );
          const quickviews = await runLayerSearch("Satellogic quickview", overviewPayload);
          if (quickviews.length) {
            overviewItems = filterOverviewItemsByPrimaryAvailability(
              quickviews,
              items,
              primarySatellogicCollection,
            );
          }
        }
        state.layerSearchResults.satellogicOverlay = {
          collectionId: primarySatellogicCollection,
          items,
          overviewItems,
        };
        state.layerSearchResults.satellogicQuickviewVisual = {
          collectionId: "quickview-visual",
          items: quickviewVisualItems,
        };
        if (items.length || overviewItems.length) {
          successfulSearchParams.push(buildSearchPayloadForSource(geometry, "satellogic", "l1d-sr"));
        }
      })());
    }
  }

  if (tasks.length) {
    await Promise.all(tasks);
  }

  applyLayerSearchResultsToState();
  const preferredSource = selectedSourceId();
  state.searchParams = successfulSearchParams.find((row) => normalizeSourceId(row.source_id) === preferredSource)
    || successfulSearchParams[0]
    || null;

  renderTimeCarouselForViewport();
  updateLockButtonState();

  // Keep analyst viewport stable; do not auto-fit search results.
  drawResults(orderedOverviewDisplayItems(), "overview", false, {
    vectorItems: stripOutlineVectorItems(orderedOverviewDisplayItems()),
    showOutlines: true,
  });
  setItemSelectors(state.items);
  if (state.searchParams) {
    await refreshMapMode(true);
  }
  const warningTag = layerWarnings.size ? ` • warnings: ${layerWarnings.size}` : "";
  toast(`Loaded ${state.items.length} timeline items, ${state.overviewItems.length} overview items${warningTag}`);
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
    if (framePreviewEl) framePreviewEl.src = `data:image/gif;base64,${data.gif_base64}`;
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

function promptAnimationSourceChoice(sourceIds) {
  const unique = Array.from(new Set((sourceIds || []).map((row) => normalizeSourceId(row)).filter(Boolean)));
  if (!unique.length) throw new Error("No source available for animation.");
  if (unique.length === 1) return unique[0];
  // Mixed-source animations default to Satellogic to avoid extra confirmation flows.
  return "satellogic";
}

function resolveAnimationSourceFromItems(items, fallbackSources = []) {
  const fromItems = (items || []).map((item) => sourceIdForItem(item));
  const options = [...fromItems, ...(fallbackSources || [])];
  const valid = Array.from(new Set(options.map((row) => normalizeSourceId(row)).filter((row) => row === "merlin-s2" || row === "satellogic")));
  const chosen = promptAnimationSourceChoice(valid.length ? valid : enabledSourceIds());
  setPreferredActionSource(chosen);
  return chosen;
}

function buildSelectedMp4AnimationPayload() {
  const selectedFrames = sortNewestFirst(selectedVisibleOverviewItems()).reverse();
  if (selectedFrames.length < 2) {
    throw new Error("Select at least two visible images in the carousel.");
  }
  const chosenSourceId = resolveAnimationSourceFromItems(selectedFrames, enabledSourceIds());
  const candidateFrames = selectedFrames.filter((item) => sourceIdForItem(item) === chosenSourceId);
  if (candidateFrames.length < 2) {
    throw new Error("Need at least two visible selected frames from one source for animation.");
  }

  const viewportBounds = map.getBounds();
  const viewportGeometry = normalizeGeometryLongitudes(geometryFromBounds(viewportBounds));
  const sourceTiles = dedupeById([...(state.detailItems || []), ...state.items])
    .filter((tile) => sourceIdForItem(tile) === chosenSourceId);

  const frames = [];
  candidateFrames.forEach((overviewItem) => {
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
  const loopEnabled = Boolean(animateSeriesLoopEl?.checked);

  return {
    viewport_geometry: viewportGeometry,
    contract_id: chosenSourceId === "satellogic" ? selectedContractId() : null,
    seconds_per_frame: secondsPerFrame,
    loop: loopEnabled,
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
    if (document.hidden) return;
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
  }, MP4_JOB_POLL_MS);

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

function clearReportRunPolling() {
  if (state.reportRunTimer) {
    clearInterval(state.reportRunTimer);
    state.reportRunTimer = null;
  }
}

function buildSelectedSeriesReportRunPayload() {
  const workflowRef = (generateSeriesReportWorkflowEl?.value || "").trim();
  if (!workflowRef) throw new Error("Choose a workflow.");
  const [workflowId, workflowVersion] = workflowRef.split("@");
  if (!workflowId || !workflowVersion) throw new Error("Invalid workflow selection.");

  const selectedFrames = sortNewestFirst(selectedOverviewItems()).reverse();
  if (selectedFrames.length < 2) {
    throw new Error("Select at least two images in the carousel.");
  }
  const viewportGeometry = normalizeGeometryLongitudes(geometryFromBounds(map.getBounds()));
  const customPrompt = (generateSeriesReportPromptEl?.value || "").trim();
  const sortedByTime = [...selectedFrames].sort((a, b) => (a.datetime || "").localeCompare(b.datetime || ""));
  const start = sortedByTime[0]?.datetime || isoDate(startDateEl.value);
  const end = sortedByTime[sortedByTime.length - 1]?.datetime || isoDate(endDateEl.value);
  const selectedSources = Array.from(new Set(selectedFrames.map((item) => sourceIdForItem(item))));
  const reportSourceId = selectedSources.length === 1 ? selectedSources[0] : selectedSourceId();
  const params = {};
  if (customPrompt) {
    params.additional_prompt = customPrompt;
    params.ai_prompt = customPrompt;
  }

  return {
    workflow_id: workflowId,
    workflow_version: workflowVersion,
    inputs_payload: {
      roi: viewportGeometry,
      viewport_geometry: viewportGeometry,
      scene_ids: selectedFrames.map((item) => item.id).filter(Boolean),
      contract_id: reportSourceId === "satellogic" ? selectedContractId() : null,
      source_id: reportSourceId,
      collection_id: collectionForSource(reportSourceId),
      start_date: start,
      end_date: end,
      max_cloud_cover: parseOptionalNumber(maxCloudEl.value),
      satellite_name: (satelliteNameEl.value || "").trim() || null,
      min_gsd: parseOptionalNumber(minGsdEl.value),
      max_gsd: parseOptionalNumber(maxGsdEl.value),
      params,
    },
  };
}

async function downloadRunArtifactBlob(runId, artifact) {
  const artifactId = artifact?.artifact_id;
  if (!artifactId) throw new Error("Artifact id missing");
  const url = `${apiBase}/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}/download`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Artifact download failed (${res.status})`);
  const blob = await res.blob();
  const uri = (artifact?.uri || "").toString();
  const name = (uri.split("/").pop() || `geoagent_report_${timestampTag()}.docx`).trim();
  triggerBlobDownload(blob, name);
}

async function tryDownloadReportDocx(runId, runData = null) {
  const run = runData || await apiJson(`/api/runs/${encodeURIComponent(runId)}`);
  const artifacts = Array.isArray(run?.artifacts) ? run.artifacts : [];
  const docx = artifacts.find((art) => (art.type || "").toLowerCase() === "docx" || String(art.uri || "").toLowerCase().endsWith(".docx"));
  if (!docx) return false;
  await downloadRunArtifactBlob(runId, docx);
  return true;
}

async function pollSeriesReportRun(runId) {
  const run = await apiJson(`/api/runs/${encodeURIComponent(runId)}`);
  const status = (run.status || "").toLowerCase();
  if (status === "queued") {
    setGenerateSeriesReportStatus("Run queued...");
    return run;
  }
  if (status === "running") {
    const stages = Array.isArray(run.stage_progress) ? run.stage_progress : [];
    const latest = stages.length ? stages[stages.length - 1] : null;
    const msg = latest?.message || "Processing selected imagery...";
    setGenerateSeriesReportStatus(msg);
    return run;
  }
  if (status === "failed") {
    clearReportRunPolling();
    state.reportRunId = null;
    state.reportRunDownloading = false;
    const logs = Array.isArray(run.logs) ? run.logs : [];
    const err = logs.length ? (logs[logs.length - 1]?.message || "Run failed") : "Run failed";
    setGenerateSeriesReportStatus(err, true);
    throw new Error(err);
  }
  if (status === "completed") {
    clearReportRunPolling();
    return run;
  }
  return run;
}

async function startSelectedSeriesReportRun() {
  const payload = buildSelectedSeriesReportRunPayload();
  setGenerateSeriesReportStatus("Submitting workflow run...");
  hideAnimateSeriesPopover();
  hideDownloadPopover();

  const run = await apiJson("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  state.reportRunId = run.run_id;
  state.reportRunDownloading = false;
  clearReportRunPolling();
  setGenerateSeriesReportStatus(`Run queued: ${run.run_id}`);
  setWorkbenchTab("runs");
  await refreshRuns();

  state.reportRunTimer = window.setInterval(async () => {
    if (!state.reportRunId) return;
    if (document.hidden) return;
    try {
      const latest = await pollSeriesReportRun(state.reportRunId);
      if ((latest.status || "").toLowerCase() === "completed" && !state.reportRunDownloading) {
        state.reportRunDownloading = true;
        const downloaded = await tryDownloadReportDocx(state.reportRunId, latest);
        if (!downloaded) throw new Error("Run completed but report.docx artifact was not found.");
        setGenerateSeriesReportStatus("Report DOCX downloaded.");
        toast("Workflow report ready");
        state.reportRunId = null;
      }
    } catch (err) {
      clearReportRunPolling();
      state.reportRunId = null;
      state.reportRunDownloading = false;
      setGenerateSeriesReportStatus(err.message || "Workflow run failed", true);
      toast(err.message || "Workflow run failed");
    }
  }, REPORT_RUN_POLL_MS);

  const first = await pollSeriesReportRun(state.reportRunId);
  if ((first.status || "").toLowerCase() === "completed" && !state.reportRunDownloading) {
    state.reportRunDownloading = true;
    const downloaded = await tryDownloadReportDocx(state.reportRunId, first);
    if (!downloaded) {
      throw new Error("Run completed but report.docx artifact was not found.");
    }
    clearReportRunPolling();
    state.reportRunId = null;
    setGenerateSeriesReportStatus("Report DOCX downloaded.");
    toast("Workflow report ready");
  } else {
    toast("Workflow run started");
  }
}

async function runSearchAnimation() {
  if (!state.animationGeometry) {
    throw new Error("Animation AOI missing. Draw a rectangle first.");
  }
  state.animationGeometry = normalizeGeometryLongitudes(state.animationGeometry);
  const chosenSourceId = resolveAnimationSourceFromItems([], enabledSourceIds());
  const chosenCollectionId = collectionForSource(chosenSourceId, { allowNone: true });
  if (!chosenCollectionId) {
    throw new Error(`Choose a ${chosenSourceId === "merlin-s2" ? "Sentinel-2" : "Satellogic"} collection (not None) for animation.`);
  }

  const payload = compactObject({
    geometry: state.animationGeometry,
    start_date: isoDate(animStartDateEl.value),
    end_date: isoDate(animEndDateEl.value),
    source_id: chosenSourceId,
    collection_id: chosenCollectionId,
    contract_id: chosenSourceId === "satellogic" ? selectedContractId() : null,
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

  const prefix = chosenSourceId === "merlin-s2" ? "sentinel2" : "satellogic";
  openAnimationWindow(data.gif_base64, `${prefix}_capture_animation.gif`);
  toast(`Animation created (${data.frame_count} frames)`);
}

async function loadContracts() {
  contractSelectEl.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Default contract";
  contractSelectEl.appendChild(placeholder);

  try {
    const params = new URLSearchParams();
    params.set("source_id", "satellogic");
    const res = await fetch(`${apiBase}/api/contracts?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load contracts");

    (data.contracts || []).forEach((contract) => {
      const opt = document.createElement("option");
      opt.value = contract.id;
      opt.textContent = contract.name ? `${contract.name} (${contract.id})` : contract.id;
      contractSelectEl.appendChild(opt);
    });

    const remembered = state.satellogicContractMemory || "";
    const fallbackContractId = data.default_contract_id || "";
    const hasRemembered = remembered && (data.contracts || []).some((row) => row.id === remembered);
    const nextContractId = hasRemembered ? remembered : fallbackContractId;
    if (nextContractId) contractSelectEl.value = nextContractId;
    if (isSourceEnabled("satellogic")) {
      state.satellogicContractMemory = (contractSelectEl.value || "").trim() || state.satellogicContractMemory;
    }
    contractSelectEl.disabled = !isSourceEnabled("satellogic");
    toast(`Contracts loaded: ${data.count}`);
  } catch (err) {
    contractSelectEl.disabled = !isSourceEnabled("satellogic");
    toast(`Contracts unavailable: ${err.message}`);
  }
}

async function loadSatellogicCollections() {
  const previous = (collectionEl.value || "").trim() || (state.perSourceCollections.satellogic || "").trim();
  collectionEl.innerHTML = "";
  const noneOpt = document.createElement("option");
  noneOpt.value = COLLECTION_NONE_VALUE;
  noneOpt.textContent = "None (do not search)";
  collectionEl.appendChild(noneOpt);
  try {
    const params = new URLSearchParams();
    params.set("source_id", "satellogic");
    const contractId = selectedSatellogicContractId();
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

    const preferredQuickview = (
      collections.find((collection) => {
        const id = (collection?.id || "").toString().trim().toLowerCase();
        const title = (collection?.title || "").toString().trim().toLowerCase();
        return id === "quickview-visual"
          || id === "quickview-visual-thumb"
          || (id.includes("quickview") && (id.includes("visual") || id.includes("thumb")))
          || (title.includes("quickview") && title.includes("visual"));
      })?.id
      || ""
    );
    const fallbackId = preferredQuickview || data.default_collection_id || "quickview-visual";
    const candidate = previous || fallbackId;
    const hasCandidate = candidate === COLLECTION_NONE_VALUE || collections.some((c) => c.id === candidate);
    if (hasCandidate) setCollectionForSource("satellogic", candidate, false);
    else if (fallbackId && collections.some((c) => c.id === fallbackId)) setCollectionForSource("satellogic", fallbackId, false);
    else if (collections.length) setCollectionForSource("satellogic", collections[0].id, false);
    else {
      const opt = document.createElement("option");
      opt.value = fallbackId;
      opt.textContent = fallbackId;
      collectionEl.appendChild(opt);
      setCollectionForSource("satellogic", fallbackId, false);
    }
    collectionEl.value = state.perSourceCollections.satellogic || collectionForSource("satellogic");
  } catch (err) {
    const fallbackId = previous || "quickview-visual";
    if (fallbackId !== COLLECTION_NONE_VALUE) {
      const opt = document.createElement("option");
      opt.value = fallbackId;
      opt.textContent = fallbackId;
      collectionEl.appendChild(opt);
    }
    setCollectionForSource("satellogic", fallbackId, false);
    collectionEl.value = state.perSourceCollections.satellogic || collectionForSource("satellogic");
    toast(`Collections unavailable: ${err.message}`);
  }
}

async function loadCollections() {
  await Promise.all([
    loadSatellogicCollections(),
    loadSentinelCollectionCatalog(),
  ]);
}

async function loadSources() {
  if (!sourceSelectEl) return;
  const previous = (sourceSelectEl.value || "").trim();
  sourceSelectEl.innerHTML = "";
  try {
    const res = await fetch(`${apiBase}/api/sources`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load sources");
    const rows = Array.isArray(data.sources) ? data.sources : [];
    rows.forEach((row) => {
      const opt = document.createElement("option");
      opt.value = row.source_id;
      opt.textContent = row.title || row.source_id;
      sourceSelectEl.appendChild(opt);
    });
    const fallback = data.default_source_id || "satellogic";
    const candidate = previous || state.preferredActionSource || fallback;
    const hasCandidate = rows.some((row) => row.source_id === candidate);
    setPreferredActionSource(hasCandidate ? candidate : (rows[0]?.source_id || fallback));
  } catch (err) {
    const opt = document.createElement("option");
    opt.value = "satellogic";
    opt.textContent = "Satellogic";
    sourceSelectEl.appendChild(opt);
    setPreferredActionSource("satellogic");
    toast(`Sources unavailable: ${err.message}`);
  }
}

async function apiJson(path, options = {}) {
  const res = await fetch(`${apiBase}${path}`, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${path} failed`);
  return data;
}

function activeSceneIdsForRun() {
  const selected = selectedOverviewItems().map((item) => item.id).filter(Boolean);
  if (selected.length) return selected;
  const active = state.selectedCarouselId;
  if (active) return [active];
  return [];
}

function setRightPanelTitle(value) {
  if (rightPanelTitleEl) rightPanelTitleEl.textContent = value;
}

function showLeftView(tab) {
  const viewByTab = {
    explore: leftExploreViewEl,
    tasking: leftTaskingViewEl,
    workflows: leftWorkflowsViewEl,
    schedules: leftSchedulesViewEl,
    runs: leftRunsViewEl,
  };
  Object.entries(viewByTab).forEach(([key, el]) => {
    if (!el) return;
    el.classList.toggle("active", key === tab);
  });
}

function renderRunArtifactsInRightPanel(run) {
  if (!timeCarouselListEl) return;
  resetCarouselLazyState();
  if (!run) {
    setRightPanelTitle("Run Artifacts");
    timeCarouselListEl.innerHTML = `<div class="meta">Select a run to view artifacts.</div>`;
    return;
  }
  const artifacts = Array.isArray(run.artifacts) ? run.artifacts : [];
  setRightPanelTitle(`Run Artifacts (${artifacts.length})`);
  if (!artifacts.length) {
    timeCarouselListEl.innerHTML = `<div class="meta">No artifacts yet. Run may still be processing.</div>`;
    return;
  }
  timeCarouselListEl.innerHTML = "";
  artifacts.forEach((artifact) => {
    const row = document.createElement("div");
    row.className = "carousel-card";
    const shortSha = (artifact.sha256 || "").slice(0, 12);
    row.innerHTML = `
      <div class="carousel-card-head"><strong>${artifact.type || "artifact"}</strong></div>
      <div class="card-date">${artifact.uri || ""}</div>
      <div class="meta">sha256: ${shortSha}${artifact.sha256 ? "..." : ""}</div>
    `;
    row.addEventListener("click", async () => {
      try {
        await openRunArtifact(run.run_id, artifact.artifact_id, artifact.type);
      } catch (err) {
        toast(err.message);
      }
    });
    timeCarouselListEl.appendChild(row);
  });
}

async function openRunArtifact(runId, artifactId, artifactType) {
  const downloadUrl = `${apiBase}/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}/download`;
  if (artifactType === "md" || artifactType === "json" || artifactType === "geojson" || artifactType === "txt") {
    const res = await fetch(downloadUrl);
    if (!res.ok) throw new Error(`Artifact open failed (${res.status})`);
    const text = await res.text();
    if (runInspectorOutEl) runInspectorOutEl.textContent = text;
    if (artifactType === "json" && text.includes("\"findings\"")) {
      try {
        const payload = JSON.parse(text);
        renderEvidenceJumpList(payload, text);
      } catch (_) {
        // ignore malformed json in viewer mode
      }
    }
    return;
  }
  window.open(downloadUrl, "_blank", "noopener");
}

function escapeHtml(value) {
  return (value || "")
    .toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderEvidenceJumpList(reportJson, rawText = "") {
  if (!runInspectorOutEl || !reportJson || !Array.isArray(reportJson.findings)) return;
  const findings = reportJson.findings
    .map((f) => f?.evidence)
    .filter((ev) => ev && ev.scene_id);
  if (!findings.length) return;
  const rows = findings.slice(0, 40).map((ev, idx) => (
    `<button type="button" class="evidence-jump" data-scene-id="${escapeHtml(ev.scene_id)}">${idx + 1}. ${escapeHtml(ev.scene_id)} @ ${escapeHtml(ev.captured_at || "n/a")}</button>`
  ));
  const escapedText = escapeHtml(rawText).replaceAll("\n", "<br>");
  runInspectorOutEl.innerHTML = `${escapedText}<br><br><strong>Evidence Jump Shortcuts:</strong><br>${rows.join("")}`;
}

async function jumpToEvidenceScene(sceneId) {
  const target = (sceneId || "").trim();
  if (!target) return;
  const overview = overviewSourceItems().find((item) => item.id === target);
  if (overview) {
    await focusFromCarousel(overview);
    return;
  }
  const fromItems = (state.items || []).find((item) => item.id === target);
  if (fromItems) {
    const matchedOverview = (state.overviewItems || []).find((o) => (
      (o.outcome_id && fromItems.outcome_id && o.outcome_id === fromItems.outcome_id)
      || (o.datetime && fromItems.datetime && o.datetime === fromItems.datetime)
    ));
    if (matchedOverview) {
      await focusFromCarousel(matchedOverview);
      return;
    }
  }
  toast(`Scene not in current explore context: ${target}`);
}

function workflowRecordFromRef(refValue) {
  const ref = (refValue || "").trim();
  if (!ref) return null;
  const [workflowId, version] = ref.split("@");
  return (state.workflows || []).find((wf) => wf.workflow_id === workflowId && wf.version === version) || null;
}

function defaultWorkflowGraphNodes() {
  return [
    { id: "evidence", skill: "evidence_bundle", depends_on: [], position: { x: 20, y: 20 } },
    { id: "analytics", skill: "analytics_provider", depends_on: ["evidence"], position: { x: 245, y: 20 } },
    { id: "metrics", skill: "scene_metrics", depends_on: ["analytics"], position: { x: 470, y: 20 } },
    { id: "change", skill: "change_pol", depends_on: ["metrics"], position: { x: 695, y: 20 } },
    { id: "ai", skill: "ai_scene_change_agent", depends_on: ["evidence", "change"], position: { x: 920, y: 20 } },
    { id: "report", skill: "report_writer", depends_on: ["evidence", "metrics", "change", "ai"], position: { x: 580, y: 130 } },
  ];
}

function normalizeGraphNodes(rawNodes) {
  if (!Array.isArray(rawNodes)) return [];
  const nodes = [];
  const seen = new Set();
  rawNodes.forEach((raw, idx) => {
    if (!raw || typeof raw !== "object") return;
    const id = String(raw.id || "").trim();
    const skill = String(raw.skill || "").trim();
    if (!id || !skill || seen.has(id)) return;
    seen.add(id);
    const depsRaw = Array.isArray(raw.depends_on) ? raw.depends_on : [];
    const deps = [];
    const seenDeps = new Set();
    depsRaw.forEach((dep) => {
      const depId = String(dep || "").trim();
      if (!depId || depId === id || seenDeps.has(depId)) return;
      deps.push(depId);
      seenDeps.add(depId);
    });
    const pos = (raw.position && typeof raw.position === "object") ? raw.position : {};
    const x = Number.isFinite(Number(pos.x)) ? Number(pos.x) : (Number.isFinite(Number(raw.x)) ? Number(raw.x) : (20 + (idx * 180)));
    const y = Number.isFinite(Number(pos.y)) ? Number(pos.y) : (Number.isFinite(Number(raw.y)) ? Number(raw.y) : 20);
    nodes.push({
      id,
      skill,
      depends_on: deps,
      position: { x, y },
    });
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  nodes.forEach((node) => {
    node.depends_on = node.depends_on.filter((dep) => nodeIds.has(dep) && dep !== node.id);
  });
  return nodes;
}

function graphNodesToPayload() {
  return (state.workflowGraph.nodes || []).map((node) => ({
    id: node.id,
    skill: node.skill,
    depends_on: Array.isArray(node.depends_on) ? [...node.depends_on] : [],
    position: {
      x: Number(node.position?.x || 0),
      y: Number(node.position?.y || 0),
    },
  }));
}

function setWorkflowBuilderMeta(message, isError = false) {
  if (!workflowBuilderMetaEl) return;
  workflowBuilderMetaEl.textContent = message;
  workflowBuilderMetaEl.style.color = isError ? "#9f2f1e" : "";
}

function syncSelectedNodeInspector() {
  const selectedId = (state.workflowGraph.selectedNodeId || "").trim();
  const selectedNode = (state.workflowGraph.nodes || []).find((node) => node.id === selectedId) || null;
  if (workflowBuilderSelectedNodeIdEl) {
    workflowBuilderSelectedNodeIdEl.value = selectedNode ? selectedNode.id : "";
    workflowBuilderSelectedNodeIdEl.disabled = !selectedNode;
  }
  if (workflowBuilderSelectedNodeSkillEl) {
    workflowBuilderSelectedNodeSkillEl.value = selectedNode ? selectedNode.skill : "";
    workflowBuilderSelectedNodeSkillEl.disabled = !selectedNode;
  }
}

function refreshWorkflowBuilderNodeSelectors() {
  const priorFrom = workflowBuilderEdgeFromEl?.value || "";
  const priorTo = workflowBuilderEdgeToEl?.value || "";
  const nodes = state.workflowGraph.nodes || [];
  [workflowBuilderEdgeFromEl, workflowBuilderEdgeToEl].forEach((sel) => {
    if (!sel) return;
    sel.innerHTML = "";
    nodes.forEach((node) => {
      const opt = document.createElement("option");
      opt.value = node.id;
      opt.textContent = `${node.id} (${node.skill})`;
      sel.appendChild(opt);
    });
  });
  if (workflowBuilderEdgeFromEl && priorFrom) workflowBuilderEdgeFromEl.value = priorFrom;
  if (workflowBuilderEdgeToEl && priorTo) workflowBuilderEdgeToEl.value = priorTo;
}

function refreshWorkflowBuilderSkillOptions() {
  if (!workflowBuilderSkillSelectEl) return;
  const prior = workflowBuilderSkillSelectEl.value;
  const priorSelectedSkill = workflowBuilderSelectedNodeSkillEl?.value || "";
  workflowBuilderSkillSelectEl.innerHTML = "";
  if (workflowBuilderSelectedNodeSkillEl) workflowBuilderSelectedNodeSkillEl.innerHTML = "";
  (state.skills || []).forEach((skill) => {
    const sid = (skill.skill_id || "").trim();
    if (!sid) return;
    const opt = document.createElement("option");
    opt.value = sid;
    opt.textContent = `${sid} @ ${skill.version || "n/a"}`;
    workflowBuilderSkillSelectEl.appendChild(opt);
    if (workflowBuilderSelectedNodeSkillEl) {
      const opt2 = document.createElement("option");
      opt2.value = sid;
      opt2.textContent = `${sid} @ ${skill.version || "n/a"}`;
      workflowBuilderSelectedNodeSkillEl.appendChild(opt2);
    }
  });
  if (prior) workflowBuilderSkillSelectEl.value = prior;
  if (workflowBuilderSelectedNodeSkillEl && priorSelectedSkill) workflowBuilderSelectedNodeSkillEl.value = priorSelectedSkill;
  syncSelectedNodeInspector();
}

function renderWorkflowBuilderEdges() {
  if (!workflowBuilderEdgesEl || !workflowBuilderCanvasWrapEl) return;
  workflowBuilderEdgesEl.innerHTML = "";
  const nodes = state.workflowGraph.nodes || [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const markerId = "workflowBuilderArrow";
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", markerId);
  marker.setAttribute("markerWidth", "7");
  marker.setAttribute("markerHeight", "7");
  marker.setAttribute("refX", "6");
  marker.setAttribute("refY", "3.5");
  marker.setAttribute("orient", "auto");
  const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path");
  arrow.setAttribute("d", "M 0 0 L 7 3.5 L 0 7 z");
  arrow.setAttribute("fill", "#5d8574");
  marker.appendChild(arrow);
  defs.appendChild(marker);
  workflowBuilderEdgesEl.appendChild(defs);

  nodes.forEach((node) => {
    const toX = Number(node.position?.x || 0) + 68;
    const toY = Number(node.position?.y || 0) + 24;
    (node.depends_on || []).forEach((depId) => {
      const dep = byId.get(depId);
      if (!dep) return;
      const fromX = Number(dep.position?.x || 0) + 68;
      const fromY = Number(dep.position?.y || 0) + 24;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(fromX));
      line.setAttribute("y1", String(fromY));
      line.setAttribute("x2", String(toX));
      line.setAttribute("y2", String(toY));
      line.setAttribute("stroke", "#5d8574");
      line.setAttribute("stroke-width", "1.5");
      line.setAttribute("marker-end", `url(#${markerId})`);
      workflowBuilderEdgesEl.appendChild(line);
    });
  });
}

function updateWorkflowBuilderJson() {
  if (!workflowBuilderJsonEl) return;
  const payload = { nodes: graphNodesToPayload() };
  workflowBuilderJsonEl.value = JSON.stringify(payload, null, 2);
}

function renderWorkflowBuilder() {
  if (!workflowBuilderCanvasEl) return;
  workflowBuilderCanvasEl.innerHTML = "";
  const selected = state.workflowGraph.selectedNodeId;
  (state.workflowGraph.nodes || []).forEach((node) => {
    const el = document.createElement("div");
    el.className = "workflow-node" + (selected === node.id ? " selected" : "");
    el.dataset.nodeId = node.id;
    el.style.left = `${Math.round(Number(node.position?.x || 0))}px`;
    el.style.top = `${Math.round(Number(node.position?.y || 0))}px`;
    el.innerHTML = `
      <div class="workflow-node-id">${escapeHtml(node.id)}</div>
      <div class="workflow-node-skill">${escapeHtml(node.skill)}</div>
    `;
    el.addEventListener("mousedown", (evt) => {
      evt.preventDefault();
      state.workflowGraph.selectedNodeId = node.id;
      state.workflowGraph.dragNodeId = node.id;
      const wrapRect = workflowBuilderCanvasWrapEl?.getBoundingClientRect();
      const x = Number(node.position?.x || 0);
      const y = Number(node.position?.y || 0);
      state.workflowGraph.dragOffsetX = evt.clientX - (wrapRect ? wrapRect.left + x : evt.clientX);
      state.workflowGraph.dragOffsetY = evt.clientY - (wrapRect ? wrapRect.top + y : evt.clientY);
      syncSelectedNodeInspector();
      renderWorkflowBuilder();
    });
    el.addEventListener("click", () => {
      state.workflowGraph.selectedNodeId = node.id;
      syncSelectedNodeInspector();
      renderWorkflowBuilder();
    });
    workflowBuilderCanvasEl.appendChild(el);
  });
  renderWorkflowBuilderEdges();
  refreshWorkflowBuilderNodeSelectors();
  syncSelectedNodeInspector();
  updateWorkflowBuilderJson();
}

function setWorkflowGraph(nodes, dirty = false) {
  state.workflowGraph.nodes = normalizeGraphNodes(nodes);
  state.workflowGraph.selectedNodeId = null;
  state.workflowGraph.dragNodeId = null;
  state.workflowGraph.dirty = Boolean(dirty);
  syncSelectedNodeInspector();
  renderWorkflowBuilder();
}

function loadSelectedWorkflowIntoBuilder() {
  const selected = workflowRecordFromRef(workflowSelectEl?.value || "");
  if (!selected) {
    setWorkflowBuilderMeta("Select a workflow to load into builder.", true);
    return;
  }
  if (workflowBuilderIdEl) workflowBuilderIdEl.value = selected.workflow_id || "";
  if (workflowBuilderVersionEl) workflowBuilderVersionEl.value = selected.version || "";
  if (workflowBuilderDefaultsEl) {
    workflowBuilderDefaultsEl.value = JSON.stringify(selected.default_params || {}, null, 2);
  }
  const nodes = normalizeGraphNodes((selected.graph_json || {}).nodes || []);
  setWorkflowGraph(nodes.length ? nodes : defaultWorkflowGraphNodes(), false);
  setWorkflowBuilderMeta(`Loaded ${selected.workflow_id}@${selected.version}`);
}

function addWorkflowBuilderNode() {
  const skillId = (workflowBuilderSkillSelectEl?.value || "").trim();
  if (!skillId) throw new Error("Choose a skill");
  const base = (workflowBuilderNodeIdEl?.value || "").trim();
  const existing = new Set((state.workflowGraph.nodes || []).map((n) => n.id));
  let id = base || `${skillId}_${(state.workflowGraph.nodes || []).length + 1}`;
  while (existing.has(id)) id = `${id}_n`;
  const nodes = [...(state.workflowGraph.nodes || [])];
  nodes.push({
    id,
    skill: skillId,
    depends_on: [],
    position: { x: 24 + ((nodes.length % 4) * 180), y: 18 + (Math.floor(nodes.length / 4) * 86) },
  });
  setWorkflowGraph(nodes, true);
  state.workflowGraph.selectedNodeId = id;
  renderWorkflowBuilder();
  if (workflowBuilderNodeIdEl) workflowBuilderNodeIdEl.value = "";
  setWorkflowBuilderMeta(`Added node ${id}`);
}

function removeSelectedWorkflowBuilderNode() {
  const selected = (state.workflowGraph.selectedNodeId || "").trim();
  if (!selected) throw new Error("Select a node first");
  let nodes = [...(state.workflowGraph.nodes || [])].filter((node) => node.id !== selected);
  nodes = nodes.map((node) => ({
    ...node,
    depends_on: (node.depends_on || []).filter((dep) => dep !== selected),
  }));
  setWorkflowGraph(nodes, true);
  setWorkflowBuilderMeta(`Removed node ${selected}`);
}

function addWorkflowBuilderEdge() {
  const fromId = (workflowBuilderEdgeFromEl?.value || "").trim();
  const toId = (workflowBuilderEdgeToEl?.value || "").trim();
  if (!fromId || !toId) throw new Error("Choose edge endpoints");
  if (fromId === toId) throw new Error("Edge endpoints must differ");
  const nodes = [...(state.workflowGraph.nodes || [])].map((node) => ({ ...node, depends_on: [...(node.depends_on || [])] }));
  const target = nodes.find((node) => node.id === toId);
  if (!target) throw new Error("Target node not found");
  if (!target.depends_on.includes(fromId)) target.depends_on.push(fromId);
  setWorkflowGraph(nodes, true);
  setWorkflowBuilderMeta(`Added edge ${fromId} -> ${toId}`);
}

function removeWorkflowBuilderEdge() {
  const fromId = (workflowBuilderEdgeFromEl?.value || "").trim();
  const toId = (workflowBuilderEdgeToEl?.value || "").trim();
  if (!fromId || !toId) throw new Error("Choose edge endpoints");
  const nodes = [...(state.workflowGraph.nodes || [])].map((node) => ({
    ...node,
    depends_on: node.id === toId ? (node.depends_on || []).filter((dep) => dep !== fromId) : [...(node.depends_on || [])],
  }));
  setWorkflowGraph(nodes, true);
  setWorkflowBuilderMeta(`Removed edge ${fromId} -> ${toId}`);
}

function autoLayoutWorkflowGraph() {
  const nodes = [...(state.workflowGraph.nodes || [])].map((node) => ({ ...node, depends_on: [...(node.depends_on || [])] }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const inDegree = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, []]));
  nodes.forEach((node) => {
    (node.depends_on || []).forEach((dep) => {
      if (!byId.has(dep)) return;
      inDegree.set(node.id, (inDegree.get(node.id) || 0) + 1);
      outgoing.get(dep).push(node.id);
    });
  });
  const queue = Array.from(inDegree.entries()).filter(([, degree]) => degree === 0).map(([id]) => id).sort();
  const layerById = new Map();
  queue.forEach((id) => layerById.set(id, 0));
  while (queue.length) {
    const id = queue.shift();
    const layer = layerById.get(id) || 0;
    (outgoing.get(id) || []).forEach((next) => {
      const current = layerById.get(next);
      if (current === undefined || current < layer + 1) layerById.set(next, layer + 1);
      const degree = (inDegree.get(next) || 0) - 1;
      inDegree.set(next, degree);
      if (degree === 0) queue.push(next);
    });
    queue.sort();
  }
  const groups = new Map();
  nodes.forEach((node) => {
    const layer = layerById.get(node.id) ?? 0;
    if (!groups.has(layer)) groups.set(layer, []);
    groups.get(layer).push(node);
  });
  Array.from(groups.keys()).sort((a, b) => a - b).forEach((layer) => {
    const group = groups.get(layer) || [];
    group.sort((a, b) => a.id.localeCompare(b.id));
    group.forEach((node, idx) => {
      node.position = { x: 20 + (layer * 190), y: 18 + (idx * 72) };
    });
  });
  setWorkflowGraph(nodes, true);
  setWorkflowBuilderMeta("Auto-layout applied");
}

function applyWorkflowBuilderJson() {
  const raw = workflowBuilderJsonEl?.value || "";
  const parsed = parseJsonInput(raw, "Workflow graph JSON");
  const nodes = normalizeGraphNodes((parsed || {}).nodes || []);
  if (!nodes.length) throw new Error("Graph JSON must include nodes");
  setWorkflowGraph(nodes, true);
  setWorkflowBuilderMeta("Applied JSON to workflow graph");
}

function applySelectedWorkflowNodeEdit() {
  const selected = (state.workflowGraph.selectedNodeId || "").trim();
  if (!selected) throw new Error("Select a node first");
  const nodes = [...(state.workflowGraph.nodes || [])].map((node) => ({ ...node, depends_on: [...(node.depends_on || [])] }));
  const node = nodes.find((row) => row.id === selected);
  if (!node) throw new Error("Selected node not found");
  const nextId = (workflowBuilderSelectedNodeIdEl?.value || "").trim();
  const nextSkill = (workflowBuilderSelectedNodeSkillEl?.value || "").trim();
  if (!nextId) throw new Error("Node ID is required");
  if (!nextSkill) throw new Error("Skill is required");
  if (nextId !== selected && nodes.some((row) => row.id === nextId)) {
    throw new Error(`Node ID already exists: ${nextId}`);
  }

  node.id = nextId;
  node.skill = nextSkill;
  if (nextId !== selected) {
    nodes.forEach((row) => {
      row.depends_on = (row.depends_on || []).map((dep) => (dep === selected ? nextId : dep));
    });
  }
  setWorkflowGraph(nodes, true);
  state.workflowGraph.selectedNodeId = nextId;
  syncSelectedNodeInspector();
  renderWorkflowBuilder();
  setWorkflowBuilderMeta(`Updated node ${nextId}`);
}

function setWorkflowBuilderDetached(detached) {
  state.workflowBuilder.isDetached = Boolean(detached);
  workflowBuilderHostEl?.classList.toggle("detached", Boolean(detached));
  if (workflowBuilderPopoutBtnEl) workflowBuilderPopoutBtnEl.disabled = Boolean(detached);
  if (workflowBuilderDockBtnEl) workflowBuilderDockBtnEl.disabled = !Boolean(detached);
}

function dockWorkflowBuilderFromWindow(closePopup = false) {
  if (!workflowBuilderDockEl || !workflowBuilderHostEl) return;
  if (workflowBuilderDockEl.parentElement !== workflowBuilderHostEl) {
    workflowBuilderHostEl.appendChild(workflowBuilderDockEl);
  }
  const popup = state.workflowBuilder.popoutWindow;
  state.workflowBuilder.popoutWindow = null;
  setWorkflowBuilderDetached(false);
  if (closePopup && popup && !popup.closed) {
    try {
      popup.close();
    } catch (_) {
      // ignore
    }
  }
  renderWorkflowBuilder();
}

function openWorkflowBuilderWorkspaceWindow() {
  if (!workflowBuilderDockEl || !workflowBuilderHostEl) return;
  const existing = state.workflowBuilder.popoutWindow;
  if (existing && !existing.closed) {
    existing.focus();
    return;
  }
  const popup = window.open("", "geoagentWorkflowBuilder", "popup=yes,width=1520,height=940,resizable=yes,scrollbars=yes");
  if (!popup) {
    toast("Popup blocked. Allow popups to open workflow workspace.");
    return;
  }
  const cssHref = `${window.location.origin}/app/styles.css`;
  popup.document.open();
  popup.document.write(`
    <!doctype html>
    <html>
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>GeoAgent Workflow Workspace</title>
        <link rel="stylesheet" href="${cssHref}" />
      </head>
      <body class="workflow-builder-popup-body">
        <div class="workflow-builder-popup-toolbar">
          <strong>Workflow Workspace</strong>
          <button id="workflowBuilderPopupDockBtn" type="button" class="ghost tiny">Dock Back</button>
        </div>
        <div id="workflowBuilderPopupMount" class="workflow-builder-popup-mount"></div>
      </body>
    </html>
  `);
  popup.document.close();
  const mount = popup.document.getElementById("workflowBuilderPopupMount");
  if (!mount) {
    popup.close();
    throw new Error("Failed to initialize workflow popup");
  }
  mount.appendChild(workflowBuilderDockEl);
  state.workflowBuilder.popoutWindow = popup;
  setWorkflowBuilderDetached(true);
  popup.document.getElementById("workflowBuilderPopupDockBtn")?.addEventListener("click", () => {
    dockWorkflowBuilderFromWindow(false);
    try {
      popup.close();
    } catch (_) {
      // ignore
    }
  });
  popup.addEventListener("beforeunload", () => {
    dockWorkflowBuilderFromWindow(false);
  });
  renderWorkflowBuilder();
  setWorkflowBuilderMeta("Workflow workspace detached to new window");
}

async function saveWorkflowBuilderWorkflow() {
  const workflowId = (workflowBuilderIdEl?.value || "").trim();
  const version = (workflowBuilderVersionEl?.value || "").trim();
  if (!workflowId || !version) throw new Error("Workflow ID and version are required");
  const defaults = parseJsonInput(workflowBuilderDefaultsEl?.value || "", "Default params JSON") || {};
  const payload = {
    workflow_id: workflowId,
    version,
    graph_json: { nodes: graphNodesToPayload() },
    default_params: defaults,
  };
  await apiJson("/api/workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await loadWorkbenchData();
  const refValue = `${workflowId}@${version}`;
  if (workflowSelectEl) workflowSelectEl.value = refValue;
  if (scheduleWorkflowSelectEl) scheduleWorkflowSelectEl.value = refValue;
  loadSelectedWorkflowIntoBuilder();
  setWorkflowBuilderMeta(`Saved workflow ${refValue}`);
}

function dragWorkflowNode(evt) {
  const nodeId = state.workflowGraph.dragNodeId;
  if (!nodeId || !workflowBuilderCanvasWrapEl) return;
  const wrapRect = workflowBuilderCanvasWrapEl.getBoundingClientRect();
  const node = (state.workflowGraph.nodes || []).find((n) => n.id === nodeId);
  if (!node) return;
  const maxX = Math.max(0, workflowBuilderCanvasWrapEl.clientWidth - 160);
  const maxY = Math.max(0, workflowBuilderCanvasWrapEl.clientHeight - 56);
  const x = Math.max(0, Math.min(maxX, evt.clientX - wrapRect.left - state.workflowGraph.dragOffsetX));
  const y = Math.max(0, Math.min(maxY, evt.clientY - wrapRect.top - state.workflowGraph.dragOffsetY));
  node.position = { x, y };
  state.workflowGraph.dirty = true;
  renderWorkflowBuilder();
}

function stopWorkflowNodeDrag() {
  if (!state.workflowGraph.dragNodeId) return;
  state.workflowGraph.dragNodeId = null;
  state.workflowGraph.dragOffsetX = 0;
  state.workflowGraph.dragOffsetY = 0;
}

function setWorkbenchTab(tab) {
  state.activeTab = tab;
  showLeftView(tab);
  const buttons = Array.from(workbenchTabsEl?.querySelectorAll(".tab-btn") || []);
  buttons.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  if (tab === "explore") {
    setRightPanelTitle("Search Results");
    renderTimeCarouselForViewport();
  } else if (tab === "tasking") {
    resetCarouselLazyState();
    setRightPanelTitle("Tasking Orders");
    timeCarouselListEl.innerHTML = `<div class="meta">Use the Tasking tab on the left to review orders and submit new tasking from the map context menu.</div>`;
    refreshTaskingPanel().catch((err) => {
      if (taskingOrdersMetaEl) taskingOrdersMetaEl.textContent = `Tasking load failed: ${err.message}`;
    });
  } else if (tab === "runs") {
    const selected = state.runs.find((r) => r.run_id === state.selectedRunId) || null;
    renderRunArtifactsInRightPanel(selected);
    renderEventFeed();
  } else if (tab === "schedules") {
    resetCarouselLazyState();
    setRightPanelTitle("Schedules");
    timeCarouselListEl.innerHTML = `<div class="meta">Schedules and subscriptions are managed in the left panel.</div>`;
  } else {
    resetCarouselLazyState();
    setRightPanelTitle("Workflows");
    timeCarouselListEl.innerHTML = `<div class="meta">Choose a workflow preset and run it.</div>`;
    renderWorkflowBuilder();
  }
}

function parseJsonInput(text, label) {
  const raw = (text || "").trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new Error(`${label} must be valid JSON`);
  }
}

function refreshWorkflowSelectOptions() {
  const workflowOptions = state.workflows || [];
  const priorWorkflow = workflowSelectEl?.value || "";
  const priorScheduleWorkflow = scheduleWorkflowSelectEl?.value || "";
  const priorCarouselWorkflow = generateSeriesReportWorkflowEl?.value || "";
  if (workflowSelectEl) workflowSelectEl.innerHTML = "";
  if (scheduleWorkflowSelectEl) scheduleWorkflowSelectEl.innerHTML = "";
  if (generateSeriesReportWorkflowEl) generateSeriesReportWorkflowEl.innerHTML = "";
  workflowOptions.forEach((wf) => {
    const value = `${wf.workflow_id}@${wf.version}`;
    const label = `${wf.workflow_id} @ ${wf.version}`;
    if (workflowSelectEl) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      workflowSelectEl.appendChild(opt);
    }
    if (scheduleWorkflowSelectEl) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      scheduleWorkflowSelectEl.appendChild(opt);
    }
    if (generateSeriesReportWorkflowEl) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      generateSeriesReportWorkflowEl.appendChild(opt);
    }
  });
  if (workflowSelectEl && priorWorkflow) workflowSelectEl.value = priorWorkflow;
  if (scheduleWorkflowSelectEl && priorScheduleWorkflow) scheduleWorkflowSelectEl.value = priorScheduleWorkflow;
  if (generateSeriesReportWorkflowEl && priorCarouselWorkflow) generateSeriesReportWorkflowEl.value = priorCarouselWorkflow;
  if (generateSeriesReportWorkflowEl && !generateSeriesReportWorkflowEl.value && workflowOptions.length) {
    const preferred = workflowOptions.find((wf) => wf.workflow_id === "carousel_scene_change_report");
    if (preferred) generateSeriesReportWorkflowEl.value = `${preferred.workflow_id}@${preferred.version}`;
    else generateSeriesReportWorkflowEl.value = `${workflowOptions[0].workflow_id}@${workflowOptions[0].version}`;
  }
  refreshWorkflowBuilderSkillOptions();
  if (workflowOptions.length && !state.workflowGraph.dirty) {
    if (workflowSelectEl && !workflowSelectEl.value) {
      workflowSelectEl.value = `${workflowOptions[0].workflow_id}@${workflowOptions[0].version}`;
    }
    loadSelectedWorkflowIntoBuilder();
  }
}

function refreshPoiAndSubscriptionOptions() {
  const poiOptions = state.poiSets || [];
  const subOptions = state.subscriptions || [];
  [workflowPoiSetSelectEl, subscriptionPoiSetSelectEl].forEach((sel) => {
    if (!sel) return;
    const prior = sel.value;
    sel.innerHTML = '<option value="">None</option>';
    poiOptions.forEach((poi) => {
      const opt = document.createElement("option");
      opt.value = poi.poi_set_id;
      opt.textContent = `${poi.name || poi.poi_set_id} (${poi.poi_set_id})`;
      sel.appendChild(opt);
    });
    if (prior) sel.value = prior;
  });
  if (scheduleSubscriptionSelectEl) {
    const prior = scheduleSubscriptionSelectEl.value;
    scheduleSubscriptionSelectEl.innerHTML = '<option value="">None</option>';
    subOptions.forEach((sub) => {
      const opt = document.createElement("option");
      opt.value = sub.subscription_id;
      opt.textContent = sub.subscription_id;
      scheduleSubscriptionSelectEl.appendChild(opt);
    });
    if (prior) scheduleSubscriptionSelectEl.value = prior;
  }
}

async function loadWorkbenchData() {
  const [workflowData, poiSets, subscriptions, schedules, runs, events] = await Promise.all([
    apiJson("/api/workflows"),
    apiJson("/api/poi_sets"),
    apiJson("/api/subscriptions"),
    apiJson("/api/schedules"),
    apiJson("/api/runs?limit=100"),
    apiJson("/api/events?limit=120"),
  ]);
  state.workflows = workflowData.workflows || [];
  state.skills = workflowData.skills || [];
  state.providers = workflowData.providers || [];
  state.poiSets = poiSets.poi_sets || [];
  state.subscriptions = subscriptions.subscriptions || [];
  state.schedules = schedules.schedules || [];
  state.runs = runs.runs || [];
  state.events = events.events || [];
  refreshWorkflowSelectOptions();
  refreshPoiAndSubscriptionOptions();
  renderScheduleList();
  renderRunsList();
  renderEventFeed();
}

function renderScheduleList() {
  if (!scheduleListOutEl) return;
  const rows = state.schedules || [];
  if (scheduleSelectEl) {
    const prior = state.selectedScheduleId || scheduleSelectEl.value || "";
    scheduleSelectEl.innerHTML = "";
    rows.forEach((row) => {
      const opt = document.createElement("option");
      opt.value = row.trigger_id;
      opt.textContent = `${row.enabled ? "ENABLED" : "DISABLED"} | ${row.type} | ${row.trigger_id}`;
      scheduleSelectEl.appendChild(opt);
    });
    if (prior) scheduleSelectEl.value = prior;
    if (!state.selectedScheduleId && scheduleSelectEl.options.length) {
      state.selectedScheduleId = scheduleSelectEl.options[0].value;
      scheduleSelectEl.value = state.selectedScheduleId;
    }
  }
  if (!rows.length) {
    scheduleListOutEl.textContent = "No schedules.";
    return;
  }
  const selected = rows.find((row) => row.trigger_id === state.selectedScheduleId) || rows[0];
  scheduleListOutEl.textContent = JSON.stringify(selected, null, 2);
}

function renderRunsList() {
  if (!runsSelectEl) return;
  const prior = state.selectedRunId;
  runsSelectEl.innerHTML = "";
  (state.runs || []).forEach((run) => {
    const opt = document.createElement("option");
    opt.value = run.run_id;
    opt.textContent = `${run.status || "unknown"} | ${run.run_id} | ${run.workflow_id}@${run.workflow_version}`;
    runsSelectEl.appendChild(opt);
  });
  if (prior) runsSelectEl.value = prior;
  if (!state.selectedRunId && runsSelectEl.options.length) {
    state.selectedRunId = runsSelectEl.options[0].value;
    runsSelectEl.value = state.selectedRunId;
  }
  if (state.selectedRunId) {
    showRunInspector(state.selectedRunId).catch((err) => toast(err.message));
  }
}

function renderEventFeed() {
  if (!runEventsOutEl) return;
  const rows = state.events || [];
  if (!rows.length) {
    runEventsOutEl.textContent = "No events.";
    return;
  }
  runEventsOutEl.textContent = rows
    .slice(-80)
    .map((ev) => `${ev.at || "n/a"} | ${ev.type || "event"} | run=${ev.run_id || "-"}`)
    .join("\n");
}

async function showRunInspector(runId) {
  const run = await apiJson(`/api/runs/${encodeURIComponent(runId)}`);
  state.selectedRunId = run.run_id;
  const artifacts = Array.isArray(run.artifacts) ? run.artifacts : [];
  if (runInspectorOutEl) {
    runInspectorOutEl.textContent = [
      `run_id: ${run.run_id}`,
      `status: ${run.status}`,
      `workflow: ${run.workflow_id}@${run.workflow_version}`,
      `trigger_id: ${run.trigger_id || "manual"}`,
      `artifacts: ${artifacts.length}`,
      `created_at: ${run.created_at}`,
      `updated_at: ${run.updated_at}`,
      "",
      "Stage progress:",
      ...(run.stage_progress || []).map((s) => `- ${s.stage}: ${s.status} (${Math.round(Number(s.progress || 0) * 100)}%) ${s.message || ""}`),
    ].join("\n");
  }
  if (state.activeTab === "runs") {
    renderRunArtifactsInRightPanel(run);
  }
}

async function createWorkflowRun() {
  const workflowRef = (workflowSelectEl?.value || "").trim();
  if (!workflowRef) throw new Error("Choose a workflow");
  const [workflowId, workflowVersion] = workflowRef.split("@");
  let roi = null;
  if (workflowUseViewportEl?.checked) roi = geometryFromBounds(map.getBounds());
  const poiSetId = (workflowPoiSetSelectEl?.value || "").trim();
  if (!roi && poiSetId) {
    const poi = (state.poiSets || []).find((x) => x.poi_set_id === poiSetId);
    if (poi?.geometry) roi = poi.geometry;
  }
  if (!roi) roi = geometryFromBounds(map.getBounds());
  const params = parseJsonInput(workflowParamsJsonEl?.value || "", "Workflow params") || {};
  const sceneIds = workflowUseSelectedEl?.checked ? activeSceneIdsForRun() : [];
  if (workflowId === "forest_urban_change_series" && sceneIds.length < 2) {
    throw new Error("Select at least 2 carousel scenes for the forest+urban workflow");
  }
  const payload = {
    workflow_id: workflowId,
    workflow_version: workflowVersion,
    inputs_payload: {
      roi: normalizeGeometryLongitudes(roi),
      viewport_geometry: normalizeGeometryLongitudes(geometryFromBounds(map.getBounds())),
      scene_ids: sceneIds,
      contract_id: selectedContractId(),
      source_id: selectedSourceId(),
      collection_id: activeCollectionId(),
      start_date: isoDate(startDateEl.value),
      end_date: isoDate(endDateEl.value),
      max_cloud_cover: parseOptionalNumber(maxCloudEl.value),
      satellite_name: (satelliteNameEl.value || "").trim() || null,
      min_gsd: parseOptionalNumber(minGsdEl.value),
      max_gsd: parseOptionalNumber(maxGsdEl.value),
      params,
    },
  };
  const run = await apiJson("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.selectedRunId = run.run_id;
  if (workflowMetaEl) workflowMetaEl.textContent = `Run created: ${run.run_id}`;
  await refreshRuns();
  setWorkbenchTab("runs");
}

async function refreshRuns() {
  const data = await apiJson("/api/runs?limit=100");
  state.runs = data.runs || [];
  renderRunsList();
}

async function refreshSchedules() {
  const data = await apiJson("/api/schedules");
  state.schedules = data.schedules || [];
  renderScheduleList();
  refreshPoiAndSubscriptionOptions();
}

async function refreshEvents() {
  const data = await apiJson("/api/events?limit=120");
  state.events = data.events || [];
  renderEventFeed();
}

workbenchTabsEl?.addEventListener("click", (evt) => {
  const btn = evt.target.closest(".tab-btn");
  if (!btn) return;
  const tab = (btn.dataset.tab || "explore").trim();
  setWorkbenchTab(tab);
});

workflowRefreshBtnEl?.addEventListener("click", async () => {
  try {
    await loadWorkbenchData();
    toast("Workflow data refreshed");
  } catch (err) {
    toast(err.message);
  }
});

workflowRunBtnEl?.addEventListener("click", async () => {
  try {
    await createWorkflowRun();
    toast("Workflow run submitted");
  } catch (err) {
    toast(err.message);
  }
});

workflowSelectEl?.addEventListener("change", () => {
  const selected = workflowRecordFromRef(workflowSelectEl.value);
  if (!selected) return;
  if (workflowMetaEl) workflowMetaEl.textContent = `Selected ${selected.workflow_id}@${selected.version}`;
  if (selected.workflow_id === "forest_urban_change_series" && workflowUseSelectedEl) {
    workflowUseSelectedEl.checked = true;
    if (workflowMetaEl) workflowMetaEl.textContent = "Selected forest+urban workflow (requires selected carousel scenes).";
  }
  if (!state.workflowGraph.dirty) loadSelectedWorkflowIntoBuilder();
});

workflowBuilderLoadSelectedBtnEl?.addEventListener("click", () => {
  try {
    loadSelectedWorkflowIntoBuilder();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Failed to load workflow", true);
  }
});

workflowBuilderAddNodeBtnEl?.addEventListener("click", () => {
  try {
    addWorkflowBuilderNode();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Add node failed", true);
  }
});

workflowBuilderRemoveNodeBtnEl?.addEventListener("click", () => {
  try {
    removeSelectedWorkflowBuilderNode();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Remove node failed", true);
  }
});

workflowBuilderAddEdgeBtnEl?.addEventListener("click", () => {
  try {
    addWorkflowBuilderEdge();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Add edge failed", true);
  }
});

workflowBuilderRemoveEdgeBtnEl?.addEventListener("click", () => {
  try {
    removeWorkflowBuilderEdge();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Remove edge failed", true);
  }
});

workflowBuilderAutoLayoutBtnEl?.addEventListener("click", () => {
  try {
    autoLayoutWorkflowGraph();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Auto-layout failed", true);
  }
});

workflowBuilderApplyJsonBtnEl?.addEventListener("click", () => {
  try {
    applyWorkflowBuilderJson();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Apply JSON failed", true);
  }
});

workflowBuilderSaveBtnEl?.addEventListener("click", async () => {
  try {
    await saveWorkflowBuilderWorkflow();
    toast("Workflow version saved");
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Save workflow failed", true);
    toast(err.message || "Save workflow failed");
  }
});

workflowBuilderApplyNodeBtnEl?.addEventListener("click", () => {
  try {
    applySelectedWorkflowNodeEdit();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Node update failed", true);
  }
});

workflowBuilderSelectedNodeIdEl?.addEventListener("keydown", (evt) => {
  if (evt.key !== "Enter") return;
  evt.preventDefault();
  try {
    applySelectedWorkflowNodeEdit();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Node update failed", true);
  }
});

workflowBuilderPopoutBtnEl?.addEventListener("click", () => {
  try {
    openWorkflowBuilderWorkspaceWindow();
  } catch (err) {
    setWorkflowBuilderMeta(err.message || "Open workspace failed", true);
  }
});

workflowBuilderDockBtnEl?.addEventListener("click", () => {
  dockWorkflowBuilderFromWindow(true);
});

scheduleRefreshBtnEl?.addEventListener("click", async () => {
  try {
    await refreshSchedules();
    await refreshEvents();
    toast("Schedules refreshed");
  } catch (err) {
    toast(err.message);
  }
});

scheduleCreateBtnEl?.addEventListener("click", async () => {
  try {
    const wfRef = (scheduleWorkflowSelectEl?.value || "").trim();
    if (!wfRef) throw new Error("Choose a workflow for schedule");
    const [workflowId, workflowVersion] = wfRef.split("@");
    const payload = {
      type: (scheduleTypeEl?.value || "CRON"),
      workflow_id: workflowId,
      workflow_version: workflowVersion,
      cron: (scheduleCronEl?.value || "").trim() || null,
      interval_seconds: Number(scheduleIntervalSecondsEl?.value || 0),
      subscription_id: (scheduleSubscriptionSelectEl?.value || "").trim() || null,
      scope: { geometry: normalizeGeometryLongitudes(geometryFromBounds(map.getBounds())) },
      batching: {
        policy: "per_day_per_region",
        max_scenes_per_run: Number(scheduleMaxScenesEl?.value || 24),
        coalesce_minutes: 30,
      },
      caps: { max_runs_per_day: 24 },
      filters: {
        contract_id: selectedContractId(),
        source_id: selectedSourceId(),
        collection_id: activeCollectionId(),
      },
      enabled: true,
    };
    await apiJson("/api/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshSchedules();
    toast("Schedule created");
  } catch (err) {
    toast(err.message);
  }
});

scheduleSelectEl?.addEventListener("change", () => {
  state.selectedScheduleId = (scheduleSelectEl.value || "").trim() || null;
  renderScheduleList();
});

scheduleEnableBtnEl?.addEventListener("click", async () => {
  const scheduleId = (scheduleSelectEl?.value || "").trim();
  if (!scheduleId) {
    toast("Select a schedule first");
    return;
  }
  try {
    await apiJson(`/api/schedules/${encodeURIComponent(scheduleId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: true }),
    });
    await refreshSchedules();
    toast("Schedule enabled");
  } catch (err) {
    toast(err.message);
  }
});

scheduleDisableBtnEl?.addEventListener("click", async () => {
  const scheduleId = (scheduleSelectEl?.value || "").trim();
  if (!scheduleId) {
    toast("Select a schedule first");
    return;
  }
  try {
    await apiJson(`/api/schedules/${encodeURIComponent(scheduleId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false }),
    });
    await refreshSchedules();
    toast("Schedule disabled");
  } catch (err) {
    toast(err.message);
  }
});

poiSetCreateBtnEl?.addEventListener("click", async () => {
  try {
    const parsed = parseJsonInput(poiSetGeoJsonEl?.value || "", "POI geometry");
    if (!parsed) throw new Error("Enter POI geometry JSON");
    const payload = {
      name: (poiSetNameEl?.value || "poi_set").trim() || "poi_set",
      geometry: parsed.type ? parsed : null,
      features: Array.isArray(parsed.features) ? parsed.features : [],
    };
    await apiJson("/api/poi_sets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const poiData = await apiJson("/api/poi_sets");
    state.poiSets = poiData.poi_sets || [];
    refreshPoiAndSubscriptionOptions();
    toast("POI set created");
  } catch (err) {
    toast(err.message);
  }
});

subscriptionCreateBtnEl?.addEventListener("click", async () => {
  try {
    const poiSetId = (subscriptionPoiSetSelectEl?.value || "").trim() || null;
    const geom = parseJsonInput(subscriptionGeometryEl?.value || "", "Subscription geometry");
    const payload = {
      poi_set_id: poiSetId,
      geometry: geom || null,
      matching_rules: {},
      filters: {
        contract_id: selectedContractId(),
        source_id: selectedSourceId(),
        collection_id: activeCollectionId(),
      },
      enabled: true,
    };
    await apiJson("/api/subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const subData = await apiJson("/api/subscriptions");
    state.subscriptions = subData.subscriptions || [];
    refreshPoiAndSubscriptionOptions();
    toast("Subscription created");
  } catch (err) {
    toast(err.message);
  }
});

taskingRefreshBtnEl?.addEventListener("click", async () => {
  try {
    await refreshTaskingPanel();
    toast("Tasking orders refreshed");
  } catch (err) {
    toast(err.message || "Tasking refresh failed");
  }
});

runsRefreshBtnEl?.addEventListener("click", async () => {
  try {
    await refreshRuns();
    await refreshEvents();
    toast("Runs refreshed");
  } catch (err) {
    toast(err.message);
  }
});

runsSelectEl?.addEventListener("change", async () => {
  const runId = (runsSelectEl.value || "").trim();
  if (!runId) return;
  try {
    await showRunInspector(runId);
  } catch (err) {
    toast(err.message);
  }
});

runInspectorOutEl?.addEventListener("click", async (evt) => {
  const target = evt.target;
  if (!(target instanceof Element)) return;
  const btn = target.closest(".evidence-jump");
  if (!(btn instanceof HTMLButtonElement)) return;
  evt.preventDefault();
  const sceneId = (btn.dataset.sceneId || "").trim();
  if (!sceneId) return;
  try {
    await jumpToEvidenceScene(sceneId);
  } catch (err) {
    toast(err.message || "Evidence jump failed");
  }
});

document.addEventListener("mousemove", (evt) => {
  if (!state.workflowGraph.dragNodeId) return;
  dragWorkflowNode(evt);
});

document.addEventListener("mouseup", () => {
  stopWorkflowNodeDrag();
});

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

timeCarouselListEl?.addEventListener("scroll", () => {
  maybeLoadMoreCarouselOnScroll();
});

document.getElementById("searchBtn")?.addEventListener("click", async () => {
  try {
    await searchArchive();
  } catch (err) {
    toast(err.message);
  }
});

sourcePickerBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  setSourcePickerOpen(!state.sourcePickerOpen);
});

sourcePickerMenuEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
});

layerSentinelBaseToggleEl?.addEventListener("change", async () => {
  state.layerControl.sentinelBaseEnabled = Boolean(layerSentinelBaseToggleEl.checked);
  syncEnabledSourcesFromLayerControl();
  if (!isSourceEnabled(state.preferredActionSource)) {
    setPreferredActionSource(selectedSourceId());
  }
  try {
    await refreshSearchForLayerControls();
  } catch (err) {
    toast(err.message || "Layer update failed");
  }
});

layerSatellogicToggleEl?.addEventListener("change", async () => {
  state.layerControl.satellogicOverlayEnabled = Boolean(layerSatellogicToggleEl.checked);
  syncEnabledSourcesFromLayerControl();
  if (!isSourceEnabled(state.preferredActionSource)) {
    setPreferredActionSource(selectedSourceId());
  }
  loadContracts().catch(() => {});
  try {
    await refreshSearchForLayerControls();
  } catch (err) {
    toast(err.message || "Layer update failed");
  }
});

layerSentinelFramesToggleEl?.addEventListener("change", () => {
  state.layerControl.sentinelFramesEnabled = Boolean(layerSentinelFramesToggleEl.checked);
  if (!state.searchParams && !state.items.length) return;
  refreshMapMode(false).catch((err) => toast(err.message || "Layer update failed"));
});

layerSatellogicFramesToggleEl?.addEventListener("change", () => {
  state.layerControl.satellogicFramesEnabled = Boolean(layerSatellogicFramesToggleEl.checked);
  if (!state.searchParams && !state.items.length) return;
  refreshMapMode(false).catch((err) => toast(err.message || "Layer update failed"));
});

layerSentinelWmtsToggleEl?.addEventListener("change", () => {
  state.layerControl.sentinelWmtsEnabled = Boolean(layerSentinelWmtsToggleEl.checked);
  if (sentinelWmtsMetaEl && !state.layerControl.sentinelWmtsEnabled) {
    sentinelWmtsMetaEl.textContent = "WMTS status: outlines-only fallback (disabled in layer controls)";
  } else if (sentinelWmtsMetaEl && state.sentinelWmtsConfig?.available && state.layerControl.sentinelWmtsEnabled) {
    sentinelWmtsMetaEl.textContent = sentinelWmtsStatusText(state.sentinelWmtsConfig);
  }
  applySentinelWmtsLayer();
  applySentinelWmtsAnalyticLayers().catch((err) => toast(err.message || "Sentinel WMTS analytic layer update failed"));
  applyLayerControlUiState();
});

layerSentinelStacToggleEl?.addEventListener("change", async () => {
  state.layerControl.sentinelStacOverlayEnabled = Boolean(layerSentinelStacToggleEl.checked);
  try {
    await refreshSearchForLayerControls();
  } catch (err) {
    toast(err.message || "Layer update failed");
  }
});

sentinelAnalyticsLayersEl?.addEventListener("change", (evt) => {
  const target = evt.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (target.type !== "checkbox") return;
  const layerId = (target.dataset.layerId || "").trim();
  if (!layerId) return;
  state.layerControl.sentinelAnalyticCollections = (state.layerControl.sentinelAnalyticCollections || []).map((row) => (
    row.id === layerId ? { ...row, enabled: Boolean(target.checked) } : row
  ));
  applySentinelWmtsAnalyticLayers().catch((err) => toast(err.message || "Layer update failed"));
});

document.getElementById("gifBtn")?.addEventListener("click", async () => {
  try {
    await buildGif();
  } catch (err) {
    toast(err.message);
  }
});

document.getElementById("playBtn")?.addEventListener("click", () => {
  if (!state.items.length) return;
  if (!timelineEl) return;
  if (state.playTimer) clearInterval(state.playTimer);
  state.playTimer = setInterval(() => {
    const next = (Number(timelineEl.value) + 1) % state.items.length;
    showFrame(next);
  }, 900);
});

document.getElementById("pauseBtn")?.addEventListener("click", () => {
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
});

compareSliderEl?.addEventListener("input", () => {
  if (!beforeClipEl) return;
  beforeClipEl.style.width = `${compareSliderEl.value}%`;
});

timelineEl?.addEventListener("input", () => {
  showFrame(Number(timelineEl.value));
});

function startWmtsBandDrag(clientX) {
  if (!mapTimebarCanvasEl || !isWmtsBandInteractive()) return false;
  const rect = mapTimebarCanvasEl.getBoundingClientRect();
  const width = rect.width;
  const height = mapTimebarCanvasEl.clientHeight;
  if (width <= 0 || height <= 0) return false;
  const x = Math.max(0, Math.min(width, clientX - rect.left));
  const { start, end } = timelineWindow();
  const band = wmtsBandRectForTimeline(width, height, start, end);
  const mode = wmtsBandHitMode(x, band);
  if (!mode || !band) return false;
  state.timeline.wmtsDrag = {
    mode,
    pointerStartX: x,
    startStartMs: band.startMs,
    startEndExclusiveMs: band.endExclusiveMs,
  };
  updateMapTimebarCursor(clientX);
  return true;
}

function updateWmtsBandDrag(clientX) {
  if (!mapTimebarCanvasEl || !state.timeline.wmtsDrag) return;
  const drag = state.timeline.wmtsDrag;
  const rect = mapTimebarCanvasEl.getBoundingClientRect();
  const width = rect.width;
  if (width <= 0) return;
  const x = Math.max(0, Math.min(width, clientX - rect.left));
  const { start, end } = timelineWindow();
  const msAtPointer = timelineXToMs(x, start, end, width);
  const msAtStartPointer = timelineXToMs(drag.pointerStartX, start, end, width);
  if (!Number.isFinite(msAtPointer) || !Number.isFinite(msAtStartPointer)) return;
  const deltaMs = msAtPointer - msAtStartPointer;
  let nextStart = drag.startStartMs;
  let nextEndExclusive = drag.startEndExclusiveMs;
  if (drag.mode === "move") {
    nextStart += deltaMs;
    nextEndExclusive += deltaMs;
  } else if (drag.mode === "resize-left") {
    nextStart = Math.min(msAtPointer, drag.startEndExclusiveMs - WMTS_BAND_MIN_WINDOW_MS);
  } else if (drag.mode === "resize-right") {
    nextEndExclusive = Math.max(msAtPointer, drag.startStartMs + WMTS_BAND_MIN_WINDOW_MS);
  }
  setWmtsPlaybackWindowFromMs(nextStart, nextEndExclusive);
  updateMapTimebarCursor(clientX);
}

function stopWmtsBandDrag() {
  if (!state.timeline.wmtsDrag) return;
  state.timeline.wmtsDrag = null;
  updateMapTimebarCursor();
}

mapTimebarCanvasEl?.addEventListener("mousemove", (evt) => {
  if (state.timeline.wmtsDrag) {
    updateWmtsBandDrag(evt.clientX);
    return;
  }
  updateMapTimebarCursor(evt.clientX);
  setTimelineHoverFromClientPoint(evt.clientX, evt.clientY);
});

mapTimebarCanvasEl?.addEventListener("mouseleave", () => {
  if (state.timeline.wmtsDrag) return;
  updateMapTimebarCursor();
  hideMapTimebarTooltip();
});

mapTimebarCanvasEl?.addEventListener("mousedown", (evt) => {
  if (evt.button !== 0) return;
  if (!startWmtsBandDrag(evt.clientX)) return;
  evt.preventDefault();
  hideMapTimebarTooltip();
  const onMove = (moveEvt) => updateWmtsBandDrag(moveEvt.clientX);
  const onUp = () => {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    stopWmtsBandDrag();
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
});

mapTimebarCanvasEl?.addEventListener("wheel", (evt) => {
  if (state.timeline.wmtsDrag) return;
  evt.preventDefault();
  zoomMapTimebarAt(evt.clientX, evt.deltaY < 0);
  setTimelineHoverFromClientPoint(evt.clientX, evt.clientY);
}, { passive: false });

mapTimebarCanvasEl?.addEventListener("click", (evt) => {
  if (state.timeline.wmtsDrag) return;
  const rect = mapTimebarCanvasEl.getBoundingClientRect();
  const width = rect.width;
  const x = Math.max(0, Math.min(width, evt.clientX - rect.left));
  const { start, end } = timelineWindow();
  const band = wmtsBandRectForTimeline(width, mapTimebarCanvasEl.clientHeight, start, end);
  if (wmtsBandHitMode(x, band)) return;
  const nearest = nearestTimelineRenderedEntry(x, Math.max(TIMELINE_HIT_PX, 8));
  if (!nearest || nearest.event?.kind !== "image") return;
  focusTimelineImageEvent(nearest.event).catch((err) => toast(err.message || "Failed to focus timeline image"));
});

mapTimebarPageBackBtnEl?.addEventListener("click", () => {
  const { span } = timelineWindow();
  shiftMapTimebarBy(-span);
});

mapTimebarPageForwardBtnEl?.addEventListener("click", () => {
  const { span } = timelineWindow();
  shiftMapTimebarBy(span);
});

mapTimebarDayBackBtnEl?.addEventListener("click", () => {
  shiftMapTimebarBy(-DAY_MS);
});

mapTimebarDayForwardBtnEl?.addEventListener("click", () => {
  shiftMapTimebarBy(DAY_MS);
});

const centerTimelineFromInput = () => {
  const iso = toUtcIsoFromLocalInput(mapTimebarCenterInputEl?.value || "");
  const ms = iso ? new Date(iso).getTime() : Number.NaN;
  if (!Number.isFinite(ms)) {
    toast("Enter a valid date/time to center the timeline.");
    return;
  }
  centerMapTimebarAt(ms);
};

const resetMapTimebarToNow = () => {
  state.timeline.userAdjusted = false;
  hideMapTimebarTooltip();
  refreshMapTimebarData();
};

mapTimebarCenterBtnEl?.addEventListener("click", resetMapTimebarToNow);
mapTimebarCenterInputEl?.addEventListener("keydown", (evt) => {
  if (evt.key !== "Enter") return;
  evt.preventDefault();
  centerTimelineFromInput();
});

frameSelectEl?.addEventListener("change", () => {
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
  renderTimeCarouselForViewport();
  scheduleMapRefresh();
});

map.on("move zoom", () => {
  updateMapStatus();
});

map.on("draw:created draw:edited draw:deleted", () => {
  ensureLayerEditorControlAnchor();
  if (layerEditorPopoverEl?.classList.contains("open")) positionLayerEditorPopover();
});

map.on("draw:toolbaropened draw:toolbarclosed", () => {
  ensureLayerEditorControlAnchor();
  if (layerEditorPopoverEl?.classList.contains("open")) positionLayerEditorPopover();
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
  await refreshMapMode(false, { renderCarousel: false });
  toast("Selections cleared");
});

compareModeBtnEl.addEventListener("click", () => {
  if (!state.overviewItems.length) {
    toast("Run a search first");
    return;
  }
  setCompareMode(!state.compareMode);
});

layerEditorSelectEl?.addEventListener("change", async (evt) => {
  const mode = evt?.target?.value || "natural";
  try {
    await applyDetailLayerMode(mode, true);
  } catch (err) {
    toast(err.message || "Layer update failed");
  }
});

layerEditorPopoverEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
});

animateSeriesBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideLayerEditorPopover();
  hideGenerateSeriesReportPopover();
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

generateSeriesReportBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideLayerEditorPopover();
  hideAnimateSeriesPopover();
  hideDownloadPopover();
  toggleGenerateSeriesReportPopover();
});

generateSeriesReportRunBtnEl?.addEventListener("click", async (evt) => {
  evt.stopPropagation();
  try {
    await startSelectedSeriesReportRun();
  } catch (err) {
    setGenerateSeriesReportStatus(err.message || "Report run failed", true);
    toast(err.message || "Report run failed");
  }
});

generateSeriesReportCloseBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideGenerateSeriesReportPopover();
});

generateSeriesReportPopoverEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
});

downloadMenuBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  hideLayerEditorPopover();
  hideAnimateSeriesPopover();
  hideGenerateSeriesReportPopover();
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
  if (state.taskingMode === "area-drawing") return;
  const p = evt.containerPoint;
  showContextMenu(p.x, p.y, evt.latlng);
});

map.on("dblclick", (evt) => {
  if (state.taskingMode !== "area-drawing") return;
  L.DomEvent.stop(evt);
  finishTaskingArea(evt.containerPoint);
});

map.on("click", (evt) => {
  if (state.taskingMode === "point-await-click") {
    hideContextMenu();
    onTaskingPointSelected(evt.latlng, evt.containerPoint);
    return;
  }
  if (state.taskingMode === "area-drawing") {
    hideContextMenu();
    onTaskingAreaVertex(evt.latlng);
    return;
  }
  if (taskingFormPopoverEl?.classList.contains("open")) {
    cancelTaskingInteraction();
  }
  hideContextMenu();
  hideTaskingTypeMenu();
  hideLocationHistoryMenu();
  hideLayerEditorPopover();
  hideAnimateSeriesPopover();
  hideGenerateSeriesReportPopover();
  hideDownloadPopover();
  setSourcePickerOpen(false);
});

document.addEventListener("click", (evt) => {
  if (mapLocateEl && !mapLocateEl.contains(evt.target)) hideLocationHistoryMenu();
  if (mapContextMenuEl && !mapContextMenuEl.contains(evt.target)) hideContextMenu();
  if (taskingTypeMenuEl && !taskingTypeMenuEl.contains(evt.target)) hideTaskingTypeMenu();
  if (taskingFormPopoverEl && !taskingFormPopoverEl.contains(evt.target)) {
    if (taskingFormPopoverEl.classList.contains("open")) cancelTaskingInteraction();
  }
  if (animateSeriesPopoverEl && animateSeriesBtnEl) {
    const target = evt.target;
    if (!animateSeriesPopoverEl.contains(target) && !animateSeriesBtnEl.contains(target)) hideAnimateSeriesPopover();
  }
  if (generateSeriesReportPopoverEl && generateSeriesReportBtnEl) {
    const target = evt.target;
    if (!generateSeriesReportPopoverEl.contains(target) && !generateSeriesReportBtnEl.contains(target)) hideGenerateSeriesReportPopover();
  }
  if (layerEditorPopoverEl && layerEditorBtnEl) {
    const target = evt.target;
    if (!layerEditorPopoverEl.contains(target) && !layerEditorBtnEl.contains(target)) hideLayerEditorPopover();
  }
  if (downloadPopoverEl && downloadMenuBtnEl) {
    const target = evt.target;
    if (!downloadPopoverEl.contains(target) && !downloadMenuBtnEl.contains(target)) hideDownloadPopover();
  }
  if (sourcePickerMenuEl && sourcePickerBtnEl) {
    const target = evt.target;
    if (!sourcePickerMenuEl.contains(target) && !sourcePickerBtnEl.contains(target)) setSourcePickerOpen(false);
  }
});

document.addEventListener("keydown", (evt) => {
  if (evt.key === "Escape") {
    hideLocationHistoryMenu();
    hideLayerEditorPopover();
    hideAnimateSeriesPopover();
    hideGenerateSeriesReportPopover();
    hideDownloadPopover();
    setSourcePickerOpen(false);
    cancelTaskingInteraction();
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

ctxTaskImageEl.addEventListener("click", (evt) => {
  evt.stopPropagation();
  const point = state.contextMenuPoint || { x: 24, y: 24 };
  hideContextMenu();
  if (!state.taskingProducts.length) {
    loadTaskingProducts().catch(() => {});
  }
  showTaskingTypeMenu(point.x, point.y);
});

taskingTypePointEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  beginPointTaskingFlow();
});

taskingTypeAreaEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  beginAreaTaskingFlow();
});

taskingFormPopoverEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
});

taskingCancelBtnEl?.addEventListener("click", (evt) => {
  evt.stopPropagation();
  cancelTaskingInteraction();
});

taskingFormEl?.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  try {
    await submitTaskingOrder();
  } catch (err) {
    toast(err.message || "Tasking submit failed");
  }
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

sourceSelectEl?.addEventListener("change", async () => {
  setPreferredActionSource(sourceSelectEl.value || "satellogic");
  try {
    await loadContracts();
    await loadCollections();
    applyLayerControlUiState();
  } catch (err) {
    toast(err.message || "Source update failed");
  }
  if (isSatellogicSource()) {
    refreshTaskingPanel().catch(() => {});
  } else if (taskingOrdersMetaEl) {
    taskingOrdersMetaEl.textContent = "Tasking order panel is currently Satellogic-only.";
  }
  if (!state.searchParams) return;
  state.lastDetailRequestKey = null;
  state.lastDetailCoverageBounds = null;
  state.lastDetailCoverageZoom = null;
  state.lastDetailContextKey = null;
  state.prefetchTileUrlSeen.clear();
  state.useCogTileProxy = Boolean(state.layerControl.satellogicOverlayEnabled);
  state.tileProxyWarned = false;
  state.tileProxyErrorCount = 0;
  refreshMapMode(true).catch((err) => toast(err.message));
});

contractSelectEl.addEventListener("change", () => {
  state.satellogicContractMemory = (contractSelectEl.value || "").trim() || state.satellogicContractMemory;
  loadSatellogicCollections().catch((err) => toast(err.message));
  refreshTaskingPanel().catch(() => {});
  if (!state.searchParams) return;
  state.lastDetailRequestKey = null;
  state.lastDetailCoverageBounds = null;
  state.lastDetailCoverageZoom = null;
  state.lastDetailContextKey = null;
  state.prefetchTileUrlSeen.clear();
  state.useCogTileProxy = Boolean(state.layerControl.satellogicOverlayEnabled);
  state.tileProxyWarned = false;
  state.tileProxyErrorCount = 0;
  refreshMapMode(true).catch((err) => toast(err.message));
});

collectionEl?.addEventListener("change", () => {
  const nextCollection = (collectionEl.value || "").trim();
  if (!nextCollection) return;
  setCollectionForSource("satellogic", nextCollection, false);
  setPreferredActionSource("satellogic");
});

sentinelCollectionEl?.addEventListener("change", () => {
  const nextBase = (sentinelCollectionEl.value || "").trim();
  if (!nextBase) return;
  setCollectionForSource("merlin-s2", nextBase, false);
  setPreferredActionSource("merlin-s2");
  applyLayerControlUiState();
});

updateLockButtonState();
updateMapStatus();
refreshMapTimebarData();
loadLocationHistory();
ensureLayerEditorControlAnchor();
applyLayerControlUiState();
setSourcePickerOpen(false);
if (layerEditorSelectEl) layerEditorSelectEl.value = normalizeDetailLayerMode(state.detailLayerMode);
setWorkflowBuilderDetached(false);
setWorkflowGraph(defaultWorkflowGraphNodes(), false);
if (DEBUG_NET) {
  if (mapDebugStatsEl) mapDebugStatsEl.style.display = "block";
  if (tilePerfHudEl) tilePerfHudEl.style.display = "inline-flex";
  updateDebugStats();
} else if (mapDebugStatsEl) {
  mapDebugStatsEl.style.display = "none";
  if (tilePerfHudEl) tilePerfHudEl.style.display = "none";
}

(async () => {
  resetLayerSearchResults();
  await loadSources();
  await loadContracts();
  await loadCollections();
  await loadSentinelWmtsConfig();
  applyLayerControlUiState();
  try {
    await loadTaskingProducts();
    await refreshTaskingPanel();
  } catch (err) {
    if (taskingOrdersMetaEl) taskingOrdersMetaEl.textContent = `Tasking load failed: ${err.message}`;
  }
  try {
    await loadWorkbenchData();
  } catch (err) {
    toast(`Workbench load failed: ${err.message}`);
  }
  setWorkbenchTab("explore");
})();

window.addEventListener("beforeunload", () => {
  const popup = state.workflowBuilder.popoutWindow;
  if (popup && !popup.closed) {
    try {
      popup.close();
    } catch (_) {
      // ignore
    }
  }
});
