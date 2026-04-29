const state = {
  ranking: null,
  selectedThemeId: null,
};

const $ = (id) => document.getElementById(id);

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function dateValue() {
  return $("dateInput").value || "2026-04-29";
}

function periodValue() {
  return $("periodInput").value || "short";
}

async function loadDashboard() {
  const date = dateValue();
  const period = periodValue();
  $("exportLink").href = `/api/v1/export/themes.xlsx?date=${date}`;

  const [ranking, report, portfolio] = await Promise.all([
    fetchJson(`/api/v1/themes/ranking?date=${date}&period=${period}`),
    fetchJson(`/api/v1/reports/daily?date=${date}`),
    fetchJson(`/api/v1/portfolio/risk?date=${date}`),
  ]);

  state.ranking = ranking;
  renderOverview(ranking);
  renderRanking(ranking.items);
  renderReport(report);
  renderPortfolio(portfolio);
  loadDataSourceStatus();

  const firstTheme = ranking.items[0];
  if (firstTheme) {
    await selectTheme(state.selectedThemeId || firstTheme.theme_id);
  }
}

async function loadDataSourceStatus() {
  try {
    const status = await fetchJson("/api/v1/data/eastmoney/status");
    const stocks = status.generated_files.stocks_csv.rows;
    const quotes = status.generated_files.daily_quotes_csv.rows;
    $("dataSourceLabel").textContent = `东方财富 / C导入 / ${stocks}只 / ${quotes}行`;
  } catch (error) {
    $("dataSourceLabel").textContent = "东方财富 / 状态未知";
  }
}

function renderOverview(ranking) {
  $("confidenceLevel").textContent = `${levelName(ranking.confidence)} ${ranking.confidence_score}`;
  $("confidenceReason").textContent = ranking.reason;
  $("marketState").textContent = `上涨占比 ${(ranking.market.up_ratio * 100).toFixed(0)}%`;
  $("marketSummary").textContent = ranking.market.summary;

  const highRisk = ranking.items.filter((item) => item.risk_penalty >= 8);
  $("riskCount").textContent = `${highRisk.length} 条`;
  $("riskSummary").textContent = highRisk.map((item) => item.theme_name).join("、") || "暂无高风险主线";
  $("rankingMeta").textContent = `${ranking.date} / ${ranking.period} / ${ranking.items.length} 条主线`;
}

function renderRanking(items) {
  $("rankingBody").innerHTML = items.map((item) => `
    <tr data-theme-id="${item.theme_id}" class="${item.theme_id === state.selectedThemeId ? "selected" : ""}">
      <td>${item.rank}</td>
      <td><strong>${item.theme_name}</strong></td>
      <td class="score">${item.theme_score}</td>
      <td>${item.heat_score}</td>
      <td>${item.continuation_score}</td>
      <td class="risk">-${item.risk_penalty}</td>
      <td>${item.status}</td>
      <td>${item.branches.join("、")}</td>
    </tr>
  `).join("");

  document.querySelectorAll("#rankingBody tr").forEach((row) => {
    row.addEventListener("click", () => selectTheme(row.dataset.themeId));
  });
}

async function selectTheme(themeId) {
  state.selectedThemeId = themeId;
  const detail = await fetchJson(`/api/v1/themes/${themeId}/detail?date=${dateValue()}`);
  renderDetail(detail);
  renderRanking(state.ranking.items);
}

function renderDetail(detail) {
  $("detailTitle").textContent = detail.theme_name;
  $("detailStatus").textContent = detail.status;
  $("scoreBars").innerHTML = [
    ["主线分", detail.theme_score, "var(--blue)"],
    ["热度分", detail.heat_score, "var(--teal)"],
    ["延续性", detail.continuation_score, "var(--green)"],
    ["风险扣分", detail.risk_penalty, "var(--red)"],
  ].map(([label, value, color]) => `
    <div class="bar-row">
      <span>${label}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, value)}%; background:${color}"></div></div>
      <strong>${value}</strong>
    </div>
  `).join("");

  $("branches").innerHTML = detail.branches.map((name) => `<span class="chip">${name}</span>`).join("");
  $("coreStocks").innerHTML = detail.core_stocks.map((name) => `<span class="chip">${name}</span>`).join("");
  $("modelExplanation").textContent = detail.model_explanation;

  $("riskList").innerHTML = detail.risks.map((risk) => `
    <div class="risk-item">
      <strong>
        <span>${risk.risk_type}</span>
        <span class="severity-${risk.severity}">-${risk.penalty}</span>
      </strong>
      <p>${risk.reason}</p>
    </div>
  `).join("") || "<p>暂无明显风险信号</p>";
}

function renderPortfolio(payload) {
  $("portfolioSummary").textContent = `持仓高风险 ${payload.summary.portfolio_high_risk_count} / 自选高风险 ${payload.summary.watchlist_high_risk_count}`;
  $("watchlist").innerHTML = payload.watchlist.map(renderStock).join("");
  $("positions").innerHTML = payload.portfolio.map(renderStock).join("");
}

function renderStock(stock) {
  const level = stock.risk_level || "unknown";
  return `
    <div class="stock-item">
      <strong>
        <span>${stock.name}</span>
        <span class="risk-${level}">${riskName(level)}</span>
      </strong>
      <p>${stock.theme_name || "未匹配主线"}${stock.quantity ? ` / ${stock.quantity}股` : ""}</p>
      <p>${stock.risk_note}</p>
    </div>
  `;
}

function renderReport(report) {
  $("reportText").textContent = report.report;
}

function levelName(level) {
  return ({ high: "高", medium: "中", low: "低" })[level] || level;
}

function riskName(level) {
  return ({ high: "高风险", medium: "中风险", low: "低风险", unknown: "未知" })[level] || level;
}

async function runBacktest() {
  const result = await fetchJson("/api/v1/backtest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_date: "2021-04-29",
      end_date: dateValue(),
      model_version: "v1.0",
      holding_period: 3,
      top_n: 5,
    }),
  });
  const target = $("backtestResult");
  target.style.display = "block";
  target.textContent = JSON.stringify(result, null, 2);
}

$("refreshBtn").addEventListener("click", loadDashboard);
$("backtestBtn").addEventListener("click", runBacktest);

loadDashboard().catch((error) => {
  $("reportText").textContent = `加载失败：${error.message}`;
});
