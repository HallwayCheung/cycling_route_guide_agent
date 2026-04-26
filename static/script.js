let map;
let currentThreadId = null;
let selectedRouteId = null;
let routeLayers = {};
let poiMarkers = [];
let routePointMarkers = [];
let currentRoutes = [];
let stepCount = 0;
let lastProgress = 0;
let mapPickMode = null;
let currentAnalysis = null;
let currentWeatherSnapshot = null;
let isPlanning = false;
let isFinalizing = false;
let manualMapPoints = { origin: null, destination: null, waypoints: [] };
let mapPickMarkers = { origin: null, destination: null, waypoints: [] };
let segmentHighlightLayer = null;
let routeNameMarkers = [];
const getEl = (id) => document.getElementById(id);

const ROUTE_COLORS = ["#0f766e", "#0284c7", "#ea580c", "#7c3aed", "#ef4444"];
const NODE_TITLE_MAP = {
  demand_parser: "Demand Parser",
  intent_research: "Intent Agent",
  geospatial_analysis: "Geo Agent",
  coordinate_control: "Coordinate Agent",
  planner: "Route Agent",
  executor: "MCP Data Agent",
  route_policy: "Policy Agent",
  lifestyle: "Lifestyle Agent",
  physics: "Simulation Agent",
  explainability: "Explain Agent",
  rag: "RAG Agent",
  safety_supply: "Safety Agent",
  finalizer: "Roadbook Agent",
};
const AGENT_CAPABILITY_MAP = {
  "Intent Agent": ["口语意图解析", "约束抽取", "周末/日落识别"],
  "Geo Agent": ["城市别名归一", "区域锚点定位", "环线理解"],
  "Route Agent": ["候选路线生成", "人工修正回路", "多策略排序"],
  "Policy Agent": ["自行车道优先", "禁骑道路拦截", "道路风险筛选"],
  "Lifestyle Agent": ["时间窗规划", "观景时刻", "风景体验"],
  "Simulation Agent": ["爬升推演", "配速估算", "卡路里预算"],
  "Explain Agent": ["分段说明", "关键道路提炼", "地图阅读摘要"],
  "RAG Agent": ["社区情报补强", "封路风险回退", "经验提示"],
  "MCP Data Agent": ["路由数据", "POI补给", "天气与高程"],
};

let uiBound = false;

function shortPlaceLabel(text) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  if (!raw.includes(",") && raw.length <= 16) return raw;
  const parts = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => !/^\d+$/.test(item) && !["中国"].includes(item));
  const scenic = parts.find((item) => /景区|景点|公园|观景|游客中心|广场|海滩|大道|山|湾/.test(item));
  if (scenic) return scenic;
  const district = parts.find((item) => /区|县|镇|乡/.test(item));
  const city = parts.find((item) => /市/.test(item));
  if (city && district) return `${city.replace("市", "")}·${district}`;
  return parts[0] || raw.slice(0, 16);
}

function shortRouteBrief(text) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  return raw
    .replaceAll("按先爬后放松的节奏组织路线，", "先爬后平，")
    .replaceAll("按先巡航后上强度的节奏组织路线，", "先平后爬，")
    .replaceAll("道路类型识别有限，建议现场结合导航复核", "需现场复核")
    .slice(0, 72);
}

function resolveBikeInfra(analysis = {}) {
  const infra = { ...(analysis.bike_infra_advice || {}) };
  const policy = analysis.bike_policy || {};
  const selected = getSelectedRoute();
  const metrics = selected?.metrics || {};
  const selectedPolicy = selected?.policy || analysis.selected_route_policy || {};

  const infraLooksEmpty =
    Number(infra.cycleway_hits || 0) === 0 &&
    Number(infra.bike_friendly_hits || 0) === 0 &&
    Number(infra.primary_hits || 0) === 0 &&
    Number(infra.forbidden_hits || 0) === 0 &&
    !(infra.named_cycleways || []).length;

  return {
    ...infra,
    cycleway_hits: Number(
      infraLooksEmpty ? policy.cycleway_hits ?? selectedPolicy.cycleway_hits ?? metrics.cycleway_hits ?? 0 : infra.cycleway_hits || 0
    ),
    bike_friendly_hits: Number(
      infraLooksEmpty
        ? policy.bike_friendly_hits ?? selectedPolicy.bike_friendly_hits ?? metrics.bike_friendly_hits ?? 0
        : infra.bike_friendly_hits || 0
    ),
    primary_hits: Number(
      infraLooksEmpty ? policy.primary_hits ?? selectedPolicy.primary_hits ?? metrics.primary_road_hits ?? 0 : infra.primary_hits || 0
    ),
    forbidden_hits: Number(
      infraLooksEmpty ? policy.forbidden_hits ?? selectedPolicy.forbidden_hits ?? metrics.forbidden_road_hits ?? 0 : infra.forbidden_hits || 0
    ),
    named_cycleways: infra.named_cycleways || [],
  };
}

function bindUi() {
  if (uiBound) return;
  uiBound = true;

  getEl("start-btn")?.addEventListener("click", startPlan);
  getEl("replan-btn")?.addEventListener("click", replanFromEditor);
  getEl("confirm-btn")?.addEventListener("click", finalizePlan);
  getEl("copy-btn")?.addEventListener("click", copyRoadbook);
  getEl("close-rp-btn")?.addEventListener("click", () => {
    getEl("roadbook-panel")?.classList.add("hidden");
  });
  getEl("pick-origin-btn")?.addEventListener("click", () => setMapPickMode("origin"));
  getEl("pick-waypoint-btn")?.addEventListener("click", () => setMapPickMode("waypoint"));
  getEl("pick-destination-btn")?.addEventListener("click", () => setMapPickMode("destination"));
  getEl("clear-map-picks-btn")?.addEventListener("click", clearMapPicks);

  document.querySelectorAll(".sample-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const input = getEl("intent-input");
      if (input) input.value = button.dataset.sample || "";
    });
  });

  document.addEventListener("click", handleDocumentClick);
  getEl("segment-list")?.addEventListener("click", handleSegmentClick);

  startClock();
  bootstrapSystemGrid();

  try {
    initMap();
  } catch (error) {
    console.error("Map init failed:", error);
    setStatus("地图初始化失败，已降级为无地图模式", "error");
    const insight = getEl("map-insight-text");
    if (insight) {
      insight.textContent = "地图脚本加载异常，但智能规划仍可继续执行。";
    }
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindUi);
} else {
  bindUi();
}

function initMap() {
  if (typeof L === "undefined") {
    throw new Error("Leaflet 未加载");
  }
  map = L.map("map", { zoomControl: false }).setView([35.8617, 104.1954], 5);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png", {
    attribution: "© OpenStreetMap © CARTO",
    maxZoom: 19,
  }).addTo(map);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png", {
    attribution: "© OpenStreetMap © CARTO",
    maxZoom: 19,
    pane: "overlayPane",
  }).addTo(map);

  L.control.zoom({ position: "bottomright" }).addTo(map);

  map.on("click", (event) => {
    handleMapPick(event.latlng);
  });

  requestAnimationFrame(() => {
    map.invalidateSize();
  });
  window.addEventListener("resize", () => {
    map?.invalidateSize();
  });
}

function hasMap() {
  return Boolean(map && typeof map.removeLayer === "function");
}

function startClock() {
  const el = getEl("clock");
  if (!el) return;
  const tick = () => {
    el.textContent = new Date().toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };
  tick();
  setInterval(tick, 1000);
}

function bootstrapSystemGrid() {
  renderSystemGrid({
    agent_stack: [
      { name: "Intent Agent", status: "idle", detail: "等待解析用户输入的骑行需求" },
      { name: "Geo Agent", status: "idle", detail: "等待锁定区域、地名和路线别名" },
      { name: "Route Agent", status: "idle", detail: "等待生成候选路线与修正方案" },
      { name: "Policy Agent", status: "idle", detail: "等待执行自行车路权与禁骑道路规则" },
      { name: "Lifestyle Agent", status: "idle", detail: "等待补充时间窗、天气和体验建议" },
      { name: "Simulation Agent", status: "idle", detail: "等待推演爬升、体能和配速节奏" },
      { name: "Explain Agent", status: "idle", detail: "等待生成分段说明和关键道路摘要" },
      { name: "RAG Agent", status: "idle", detail: "等待补充社区骑行经验和风险情报" },
      { name: "MCP Data Agent", status: "idle", detail: "等待调用路线、天气、POI、高程等数据源" },
    ],
  });
}

function setStatus(text, mode = "normal") {
  const statusText = getEl("status-text");
  if (statusText) statusText.textContent = text;
  const dot = getEl("status-dot");
  if (!dot) return;
  dot.className = "status-dot";
  if (mode === "busy") dot.classList.add("busy");
  if (mode === "error") dot.classList.add("error");
}

function updateProgress(value) {
  lastProgress = Math.max(lastProgress, value || 0);
  const bar = getEl("progress-bar");
  const percent = getEl("progress-percent");
  if (bar) bar.style.width = `${lastProgress}%`;
  if (percent) percent.textContent = `${lastProgress}%`;
}

function addStep(label, state = "active", nodeName = "", progress = null) {
  const timeline = getEl("timeline");
  const timelineEmpty = getEl("timeline-empty");
  if (!timeline) return;
  timelineEmpty?.classList.add("hidden");

  timeline.querySelectorAll(".tl-step.active").forEach((item) => {
    item.classList.remove("active");
    item.classList.add("done");
    const dot = item.querySelector(".tl-dot");
    if (dot) dot.textContent = "✓";
  });

  stepCount += 1;
  const step = document.createElement("div");
  step.className = `tl-step ${state}`;
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  step.innerHTML = `
    <div class="tl-dot">${progress ?? stepCount}</div>
    <div class="tl-body">
      <div class="tl-meta">
        <span class="tl-title">${NODE_TITLE_MAP[nodeName] || "Planner"}</span>
        <span class="tl-time">${now}</span>
      </div>
      <div class="tl-text">${label}</div>
    </div>
  `;
  timeline.appendChild(step);
  timeline.scrollTop = timeline.scrollHeight;
}

function resetTimeline() {
  getEl("timeline") && (getEl("timeline").innerHTML = "");
  getEl("timeline-empty")?.classList.remove("hidden");
  stepCount = 0;
  lastProgress = 0;
  updateProgress(0);
}

function safeSetHtml(id, html = "") {
  const el = getEl(id);
  if (el) el.innerHTML = html;
}

function safeSetText(id, text = "") {
  const el = getEl(id);
  if (el) el.textContent = text;
}

function safeToggleHidden(id, hidden = true) {
  const el = getEl(id);
  if (!el) return;
  el.classList.toggle("hidden", hidden);
}

function clearMap() {
  if (hasMap()) {
    Object.values(routeLayers).forEach((layer) => map.removeLayer(layer));
  }
  routeLayers = {};
  currentRoutes = [];
  if (hasMap()) {
    poiMarkers.forEach((marker) => map.removeLayer(marker));
  }
  poiMarkers = [];
  if (hasMap()) {
    routePointMarkers.forEach((marker) => map.removeLayer(marker));
  }
  routePointMarkers = [];
  clearSegmentHighlight();
  clearRoadNameMarkers();
  clearMapPicks({ preserveInputs: true, keepMode: true });
  selectedRouteId = null;
}

function resetPanels() {
  resetTimeline();
  clearMap();
  currentAnalysis = null;
  currentWeatherSnapshot = null;
  [
    "route-legend",
    "poi-drawer",
    "roadbook-panel",
    "weather-section",
    "feature-section",
    "atlas-section",
    "segment-section",
    "route-section",
    "focus-section",
    "editor-section",
    "metrics-strip",
    "route-resolution",
  ].forEach((id) => safeToggleHidden(id, true));
  safeSetHtml("route-cards", "");
  safeSetHtml("legend-list", "");
  safeSetHtml("poi-list", "");
  safeSetHtml("insight-grid", "");
  safeSetHtml("feature-grid", "");
  safeSetHtml("atlas-grid", "");
  safeSetHtml("segment-list", "");
  safeSetText("focus-title", "当前聚焦");
  safeSetHtml("focus-body", "");
  safeSetHtml("road-ribbon", "");
  safeToggleHidden("road-ribbon", true);
  safeSetHtml("analysis-overview", `<span class="muted">候选路线生成后，这里会展示拟合度、时间规划和道路特征。</span>`);
  getEl("analysis-overview")?.classList.add("empty");
  safeSetHtml("metrics-strip", "");
  const chips = getEl("constraint-chips");
  if (chips) {
    chips.className = "chip-cloud empty";
    chips.innerHTML = `<span class="muted">系统会在这里展示识别到的区域、环线类型和骑行约束。</span>`;
  }
  safeSetHtml("route-resolution", "");
  safeSetHtml("roadbook-body", "");
  safeSetText("resolved-region", "等待解析");
  safeSetText("map-insight-text", "地图会高亮主线、关键道路和当前分段。");
  setMapPickMode(null);
  bootstrapSystemGrid();
}

function setMapPickMode(mode) {
  mapPickMode = mode;
  ["origin", "waypoint", "destination"].forEach((key) => {
    const button = document.getElementById(`pick-${key}-btn`);
    if (!button) return;
    button.classList.toggle("is-active", key === mode);
  });

  const statusMessage = mode
    ? `地图点选模式已开启：${mode === "origin" ? "请选择起点" : mode === "destination" ? "请选择终点" : "请在地图上添加途经点"}`
    : "地图可自由拖动，也可点选起终点和途经点。";
  document.getElementById("map-insight-text").textContent = statusMessage;
}

function clearMapPicks(options = {}) {
  const { preserveInputs = false, keepMode = false } = options;

  if (hasMap() && mapPickMarkers.origin) {
    map.removeLayer(mapPickMarkers.origin);
    mapPickMarkers.origin = null;
  }
  if (hasMap() && mapPickMarkers.destination) {
    map.removeLayer(mapPickMarkers.destination);
    mapPickMarkers.destination = null;
  }
  if (hasMap()) {
    mapPickMarkers.waypoints.forEach((marker) => map.removeLayer(marker));
  }
  mapPickMarkers.waypoints = [];

  manualMapPoints = { origin: null, destination: null, waypoints: [] };

  if (!preserveInputs) {
    const originInput = document.getElementById("edit-origin");
    const destinationInput = document.getElementById("edit-destination");
    const waypointInput = document.getElementById("edit-waypoints");
    if (originInput) originInput.value = "";
    if (destinationInput) destinationInput.value = "";
    if (waypointInput) waypointInput.value = "";
  }

  if (!keepMode) {
    setMapPickMode(null);
  }
}

function handleMapPick(latlng) {
  if (!mapPickMode) return;

  const coord = `${latlng.lng.toFixed(6)},${latlng.lat.toFixed(6)}`;
  if (mapPickMode === "origin") {
    manualMapPoints.origin = coord;
    document.getElementById("edit-origin").value = coord;
    if (mapPickMarkers.origin) map.removeLayer(mapPickMarkers.origin);
    mapPickMarkers.origin = createMapPickMarker(latlng, "起点", "#10b981");
    setMapPickMode(null);
    return;
  }

  if (mapPickMode === "destination") {
    manualMapPoints.destination = coord;
    document.getElementById("edit-destination").value = coord;
    if (mapPickMarkers.destination) map.removeLayer(mapPickMarkers.destination);
    mapPickMarkers.destination = createMapPickMarker(latlng, "终点", "#ef4444");
    setMapPickMode(null);
    return;
  }

  manualMapPoints.waypoints.push(coord);
  mapPickMarkers.waypoints.push(createMapPickMarker(latlng, `途经点 ${manualMapPoints.waypoints.length}`, "#0284c7"));
  document.getElementById("edit-waypoints").value = manualMapPoints.waypoints.join(" / ");
}

function createMapPickMarker(latlng, label, color) {
  if (!hasMap()) return null;
  const marker = L.circleMarker([latlng.lat, latlng.lng], {
    radius: 7,
    color: "#ffffff",
    weight: 3,
    fillColor: color,
    fillOpacity: 0.96,
  }).bindTooltip(label, { permanent: false });
  marker.addTo(map);
  return marker;
}

async function startPlan(customIntent = null) {
  try {
    if (isPlanning) return;
    const input = getEl("intent-input");
    const intent = (customIntent ?? input?.value ?? "").trim();
    if (!intent) {
      input?.focus();
      return;
    }

    const button = getEl("start-btn");
    if (button) {
      button.disabled = true;
      button.textContent = "规划中...";
    }
    isPlanning = true;

    resetPanels();
    setStatus("正在解析全国骑行需求并规划路线...", "busy");
    addStep("已接收骑行需求，开始进入多 Agent 规划链路。", "active", "intent_research", 1);

    const response = await fetch("/api/v1/stream_plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent }),
    });
    if (!response.ok) {
      throw new Error(`请求失败 (${response.status})`);
    }
    await consumeEventStream(response, handlePlanEvent);
  } catch (error) {
    console.error("startPlan failed:", error);
    addStep(`连接失败：${error.message}`, "error", "intent_research");
    setStatus("规划失败", "error");
  } finally {
    isPlanning = false;
    const button = getEl("start-btn");
    if (button) {
      button.disabled = false;
      button.textContent = "开始智能规划";
    }
  }
}

async function consumeEventStream(response, handler) {
  if (response.body && typeof response.body.getReader === "function") {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = flushSseBuffer(buffer, handler);
    }
    flushSseBuffer(buffer, handler, true);
    return;
  }

  const text = await response.text();
  flushSseBuffer(text, handler, true);
}

function flushSseBuffer(buffer, handler, flushAll = false) {
  const lines = buffer.split("\n");
  const remainder = flushAll ? "" : lines.pop();

  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    try {
      handler(JSON.parse(line.slice(6)));
    } catch (error) {
      console.warn("Failed to parse SSE line", error, line);
    }
  }
  return remainder;
}

function replanFromEditor() {
  const origin = document.getElementById("edit-origin").value.trim();
  const destination = document.getElementById("edit-destination").value.trim();
  const waypoints = document.getElementById("edit-waypoints").value.trim();
  const notes = document.getElementById("edit-notes").value.trim();

  const rebuiltIntent = [
    "请按以下人工修正后的路线重新规划骑行。",
    origin ? `起点：${origin}` : "",
    destination ? `终点：${destination}` : "",
    waypoints ? `途经点：${waypoints}` : "",
    notes ? `附加要求：${notes}` : "",
  ]
    .filter(Boolean)
    .join(" ");

  document.getElementById("intent-input").value = rebuiltIntent;
  startPlan(rebuiltIntent);
}

function handlePlanEvent(data) {
  if (data.type === "session") {
    currentThreadId = data.thread_id;
    return;
  }

  if (data.type === "error") {
    addStep(`错误：${data.message}`, "error", data.node || "planner");
    setStatus("规划失败", "error");
    return;
  }

  if (data.label) {
    addStep(data.label, "active", data.node || "", data.progress || null);
  }
  updateProgress(data.progress || 0);

  if (data.analysis) {
    renderAnalysis(data.analysis || {}, data.constraints || {});
  }

  if (data.weather) {
    renderWeather(data.weather || {});
  }

  if (data.poi) {
    renderPOIs(data.poi || {});
  }

  if (data.type === "routes_ready") {
    renderRouteOptions(data.routes || []);
    if ((data.routes || []).length) {
      setStatus("候选路线已生成，请选择最合适的方案", "normal");
    } else {
      setStatus("未找到安全可执行路线，请修正后重试", "error");
    }
  }
}

function renderWeather(weather) {
  const current = weather.current || {};
  if (current.temperature_2m == null) return;
  currentWeatherSnapshot = current;
  document.getElementById("w-temp").textContent = `${Math.round(current.temperature_2m)}°`;
  document.getElementById("w-wind").textContent = `${(current.wind_speed_10m ?? 0).toFixed(1)} km/h`;
  document.getElementById("w-rain").textContent = `${current.precipitation ?? 0} mm`;
  document.getElementById("w-desc").textContent =
    current.precipitation > 0 ? "注意降水" : current.wind_speed_10m > 18 ? "有侧风影响" : "适合骑行";
  document.getElementById("weather-section").classList.remove("hidden");
  if (selectedRouteId) {
    renderRouteAtlas(getSelectedRoute(), currentAnalysis || {});
  }
}

function renderConstraintChips(chips = []) {
  const container = document.getElementById("constraint-chips");
  if (!chips.length) {
    container.className = "chip-cloud empty";
    container.innerHTML = `<span class="muted">系统会在这里展示识别到的区域、环线类型和骑行约束。</span>`;
    return;
  }
  container.className = "chip-cloud";
  container.innerHTML = chips.map((chip) => `<span class="chip">${chip}</span>`).join("");
}

function renderAnalysis(analysis = {}, constraints = {}) {
  currentAnalysis = analysis;
  currentWeatherSnapshot = analysis.weather_snapshot || currentWeatherSnapshot;
  renderConstraintChips(analysis.constraint_chips || []);
  document.getElementById("resolved-region").textContent = shortPlaceLabel(analysis.resolved_region || analysis.region || "已解析");

  if (analysis.route_resolution) {
    const resolution = analysis.route_resolution;
    const lines = [
      `<strong>起终点</strong> ${shortPlaceLabel(resolution.origin || "--")} → ${shortPlaceLabel(resolution.destination || "--")}`,
      resolution.preset ? `<strong>命中线路</strong> ${resolution.preset}` : "",
      resolution.waypoints?.length ? `<strong>关键途经</strong> ${(resolution.waypoints || []).slice(0, 4).map(shortPlaceLabel).join(" / ")}` : "",
    ].filter(Boolean);
    const box = document.getElementById("route-resolution");
    box.innerHTML = lines.join("<br>");
    box.classList.remove("hidden");
    document.getElementById("editor-section").classList.remove("hidden");
    document.getElementById("edit-origin").value = resolution.origin || "";
    document.getElementById("edit-destination").value = resolution.destination || "";
    document.getElementById("edit-waypoints").value = (resolution.waypoints || []).join(" / ");
  }

  const cards = [];
  (analysis.route_overview || []).slice(0, 3).forEach((item) => {
    cards.push(`
      <div class="analysis-card">
        <strong>${item.label || "候选方案"} · ${item.fit_score ?? "--"}</strong>
        <div>${shortRouteBrief(item.brief || "等待分析摘要")}</div>
      </div>
    `);
  });
  if (constraints.order_preference === "climb_then_flat") {
    cards.unshift(`
      <div class="analysis-card">
        <strong>节奏策略</strong>
        <div>前半段更偏爬升，后半段更偏巡航。</div>
      </div>
    `);
  }
  if (analysis.bike_policy?.summary) {
    cards.unshift(`
      <div class="analysis-card">
        <strong>骑行路权策略</strong>
        <div>${analysis.bike_policy.summary}</div>
      </div>
    `);
  }
  if (analysis.community_route_brief) {
    cards.unshift(`
      <div class="analysis-card">
        <strong>社区线路骨架</strong>
        <div>${analysis.community_route_brief}</div>
      </div>
    `);
  }
  if (analysis.route_fetch_note) {
    const fetchTitleMap = {
      unsafe_rejected: "安全拦截",
      no_bike_route: "无可行骑行路线",
      unresolved: "定位失败",
      fallback: "接口回退",
    };
    cards.unshift(`
      <div class="analysis-card">
        <strong>${fetchTitleMap[analysis.route_fetch_status] || "路线提示"}</strong>
        <div>${analysis.route_fetch_note}</div>
      </div>
    `);
  }

  const overview = document.getElementById("analysis-overview");
  overview.classList.remove("empty");
  overview.innerHTML = cards.join("") || `<span class="muted">候选路线生成后，这里会展示拟合度、时间规划和道路特征。</span>`;

  if (analysis.resolved_region || analysis.route_resolution) {
    document.getElementById("map-insight-text").textContent =
      `${shortPlaceLabel(analysis.resolved_region || analysis.region || "已解析")} · 主线已就绪`;
  }

  renderSystemGrid(analysis);
  renderInsightGrid(analysis);
  renderFeatureGrid(analysis);
  if (selectedRouteId) {
    renderRouteAtlas(getSelectedRoute(), analysis);
  }
}

function renderSystemGrid(analysis = {}) {
  const stack = analysis.agent_stack || [];
  const rows = stack.length
    ? stack
    : [
        { name: "Intent Agent", status: "idle", detail: "等待解析用户输入的骑行需求" },
        { name: "Geo Agent", status: "idle", detail: "等待锁定区域、地名和路线别名" },
        { name: "Route Agent", status: "idle", detail: "等待生成候选路线与修正方案" },
        { name: "RAG Agent", status: "idle", detail: "等待补充社区骑行经验和风险情报" },
        { name: "MCP Data Agent", status: "idle", detail: "等待调用路线、天气、POI、高程等数据源" },
      ];

  document.getElementById("system-grid").innerHTML = rows
    .map((row) => {
      const capabilities = row.capabilities || AGENT_CAPABILITY_MAP[row.name] || [];
      const status = row.status || "idle";
      return `
        <article class="agent-item${status === "running" ? " is-active" : ""}">
          <div class="agent-top">
            <div>
              <span class="agent-name">${row.name || "Agent"}</span>
            </div>
            <span class="agent-status ${status}">${statusText(status)}</span>
          </div>
          <div class="agent-detail">${row.detail || "等待执行任务"}</div>
          ${
            capabilities.length
              ? `<div class="agent-tags">${capabilities.map((tag) => `<span class="agent-tag">${tag}</span>`).join("")}</div>`
              : ""
          }
        </article>
      `;
    })
    .join("");
}

function statusText(status) {
  if (status === "done") return "已完成";
  if (status === "running") return "执行中";
  if (status === "waiting") return "等待中";
  if (status === "error") return "异常";
  return "待命";
}

function renderInsightGrid(analysis = {}) {
  const timing = analysis.timing_advice || {};
  const weather = analysis.weather_snapshot || {};
  const bikeInfra = resolveBikeInfra(analysis);
  const windExplanation = analysis.wind_explanation || {};
  const routeCount = analysis.candidate_count || 0;

  const cards = [
    {
      title: "候选路线数",
      summary: routeCount ? `已生成 ${routeCount} 条路线，可对比节奏与绕行方式。` : "当前还没有可用路线。",
      detail: (analysis.route_overview || []).length
        ? analysis.route_overview.map((item) => `${item.label} · ${item.fit_score ?? "--"} · ${shortRouteBrief(item.candidate_reason || item.brief || "已纳入候选")}`).join("<br>")
        : "生成候选路线后，这里会展开说明每条路线被选中的原因。",
      badge: routeCount ? `${routeCount} 条` : "待生成",
    },
    {
      title: "风况提醒",
      summary: weather.wind_speed_10m != null
        ? `风速约 ${weather.wind_speed_10m} km/h，${weather.wind_speed_10m > 18 ? "注意侧风。" : "整体可接受。"}`
        : "等待天气返回。",
      detail: weather.wind_direction_10m != null
        ? `风向约 ${weather.wind_direction_10m}°。去程：${windExplanation.outbound || "风况待定"}；返程：${windExplanation.return || "风况待定"}。`
        : "天气接口返回后会补充风向与降水提示。",
      badge: weather.wind_speed_10m != null ? `${weather.wind_speed_10m} km/h` : "待返回",
    },
    {
      title: "时间安排",
      summary: timing.depart_time
        ? `建议 ${timing.depart_time} 出发，目标时间 ${timing.target_time || "--"}。`
        : "如有日落/日出要求，这里会给时间建议。",
      detail: timing.reference_time
        ? `参考天象时间 ${timing.reference_time}，规划目标为 ${timing.goal === "sunset" ? "日落观景" : "日出观景"}。`
        : "你也可以在附加要求里写“几点前结束”或“什么时候到海边”，系统会继续拟合时间窗。",
      badge: timing.depart_time || "待定",
    },
    {
      title: "道路特征",
      summary: (bikeInfra.named_cycleways || []).length
        ? `识别到骑行道路：${bikeInfra.named_cycleways.slice(0, 2).join(" / ")}。`
        : bikeInfra.cycleway_hits || bikeInfra.bike_friendly_hits
          ? `骑行道 ${bikeInfra.cycleway_hits || 0} / 友好道路 ${bikeInfra.bike_friendly_hits || 0}。`
          : "道路类型仍在补充。",
      detail: [
        `骑行道命中 ${bikeInfra.cycleway_hits ?? 0} 处`,
        `适合骑行道路命中 ${bikeInfra.bike_friendly_hits ?? 0} 处`,
        `主干道路风险命中 ${(bikeInfra.primary_hits ?? 0) + (bikeInfra.motorway_hits ?? 0) + (bikeInfra.forbidden_hits ?? 0)} 处`,
      ].join("<br>"),
      badge: `${bikeInfra.cycleway_hits ?? 0} 处`,
    },
  ];

  document.getElementById("insight-grid").innerHTML = cards
    .map((card, index) => renderDetailRow({ ...card, open: index === 0 }))
    .join("");
  document.getElementById("feature-section").classList.remove("hidden");
}

function renderFeatureGrid(analysis = {}) {
  const poiSummary = analysis.poi_summary || {};
  const supply = analysis.supply_detail || {};
  const cards = [
    {
      title: "补给点",
      summary: [...(poiSummary.food || []), ...(supply.food || [])].slice(0, 2).map(shortPlaceLabel).join(" / ") || "补给较少",
      detail: [...(poiSummary.food || []), ...(supply.food || [])].join("<br>") || "当前还没有更详细的餐饮补给清单。",
      badge: `${[...(poiSummary.food || []), ...(supply.food || [])].length} 个`,
    },
    {
      title: "饮水与休整",
      summary: [...(poiSummary.water || []), ...(supply.rest || [])].slice(0, 2).map(shortPlaceLabel).join(" / ") || "休整待补充",
      detail: [...(poiSummary.water || []), ...(supply.rest || [])].join("<br>") || "可在路线修正里加上“优先经过补水点/公厕/公园休息点”。",
      badge: `${[...(poiSummary.water || []), ...(supply.rest || [])].length} 个`,
    },
    {
      title: "风景点",
      summary: [...(poiSummary.scenic || []), ...(supply.scenic || [])].slice(0, 2).map(shortPlaceLabel).join(" / ") || "观景待补充",
      detail: [...(poiSummary.scenic || []), ...(supply.scenic || [])].join("<br>") || "如果你强调海边、山顶、湖边或看日落，系统会优先把观景点纳入候选。",
      badge: `${[...(poiSummary.scenic || []), ...(supply.scenic || [])].length} 处`,
    },
    {
      title: "维修与应急",
      summary: [...(poiSummary.repair || []), ...(supply.repair || []), ...(poiSummary.medical || [])].slice(0, 2).map(shortPlaceLabel).join(" / ") || "建议自带基础维修工具",
      detail: [...(poiSummary.repair || []), ...(supply.repair || []), ...(poiSummary.medical || [])].join("<br>") || "当前沿线显式维修/医疗点较少，请提前准备补胎和紧急联系人。",
      badge: `${[...(poiSummary.repair || []), ...(supply.repair || []), ...(poiSummary.medical || [])].length} 点`,
    },
  ];

  document.getElementById("feature-grid").innerHTML = cards
    .map((card) => renderDetailRow(card))
    .join("");
}

function renderDetailRow({ title, summary, detail, badge = "展开", open = false }) {
  return `
    <div class="detail-row${open ? " is-open" : ""}">
      <button class="detail-toggle" type="button" data-detail-toggle="true">
        <span>
          <span class="detail-title">${title}</span>
          <span class="detail-summary">${summary}</span>
        </span>
        <span class="detail-badge">${badge}</span>
      </button>
      <div class="detail-content">${detail || "暂无更多细节。"}</div>
    </div>
  `;
}

function handleDocumentClick(event) {
  const toggle = event.target.closest("[data-detail-toggle]");
  if (toggle) {
    const row = toggle.closest(".detail-row");
    row?.classList.toggle("is-open");
    return;
  }
}

function showFocusPanel(title, detail) {
  document.getElementById("focus-title").textContent = title;
  document.getElementById("focus-body").innerHTML = detail || "暂无更多细节。";
  document.getElementById("focus-section").classList.remove("hidden");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderPOIs(poiData) {
  const elements = poiData.elements || [];
  if (!elements.length) return;

  const list = document.getElementById("poi-list");
  list.innerHTML = "";

  const iconMap = {
    restaurant: "餐饮",
    cafe: "咖啡",
    convenience: "便利店",
    supermarket: "商圈",
    bicycle_parking: "停车",
    drinking_water: "饮水",
    viewpoint: "观景点",
    attraction: "景点",
    toilets: "厕所",
    pharmacy: "药店",
    hospital: "医疗",
    bicycle: "维修",
  };

  elements.slice(0, 16).forEach((element) => {
    const tags = element.tags || {};
    const type = tags.amenity || tags.tourism || tags.shop || tags.leisure || "poi";
    const name = tags.name || iconMap[type] || "设施";
    const chip = document.createElement("span");
    chip.className = "poi-chip";
    chip.textContent = `${iconMap[type] || "设施"} · ${name}`;
    list.appendChild(chip);

    if (hasMap() && element.lat && element.lon) {
      const category = getPoiCategory(tags);
      const marker = L.marker([element.lat, element.lon], {
        icon: L.divIcon({
          className: "poi-marker-wrap",
          html: `<span class="poi-marker ${category.className}">${category.glyph}</span>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        }),
      }).bindTooltip(`${category.label} · ${name}`, { direction: "top", offset: [0, -8] });
      marker.addTo(map);
      poiMarkers.push(marker);
    }
  });

  const drawer = document.getElementById("poi-drawer");
  drawer?.classList.add("hidden");
}

function getPoiCategory(tags = {}) {
  const amenity = tags.amenity;
  const shop = tags.shop;
  const tourism = tags.tourism;
  if (amenity === "drinking_water") return { className: "water", glyph: "水", label: "饮水" };
  if (amenity === "toilets" || amenity === "bicycle_parking") return { className: "rest", glyph: "休", label: "休整" };
  if (amenity === "pharmacy" || amenity === "hospital") return { className: "medical", glyph: "医", label: "医疗" };
  if (shop === "bicycle") return { className: "repair", glyph: "修", label: "维修" };
  if (tourism === "viewpoint" || tourism === "attraction") return { className: "scenic", glyph: "景", label: "风景" };
  if (shop === "supermarket" || shop === "sports") return { className: "business", glyph: "商", label: "商圈" };
  if (amenity === "restaurant" || amenity === "cafe" || amenity === "convenience") return { className: "food", glyph: "补", label: "补给" };
  return { className: "business", glyph: "点", label: "设施" };
}

function renderRouteAtlas(route, analysis = {}) {
  if (!route) return;
  const metrics = route.metrics || {};
  const routeAnalysis = route.analysis || {};
  const segments = routeAnalysis.segments || [];
  const supply = analysis.supply_detail || {};
  const poiSummary = analysis.poi_summary || {};
  const weather = currentWeatherSnapshot || analysis.weather_snapshot || {};
  const windExplanation = analysis.wind_explanation || {};
  const scenicNames = [...new Set([...(poiSummary.scenic || []), ...(supply.scenic || [])].filter(Boolean))];
  const foodNames = [...new Set([...(poiSummary.food || []), ...(supply.food || [])].filter(Boolean))];
  const waterNames = [...new Set([...(poiSummary.water || []), ...(supply.water || []), ...(supply.rest || [])].filter(Boolean))];
  const riskCount = (metrics.primary_road_hits ?? 0) + (metrics.trunk_road_hits ?? 0) + (metrics.forbidden_road_hits ?? 0);
  const maxClimbSegment = [...segments].sort((a, b) => (b.climb_m || 0) - (a.climb_m || 0))[0];
  const roadFocus = (routeAnalysis.road_focus || []).slice(0, 3).join(" / ");

  const atlasItems = [
    {
      label: "总爬升",
      value: `${metrics.climb_m ?? "--"} m`,
      note: maxClimbSegment ? `最硬的一段是 ${maxClimbSegment.title || "关键爬升段"}，约 ${maxClimbSegment.climb_m || 0} m。` : "系统会按分段追踪爬升并提示节奏变化。",
      bar: Math.min(100, Math.round(((metrics.climb_m || 0) / 1600) * 100)),
    },
    {
      label: "能量预算",
      value: `${metrics.calories_kcal ?? "--"} kcal`,
      note: `${metrics.est_hours ?? "--"} h 骑行窗口，适合提前安排两次以上补给停靠。`,
      bar: Math.min(100, Math.round(((metrics.calories_kcal || 0) / 3200) * 100)),
    },
    {
      label: "补给密度",
      value: `${foodNames.length + waterNames.length} 个关键点`,
      note: `餐饮 ${foodNames.length} / 饮水与休整 ${waterNames.length}。${foodNames.slice(0, 2).join(" / ") || "建议手动补充更多补给点"}`,
      bar: Math.min(100, (foodNames.length + waterNames.length) * 14),
    },
    {
      label: "风况节奏",
      value: weather.wind_speed_10m != null ? `${Number(weather.wind_speed_10m).toFixed(1)} km/h` : `${metrics.wind_speed_kmh ?? "--"} km/h`,
      note: `去程 ${windExplanation.outbound || "风况待定"}；返程 ${windExplanation.return || "风况待定"}。`,
      bar: Math.max(10, Math.min(100, Math.round(((weather.wind_speed_10m || metrics.wind_speed_kmh || 0) / 30) * 100))),
    },
    {
      label: "观景节点",
      value: `${scenicNames.length} 处`,
      note: scenicNames.length ? scenicNames.slice(0, 3).join(" / ") : "当前未识别到明确观景点，可用人工修正再补一轮。",
      bar: Math.min(100, scenicNames.length * 18),
    },
    {
      label: "道路偏好",
      value: roadFocus || "自行车道优先",
      note: routeAnalysis.policy_summary || "系统会硬拦截高速与封闭道路，并对快速路、高架、隧道做降权提示。",
      bar: Math.min(100, Math.round(metrics.policy_score || 0)),
    },
    {
      label: "路权评分",
      value: `${metrics.policy_score ?? "--"} / 100`,
      note: `骑行道 ${metrics.cycleway_hits ?? 0} / 友好道路 ${metrics.bike_friendly_hits ?? 0} / 风险命中 ${riskCount}。`,
      bar: Math.min(100, Math.round(metrics.policy_score || 0)),
    },
    {
      label: "分段强度",
      value: `${segments.length} 段`,
      note: segments.length ? `已拆成 ${segments.length} 段 turn-by-turn 路书，可逐段查看补给、风险和海拔摘要。` : "等待分段说明生成后补齐。",
      bar: Math.min(100, segments.length * 10),
    },
  ];

  document.getElementById("atlas-grid").innerHTML = atlasItems
    .map(
      (item) => `
        <article class="atlas-item">
          <span class="atlas-label">${item.label}</span>
          <span class="atlas-value">${item.value}</span>
          <div class="atlas-note">${item.note}</div>
          <div class="atlas-bar"><div class="atlas-fill" style="width:${item.bar || 0}%"></div></div>
        </article>
      `
    )
    .join("");
  document.getElementById("atlas-section").classList.remove("hidden");
}

function renderRouteOptions(routes) {
  if (!routes.length) {
    const emptyMessage =
      currentAnalysis?.route_fetch_note || "当前没有可展示的候选路线，请尝试修正起终点或途经点。";
    document.getElementById("route-section").classList.remove("hidden");
    document.getElementById("route-cards").innerHTML = `<div class="muted">${emptyMessage}</div>`;
    document.getElementById("confirm-btn").disabled = true;
    document.getElementById("map-insight-text").textContent = "当前未输出可执行路线，请优先修正起终点或添加可骑行中转点。";
    document.getElementById("segment-section").classList.add("hidden");
    document.getElementById("atlas-section").classList.add("hidden");
    return;
  }
  currentRoutes = routes.slice(0, 5);

  const container = document.getElementById("route-cards");
  container.innerHTML = "";
  const bounds = hasMap() ? L.featureGroup() : null;

  currentRoutes.forEach((route, index) => {
    const metrics = route.metrics || {};
    const analysis = route.analysis || {};
    const color = ROUTE_COLORS[index % ROUTE_COLORS.length];
    const segments = analysis.segments || [];
    const supportSegments = segments.filter((segment) => segment.supply_detail || segment.supply_preview).length;
    const scenicSegments = segments.filter((segment) => (segment.supply_preview || "").includes("观景") || (segment.supply_detail || "").includes("观景")).length;
    const riskHits = (metrics.primary_road_hits ?? 0) + (metrics.trunk_road_hits ?? 0) + (metrics.forbidden_road_hits ?? 0);
    const footerChips = [
      ...(analysis.road_focus || []).slice(0, 2),
      supportSegments ? `补给段 ${supportSegments}` : "",
      scenicSegments ? `风景段 ${scenicSegments}` : "",
      segments[0]?.wind_label || "",
      route.fallback_generated ? "骨架回退" : "",
    ].filter(Boolean);
    const brief = shortRouteBrief(analysis.route_brief || analysis.candidate_reason || "等待路线分析摘要");
    const note = route.fallback_generated
      ? "当前为骨架估计，可继续手动修正后再规划。"
      : analysis.candidate_reason
        ? shortRouteBrief(analysis.candidate_reason)
        : "";

    if (hasMap()) {
      const glow = L.geoJSON(route.geometry, {
        style: { color, weight: index === 0 ? 14 : 12, opacity: index === 0 ? 0.2 : 0.12 },
      });
      const casing = L.geoJSON(route.geometry, {
        style: { color: "#ffffff", weight: index === 0 ? 9 : 7, opacity: index === 0 ? 0.92 : 0.26 },
      });
      const line = L.geoJSON(route.geometry, {
        style: { color, weight: index === 0 ? 6 : 4, opacity: index === 0 ? 0.96 : 0.38 },
      });
      const layer = L.featureGroup([glow, casing, line]).addTo(map);
      routeLayers[metrics.id] = layer;
      bounds?.addLayer(layer);
    }

    const card = document.createElement("div");
    card.className = `route-card${index === 0 ? " selected" : ""}`;
    card.id = `card-${metrics.id}`;
    card.innerHTML = `
        <div class="rc-top">
          <div>
            <div class="rc-title" style="color:${color}">${metrics.label || `方案 ${index + 1}`}</div>
            <div class="rc-brief">${brief}</div>
            ${note ? `<div class="rc-note">${note}</div>` : ""}
          </div>
          <div class="rc-fit">匹配 ${metrics.fit_score ?? "--"}</div>
        </div>
        <div class="rc-tags">
          <span class="rc-tag">骑行道 ${metrics.cycleway_hits ?? 0}</span>
          <span class="rc-tag">友好道路 ${metrics.bike_friendly_hits ?? 0}</span>
          <span class="rc-tag danger">风险 ${riskHits}</span>
        </div>
        <div class="rc-grid">
          <div class="rc-cell"><span>距离</span><strong>${metrics.distance_km ?? "--"} km</strong></div>
          <div class="rc-cell"><span>爬升</span><strong>${metrics.climb_m ?? "--"} m</strong></div>
          <div class="rc-cell"><span>时长</span><strong>${metrics.est_hours ?? "--"} h</strong></div>
          <div class="rc-cell"><span>路权分</span><strong>${metrics.policy_score ?? "--"}</strong></div>
        </div>
        <div class="route-card-footer">
          ${footerChips.map((chip) => `<span class="route-chip">${chip}</span>`).join("")}
        </div>
      `;
    card.addEventListener("click", () => selectRoute(metrics.id));
    container.appendChild(card);

    if (index === 0) {
      selectedRouteId = metrics.id;
      renderRoutePoints(route);
      renderSegments(route);
      renderMetrics(metrics);
      renderRouteAtlas(route, currentAnalysis || {});
      renderRoadRibbon(route);
      renderRoadNameMarkers(route);
      if (analysis.policy_summary || analysis.route_brief) {
        showRouteFocus(route, index + 1);
      }
    }
  });

  if (hasMap() && bounds) {
    try {
      map.fitBounds(bounds.getBounds(), { padding: [90, 90] });
    } catch (_) {}
  }

  document.getElementById("route-section").classList.remove("hidden");
  document.getElementById("confirm-btn").disabled = false;
  renderLegend(currentRoutes);
}

function renderRoutePoints(route) {
  if (!hasMap()) return;
  routePointMarkers.forEach((marker) => map.removeLayer(marker));
  routePointMarkers = [];

  const pointNames = route.analysis?.candidate_points || route.candidate_point_names || [];
  if (!pointNames.length || !route.geometry?.coordinates?.length) return;

  const coords = route.geometry.coordinates;
  const positions = [
    coords[0],
    ...sampleMidpoints(coords, Math.max(0, pointNames.length - 2)),
    coords[coords.length - 1],
  ].slice(0, pointNames.length);

  positions.forEach((coord, index) => {
    const isStart = index === 0;
    const isEnd = index === positions.length - 1;
    const marker = L.circleMarker([coord[1], coord[0]], {
      radius: isStart || isEnd ? 8 : 6,
      color: "#ffffff",
      weight: 3,
      fillColor: isStart ? "#10b981" : isEnd ? "#ef4444" : "#0284c7",
      fillOpacity: 0.96,
    }).bindTooltip(pointNames[index] || `节点 ${index + 1}`);
    marker.addTo(map);
    routePointMarkers.push(marker);
  });
}

function sampleMidpoints(coords, count) {
  if (count <= 0 || coords.length < 3) return [];
  const result = [];
  const step = Math.max(1, Math.floor(coords.length / (count + 1)));
  for (let i = 1; i <= count; i += 1) {
    result.push(coords[Math.min(coords.length - 2, i * step)]);
  }
  return result;
}

function selectRoute(routeId) {
  selectedRouteId = routeId;
  document.querySelectorAll(".route-card").forEach((card) => card.classList.remove("selected"));
  document.getElementById(`card-${routeId}`)?.classList.add("selected");

  Object.entries(routeLayers).forEach(([id, layer]) => {
    const active = id === routeId;
    layer.eachLayer((segment) => {
      segment.setStyle({
        opacity: active
          ? segment.options.color === "#ffffff"
            ? 0.96
            : segment.options.weight > 8
              ? 0.24
              : 0.98
          : segment.options.color === "#ffffff"
            ? 0.2
            : segment.options.weight > 8
              ? 0.06
              : 0.18,
        weight: active
          ? segment.options.color === "#ffffff"
            ? 10
            : segment.options.weight > 8
              ? 16
              : 7
          : segment.options.color === "#ffffff"
            ? 7
            : segment.options.weight > 8
              ? 12
              : 4,
      });
      if (active) segment.bringToFront();
    });
  });

  const selectedCardIndex = Array.from(document.querySelectorAll(".route-card")).findIndex((card) => card.id === `card-${routeId}`);
  if (selectedCardIndex >= 0) {
    const routeCards = document.querySelectorAll(".route-card");
    const card = routeCards[selectedCardIndex];
    card?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    if (currentRoutes[selectedCardIndex]) {
      const route = currentRoutes[selectedCardIndex];
      renderRoutePoints(route);
      renderSegments(route);
      renderMetrics(route.metrics || {});
      renderRouteAtlas(route, currentAnalysis || {});
      renderRoadRibbon(route);
      renderRoadNameMarkers(route);
      showRouteFocus(route, selectedCardIndex + 1);
      document.getElementById("map-insight-text").textContent = `${route.metrics?.label || "已选路线"} 已高亮`;
    }
  }
}

function renderSegments(route) {
  const segments = route?.analysis?.segments || [];
  const container = document.getElementById("segment-list");
  if (!segments.length) {
    container.innerHTML = `<div class="muted">当前路线还没有可展示的分段说明。</div>`;
    document.getElementById("segment-section").classList.add("hidden");
    return;
  }

  container.innerHTML = segments
    .map(
      (segment) => `
        <button class="segment-item" type="button" data-segment-index="${segment.index - 1}">
          <div class="segment-head">
            <div class="segment-title">#${segment.index} ${segment.title}</div>
            <div class="segment-meta">${segment.distance_km ?? "--"} km · ${segment.duration_min ?? "--"} min</div>
          </div>
          <div class="segment-meta">道路：${segment.road_name || "无名道路"} · 模式：${segment.mode || "cycling"}</div>
          <div class="segment-pills">
            <span class="segment-pill">${segment.climb_m ?? 0} m 爬升</span>
            <span class="segment-pill">${segment.wind_label || "风况待定"}</span>
            <span class="segment-pill">${segment.supply_preview || "补给待补充"}</span>
            ${segment.risk_detail ? `<span class="segment-pill">${segment.risk_detail}</span>` : ""}
          </div>
          <div class="segment-elev-mini">${renderElevationMini(segment)}</div>
        </button>
      `
    )
    .join("");
  document.getElementById("segment-section").classList.remove("hidden");
  highlightSegmentByIndex(0, false);
}

function handleSegmentClick(event) {
  const item = event.target.closest(".segment-item[data-segment-index]");
  if (!item) return;
  highlightSegmentByIndex(Number(item.dataset.segmentIndex || 0), true);
}

function getSelectedRoute() {
  return currentRoutes.find((route) => (route.metrics || {}).id === selectedRouteId) || null;
}

function highlightSegmentByIndex(index, shouldFocus = true) {
  const route = getSelectedRoute();
  const segments = route?.analysis?.segments || [];
  const segment = segments[index];
  if (!segment) return;

  document.querySelectorAll(".segment-item").forEach((item) => item.classList.remove("is-active"));
  document.querySelector(`.segment-item[data-segment-index="${index}"]`)?.classList.add("is-active");

  clearSegmentHighlight();
  const coords = segment.geometry || [];
  if (hasMap() && coords.length >= 2) {
    segmentHighlightLayer = L.geoJSON(
      { type: "LineString", coordinates: coords },
      { style: { color: "#f59e0b", weight: 9, opacity: 0.95, lineCap: "round" } }
    ).addTo(map);
    segmentHighlightLayer.bringToFront();
    if (shouldFocus) {
      try {
        map.fitBounds(segmentHighlightLayer.getBounds(), { padding: [80, 80], maxZoom: 14 });
      } catch (_) {}
    }
  }

  showFocusPanel(
    `分段 #${segment.index}`,
    [
      `<strong>${segment.title}</strong>`,
      `道路：${segment.road_name || "无名道路"}`,
      `距离：${segment.distance_km ?? "--"} km`,
      `预计用时：${segment.duration_min ?? "--"} min`,
      `估计爬升：${segment.climb_m ?? 0} m`,
      `风况：${segment.wind_label || "风况待定"}`,
      segment.supply_detail ? `沿线补给：${segment.supply_detail}` : "",
      segment.risk_detail ? `风险提示：${segment.risk_detail}` : "",
    ].join("<br>")
  );
  document.getElementById("map-insight-text").textContent =
    `第 ${segment.index} 段 · ${segment.road_name || segment.title || "无名道路"}`;
}

function clearSegmentHighlight() {
  if (hasMap() && segmentHighlightLayer) {
    map.removeLayer(segmentHighlightLayer);
    segmentHighlightLayer = null;
  }
}

function renderRoadRibbon(route) {
  const ribbon = document.getElementById("road-ribbon");
  const names = route?.analysis?.road_focus || [];
  if (!names.length) {
    ribbon.innerHTML = "";
    ribbon.classList.add("hidden");
    return;
  }
  ribbon.innerHTML = names.map((name) => `<span class="road-chip">${name}</span>`).join("");
  ribbon.classList.remove("hidden");
}

function showRouteFocus(route, order) {
  const metrics = route?.metrics || {};
  const analysis = route?.analysis || {};
  const segments = analysis.segments || [];
  const firstSegment = segments[0];
  const lastSegment = segments[segments.length - 1];
  showFocusPanel(
    metrics.label || `方案 ${order}`,
    [
      analysis.route_brief ? `<strong>${analysis.route_brief}</strong>` : "",
      analysis.policy_summary ? `路权策略：${analysis.policy_summary}` : "",
      analysis.candidate_reason ? `入选原因：${analysis.candidate_reason}` : "",
      analysis.road_focus?.length ? `关键道路：${analysis.road_focus.join(" / ")}` : "",
      firstSegment?.wind_label ? `去程风况：${firstSegment.wind_label}` : "",
      lastSegment?.wind_label ? `返程风况：${lastSegment.wind_label}` : "",
    ]
      .filter(Boolean)
      .join("<br><br>")
  );
}

function renderRoadNameMarkers(route) {
  if (!hasMap()) return;
  clearRoadNameMarkers();
  const segments = (route?.analysis?.segments || []).filter((segment) => segment.road_name && segment.road_name !== "无名道路");
  const seenNames = new Set();
  segments.filter((segment) => {
    if (seenNames.has(segment.road_name)) return false;
    seenNames.add(segment.road_name);
    return true;
  }).slice(0, 3).forEach((segment) => {
    const point = pickSegmentLabelPoint(segment);
    if (!point) return;
    const marker = L.marker([point[1], point[0]], {
      interactive: false,
      icon: L.divIcon({
        className: "road-label-marker",
        html: `<span>${escapeHtml(segment.road_name)}</span>`,
      }),
    }).addTo(map);
    routeNameMarkers.push(marker);
  });
}

function pickSegmentLabelPoint(segment) {
  const geometry = segment.geometry || [];
  if (geometry.length >= 2) {
    return geometry[Math.floor(geometry.length / 2)];
  }
  const start = segment.start_location || [];
  return start.length >= 2 ? start : null;
}

function clearRoadNameMarkers() {
  if (hasMap()) {
    routeNameMarkers.forEach((marker) => map.removeLayer(marker));
  }
  routeNameMarkers = [];
}

function renderLegend(routes) {
  document.getElementById("route-legend")?.classList.add("hidden");
  return;
  const list = document.getElementById("legend-list");
  list.innerHTML = routes
    .map((route, index) => {
      const metrics = route.metrics || {};
      return `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${ROUTE_COLORS[index % ROUTE_COLORS.length]}"></span>
          <span>${metrics.label || `方案 ${index + 1}`} · ${metrics.distance_km ?? "--"} km · 拟合度 ${metrics.fit_score ?? "--"}</span>
        </div>
      `;
    })
    .join("");
  document.getElementById("route-legend").classList.remove("hidden");
}

function renderElevationMini(segment) {
  const climb = Math.max(0, Number(segment.climb_m || 0));
  const bars = 10;
  const values = Array.from({ length: bars }, (_, index) => {
    const ratio = (index + 1) / bars;
    const raw = Math.min(100, Math.max(12, Math.round((climb / 4) * ratio)));
    return `<span class="elev-bar" style="height:${raw}%"></span>`;
  });
  return `
    <div class="elev-mini">
      <div class="elev-bars">${values.join("")}</div>
      <div class="elev-caption">分段海拔</div>
    </div>
  `;
}

async function finalizePlan() {
  if (isFinalizing) return;
  if (!currentThreadId || !selectedRouteId) return;
  setStatus("正在生成最终执行路书...", "busy");
  updateProgress(0);
  document.getElementById("confirm-btn").disabled = true;
  isFinalizing = true;
  document.getElementById("roadbook-panel").classList.remove("hidden");
  document.getElementById("roadbook-body").innerHTML = `<div class="muted">正在综合时间、道路、补给和风险信息生成专业路书，请稍候。</div>`;

  try {
    const response = await fetch("/api/v1/stream_finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: currentThreadId, route_id: selectedRouteId }),
    });
    if (!response.ok) {
      throw new Error(`请求失败 (${response.status})`);
    }
    await consumeEventStream(response, handleFinalizeEvent);
  } catch (error) {
    document.getElementById("roadbook-body").innerHTML = `<div class="muted">生成失败：${error.message}</div>`;
    setStatus("路书生成失败", "error");
  } finally {
    isFinalizing = false;
    document.getElementById("confirm-btn").disabled = false;
  }
}

function handleFinalizeEvent(data) {
  if (data.type === "error") {
    addStep(`错误：${data.message}`, "error", data.node || "finalizer");
    setStatus("路书生成失败", "error");
    return;
  }

  if (data.label) {
    addStep(data.label, "active", data.node || "", data.progress || null);
  }
  updateProgress(data.progress || 0);

  if (data.analysis) {
    renderAnalysis(data.analysis || {}, {});
  }

  if (data.type === "roadbook_ready") {
    document.getElementById("roadbook-body").innerHTML = marked.parse(data.markdown || "");
    document.getElementById("roadbook-panel").classList.remove("hidden");
    renderMetrics(data.route?.routes?.[0]?.metrics || {});
    renderRouteAtlas(data.route?.routes?.[0] || getSelectedRoute(), data.analysis || currentAnalysis || {});
    setStatus("路书已生成，可以直接参考执行", "normal");
  }
}

function renderMetrics(metrics) {
  const items = [
    ["距离", `${metrics.distance_km ?? "--"} km`],
    ["时长", `${metrics.est_hours ?? "--"} h`],
    ["爬升", `${metrics.climb_m ?? "--"} m`],
    ["热量", `${metrics.calories_kcal ?? "--"} kcal`],
    ["路权分", `${metrics.policy_score ?? "--"}`],
    ["拟合度", `${metrics.fit_score ?? "--"}`],
  ];

  const container = document.getElementById("metrics-strip");
  container.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="metric-item">
          <span class="metric-label">${label}</span>
          <span class="metric-value">${value}</span>
        </div>
      `
    )
    .join("");
  container.classList.remove("hidden");
}

function copyRoadbook() {
  const text = document.getElementById("roadbook-body").innerText;
  navigator.clipboard.writeText(text).then(() => {
    const button = document.getElementById("copy-btn");
    button.textContent = "已复制";
    setTimeout(() => {
      button.textContent = "复制";
    }, 1800);
  });
}

window.startPlan = startPlan;
window.replanFromEditor = replanFromEditor;
window.finalizePlan = finalizePlan;
