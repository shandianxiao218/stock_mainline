const state = {
  ranking: null,
  modelConfig: null,
  backtestResult: null,
  selectedThemeId: null,
  stockSort: { key: "amount", direction: "desc" },
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

  const [ranking, matrix, report, portfolio, quality, modelConfig, factors, confidenceHistory, audit, roles, catalysts] = await Promise.all([
    fetchJson(`/api/v1/themes/ranking?date=${date}&period=${period}`),
    fetchJson(`/api/v1/themes/matrix?date=${date}&days=20`),
    fetchJson(`/api/v1/reports/daily?date=${date}`),
    fetchJson(`/api/v1/portfolio/risk?date=${date}`),
    fetchJson("/api/v1/data/quality"),
    fetchJson("/api/v1/model/config"),
    fetchJson(`/api/v1/factors/effectiveness?date=${date}&holding_period=3`),
    fetchJson(`/api/v1/confidence/history?date=${date}&days=20`),
    fetchJson("/api/v1/audit/logs?limit=80"),
    fetchJson("/api/v1/auth/roles"),
    fetchJson(`/api/v1/catalysts?date=${date}&limit=50`),
  ]);

  state.ranking = ranking;
  state.modelConfig = modelConfig;
  renderOverview(ranking);
  renderRanking(ranking.items);
  renderMatrix(matrix);
  renderReport(report);
  renderPortfolio(portfolio);
  renderQuality(quality);
  renderModelConfig(modelConfig);
  renderBacktestDefaults(modelConfig);
  renderFactors(factors);
  renderConfidenceHistory(ranking, confidenceHistory);
  renderAudit(audit);
  renderRoles(roles);
  renderCatalysts(catalysts);
  loadDataSourceStatus();

  const firstTheme = ranking.items[0];
  if (firstTheme) {
    await selectTheme(state.selectedThemeId || firstTheme.theme_id);
  }
}

function renderQuality(quality) {
  $("qualityMeta").textContent = quality.status === "ok" ? "正常" : `${quality.warn_count} 项需关注`;
  const dateHealth = quality.date_health || {};
  const dateCard = `
    <div class="quality-card">
      <strong>交易日覆盖</strong>
      <p>${dateHealth.trade_day_count || 0} 日 / ${dateHealth.min_trade_date || "-"} - ${dateHealth.max_trade_date || "-"}</p>
    </div>
  `;
  $("qualityChecks").innerHTML = dateCard + quality.checks.map((check) => `
    <div class="quality-card ${check.status}">
      <strong>${check.name}</strong>
      <p>${check.detail}</p>
    </div>
  `).join("");
}

function renderAudit(payload) {
  const items = payload.items || [];
  $("auditMeta").textContent = `最近 ${items.length} 条`;
  $("auditBody").innerHTML = items.slice(0, 60).map((item) => `
    <tr>
      <td>${item.event_time}</td>
      <td>${auditName(item.event_type)}</td>
      <td>${item.method || "-"}</td>
      <td>${item.path || "-"}</td>
      <td>${item.target || "-"}</td>
      <td>${item.actor || "-"}</td>
    </tr>
  `).join("");
}

function renderRoles(payload) {
  $("roleMeta").textContent = `当前：${payload.current_role_name || payload.current_role}`;
  $("roleGrid").innerHTML = (payload.roles || []).map((role) => `
    <div class="role-card ${role.role === payload.current_role ? "active" : ""}">
      <strong>${role.name}</strong>
      <span>${role.role}</span>
      <p>${role.permissions.join("、")}</p>
    </div>
  `).join("");
}

function renderMatrix(matrix) {
  $("matrixMeta").textContent = `${matrix.dates.length} 个交易日`;
  $("matrixHead").innerHTML = `
    <tr>
      <th>主线</th>
      ${matrix.dates.map((date) => `<th>${date.slice(5)}</th>`).join("")}
    </tr>
  `;
  $("matrixBody").innerHTML = matrix.items.map((item) => `
    <tr>
      <td><strong>${item.theme_name}</strong></td>
      ${matrix.dates.map((date) => {
        const cell = item.cells[date];
        if (!cell) return "<td class=\"empty-cell\">-</td>";
        const level = cell.theme_score >= 68 ? "hot" : cell.theme_score >= 58 ? "warm" : "cold";
        return `<td class="matrix-cell ${level}" title="排名 ${cell.rank} / 风险 ${cell.risk_penalty}">${cell.theme_score.toFixed(1)}</td>`;
      }).join("")}
    </tr>
  `).join("");
}

async function loadDataSourceStatus() {
  try {
    const status = await fetchJson("/api/v1/data/eastmoney/status");
    const stocks = status.generated_files.stocks_csv.rows;
    const quotes = status.generated_files.daily_quotes_csv.rows;
    const dbQuotes = status.database.exists ? status.database.quote_count : 0;
    $("dataSourceLabel").textContent = `东方财富 / C导入${stocks}只 / 入库${dbQuotes || quotes}行`;
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

function renderConfidenceHistory(ranking, history) {
  const components = ranking.components || {};
  const names = {
    liquidity: "流动性",
    theme_spread: "主线分差",
    risk_stability: "风险稳定",
    market_breadth: "市场广度",
    theme_consistency: "主线一致性",
  };
  $("confidenceMeta").textContent = `${history.days || 0} 日历史`;
  $("confidenceComponents").innerHTML = Object.entries(names).map(([key, label]) => `
    <div class="confidence-card">
      <span>${label}</span>
      <strong>${Number(components[key] || 0).toFixed(1)}</strong>
    </div>
  `).join("");
  $("confidenceHistoryBody").innerHTML = (history.items || []).map((item) => {
    const c = item.components || {};
    return `
      <tr>
        <td>${item.date}</td>
        <td>${levelName(item.confidence)}</td>
        <td>${item.confidence_score}</td>
        <td>${Number(c.liquidity || 0).toFixed(1)}</td>
        <td>${Number(c.theme_spread || 0).toFixed(1)}</td>
        <td>${Number(c.risk_stability || 0).toFixed(1)}</td>
        <td>${Number(c.market_breadth || 0).toFixed(1)}</td>
        <td>${Number(c.theme_consistency || 0).toFixed(1)}</td>
        <td>${item.top_theme || "-"}</td>
      </tr>
    `;
  }).join("");
}

function renderModelConfig(payload) {
  const active = payload.active || {};
  $("modelVersion").value = active.model_version || "v1.0-local";
  $("configVersion").value = active.config_version || "default";
  $("heatWeight").value = active.heat_weight ?? 0.4;
  $("continuationWeight").value = active.continuation_weight ?? 0.6;
  $("riskCap").value = active.risk_cap ?? 20;
  $("modelConfigMeta").textContent = `${active.model_version || "-"} / ${active.config_version || "-"} / 风险上限 ${active.risk_cap ?? "-"}`;
  $("modelConfigHistory").innerHTML = (payload.items || []).slice(0, 5).map((item) => {
    const cfg = item.config || {};
    return `
      <div class="config-row ${item.is_active ? "active" : ""}">
        <strong>${cfg.model_version || item.model_version} / ${cfg.config_version || item.config_version}</strong>
        <span>热度 ${cfg.heat_weight}，延续 ${cfg.continuation_weight}，风险上限 ${cfg.risk_cap}</span>
        <small>${item.created_at || ""}${item.is_active ? " / 当前生效" : ""}</small>
      </div>
    `;
  }).join("");
}

function renderBacktestDefaults(payload) {
  const active = (payload && payload.active) || {};
  $("backtestModelVersion").value = active.model_version || "v1.0-local";
  $("backtestEnd").value = dateValue();
}

function renderFactors(payload) {
  $("factorMeta").textContent = payload.status === "completed"
    ? `${payload.date} / ${payload.holding_period}日收益验证`
    : "数据不足";
  $("factorSummary").textContent = payload.summary || "暂无因子有效性数据";
  $("factorBody").innerHTML = (payload.items || []).map((item) => `
    <tr>
      <td><strong>${item.factor}</strong></td>
      <td>${formatIc(item.ic_5d)}</td>
      <td>${formatIc(item.rank_ic_5d)}</td>
      <td>${item.state_5d}</td>
      <td>${formatIc(item.ic_20d)}</td>
      <td>${formatIc(item.rank_ic_20d)}</td>
      <td>${item.state_20d}</td>
      <td>${item.base_weight ?? "-"}</td>
      <td>${item.final_weight ?? "-"}</td>
      <td><span class="factor-action ${item.action === "小幅上调" ? "up-action" : item.action === "小幅下调" ? "down-action" : ""}">${item.action}</span></td>
    </tr>
  `).join("");
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
  const [detail, riskHistory] = await Promise.all([
    fetchJson(`/api/v1/themes/${themeId}/detail?date=${dateValue()}`),
    fetchJson(`/api/v1/themes/${themeId}/risk-history?date=${dateValue()}&days=20`),
  ]);
  renderDetail(detail);
  renderRiskHistory(riskHistory);
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
  renderStockMetrics(detail.stock_metrics || []);

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

function renderRiskHistory(payload) {
  $("riskHistoryBody").innerHTML = (payload.items || []).map((item) => {
    const mainRisk = (item.risks || []).slice(0, 2).map((risk) => risk.risk_type).join("、") || "无明显风险";
    return `
      <tr>
        <td>${item.date}</td>
        <td class="risk">-${item.risk_penalty}</td>
        <td>${item.status}</td>
        <td>${mainRisk}</td>
      </tr>
    `;
  }).join("");
}

function renderStockMetrics(stocks) {
  const sorted = [...stocks].sort((a, b) => {
    const key = state.stockSort.key;
    const left = a[key];
    const right = b[key];
    const result = typeof left === "number" && typeof right === "number"
      ? left - right
      : String(left ?? "").localeCompare(String(right ?? ""), "zh-CN");
    return state.stockSort.direction === "asc" ? result : -result;
  });
  $("stockMetrics").innerHTML = sorted.map((stock) => `
    <tr data-symbol="${stock.symbol}" data-name="${stock.name}">
      <td><strong>${stock.name}</strong></td>
      <td>${stock.symbol}</td>
      <td>${price(stock.open)}</td>
      <td>${price(stock.close)}</td>
      <td>${price(stock.high)}</td>
      <td>${price(stock.low)}</td>
      <td class="${stock.pct1 >= 0 ? "up" : "down"}">${stock.pct1.toFixed(2)}%</td>
      <td class="${stock.pct5 >= 0 ? "up" : "down"}">${stock.pct5.toFixed(2)}%</td>
      <td>${formatNumber(stock.volume)}</td>
      <td>${formatAmount(stock.amount)}</td>
      <td>${stock.limit_break ? "是" : "否"}</td>
      <td>${stock.hot_money || "未接入"}</td>
    </tr>
  `).join("");
  document.querySelectorAll("#stockMetrics tr").forEach((row) => {
    row.addEventListener("dblclick", () => openKline(row.dataset.symbol, row.dataset.name));
  });
}

function renderPortfolio(payload) {
  $("portfolioSummary").textContent = `持仓高风险 ${payload.summary.portfolio_high_risk_count} / 自选高风险 ${payload.summary.watchlist_high_risk_count}`;
  $("watchlist").innerHTML = payload.watchlist.map((stock) => renderStock(stock, true)).join("");
  $("positions").innerHTML = payload.portfolio.map((stock) => renderStock(stock, false, true)).join("");
}

function renderStock(stock, canDelete, canDeletePosition = false) {
  const level = stock.risk_level || "unknown";
  const deleteButton = canDelete ? `<button class="text-btn" data-delete-watch="${stock.symbol || (stock.ts_code || "").slice(0, 6)}">删除</button>` : "";
  const deletePositionButton = canDeletePosition ? `<button class="text-btn" data-delete-position="${stock.symbol || (stock.ts_code || "").slice(0, 6)}">删除</button>` : "";
  return `
    <div class="stock-item">
      <strong>
        <span>${stock.name}</span>
        <span>${deleteButton}${deletePositionButton}<span class="risk-${level}">${riskName(level)}</span></span>
      </strong>
      <p>${stock.theme_name || "未匹配主线"}${stock.quantity ? ` / ${stock.quantity}股` : ""}${stock.cost_price ? ` / 成本 ${stock.cost_price}` : ""}</p>
      <p>${stock.risk_note}</p>
    </div>
  `;
}

function renderReport(report) {
  $("reportText").textContent = report.report;
}

function renderCatalysts(payload) {
  const items = payload.items || [];
  $("catalystMeta").textContent = `${items.length} 条`;
  $("catalystList").innerHTML = items.map((item) => `
    <div class="catalyst-item">
      <strong>
        <span>${item.title}</span>
        <span>${item.level}级 / ${item.score}</span>
      </strong>
      <p>${item.theme_name || "未绑定主线"} / ${item.source || "未填来源"} / ${item.note || "无备注"}</p>
    </div>
  `).join("") || "<p class=\"empty-note\">暂无人工催化事件</p>";
}

async function addCatalyst(event) {
  event.preventDefault();
  const title = $("catalystTitle").value.trim();
  if (!title) return;
  await fetchJson("/api/v1/catalysts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trade_date: dateValue(),
      theme_name: $("catalystTheme").value.trim(),
      level: $("catalystLevel").value,
      title,
      source: $("catalystSource").value.trim(),
      note: $("catalystNote").value.trim(),
    }),
  });
  $("catalystTitle").value = "";
  $("catalystSource").value = "";
  $("catalystNote").value = "";
  await loadDashboard();
}

function levelName(level) {
  return ({ high: "高", medium: "中", low: "低" })[level] || level;
}

function riskName(level) {
  return ({ high: "高风险", medium: "中风险", low: "低风险", unknown: "未知" })[level] || level;
}

function auditName(type) {
  return ({
    api_access: "API访问",
    model_config_save: "参数修改",
    review_save: "复盘保存",
    backtest_run: "回测运行",
    watchlist_add: "自选新增",
    watchlist_delete: "自选删除",
    position_save: "持仓保存",
    position_delete: "持仓删除",
    catalyst_add: "催化新增",
  })[type] || type;
}

async function runBacktest(event) {
  if (event) event.preventDefault();
  const result = await fetchJson("/api/v1/backtest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_date: $("backtestStart").value || "2021-04-29",
      end_date: $("backtestEnd").value || dateValue(),
      model_version: $("backtestModelVersion").value.trim() || "v1.0-local",
      holding_period: Number($("backtestHolding").value || 3),
      top_n: Number($("backtestTopN").value || 5),
    }),
  });
  state.backtestResult = result;
  const target = $("backtestResult");
  target.style.display = "block";
  target.textContent = formatBacktest(result);
}

function downloadBacktestCsv() {
  const result = state.backtestResult;
  if (!result || !result.samples || !result.samples.length) return;
  const rows = [
    ["trade_date", "exit_date", "selected_return", "benchmark_return", "excess_return", "selected_themes"],
    ...result.samples.map((sample) => [
      sample.trade_date,
      sample.exit_date,
      sample.selected_return,
      sample.benchmark_return,
      sample.excess_return,
      sample.selected_themes.join("|"),
    ]),
  ];
  const csv = rows.map((row) => row.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
  const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `backtest_${dateValue()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

async function saveReview() {
  const result = await fetchJson(`/api/v1/reviews/save?date=${dateValue()}`, {
    method: "POST",
  });
  const target = $("backtestResult");
  target.style.display = "block";
  target.textContent = `复盘已保存：${result.trade_date}，主线 ${result.theme_count} 条，风险 ${result.risk_count} 条，置信度 ${levelName(result.confidence)} ${result.confidence_score}`;
  loadDataSourceStatus();
}

async function saveModelConfig(event) {
  event.preventDefault();
  const payload = {
    model_version: $("modelVersion").value.trim() || "v1.0-local",
    config_version: $("configVersion").value.trim() || "default",
    heat_weight: Number($("heatWeight").value || 0),
    continuation_weight: Number($("continuationWeight").value || 0),
    risk_cap: Number($("riskCap").value || 20),
  };
  const saved = await fetchJson("/api/v1/model/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("modelConfigMeta").textContent = `${saved.model_version} / ${saved.config_version} / 已保存`;
  await loadDashboard();
}

async function addWatchlist(event) {
  event.preventDefault();
  const symbol = $("watchSymbol").value.trim();
  const name = $("watchName").value.trim();
  if (!symbol) return;
  await fetchJson("/api/v1/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, name }),
  });
  $("watchSymbol").value = "";
  $("watchName").value = "";
  loadDashboard();
}

async function addPosition(event) {
  event.preventDefault();
  const symbol = $("positionSymbol").value.trim();
  const name = $("positionName").value.trim();
  const quantity = Number($("positionQty").value || 0);
  const cost_price = $("positionCost").value;
  if (!symbol || quantity <= 0) return;
  await fetchJson("/api/v1/positions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, name, quantity, cost_price }),
  });
  $("positionSymbol").value = "";
  $("positionName").value = "";
  $("positionQty").value = "";
  $("positionCost").value = "";
  loadDashboard();
}

async function deleteWatch(symbol) {
  if (!symbol) return;
  await fetchJson(`/api/v1/watchlist/${symbol}`, { method: "DELETE" });
  loadDashboard();
}

async function deletePosition(symbol) {
  if (!symbol) return;
  await fetchJson(`/api/v1/positions/${symbol}`, { method: "DELETE" });
  loadDashboard();
}

async function openKline(symbol, name) {
  const payload = await fetchJson(`/api/v1/stocks/${symbol}/kline?date=${dateValue()}&window=80`);
  $("klineTitle").textContent = `${name} ${symbol}`;
  $("klineChart").innerHTML = renderKlineSvg(payload.bars);
  $("klineModal").classList.add("open");
  $("klineModal").setAttribute("aria-hidden", "false");
}

function closeKline() {
  $("klineModal").classList.remove("open");
  $("klineModal").setAttribute("aria-hidden", "true");
}

function renderKlineSvg(bars) {
  if (!bars.length) return "<p>暂无K线数据</p>";
  const width = 920;
  const height = 360;
  const pad = 28;
  const maxPrice = Math.max(...bars.map((bar) => bar.high));
  const minPrice = Math.min(...bars.map((bar) => bar.low));
  const priceSpan = maxPrice - minPrice || 1;
  const step = (width - pad * 2) / bars.length;
  const y = (price) => pad + (maxPrice - price) / priceSpan * (height - pad * 2);
  const candles = bars.map((bar, index) => {
    const x = pad + index * step + step / 2;
    const color = bar.close >= bar.open ? "#c24135" : "#1b8a5a";
    const bodyTop = Math.min(y(bar.open), y(bar.close));
    const bodyHeight = Math.max(2, Math.abs(y(bar.open) - y(bar.close)));
    return `
      <line x1="${x}" y1="${y(bar.high)}" x2="${x}" y2="${y(bar.low)}" stroke="${color}" stroke-width="1" />
      <rect x="${x - Math.max(2, step * 0.28)}" y="${bodyTop}" width="${Math.max(3, step * 0.56)}" height="${bodyHeight}" fill="${color}" />
    `;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img">
      <rect width="${width}" height="${height}" fill="#ffffff" />
      <text x="${pad}" y="18" fill="#657383" font-size="12">${bars[0].date} 至 ${bars[bars.length - 1].date}</text>
      <text x="${width - 120}" y="18" fill="#657383" font-size="12">${minPrice.toFixed(2)} - ${maxPrice.toFixed(2)}</text>
      ${candles}
    </svg>
  `;
}

function formatBacktest(result) {
  if (result.status !== "completed") return JSON.stringify(result, null, 2);
  const m = result.metrics;
  const lines = [
    `状态：${result.status}`,
    `样本数：${m.sample_count}`,
    `区间：${m.start_date} 至 ${m.end_date}`,
    `持有期：${m.holding_period}日 / Top ${m.top_n}`,
    `平均收益：${m.avg_return}%`,
    `平均超额：${m.avg_excess_return}%`,
    `胜率：${(m.win_rate * 100).toFixed(1)}%`,
    `超额胜率：${(m.excess_win_rate * 100).toFixed(1)}%`,
    `最大回撤：${m.max_drawdown}%`,
    `Rank IC：${m.rank_ic}`,
    "",
    "最近样本：",
    ...(result.samples || []).slice(-8).map((sample) =>
      `${sample.trade_date} -> ${sample.exit_date}，收益 ${(sample.selected_return * 100).toFixed(2)}%，超额 ${(sample.excess_return * 100).toFixed(2)}%，${sample.selected_themes.join("、")}`
    ),
  ];
  return lines.join("\n");
}

function price(value) {
  return Number(value || 0).toFixed(2);
}

function formatAmount(value) {
  return `${(Number(value || 0) / 100000000).toFixed(2)}亿`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function formatIc(value) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(4);
}

$("refreshBtn").addEventListener("click", loadDashboard);
$("dateInput").addEventListener("change", loadDashboard);
$("periodInput").addEventListener("change", loadDashboard);
$("backtestForm").addEventListener("submit", runBacktest);
$("downloadBacktestBtn").addEventListener("click", downloadBacktestCsv);
$("saveReviewBtn").addEventListener("click", saveReview);
$("watchlistForm").addEventListener("submit", addWatchlist);
$("positionForm").addEventListener("submit", addPosition);
$("modelConfigForm").addEventListener("submit", saveModelConfig);
$("catalystForm").addEventListener("submit", addCatalyst);
$("closeKlineBtn").addEventListener("click", closeKline);
document.querySelectorAll(".component-table th[data-sort]").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    state.stockSort = {
      key,
      direction: state.stockSort.key === key && state.stockSort.direction === "desc" ? "asc" : "desc",
    };
    selectTheme(state.selectedThemeId);
  });
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-delete-watch]");
  if (button) deleteWatch(button.dataset.deleteWatch);
  const positionButton = event.target.closest("[data-delete-position]");
  if (positionButton) deletePosition(positionButton.dataset.deletePosition);
});

loadDashboard().catch((error) => {
  $("reportText").textContent = `加载失败：${error.message}`;
});
