const API_BASE = window.location.hostname === "localhost" ? "http://localhost:8000" : "/api";
const POLL_MS = 30_000;
const WATCHLIST_STORAGE_KEY = "memetracker_watchlist";
const ALERT_RULES_STORAGE_KEY = "memetracker_alert_rules";

const boardBody = document.getElementById("board-body");
const connDot = document.getElementById("conn-dot");
const connText = document.getElementById("conn-text");
const clockEl = document.getElementById("clock");
const minScoreInput = document.getElementById("min-score");
const minScoreOut = document.getElementById("min-score-out");
const limitSelect = document.getElementById("limit");
const refreshBtn = document.getElementById("refresh-btn");
const searchInput = document.getElementById("search-input");
const chainFilters = document.getElementById("chain-filters");
const resultCount = document.getElementById("result-count");
const statCount = document.getElementById("stat-count");
const statAvg = document.getElementById("stat-avg");
const statTop = document.getElementById("stat-top");
const navLinks = document.getElementById("nav-links");
const breadcrumbCurrent = document.getElementById("breadcrumb-current");
const podium = document.getElementById("podium");
const heatmapGrid = document.getElementById("heatmap-grid");
const alertsPanel = document.getElementById("alerts-panel");
const tableWrap = document.getElementById("table-wrap");
const segmentRow = document.getElementById("segment-row");
const toolbar = document.getElementById("toolbar");
const watchlistCountBadge = document.getElementById("watchlist-count");
const alertsCountBadge = document.getElementById("alerts-count");
const toastStack = document.getElementById("toast-stack");

const alertTokenSelect = document.getElementById("alert-token");
const alertMetricSelect = document.getElementById("alert-metric");
const alertDirectionSelect = document.getElementById("alert-direction");
const alertThresholdInput = document.getElementById("alert-threshold");
const alertAddBtn = document.getElementById("alert-add-btn");
const alertRuleList = document.getElementById("alert-rule-list");
const alertTriggerList = document.getElementById("alert-trigger-list");

const modalOverlay = document.getElementById("modal-overlay");
const modalClose = document.getElementById("modal-close");
const modalSymbol = document.getElementById("modal-symbol");
const modalName = document.getElementById("modal-name");
const modalChainBadge = document.getElementById("modal-chain-badge");
const modalPrice = document.getElementById("modal-price");
const modalWatchBtn = document.getElementById("modal-watch-btn");
const modalWatchIcon = document.getElementById("modal-watch-icon");
const modalWatchLabel = document.getElementById("modal-watch-label");
const modalChartCanvas = document.getElementById("modal-chart");
const modalChartEmpty = document.getElementById("modal-chart-empty");
const modalVolatility = document.getElementById("modal-volatility");
const modalMomentum = document.getElementById("modal-momentum");
const modalLiquidity = document.getElementById("modal-liquidity");
const modalComposite = document.getElementById("modal-composite");
const modalHolderStat = document.getElementById("modal-holder-stat");
const modalHolder = document.getElementById("modal-holder");
const modalSocialStat = document.getElementById("modal-social-stat");
const modalSocial = document.getElementById("modal-social");

let modalChart = null;
let currentModalTokenId = null;

let rawResults = [];
let activeChain = "all";
let activeView = "markets"; // markets | rankings | trending | heatmap | watchlist | alerts
let sortKey = "composite_score";
let sortDir = "desc";
let recentTriggers = []; // {ruleId, symbol, metric, direction, threshold, value, time}

// ---------------- persistence ----------------

function loadSet(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}
function saveSet(key, set) {
  try {
    localStorage.setItem(key, JSON.stringify([...set]));
  } catch {
    /* private browsing etc. - non-fatal, just won't persist */
  }
}
const watched = loadSet(WATCHLIST_STORAGE_KEY);

function loadAlertRules() {
  try {
    const raw = localStorage.getItem(ALERT_RULES_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}
function saveAlertRules() {
  try {
    localStorage.setItem(ALERT_RULES_STORAGE_KEY, JSON.stringify(alertRules));
  } catch {
    /* non-fatal */
  }
}
let alertRules = loadAlertRules(); // {id, tokenId, symbol, metric, direction, threshold, wasTriggeredState}

function updateWatchlistBadge() {
  watchlistCountBadge.hidden = watched.size === 0;
  watchlistCountBadge.textContent = watched.size;
}
function updateAlertsBadge() {
  alertsCountBadge.hidden = alertRules.length === 0;
  alertsCountBadge.textContent = alertRules.length;
}

// ---------------- misc helpers ----------------

function tickClock() {
  clockEl.textContent = new Date().toLocaleTimeString("en-GB");
}
setInterval(tickClock, 1000);
tickClock();

function setConnected(ok) {
  connDot.classList.toggle("dot-on", ok);
  connDot.classList.toggle("dot-off", !ok);
  connText.textContent = ok ? "Live" : "Disconnected";
}

function fmtPrice(p) {
  if (p >= 1) return `$${p.toFixed(2)}`;
  return `$${p.toPrecision(3)}`;
}

function scoreClass(value) {
  if (value >= 70) return "score-high";
  if (value >= 35) return "score-mid";
  return "score-low";
}

function chainDotClass(chain) {
  const known = ["solana", "bsc", "ethereum"];
  return known.includes(chain) ? `chain-${chain}` : "chain-multi";
}

// Red (0) -> amber (50) -> green (100), used for heat map tile backgrounds
function scoreToColor(value) {
  const clamped = Math.max(0, Math.min(100, value));
  const hue = (clamped / 100) * 120; // 0=red, 120=green
  return `hsl(${hue}, 62%, 32%)`;
}

// ---------------- filtering / sorting shared by table views ----------------

function applyFilterSortSearch(rows) {
  let out = rows;

  if (activeView === "watchlist") {
    out = out.filter((r) => watched.has(r.token_id));
  }

  if (activeChain !== "all") {
    out = out.filter((r) => r.chain === activeChain);
  }

  const query = searchInput.value.trim().toLowerCase();
  if (query) {
    out = out.filter(
      (r) => r.symbol.toLowerCase().includes(query) || r.name.toLowerCase().includes(query)
    );
  }

  let key = sortKey;
  let dir = sortDir;
  if (activeView === "rankings") { key = "composite_score"; dir = "desc"; }
  if (activeView === "trending") { key = "momentum_score"; dir = "desc"; }

  out = [...out].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
    return dir === "asc" ? cmp : -cmp;
  });

  return out;
}

function renderStats(rows) {
  if (!rows.length) {
    statCount.textContent = "0";
    statAvg.textContent = "--";
    statTop.textContent = "--";
    return;
  }
  statCount.textContent = rows.length;
  const avg = rows.reduce((sum, r) => sum + r.composite_score, 0) / rows.length;
  statAvg.textContent = avg.toFixed(1);
  const top = rows.reduce((best, r) => (r.composite_score > best.composite_score ? r : best), rows[0]);
  statTop.textContent = top.symbol;
}

const starIcon = `<svg viewBox="0 0 16 16"><path d="M8 1.6l1.9 4.2 4.5.5-3.4 3.1.9 4.5L8 11.7l-3.9 2.2.9-4.5-3.4-3.1 4.5-.5z" fill="currentColor"/></svg>`;

function renderPodium(rows) {
  const top3 = [...rows].sort((a, b) => b.composite_score - a.composite_score).slice(0, 3);
  if (!top3.length) { podium.hidden = true; return; }
  podium.hidden = false;
  const labels = ["#1", "#2", "#3"];
  podium.innerHTML = top3
    .map(
      (r, i) => `
      <div class="podium-card podium-${i + 1}">
        <span class="podium-rank">${labels[i]}</span>
        <span class="podium-symbol">${r.symbol}</span>
        <span class="podium-name">${r.name}</span>
        <span class="podium-score ${scoreClass(r.composite_score)}">${r.composite_score.toFixed(1)}</span>
      </div>`
    )
    .join("");
}

function renderHeatmap(rows) {
  const filtered = applyFilterSortSearch(rows);
  if (!filtered.length) {
    heatmapGrid.innerHTML = `<div class="alert-empty">No tokens match the current filters</div>`;
    return;
  }
  heatmapGrid.innerHTML = filtered
    .map(
      (r) => `
      <div class="heat-tile row-clickable" data-token="${r.token_id}" style="background:${scoreToColor(r.composite_score)}" title="${r.name} — composite ${r.composite_score.toFixed(1)}">
        <div>
          <div class="heat-tile-symbol">${r.symbol}</div>
          <div class="heat-tile-chain">${r.chain}</div>
        </div>
        <div class="heat-tile-score">${r.composite_score.toFixed(0)}</div>
      </div>`
    )
    .join("");
}

function renderEmptyState() {
  if (activeView === "watchlist") {
    boardBody.innerHTML = `
      <tr><td colspan="9" class="empty empty-watchlist">
        <svg viewBox="0 0 16 16" class="empty-watchlist-icon" fill="none" stroke="currentColor" stroke-width="1.3">
          <path d="M8 1.6l1.9 4.2 4.5.5-3.4 3.1.9 4.5L8 11.7l-3.9 2.2.9-4.5-3.4-3.1 4.5-.5z"/>
        </svg>
        <div class="empty-watchlist-title">Your watchlist is empty</div>
        <div class="empty-watchlist-hint">Click the star on any token to add it here</div>
      </td></tr>`;
    return;
  }
  boardBody.innerHTML = `<tr><td colspan="9" class="empty">No tokens match the current filters</td></tr>`;
}

function renderTable(rows) {
  const filtered = applyFilterSortSearch(rows);
  resultCount.textContent = `${filtered.length} token${filtered.length === 1 ? "" : "s"}`;

  if (!filtered.length) { renderEmptyState(); return; }

  boardBody.innerHTML = filtered
    .map((r, i) => {
      const isWatched = watched.has(r.token_id);
      return `
      <tr class="row-clickable" data-token="${r.token_id}">
        <td class="rank-cell">${i + 1}</td>
        <td>
          <div class="token-cell">
            <span class="token-symbol">${r.symbol}</span>
            <span class="token-name">${r.name}</span>
          </div>
        </td>
        <td><span class="chain-badge"><i class="chain-dot ${chainDotClass(r.chain)}"></i>${r.chain}</span></td>
        <td class="price-cell">${fmtPrice(r.price_usd)}</td>
        <td><span class="score-num ${scoreClass(r.volatility_score)}">${r.volatility_score.toFixed(0)}</span></td>
        <td><span class="score-num ${scoreClass(r.momentum_score)}">${r.momentum_score.toFixed(0)}</span></td>
        <td><span class="score-num ${scoreClass(r.liquidity_score)}">${r.liquidity_score.toFixed(0)}</span></td>
        <td><span class="composite-cell ${scoreClass(r.composite_score)}">${r.composite_score.toFixed(1)}</span></td>
        <td>
          <button class="watch-btn ${isWatched ? "watched" : ""}" data-token="${r.token_id}" data-stop-row-click title="Toggle watchlist">
            ${starIcon}
          </button>
        </td>
      </tr>`;
    })
    .join("");
}

// ---------------- token detail modal ----------------

function updateModalWatchButton(tokenId) {
  const isWatched = watched.has(tokenId);
  modalWatchBtn.classList.toggle("watched", isWatched);
  modalWatchIcon.innerHTML = starIcon;
  modalWatchLabel.textContent = isWatched ? "Watching" : "Watch";
}

async function fetchTokenHistory(tokenId) {
  const res = await fetch(`${API_BASE}/api/v1/coins/${encodeURIComponent(tokenId)}/history?hours=24`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function renderModalChart(points) {
  if (modalChart) { modalChart.destroy(); modalChart = null; }

  if (!points || points.length < 2) {
    modalChartCanvas.hidden = true;
    modalChartEmpty.hidden = false;
    return;
  }
  modalChartCanvas.hidden = false;
  modalChartEmpty.hidden = true;

  const labels = points.map((p) => new Date(p.time).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }));
  const prices = points.map((p) => p.price_usd);
  const rising = prices[prices.length - 1] >= prices[0];

  modalChart = new Chart(modalChartCanvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: prices,
        borderColor: rising ? "#22c55e" : "#ef4444",
        backgroundColor: rising ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
        borderWidth: 1.75,
        pointRadius: 0,
        fill: true,
        tension: 0.25,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#545e7d", maxTicksLimit: 6, font: { size: 10 } }, grid: { color: "#1f2740" } },
        y: { ticks: { color: "#545e7d", font: { size: 10 } }, grid: { color: "#1f2740" } },
      },
    },
  });
}

async function openTokenModal(tokenId) {
  const token = rawResults.find((r) => r.token_id === tokenId);
  if (!token) return;

  currentModalTokenId = tokenId;
  modalOverlay.hidden = false;
  document.body.style.overflow = "hidden";

  modalSymbol.textContent = token.symbol;
  modalName.textContent = token.name;
  modalChainBadge.innerHTML = `<i class="chain-dot ${chainDotClass(token.chain)}"></i>${token.chain}`;
  modalPrice.textContent = fmtPrice(token.price_usd);
  updateModalWatchButton(tokenId);

  modalVolatility.textContent = token.volatility_score.toFixed(1);
  modalMomentum.textContent = token.momentum_score.toFixed(1);
  modalLiquidity.textContent = token.liquidity_score.toFixed(1);
  modalComposite.textContent = token.composite_score.toFixed(1);
  modalVolatility.className = `modal-stat-value ${scoreClass(token.volatility_score)}`;
  modalMomentum.className = `modal-stat-value ${scoreClass(token.momentum_score)}`;
  modalLiquidity.className = `modal-stat-value ${scoreClass(token.liquidity_score)}`;
  modalComposite.className = `modal-stat-value ${scoreClass(token.composite_score)}`;

  // holder_safety_score / social_score are optional enrichment fields -
  // only shown when the API actually returned them for this token.
  if (token.holder_safety_score != null) {
    modalHolderStat.hidden = false;
    modalHolder.textContent = token.holder_safety_score.toFixed(1);
    modalHolder.className = `modal-stat-value ${scoreClass(token.holder_safety_score)}`;
  } else {
    modalHolderStat.hidden = true;
  }
  if (token.social_score != null) {
    modalSocialStat.hidden = false;
    modalSocial.textContent = token.social_score.toFixed(1);
    modalSocial.className = `modal-stat-value ${scoreClass(token.social_score)}`;
  } else {
    modalSocialStat.hidden = true;
  }

  modalChartCanvas.hidden = true;
  modalChartEmpty.hidden = true;

  try {
    const history = await fetchTokenHistory(tokenId);
    if (currentModalTokenId === tokenId) renderModalChart(history.points);
  } catch (err) {
    console.error("fetchTokenHistory failed", err);
    if (currentModalTokenId === tokenId) renderModalChart([]);
  }
}

function closeModal() {
  modalOverlay.hidden = true;
  document.body.style.overflow = "";
  currentModalTokenId = null;
  if (modalChart) { modalChart.destroy(); modalChart = null; }
}

modalClose.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modalOverlay.hidden) closeModal(); });

modalWatchBtn.addEventListener("click", () => {
  if (!currentModalTokenId) return;
  if (watched.has(currentModalTokenId)) watched.delete(currentModalTokenId);
  else watched.add(currentModalTokenId);
  saveSet(WATCHLIST_STORAGE_KEY, watched);
  updateWatchlistBadge();
  updateModalWatchButton(currentModalTokenId);
  render();
});

boardBody.addEventListener("click", (e) => {
  if (e.target.closest("[data-stop-row-click]")) return; // watch button handled separately
  const row = e.target.closest("tr[data-token]");
  if (!row) return;
  openTokenModal(row.dataset.token);
});

heatmapGrid.addEventListener("click", (e) => {
  const tile = e.target.closest(".heat-tile[data-token]");
  if (!tile) return;
  openTokenModal(tile.dataset.token);
});

// ---------------- alerts engine ----------------

function populateAlertTokenSelect(rows) {
  const current = alertTokenSelect.value;
  alertTokenSelect.innerHTML = rows
    .map((r) => `<option value="${r.token_id}">${r.symbol} — ${r.name}</option>`)
    .join("");
  if (current && rows.some((r) => r.token_id === current)) alertTokenSelect.value = current;
}

function renderAlertRules() {
  if (!alertRules.length) {
    alertRuleList.innerHTML = `<li class="alert-empty">No alert rules yet — add one above.</li>`;
    return;
  }
  const metricLabels = { composite_score: "Score", volatility_score: "Volatility", momentum_score: "Momentum" };
  alertRuleList.innerHTML = alertRules
    .map(
      (rule) => `
      <li class="alert-rule-item">
        <span class="alert-rule-text"><strong>${rule.symbol}</strong> ${metricLabels[rule.metric]} ${rule.direction === "above" ? "≥" : "≤"} ${rule.threshold}</span>
        <button class="alert-rule-remove" data-rule-id="${rule.id}" title="Remove">✕</button>
      </li>`
    )
    .join("");
}

function renderAlertTriggers() {
  if (!recentTriggers.length) {
    alertTriggerList.innerHTML = `<li class="alert-empty">No triggers yet.</li>`;
    return;
  }
  const metricLabels = { composite_score: "Score", volatility_score: "Volatility", momentum_score: "Momentum" };
  alertTriggerList.innerHTML = recentTriggers
    .slice(0, 20)
    .map(
      (t) => `
      <li class="alert-trigger-item">
        <span class="alert-rule-text"><strong>${t.symbol}</strong> ${metricLabels[t.metric]} ${t.direction === "above" ? "rose above" : "dropped below"} ${t.threshold} (now ${t.value.toFixed(1)})</span>
        <span class="alert-trigger-time">${t.time}</span>
      </li>`
    )
    .join("");
}

function showToast(title, body) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div class="toast-title">${title}</div><div class="toast-body">${body}</div>`;
  toastStack.appendChild(el);
  setTimeout(() => el.remove(), 8000);

  if (window.Notification && Notification.permission === "granted") {
    new Notification(title, { body });
  }
}

function checkAlertRules(rows) {
  const byId = Object.fromEntries(rows.map((r) => [r.token_id, r]));

  for (const rule of alertRules) {
    const token = byId[rule.tokenId];
    if (!token) continue;

    const value = token[rule.metric];
    const isCrossed = rule.direction === "above" ? value >= rule.threshold : value <= rule.threshold;

    // Edge-trigger: only fire on the transition into the crossed state,
    // not on every poll cycle while it stays crossed - otherwise a token
    // sitting just above its threshold would spam a toast every 30s.
    if (isCrossed && !rule.wasTriggered) {
      const time = new Date().toLocaleTimeString("en-GB");
      recentTriggers.unshift({
        ruleId: rule.id, symbol: rule.symbol, metric: rule.metric,
        direction: rule.direction, threshold: rule.threshold, value, time,
      });
      recentTriggers = recentTriggers.slice(0, 50);
      showToast(
        `${rule.symbol} alert triggered`,
        `${rule.metric.replace("_score", "")} ${rule.direction === "above" ? "rose above" : "dropped below"} ${rule.threshold} (now ${value.toFixed(1)})`
      );
      renderAlertTriggers();
    }
    rule.wasTriggered = isCrossed;
  }
  saveAlertRules();
}

alertAddBtn.addEventListener("click", () => {
  const tokenId = alertTokenSelect.value;
  const option = alertTokenSelect.selectedOptions[0];
  if (!tokenId || !option) return;

  const rule = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    tokenId,
    symbol: option.textContent.split(" — ")[0],
    metric: alertMetricSelect.value,
    direction: alertDirectionSelect.value,
    threshold: Number(alertThresholdInput.value) || 0,
    wasTriggered: false,
  };
  alertRules.push(rule);
  saveAlertRules();
  updateAlertsBadge();
  renderAlertRules();

  if (window.Notification && Notification.permission === "default") {
    Notification.requestPermission();
  }
});

alertRuleList.addEventListener("click", (e) => {
  const btn = e.target.closest(".alert-rule-remove");
  if (!btn) return;
  alertRules = alertRules.filter((r) => r.id !== btn.dataset.ruleId);
  saveAlertRules();
  updateAlertsBadge();
  renderAlertRules();
});

// ---------------- view switching ----------------

const VIEW_CONFIG = {
  markets:   { table: true,  podium: false, heatmap: false, alerts: false, filters: true,  breadcrumb: "Meme Coin Rankings" },
  rankings:  { table: true,  podium: true,  heatmap: false, alerts: false, filters: true,  breadcrumb: "Top Rankings" },
  trending:  { table: true,  podium: false, heatmap: false, alerts: false, filters: true,  breadcrumb: "Trending (by momentum)" },
  heatmap:   { table: false, podium: false, heatmap: true,  alerts: false, filters: true,  breadcrumb: "Heat Map" },
  watchlist: { table: true,  podium: false, heatmap: false, alerts: false, filters: true,  breadcrumb: "My Watchlist" },
  alerts:    { table: false, podium: false, heatmap: false, alerts: true,  filters: false, breadcrumb: "Alerts" },
};

function setView(view) {
  activeView = view;
  const cfg = VIEW_CONFIG[view];

  navLinks.querySelectorAll(".nav-link[data-view]").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
  breadcrumbCurrent.textContent = cfg.breadcrumb;

  tableWrap.hidden = !cfg.table;
  podium.hidden = !cfg.podium;
  heatmapGrid.hidden = !cfg.heatmap;
  alertsPanel.hidden = !cfg.alerts;
  segmentRow.hidden = !cfg.filters;
  toolbar.hidden = !cfg.filters;
  document.querySelector(".table-footer").hidden = !cfg.table;

  document.querySelectorAll("th.sortable").forEach((t) => {
    t.classList.remove("active-sort");
    t.querySelector(".sort-arrow").textContent = "";
  });
  const forcedKey = view === "rankings" ? "composite_score" : view === "trending" ? "momentum_score" : sortKey;
  const forcedDir = view === "rankings" || view === "trending" ? "desc" : sortDir;
  const activeHeader = document.querySelector(`th[data-sort="${forcedKey}"]`);
  if (activeHeader) {
    activeHeader.classList.add("active-sort");
    activeHeader.querySelector(".sort-arrow").textContent = forcedDir === "asc" ? "▲" : "▼";
  }

  render();
}

function render() {
  if (activeView === "heatmap") {
    renderHeatmap(rawResults);
  } else if (activeView === "alerts") {
    renderAlertRules();
    renderAlertTriggers();
  } else {
    if (activeView === "rankings") renderPodium(applyFilterSortSearch(rawResults));
    renderTable(rawResults);
  }
}

// ---------------- data loading ----------------

async function loadData() {
  const minScore = minScoreInput.value;
  const limit = limitSelect.value;

  try {
    const res = await fetch(`${API_BASE}/api/v1/coins/ranked?limit=${limit}&min_score=${minScore}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    setConnected(true);
    rawResults = data.results;
    renderStats(rawResults);
    populateAlertTokenSelect(rawResults);
    checkAlertRules(rawResults);
    render();
  } catch (err) {
    setConnected(false);
    if (activeView !== "alerts" && activeView !== "heatmap") {
      boardBody.innerHTML = `<tr><td colspan="9" class="empty">Could not reach API — is docker compose running?</td></tr>`;
    }
    console.error("loadData failed", err);
  }
}

// ---------------- event wiring ----------------

minScoreInput.addEventListener("input", () => { minScoreOut.textContent = minScoreInput.value; });
minScoreInput.addEventListener("change", loadData);
limitSelect.addEventListener("change", loadData);
refreshBtn.addEventListener("click", loadData);

searchInput.addEventListener("input", render);

chainFilters.addEventListener("click", (e) => {
  const tab = e.target.closest(".segment-tab");
  if (!tab) return;
  chainFilters.querySelectorAll(".segment-tab").forEach((t) => t.classList.remove("active"));
  tab.classList.add("active");
  activeChain = tab.dataset.chain;
  render();
});

navLinks.addEventListener("click", (e) => {
  const link = e.target.closest(".nav-link[data-view]");
  if (!link) return;
  setView(link.dataset.view);
});

boardBody.addEventListener("click", (e) => {
  const btn = e.target.closest(".watch-btn");
  if (!btn) return;
  const tokenId = btn.dataset.token;
  if (watched.has(tokenId)) watched.delete(tokenId); else watched.add(tokenId);
  saveSet(WATCHLIST_STORAGE_KEY, watched);
  updateWatchlistBadge();
  render();
});

document.querySelectorAll("th.sortable").forEach((th) => {
  th.addEventListener("click", () => {
    if (activeView === "rankings" || activeView === "trending") return; // forced sort
    const key = th.dataset.sort;
    if (sortKey === key) { sortDir = sortDir === "asc" ? "desc" : "asc"; }
    else { sortKey = key; sortDir = "desc"; }
    document.querySelectorAll("th.sortable").forEach((t) => {
      t.classList.remove("active-sort");
      t.querySelector(".sort-arrow").textContent = "";
    });
    th.classList.add("active-sort");
    th.querySelector(".sort-arrow").textContent = sortDir === "asc" ? "▲" : "▼";
    render();
  });
});

updateWatchlistBadge();
updateAlertsBadge();
loadData();
setInterval(loadData, POLL_MS);
