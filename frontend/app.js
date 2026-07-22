const API_BASE = window.location.hostname === "localhost" ? "http://localhost:8000" : "/api";
const POLL_MS = 30_000;

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

let rawResults = [];
let activeChain = "all";
let sortKey = "composite_score";
let sortDir = "desc"; // 'asc' | 'desc'

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

function applyFilterSortSearch(rows) {
  let out = rows;

  if (activeChain !== "all") {
    out = out.filter((r) => r.chain === activeChain);
  }

  const query = searchInput.value.trim().toLowerCase();
  if (query) {
    out = out.filter(
      (r) => r.symbol.toLowerCase().includes(query) || r.name.toLowerCase().includes(query)
    );
  }

  out = [...out].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    let cmp;
    if (typeof av === "string") {
      cmp = av.localeCompare(bv);
    } else {
      cmp = av - bv;
    }
    return sortDir === "asc" ? cmp : -cmp;
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

function renderRows(rows) {
  const filtered = applyFilterSortSearch(rows);
  resultCount.textContent = `${filtered.length} token${filtered.length === 1 ? "" : "s"}`;

  if (!filtered.length) {
    boardBody.innerHTML = `<tr><td colspan="8" class="empty">No tokens match the current filters</td></tr>`;
    return;
  }

  boardBody.innerHTML = filtered
    .map(
      (r, i) => `
      <tr>
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
      </tr>`
    )
    .join("");
}

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
    renderRows(rawResults);
  } catch (err) {
    setConnected(false);
    boardBody.innerHTML = `<tr><td colspan="8" class="empty">Could not reach API — is docker compose running?</td></tr>`;
    console.error("loadData failed", err);
  }
}

// ---- event wiring ----

minScoreInput.addEventListener("input", () => {
  minScoreOut.textContent = minScoreInput.value;
});
minScoreInput.addEventListener("change", loadData);
limitSelect.addEventListener("change", loadData);
refreshBtn.addEventListener("click", loadData);

searchInput.addEventListener("input", () => renderRows(rawResults));

chainFilters.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  chainFilters.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
  chip.classList.add("active");
  activeChain = chip.dataset.chain;
  renderRows(rawResults);
});

document.querySelectorAll("th.sortable").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (sortKey === key) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortKey = key;
      sortDir = "desc";
    }
    document.querySelectorAll("th.sortable").forEach((t) => {
      t.classList.remove("active-sort");
      t.querySelector(".sort-arrow").textContent = "";
    });
    th.classList.add("active-sort");
    th.querySelector(".sort-arrow").textContent = sortDir === "asc" ? "▲" : "▼";
    renderRows(rawResults);
  });
});

loadData();
setInterval(loadData, POLL_MS);

