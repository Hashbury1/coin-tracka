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

function tickClock() {
  clockEl.textContent = new Date().toLocaleTimeString("en-GB");
}
setInterval(tickClock, 1000);
tickClock();

function setConnected(ok) {
  connDot.classList.toggle("dot-on", ok);
  connDot.classList.toggle("dot-off", !ok);
  connText.textContent = ok ? "live" : "disconnected";
}

function fmtPrice(p) {
  if (p >= 1) return `$${p.toFixed(2)}`;
  return `$${p.toPrecision(3)}`;
}

function scoreBar(value) {
  const clamped = Math.max(0, Math.min(100, value));
  return `
    <div class="score-bar-wrap">
      <div class="score-bar"><div class="score-bar-fill" style="width:${clamped}%"></div></div>
      <span>${clamped.toFixed(0)}</span>
    </div>`;
}

function renderRows(rows) {
  if (!rows.length) {
    boardBody.innerHTML = `<tr><td colspan="8" class="empty">no tokens meet the current filter</td></tr>`;
    return;
  }

  boardBody.innerHTML = rows
    .map(
      (r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td class="symbol">${r.symbol}</td>
        <td><span class="chain-tag">${r.chain}</span></td>
        <td>${fmtPrice(r.price_usd)}</td>
        <td>${scoreBar(r.volatility_score)}</td>
        <td>${scoreBar(r.momentum_score)}</td>
        <td>${scoreBar(r.liquidity_score)}</td>
        <td class="composite-cell">${r.composite_score.toFixed(1)}</td>
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
    renderRows(data.results);
  } catch (err) {
    setConnected(false);
    boardBody.innerHTML = `<tr><td colspan="8" class="empty">could not reach API — is docker compose running?</td></tr>`;
    console.error("loadData failed", err);
  }
}

minScoreInput.addEventListener("input", () => {
  minScoreOut.textContent = minScoreInput.value;
});
minScoreInput.addEventListener("change", loadData);
limitSelect.addEventListener("change", loadData);
refreshBtn.addEventListener("click", loadData);

loadData();
setInterval(loadData, POLL_MS);
