const state = {
  ranking: null,
  modelConfig: null,
  backtestResult: null,
  selectedThemeId: null,
  selectedSectorCode: null,
  sectorsLoaded: false,
  stockSort: { key: "amount", direction: "desc" },
  rankingFilter: { confidence: "all", status: "all", riskLevel: "all" },
  rankingLimit: "10",
  matrixLimit: "10",
  loadToken: 0,
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

function matrixLimitValue() {
  return $("matrixLimit") ? $("matrixLimit").value : state.matrixLimit;
}

function rankingLimitValue() {
  return $("rankingLimit") ? $("rankingLimit").value : state.rankingLimit;
}

function sortByDateDesc(items, key = "date") {
  const valueOf = (item) => {
    if (item && typeof item === "object") return String(item[key] || "");
    return String(item || "");
  };
  return [...(items || [])].sort((a, b) => valueOf(b).localeCompare(valueOf(a)));
}

async function loadDashboard() {
  const date = dateValue();
  const period = periodValue();
  const token = ++state.loadToken;
  $("exportLink").href = `/api/v1/export/themes.xlsx?date=${date}`;
  $("rankingMeta").textContent = "榜单加载中";
  $("matrixMeta").textContent = "矩阵加载中";

  const [ranking, quality, modelConfig, roles] = await Promise.all([
    fetchJson(`/api/v1/themes/ranking?date=${date}&period=${period}&limit=${rankingLimitValue()}`),
    fetchJson("/api/v1/data/quality"),
    fetchJson("/api/v1/model/config"),
    fetchJson("/api/v1/auth/roles"),
  ]);
  if (token !== state.loadToken) return;

  state.ranking = ranking;
  state.modelConfig = modelConfig;
  state.rankingLimit = rankingLimitValue();
  state.matrixLimit = matrixLimitValue();
  renderOverview(ranking);
  renderRanking(ranking.items);
  renderQuality(quality);
  renderModelConfig(modelConfig);
  renderBacktestDefaults(modelConfig);
  renderRoles(roles);
  loadDataSourceStatus();

  const firstTheme = ranking.items[0];
  if (firstTheme) {
    selectTheme(state.selectedThemeId || firstTheme.theme_id).catch((error) => {
      $("detailStatus").textContent = `详情加载失败：${error.message}`;
    });
  }
  if (!$("sectors").classList.contains("is-hidden")) {
    loadSectors().catch((error) => {
      $("sectorMeta").textContent = `真实板块加载失败：${error.message}`;
    });
  }

  loadDashboardModule(token, fetchJson(`/api/v1/themes/matrix?date=${date}&days=20&limit=${matrixLimitValue()}`), renderMatrix, (error) => {
    $("matrixMeta").textContent = `矩阵加载失败：${error.message}`;
  });
  loadDashboardModule(token, fetchJson(`/api/v1/reports/daily?date=${date}`), renderReport);
  loadDashboardModule(token, fetchJson(`/api/v1/portfolio/risk?date=${date}`), renderPortfolio);
  loadDashboardModule(token, fetchJson(`/api/v1/factors/effectiveness?date=${date}&holding_period=3`), renderFactors);
  loadDashboardModule(token, fetchJson(`/api/v1/confidence/history?date=${date}&days=20`), (payload) => renderConfidenceHistory(ranking, payload));
  loadDashboardModule(token, fetchJson("/api/v1/audit/logs?limit=80"), renderAudit);
  loadDashboardModule(token, fetchJson(`/api/v1/catalysts?date=${date}&limit=50`), renderCatalysts);
  loadDashboardModule(token, fetchJson(`/api/v1/alerts?date=${date}`), renderAlerts);
}

async function loadDashboardModule(token, promise, render, onError) {
  try {
    const payload = await promise;
    if (token === state.loadToken) render(payload);
  } catch (error) {
    console.error(error);
    if (token === state.loadToken && onError) onError(error);
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
  const dates = sortByDateDesc(matrix.dates);
  const shown = matrix.items.length;
  const total = matrix.row_limit === "all" ? matrix.total_count : matrix.target_count;
  $("matrixMeta").textContent = `${matrix.dates.length} 个交易日 / ${shown} / ${total || shown} 个板块`;
  $("matrixHead").innerHTML = `
    <tr>
      <th>主线</th>
      ${dates.map((date) => `<th>${date.slice(5)}</th>`).join("")}
    </tr>
  `;
  $("matrixBody").innerHTML = matrix.items.map((item) => `
    <tr>
      <td><strong>${item.theme_name}</strong></td>
      ${dates.map((date) => {
        const cell = item.cells[date];
        if (!cell) return "<td class=\"empty-cell\">-</td>";
        const level = cell.theme_score >= 68 ? "hot" : cell.theme_score >= 58 ? "warm" : "cold";
        return `<td class="matrix-cell ${level}" title="排名 ${cell.rank} / 风险 ${cell.risk_penalty}">${cell.theme_score.toFixed(1)}</td>`;
      }).join("")}
    </tr>
  `).join("");
}

async function loadMatrixOnly() {
  state.matrixLimit = matrixLimitValue();
  const matrix = await fetchJson(`/api/v1/themes/matrix?date=${dateValue()}&days=20&limit=${state.matrixLimit}`);
  renderMatrix(matrix);
}

function renderSectors(payload) {
  const items = payload.items || [];
  $("sectorMeta").textContent = `${items.length} 个板块`;
  $("sectorBody").innerHTML = items.map((item) => `
    <tr data-sector-code="${item.sector_code}" class="${item.sector_code === state.selectedSectorCode ? "selected" : ""}">
      <td>${item.sector_code}</td>
      <td><strong>${item.sector_name}</strong></td>
      <td>${item.stock_count}</td>
    </tr>
  `).join("");
  document.querySelectorAll("#sectorBody tr").forEach((row) => {
    row.addEventListener("click", () => selectSector(row.dataset.sectorCode));
  });
}

async function showSectorsPanel() {
  $("sectors").classList.remove("is-hidden");
  $("sectors").setAttribute("aria-hidden", "false");
  if (!state.sectorsLoaded) {
    await loadSectors();
  }
}

async function loadSectors() {
  const sectors = await fetchJson("/api/v1/sectors?limit=80");
  renderSectors(sectors);
  state.sectorsLoaded = true;
  const firstSector = sectors.items && sectors.items[0];
  if (firstSector) {
    await selectSector(state.selectedSectorCode || firstSector.sector_code);
  }
}

function renderAlerts(payload) {
  const items = payload.items || [];
  const countEl = $("alertCount");
  if (countEl) countEl.textContent = `${items.length} 条`;
  const listEl = $("alertList");
  if (!listEl) return;
  if (!items.length) {
    listEl.innerHTML = "<p style='padding:4px 8px;font-size:13px;color:#657383;'>当前无预警信号</p>";
    return;
  }
  const typeNames = {
    new_top10: "新晋前10",
    rank_surge: "排名急升",
    risk_surge: "风险急升",
    core_break: "核心股炸板",
    relay_break: "接力断裂",
    confidence_drop: "置信度下降",
    high_vol_stagnation: "高位滞涨",
  };
  listEl.innerHTML = items.map((alert) => `
    <div class="risk-item">
      <strong>
        <span class="severity-${alert.severity}">${typeNames[alert.alert_type] || alert.alert_type}</span>
      </strong>
      <p>${alert.message}</p>
    </div>
  `).join("");
}

async function selectSector(sectorCode) {
  state.selectedSectorCode = sectorCode;
  const payload = await fetchJson(`/api/v1/sectors/${sectorCode}/constituents?limit=500`);
  $("sectorConstituentBody").innerHTML = (payload.items || []).map((item) => `
    <tr>
      <td>${item.symbol}</td>
      <td><strong>${item.name}</strong></td>
      <td>${item.market || "-"}</td>
    </tr>
  `).join("");
  document.querySelectorAll("#sectorBody tr").forEach((row) => {
    row.classList.toggle("selected", row.dataset.sectorCode === sectorCode);
  });
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

  // R-P0-2: 低置信度时弱化榜单视觉权重
  const rankingSection = $("ranking");
  if (rankingSection) {
    if (ranking.confidence === "low") {
      rankingSection.classList.add("low-confidence-mask");
    } else {
      rankingSection.classList.remove("low-confidence-mask");
    }
  }

  const highRisk = ranking.items.filter((item) => item.risk_penalty >= 8);
  $("riskCount").textContent = `${highRisk.length} 条`;
  $("riskSummary").textContent = highRisk.map((item) => item.theme_name).join("、") || "暂无高风险主线";

  // 退潮主线：风险扣分>=8 或 状态含"退潮"
  const declining = ranking.items.filter(
    (item) => item.risk_penalty >= 8 || item.status.includes("退潮")
  );
  const decliningEl = $("decliningThemes");
  if (decliningEl) {
    decliningEl.textContent = declining.map((item) => `${item.theme_name}(-${item.risk_penalty})`).join("、") || "暂无退潮主线";
  }

  // 关键验证点：取排名前 3 主线的 next_checks
  const checks = ranking.items.slice(0, 3).flatMap((item) =>
    (item.next_checks || []).map((check) => `[${item.theme_name}] ${check}`)
  );
  const checksEl = $("keyChecks");
  if (checksEl) {
    checksEl.innerHTML = checks.length
      ? checks.map((c) => `<li>${c}</li>`).join("")
      : "<li>暂无</li>";
  }

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
  $("confidenceHistoryBody").innerHTML = sortByDateDesc(history.items).map((item) => {
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

function getFilteredItems() {
  const items = (state.ranking && state.ranking.items) || [];
  const filter = state.rankingFilter;
  return items.filter((item) => {
    if (filter.confidence !== "all") {
      const conf = item.confidence || "";
      if (filter.confidence === "high" && conf !== "high") return false;
      if (filter.confidence === "medium" && conf !== "medium" && conf !== "medium_high" && conf !== "medium_low") return false;
      if (filter.confidence === "low" && conf !== "low") return false;
    }
    if (filter.status !== "all" && !item.status.includes(filter.status)) return false;
    if (filter.riskLevel === "high" && item.risk_penalty < 8) return false;
    if (filter.riskLevel === "medium" && item.risk_penalty < 4) return false;
    return true;
  });
}

function renderRanking(items) {
  const filtered = getFilteredItems();
  const shown = (state.ranking && state.ranking.items ? state.ranking.items.length : filtered.length);
  const total = state.ranking ? state.ranking.total_count : shown;
  $("rankingMeta").textContent = `${filtered.length} / ${shown} / ${total || shown} 个板块`;
  $("rankingBody").innerHTML = filtered.map((item) => `
    <tr data-theme-id="${item.theme_id}" class="${item.theme_id === state.selectedThemeId ? "selected" : ""}">
      <td>${item.rank}</td>
      <td><strong>${item.theme_name}</strong></td>
      <td class="score">${item.theme_score}</td>
      <td>${item.heat_score}</td>
      <td>${item.continuation_score}</td>
      <td class="risk">-${item.risk_penalty}</td>
      <td>${item.stage ? `<span class="stage-badge stage-${item.stage}">${item.stage}</span>` : item.status}</td>
      <td>${item.branches.join("、")}</td>
    </tr>
  `).join("");

  document.querySelectorAll("#rankingBody tr").forEach((row) => {
    row.addEventListener("click", () => selectTheme(row.dataset.themeId));
  });
}

async function loadRankingOnly() {
  state.rankingLimit = rankingLimitValue();
  state.ranking = await fetchJson(`/api/v1/themes/ranking?date=${dateValue()}&period=${periodValue()}&limit=${state.rankingLimit}`);
  renderOverview(state.ranking);
  renderRanking(state.ranking.items);
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

  // 主线阶段展示
  const stageSummary = $("stageSummary");
  if (stageSummary && detail.stage) {
    const prevText = detail.previous_stage ? `（前阶段：${detail.previous_stage}）` : "";
    stageSummary.innerHTML = `
      <p style="margin:0 0 6px;">
        <span class="stage-badge stage-${detail.stage}">${detail.stage}</span>
        ${prevText}
        <span style="color:var(--muted);font-size:12px;margin-left:8px;">置信度 ${(detail.stage_confidence * 100).toFixed(0)}%</span>
      </p>
      <p style="margin:0;color:var(--muted);font-size:12px;">${detail.stage_reason || ""}</p>
      ${(detail.transition_signals || []).map(s => `<span style="font-size:11px;color:var(--muted);background:#edf2f7;border-radius:4px;padding:2px 6px;margin:2px;display:inline-block;">${s}</span>`).join("")}
    `;
  }
  // 加载阶段历史
  if (detail.theme_id) {
    fetchJson(`/api/v1/themes/${detail.theme_id}/stage-history?date=${dateValue()}&days=20`).then((payload) => {
      const listEl = $("stageHistoryList");
      if (!listEl) return;
      const items = payload.items || [];
      listEl.innerHTML = items.length
        ? items.map((item) => `
          <div class="stage-history-item">
            <span class="stage-date">${item.date}</span>
            <span class="stage-badge stage-${item.stage}">${item.stage}</span>
            <span class="stage-reason">${item.reason || ""}</span>
          </div>
        `).join("")
        : "<p style='font-size:12px;color:var(--muted);'>暂无阶段历史</p>";
    }).catch(() => {});
  }
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
  renderScoreAudit(detail);
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

  // 资金接力断裂分析
  const relayItems = (detail.sectors || []).map((sec) => {
    const relay = (sec.stats || {}).relay_break || {};
    return { name: sec.sector_name, relay };
  }).filter((item) => item.relay.lead_continue_rate !== null && item.relay.lead_continue_rate !== undefined);
  $("relayBreakList").innerHTML = relayItems.length
    ? relayItems.map((item) => {
      const r = item.relay;
      const leadTag = r.lead_continue_rate < 0.4 ? " style='color:#c24135'" : "";
      return `<p><strong>${item.name}</strong>：领涨延续率 <span${leadTag}>${(r.lead_continue_rate * 100).toFixed(0)}%</span>` +
        (r.limit_overlap_rate !== null ? `，涨停重合率 ${(r.limit_overlap_rate * 100).toFixed(0)}%` : "") +
        (r.core_deviation !== null ? `，核心偏离 ${r.core_deviation.toFixed(2)}%` : "") +
        "</p>";
    }).join("")
    : "<p>暂无接力断裂数据</p>";

  // 次日验证条件
  const checks = detail.next_checks || [];
  $("nextChecksList").innerHTML = checks.length
    ? checks.map((c) => `<li>${c}</li>`).join("")
    : "<li>暂无</li>";

  // 加载接力断裂详细 API
  fetchJson(`/api/v1/themes/${detail.theme_id}/relay-break?date=${dateValue()}`).then((relay) => {
    // 已通过 sectors 中的 relay_break 展示，此处预留扩展
  }).catch(() => {});
}

function renderScoreAudit(detail) {
  const config = (state.modelConfig && state.modelConfig.active) || {};
  const heatWeight = Number(config.heat_weight ?? 0.4);
  const continuationWeight = Number(config.continuation_weight ?? 0.6);
  const sectors = detail.sectors || [];
  const stats = sectors[0] ? (sectors[0].stats || {}) : {};
  $("scoreFormula").innerHTML = `
    <strong>主线分 = ${heatWeight.toFixed(2)} × 热度分 + ${continuationWeight.toFixed(2)} × 延续性分 - 风险扣分</strong>
    <span>${detail.theme_score} = ${heatWeight.toFixed(2)} × ${detail.heat_score} + ${continuationWeight.toFixed(2)} × ${detail.continuation_score} - ${detail.risk_penalty}</span>
  `;

  const sourceLabel = stats.universe_source === "theme_universe" ? "配置样例成分" : "东方财富映射成分";
  const cards = [
    ["成分来源", sourceLabel, stats.universe_note || ""],
    ["有效成分", `${stats.stock_count || 0} 只`, `配置成分 ${stats.configured_stock_count || stats.stock_count || 0} 只`],
    ["涨停/触板", `${stats.limit_count || 0}/${stats.touched_count || 0}`, `炸板 ${stats.break_count || 0}，最高连板 ${stats.max_consecutive_boards || 0}`],
    ["成交放大", `${Number(stats.amount_ratio || 0).toFixed(2)} 倍`, `成交额 ${formatAmount(stats.amount || 0)}`],
    ["上涨广度", `${Math.round(Number(stats.up_ratio || 0) * 100)}%`, `中位涨幅 ${Number(stats.median_pct || 0).toFixed(2)}%`],
    ["近5日强度", `${Number(stats.avg_pct5 || 0).toFixed(2)}%`, `平均涨幅 ${Number(stats.avg_pct || 0).toFixed(2)}%`],
  ];

  $("scoreAudit").innerHTML = `
    <div class="audit-card-grid">
      ${cards.map(([label, value, note]) => `
        <div class="audit-card">
          <span>${label}</span>
          <strong>${value}</strong>
          <small>${note}</small>
        </div>
      `).join("")}
    </div>
    ${renderFactorChart("热度分拆解", detail.factor_contribution?.heat || [], "var(--teal)")}
    ${renderFactorChart("延续性分拆解", detail.factor_contribution?.continuation || [], "var(--green)")}
    ${renderRiskChart(detail.factor_contribution?.risk || [])}
  `;
}

function renderFactorChart(title, rows, color) {
  if (!rows.length) return "";
  return `
    <div class="factor-chart">
      <h4>${title}</h4>
      ${rows.map((row) => `
        <div class="factor-row">
          <div class="factor-head">
            <strong>${row.name}</strong>
            <span>得分 ${Number(row.score || 0).toFixed(2)} / 权重 ${Number(row.weight || 0).toFixed(2)} / 贡献 ${Number(row.weighted || 0).toFixed(2)}</span>
          </div>
          <div class="factor-track">
            <div class="factor-fill" style="width:${Math.max(0, Math.min(100, Number(row.score || 0)))}%;background:${color};"></div>
          </div>
          <p>${row.basis || "-"}；${row.formula || "-"}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderRiskChart(rows) {
  if (!rows.length) {
    return `
      <div class="factor-chart">
        <h4>风险扣分拆解</h4>
        <div class="factor-row">
          <div class="factor-head"><strong>无触发风险项</strong><span>扣分 0.00</span></div>
          <div class="factor-track"><div class="factor-fill" style="width:0%;background:var(--red);"></div></div>
          <p>当前规则未触发风险扣分。</p>
        </div>
      </div>
    `;
  }
  return `
    <div class="factor-chart">
      <h4>风险扣分拆解</h4>
      ${rows.map((row) => `
        <div class="factor-row">
          <div class="factor-head"><strong>${row.name}</strong><span>扣分 ${Number(row.penalty || 0).toFixed(2)}</span></div>
          <div class="factor-track">
            <div class="factor-fill" style="width:${Math.min(100, Number(row.penalty || 0) * 20)}%;background:var(--red);"></div>
          </div>
          <p>该项从主线分中扣除。</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderRiskHistory(payload) {
  $("riskHistoryBody").innerHTML = sortByDateDesc(payload.items).map((item) => {
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
  const disclaimer = "【免责声明】以下复盘内容为研究辅助，不构成投资建议。\n\n";
  $("reportText").textContent = disclaimer + report.report;
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
  const target = $("backtestResult");
  target.style.display = "block";
  target.textContent = "回测任务已提交，等待后台计算...";
  const result = await fetchJson("/api/v1/backtest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_date: $("backtestStart").value || "2021-04-29",
      end_date: $("backtestEnd").value || dateValue(),
      model_version: $("backtestModelVersion").value.trim() || "v1.0-local",
      holding_period: Number($("backtestHolding").value || 3),
      top_n: Number($("backtestTopN").value || 5),
      async: true,
    }),
  });
  state.backtestResult = result;
  target.textContent = formatBacktest(result);
  if (result.task_id && result.status === "running") {
    await pollBacktest(result.task_id);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollBacktest(taskId) {
  const target = $("backtestResult");
  for (let attempt = 0; attempt < 180; attempt += 1) {
    await sleep(attempt < 10 ? 800 : 2000);
    const result = await fetchJson(`/api/v1/backtest/runs/${taskId}`);
    state.backtestResult = result;
    target.textContent = formatBacktest(result);
    if (result.status !== "running") return;
  }
  target.textContent = `${target.textContent}\n\n任务仍在后台运行，可稍后刷新任务状态。`;
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
  const disclaimer = "\n\n【免责声明】本系统为个人研究辅助工具，回测结果仅供学习参考，不构成任何投资建议。历史表现不代表未来收益。";
  if (result.status !== "completed") {
    const lines = [
      `状态：${result.status}`,
      result.task_id ? `任务：${result.task_id}` : null,
      result.note ? `说明：${result.note}` : null,
      result.error ? `错误：${result.error}` : null,
    ].filter(Boolean);
    return lines.join("\n") || JSON.stringify(result, null, 2);
  }
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
  return lines.join("\n") + disclaimer;
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
$("rankingLimit").addEventListener("change", () => {
  loadRankingOnly().catch((error) => {
    $("rankingMeta").textContent = `榜单加载失败：${error.message}`;
  });
});
$("matrixLimit").addEventListener("change", () => {
  loadMatrixOnly().catch((error) => {
    $("matrixMeta").textContent = `矩阵加载失败：${error.message}`;
  });
});
$("backtestForm").addEventListener("submit", runBacktest);
$("downloadBacktestBtn").addEventListener("click", downloadBacktestCsv);
$("saveReviewBtn").addEventListener("click", saveReview);
$("watchlistForm").addEventListener("submit", addWatchlist);
$("positionForm").addEventListener("submit", addPosition);
$("modelConfigForm").addEventListener("submit", saveModelConfig);
$("catalystForm").addEventListener("submit", addCatalyst);
$("closeKlineBtn").addEventListener("click", closeKline);
$("sectorsNav").addEventListener("click", (event) => {
  event.preventDefault();
  showSectorsPanel().then(() => {
    $("sectors").scrollIntoView({ behavior: "smooth", block: "start" });
  }).catch((error) => {
    $("reportText").textContent = `真实板块加载失败：${error.message}`;
  });
});
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

// 榜单筛选器
["filterConfidence", "filterStatus", "filterRisk"].forEach((id) => {
  const el = $(id);
  if (el) {
    el.addEventListener("change", () => {
      state.rankingFilter.confidence = $("filterConfidence") ? $("filterConfidence").value : "all";
      state.rankingFilter.status = $("filterStatus") ? $("filterStatus").value : "all";
      state.rankingFilter.riskLevel = $("filterRisk") ? $("filterRisk").value : "all";
      renderRanking(state.ranking ? state.ranking.items : []);
    });
  }
});
