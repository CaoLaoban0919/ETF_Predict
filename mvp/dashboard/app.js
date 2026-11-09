"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART_WIDTH = 960;
const CHART_HEIGHT = 360;
const CHART_PADDING = { top: 20, right: 24, bottom: 38, left: 64 };
const COLORS = ["#167d6c", "#d46a45", "#3b6f8f", "#b68a31", "#7b6295", "#8b9691"];
const FACTOR_LABELS = {
  momentum: "动量",
  trend: "趋势",
  low_volatility: "低波动",
};
const MARKET_COLUMNS = [
  ["date", "日期"],
  ["open", "开盘"],
  ["close", "收盘"],
  ["high", "最高"],
  ["low", "最低"],
  ["volume", "成交量"],
  ["amount", "成交额"],
  ["amplitude", "振幅"],
  ["change_pct", "涨跌幅"],
  ["change_amount", "涨跌额"],
  ["turnover_rate", "换手率"],
];

const state = {
  data: null,
  market: null,
  marketSummary: null,
  chartMode: "equity",
  chartGeometry: null,
};

const elements = {
  dashboard: document.querySelector("#dashboard"),
  loading: document.querySelector("#loadingState"),
  error: document.querySelector("#errorState"),
  errorMessage: document.querySelector("#errorMessage"),
  refresh: document.querySelector("#refreshButton"),
  retry: document.querySelector("#retryButton"),
  chart: document.querySelector("#performanceChart"),
  chartFrame: document.querySelector("#chartFrame"),
  chartTooltip: document.querySelector("#chartTooltip"),
  chartLegend: document.querySelector("#chartLegend"),
  symbolInput: document.querySelector("#symbolInput"),
  loadSymbol: document.querySelector("#loadSymbolButton"),
  saveRecord: document.querySelector("#saveRecordButton"),
  compareSymbol: document.querySelector("#compareSymbolInput"),
  compareButton: document.querySelector("#compareButton"),
  compareResult: document.querySelector("#marketCompareResult"),
  marketTable: document.querySelector("#marketTable"),
  marketRawJson: document.querySelector("#marketRawJson"),
  marketHistoryList: document.querySelector("#marketHistoryList"),
};

document.addEventListener("DOMContentLoaded", () => {
  elements.refresh.addEventListener("click", loadDashboard);
  elements.retry.addEventListener("click", loadDashboard);
  elements.loadSymbol.addEventListener("click", loadMarketHistory);
  elements.saveRecord.addEventListener("click", saveMarketRecord);
  elements.compareButton.addEventListener("click", compareMarketRecords);
  elements.symbolInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadMarketHistory();
    }
  });
  elements.compareSymbol.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      compareMarketRecords();
    }
  });
  document.querySelectorAll("[data-chart-mode]").forEach((button) => {
    button.addEventListener("click", () => selectChartMode(button.dataset.chartMode));
  });
  elements.chartFrame.addEventListener("pointermove", handleChartPointer);
  elements.chartFrame.addEventListener("pointerleave", hideChartTooltip);
  loadDashboard();
});

async function loadDashboard() {
  setView("loading");
  elements.refresh.disabled = true;
  const originalLabel = elements.refresh.textContent;
  elements.refresh.textContent = "刷新中...";
  try {
    const query = new URLSearchParams(window.location.search);
    const source = query.get("data") || "./data/dashboard_data.json";
    const separator = source.includes("?") ? "&" : "?";
    let payload;
    if (!query.get("data")) {
      // 数据刷新：按钮触发 Agent 重新生成 output，再用返回快照更新页面。
      const refreshResponse = await fetch(`/api/dashboard/refresh?v=${Date.now()}`, {
        method: "POST",
        cache: "no-store",
      });
      if (!refreshResponse.ok) {
        throw new Error(`刷新失败 HTTP ${refreshResponse.status}`);
      }
      const refreshPayload = await refreshResponse.json();
      payload = refreshPayload.dashboard;
    } else {
      const response = await fetch(`${source}${separator}v=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText || "data unavailable"}`);
      }
      payload = await response.json();
    }
    validatePayload(payload);
    state.data = payload;
    renderDashboard();
    setView("dashboard");
    loadMarketHistory();
    loadMarketRecords();
    elements.refresh.textContent = "已更新";
    window.setTimeout(() => {
      elements.refresh.textContent = originalLabel;
    }, 1600);
  } catch (error) {
    elements.errorMessage.textContent = error instanceof Error ? error.message : String(error);
    setView("error");
  } finally {
    elements.refresh.disabled = false;
    if (elements.refresh.textContent === "刷新中...") {
      elements.refresh.textContent = originalLabel;
    }
  }
}

async function loadMarketRecords() {
  try {
    const response = await fetch(`/api/market/records?v=${Date.now()}`, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    renderMarketRecords(Array.isArray(payload.records) ? payload.records : []);
  } catch (_error) {
    renderMarketRecords([]);
  }
}

async function loadMarketHistory() {
  const symbol = elements.symbolInput.value.trim();
  if (!symbol) return;
  elements.loadSymbol.disabled = true;
  elements.loadSymbol.textContent = "读取中...";
  try {
    const response = await fetch(`/api/market/etf/${encodeURIComponent(symbol)}?v=${Date.now()}`, {
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    state.market = payload.record || payload;
    state.marketSummary = payload.summary || null;
    renderMarket();
  } catch (error) {
    elements.marketTable.replaceChildren();
    elements.marketRawJson.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    elements.loadSymbol.disabled = false;
    elements.loadSymbol.textContent = "查看行情";
  }
}

async function saveMarketRecord() {
  const symbol = elements.symbolInput.value.trim();
  if (!symbol) return;
  elements.saveRecord.disabled = true;
  elements.saveRecord.textContent = "记录中...";
  try {
    const response = await fetch(`/api/market/records/${encodeURIComponent(symbol)}`, {
      method: "POST",
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    state.market = payload.record;
    state.marketSummary = null;
    renderMarket();
    renderMarketRecords(payload.history?.records || []);
    const compareInput = document.querySelector("#agentCompareSymbol");
    const question = document.querySelector("#agentQuestion");
    if (compareInput && question) {
      const compareSymbol = compareInput.value.trim();
      question.value = compareSymbol
        ? `请基于已记录的真实行情，对比 ${symbol} 和 ${compareSymbol} 的最新收盘、涨跌幅、成交额、换手率和可见风险。`
        : `请基于已记录的真实行情，分析 ${symbol} 的最新表现和风险。`;
      question.dispatchEvent(new Event("input", { bubbles: true }));
    }
    elements.saveRecord.textContent = "已记录";
    window.setTimeout(() => {
      elements.saveRecord.textContent = "记录当前数据";
    }, 1600);
  } catch (error) {
    elements.marketRawJson.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    elements.saveRecord.disabled = false;
    if (elements.saveRecord.textContent === "记录中...") {
      elements.saveRecord.textContent = "记录当前数据";
    }
  }
}

async function compareMarketRecords() {
  const current = elements.symbolInput.value.trim();
  const target = elements.compareSymbol.value.trim();
  if (!current || !target) return;
  elements.compareButton.disabled = true;
  elements.compareButton.textContent = "对比中...";
  try {
    const response = await fetch(
      `/api/market/compare/${encodeURIComponent(current)}/${encodeURIComponent(target)}?v=${Date.now()}`,
      { cache: "no-store" },
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    renderMarketComparison(payload);
    const agentCompare = document.querySelector("#agentCompareSymbol");
    const question = document.querySelector("#agentQuestion");
    if (agentCompare) agentCompare.value = target;
    if (question) {
      question.value = `请基于已保存记录，对比 ${current} 与 ${target} 的最新收盘、涨跌幅、成交额、换手率、波动和风险差异。`;
      question.dispatchEvent(new Event("input", { bubbles: true }));
    }
  } catch (error) {
    elements.compareResult.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    elements.compareButton.disabled = false;
    elements.compareButton.textContent = "对比当前代码";
  }
}

function renderMarket() {
  const payload = state.market;
  if (!payload) return;
  setText("marketSource", payload.source || "--");
  setText("marketPeriod", payload.period || "--");
  setText("marketAdjust", payload.adjust || "--");
  setText("marketCount", formatInteger(payload.count));
  setText("marketRange", `${formatDate(payload.first_date)} 至 ${formatDate(payload.last_date)}`);
  setText("marketFetchedAt", formatTimestamp(payload.fetched_at));
  elements.marketRawJson.textContent = JSON.stringify(payload.raw_payload || payload, null, 2);
  renderMarketTable(payload.rows || []);
}

function renderMarketTable(rows) {
  elements.marketTable.replaceChildren();
  const visibleRows = rows.slice().reverse();
  for (const item of visibleRows) {
    const row = document.createElement("tr");
    MARKET_COLUMNS.forEach(([key]) => {
      const cell = document.createElement("td");
      const value = item[key];
      if (key === "date") cell.textContent = formatDate(value);
      else if (key === "volume") cell.textContent = formatInteger(value);
      else if (["amplitude", "change_pct", "turnover_rate"].includes(key)) cell.textContent = `${formatNumber(value, 2)}%`;
      else if (key === "amount") cell.textContent = formatCurrency(value);
      else cell.textContent = formatNumber(value, 3);
      row.appendChild(cell);
    });
    elements.marketTable.appendChild(row);
  }
}

function renderMarketRecords(records) {
  elements.marketHistoryList.replaceChildren();
  const latest = [...records].reverse();
  if (!latest.length) {
    const empty = document.createElement("span");
    empty.className = "market-history-empty";
    empty.textContent = "暂无记录";
    elements.marketHistoryList.appendChild(empty);
    return;
  }
  for (const record of latest) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "market-history-item";
    const title = document.createElement("strong");
    title.textContent = `${record.symbol || "--"} · ${formatDate(record.last_date)}`;
    const meta = document.createElement("span");
    meta.textContent = `${formatTimestamp(record.fetched_at)} · 收盘 ${formatNumber(record.latest_row?.close, 3)} · 记录 ${formatInteger(record.count)}`;
    button.appendChild(title);
    button.appendChild(meta);
    button.addEventListener("click", () => {
      state.market = record;
      elements.symbolInput.value = record.symbol || elements.symbolInput.value;
      renderMarket();
    });
    elements.marketHistoryList.appendChild(button);
  }
}

function renderMarketComparison(payload) {
  elements.compareResult.replaceChildren();
  const cards = [
    payload.symbol_a,
    payload.symbol_b,
  ].filter(Boolean);
  const grid = document.createElement("div");
  grid.className = "compare-card-grid";
  cards.forEach((item) => {
    const card = document.createElement("div");
    card.className = "compare-card";
    const title = document.createElement("strong");
    title.textContent = item.symbol || "--";
    const latest = item.latest || {};
    const lines = [
      ["最新日期", item.last_date],
      ["收盘", formatNumber(latest.close, 3)],
      ["涨跌幅", `${formatNumber(latest.change_pct, 2)}%`],
      ["成交额", formatCurrency(latest.amount)],
      ["换手率", `${formatNumber(latest.turnover_rate, 2)}%`],
    ];
    card.appendChild(title);
    lines.forEach(([label, value]) => {
      const row = document.createElement("span");
      row.textContent = `${label}: ${value || "--"}`;
      card.appendChild(row);
    });
    grid.appendChild(card);
  });
  elements.compareResult.appendChild(grid);

  const diff = payload.comparison || {};
  const diffList = document.createElement("div");
  diffList.className = "compare-diff-list";
  [
    ["收盘差值", formatNumber(diff.latest_close_diff, 3)],
    ["涨跌幅差值", `${formatNumber(diff.latest_change_pct_diff, 2)}%`],
    ["换手率差值", `${formatNumber(diff.latest_turnover_rate_diff, 2)}%`],
    ["成交额差值", formatCurrency(diff.latest_amount_diff)],
  ].forEach(([label, value]) => {
    const item = document.createElement("span");
    item.textContent = `${label}: ${value}`;
    diffList.appendChild(item);
  });
  elements.compareResult.appendChild(diffList);
}

function validatePayload(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("回测数据格式无效");
  }
  if (!payload.meta || !payload.metrics || !payload.config) {
    throw new Error("回测数据缺少 meta、metrics 或 config");
  }
  if (!Array.isArray(payload.series) || payload.series.length === 0) {
    throw new Error("回测时间序列为空");
  }
  if (!Array.isArray(payload.current_allocation) || !Array.isArray(payload.recent_rebalances)) {
    throw new Error("仓位或调仓数据格式无效");
  }
}

function setView(view) {
  elements.loading.hidden = view !== "loading";
  elements.error.hidden = view !== "error";
  elements.dashboard.hidden = view !== "dashboard";
}

function renderDashboard() {
  renderHeader();
  renderMetrics();
  renderChart();
  renderAllocation();
  renderRebalances();
  renderConfig();
}

function renderHeader() {
  const { meta, metrics, config } = state.data;
  setText("periodLabel", `${formatDate(metrics.start_date)} 至 ${formatDate(metrics.end_date)} | ${metrics.observations} 个交易日`);
  setText("updatedAt", formatTimestamp(meta.generated_at));
  setText("dataSource", meta.data_source);
  document.querySelector("#dataSource").title = meta.data_source;
  setText("symbolUniverse", `${meta.symbols.length} 只 | ${meta.symbols.join(" / ")}`);
  setText("executionRule", `每 ${config.rebalance_frequency} 日调仓 | Top ${config.top_k} | T+1 执行`);

  const badge = document.querySelector("#environmentBadge");
  badge.textContent = meta.is_demo ? "演示数据" : "实盘数据源";
  badge.classList.toggle("live", !meta.is_demo);
  setText("allocationDate", formatDate(metrics.end_date));
  setText("footerNotice", meta.is_demo ? "演示数据结果不构成投资建议" : "历史回测结果不构成投资建议");
}

function renderMetrics() {
  const metrics = state.data.metrics;
  setMetric("totalReturn", formatPercent(metrics.total_return), metrics.total_return);
  setText("totalReturnMeta", `等权基准 ${formatPercent(metrics.benchmark_total_return)}`);

  setMetric("cagr", formatPercent(metrics.cagr), metrics.cagr);
  setText("cagrMeta", `年化波动 ${formatPercent(metrics.annualized_volatility)}`);

  setMetric("sharpe", formatNumber(metrics.sharpe, 2), metrics.sharpe - 1.0);
  setText("sharpeMeta", `无风险利率 ${formatPercent(state.data.config.risk_free_rate)}`);

  setMetric("maxDrawdown", formatPercent(metrics.max_drawdown), metrics.max_drawdown);
  setText("maxDrawdownMeta", `胜率 ${formatPercent(metrics.active_win_rate)}`);

  setMetric("transactionCost", formatPercent(-metrics.total_transaction_cost), -metrics.total_transaction_cost);
  setText("transactionCostMeta", `成交名义额 ${formatNumber(metrics.total_traded_notional, 1)}x`);

  setMetric("investedRatio", formatPercent(metrics.invested_days_ratio), metrics.invested_days_ratio - 0.5);
  setText("investedRatioMeta", `${metrics.rebalance_count} 次调仓 | ${metrics.execution_count} 次成交`);
}

function setMetric(id, text, direction) {
  const element = document.querySelector(`#${id}`);
  element.textContent = text;
  element.classList.remove("positive", "negative");
  if (direction > 0) element.classList.add("positive");
  if (direction < 0) element.classList.add("negative");
}

function selectChartMode(mode) {
  if (!state.data || !["equity", "drawdown"].includes(mode)) return;
  state.chartMode = mode;
  document.querySelectorAll("[data-chart-mode]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.chartMode === mode));
  });
  hideChartTooltip();
  renderChart();
}

function renderChart() {
  const svg = elements.chart;
  svg.replaceChildren();
  svg.setAttribute(
    "aria-label",
    state.chartMode === "equity" ? "策略净值与基准净值走势" : "策略历史回撤走势",
  );
  const data = state.data.series;
  const series = state.chartMode === "equity"
    ? [
        { key: "equity", label: "策略净值", color: "#167d6c" },
        { key: "benchmark", label: "等权基准", color: "#d46a45" },
      ]
    : [{ key: "drawdown", label: "策略回撤", color: "#bb4d4d", area: true }];

  const values = series.flatMap((item) => data.map((row) => Number(row[item.key]))).filter(Number.isFinite);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (state.chartMode === "drawdown") maximum = 0;
  if (minimum === maximum) {
    minimum -= 0.05;
    maximum += 0.05;
  }
  const padding = Math.max((maximum - minimum) * 0.08, 0.01);
  if (state.chartMode === "equity") {
    minimum -= padding;
    maximum += padding;
  } else {
    minimum -= padding * 0.25;
  }

  const plotWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const plotHeight = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  const xFor = (index) => CHART_PADDING.left + (index / Math.max(data.length - 1, 1)) * plotWidth;
  const yFor = (value) => CHART_PADDING.top + ((maximum - value) / (maximum - minimum)) * plotHeight;

  for (let tick = 0; tick < 5; tick += 1) {
    const ratio = tick / 4;
    const value = maximum - ratio * (maximum - minimum);
    const y = CHART_PADDING.top + ratio * plotHeight;
    svg.appendChild(createSvg("line", {
      x1: CHART_PADDING.left,
      y1: y,
      x2: CHART_WIDTH - CHART_PADDING.right,
      y2: y,
      class: "chart-grid-line",
    }));
    const label = createSvg("text", {
      x: CHART_PADDING.left - 10,
      y: y + 4,
      "text-anchor": "end",
      class: "chart-axis-label",
    });
    label.textContent = state.chartMode === "drawdown" ? formatPercent(value, 0) : formatNumber(value, 2);
    svg.appendChild(label);
  }

  const xTickCount = 5;
  for (let tick = 0; tick < xTickCount; tick += 1) {
    const index = Math.round((tick / (xTickCount - 1)) * (data.length - 1));
    const label = createSvg("text", {
      x: xFor(index),
      y: CHART_HEIGHT - 10,
      "text-anchor": tick === 0 ? "start" : tick === xTickCount - 1 ? "end" : "middle",
      class: "chart-axis-label",
    });
    label.textContent = compactDate(data[index].date);
    svg.appendChild(label);
  }

  for (const item of series) {
    const points = data.map((row, index) => [xFor(index), yFor(Number(row[item.key]))]);
    const pathData = points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
    if (item.area) {
      const baseY = yFor(0);
      const areaPath = `${pathData} L${points.at(-1)[0].toFixed(2)},${baseY.toFixed(2)} L${points[0][0].toFixed(2)},${baseY.toFixed(2)} Z`;
      svg.appendChild(createSvg("path", { d: areaPath, fill: item.color, class: "chart-area" }));
    }
    svg.appendChild(createSvg("path", {
      d: pathData,
      stroke: item.color,
      class: "chart-line",
    }));
  }

  const hoverGroup = createSvg("g", { visibility: "hidden" });
  const hoverLine = createSvg("line", {
    y1: CHART_PADDING.top,
    y2: CHART_HEIGHT - CHART_PADDING.bottom,
    class: "hover-line",
  });
  hoverGroup.appendChild(hoverLine);
  const hoverDots = series.map((item) => {
    const dot = createSvg("circle", { r: 5, fill: item.color, class: "hover-dot" });
    hoverGroup.appendChild(dot);
    return dot;
  });
  svg.appendChild(hoverGroup);

  state.chartGeometry = { data, series, xFor, yFor, hoverGroup, hoverLine, hoverDots };
  renderChartLegend(series);
}

function renderChartLegend(series) {
  elements.chartLegend.replaceChildren();
  for (const item of series) {
    const wrapper = document.createElement("span");
    wrapper.className = "legend-item";
    const line = document.createElement("span");
    line.className = "legend-line";
    line.style.background = item.color;
    const label = document.createElement("span");
    label.textContent = item.label;
    wrapper.append(line, label);
    elements.chartLegend.appendChild(wrapper);
  }
}

function handleChartPointer(event) {
  if (!state.chartGeometry) return;
  const geometry = state.chartGeometry;
  const bounds = elements.chart.getBoundingClientRect();
  const viewX = ((event.clientX - bounds.left) / bounds.width) * CHART_WIDTH;
  const plotWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const ratio = clamp((viewX - CHART_PADDING.left) / plotWidth, 0, 1);
  const index = Math.round(ratio * (geometry.data.length - 1));
  const row = geometry.data[index];
  const x = geometry.xFor(index);

  geometry.hoverGroup.setAttribute("visibility", "visible");
  geometry.hoverLine.setAttribute("x1", x);
  geometry.hoverLine.setAttribute("x2", x);
  geometry.series.forEach((item, itemIndex) => {
    geometry.hoverDots[itemIndex].setAttribute("cx", x);
    geometry.hoverDots[itemIndex].setAttribute("cy", geometry.yFor(Number(row[item.key])));
  });

  const tooltipRows = geometry.series.map((item) => {
    const value = state.chartMode === "drawdown"
      ? formatPercent(row[item.key])
      : formatNumber(row[item.key], 3);
    return `<span class="tooltip-row"><span>${item.label}</span><b>${value}</b></span>`;
  }).join("");
  elements.chartTooltip.innerHTML = `<strong>${formatDate(row.date)}</strong>${tooltipRows}`;
  elements.chartTooltip.hidden = false;
  const pixelX = (x / CHART_WIDTH) * bounds.width;
  const firstY = geometry.yFor(Number(row[geometry.series[0].key]));
  const pixelY = (firstY / CHART_HEIGHT) * bounds.height;
  elements.chartTooltip.style.left = `${clamp(pixelX, 84, bounds.width - 84)}px`;
  elements.chartTooltip.style.top = `${Math.max(pixelY, 78)}px`;
}

function hideChartTooltip() {
  elements.chartTooltip.hidden = true;
  if (state.chartGeometry) state.chartGeometry.hoverGroup.setAttribute("visibility", "hidden");
}

function renderAllocation() {
  const allocation = state.data.current_allocation;
  const donut = document.querySelector("#allocationDonut");
  const list = document.querySelector("#allocationList");
  list.replaceChildren();

  let cursor = 0;
  const segments = allocation.map((item, index) => {
    const start = cursor;
    cursor += item.weight * 100;
    return `${COLORS[index % COLORS.length]} ${start.toFixed(3)}% ${cursor.toFixed(3)}%`;
  });
  donut.style.background = `conic-gradient(${segments.join(",")})`;

  const cash = allocation.find((item) => item.symbol === "CASH")?.weight || 0;
  setText("exposureValue", formatPercent(1 - cash, 0));

  allocation.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    const swatch = document.createElement("span");
    swatch.className = "color-swatch";
    swatch.style.background = COLORS[index % COLORS.length];
    const symbol = document.createElement("span");
    symbol.className = "allocation-symbol";
    symbol.textContent = item.symbol;
    const track = document.createElement("span");
    track.className = "allocation-track";
    const fill = document.createElement("span");
    fill.className = "allocation-fill";
    fill.style.width = `${clamp(item.weight * 100, 0, 100)}%`;
    fill.style.background = COLORS[index % COLORS.length];
    track.appendChild(fill);
    const value = document.createElement("span");
    value.className = "allocation-weight";
    value.textContent = formatPercent(item.weight, 1);
    row.append(swatch, symbol, track, value);
    list.appendChild(row);
  });
}

function renderRebalances() {
  const tbody = document.querySelector("#rebalanceTable");
  tbody.replaceChildren();
  const events = state.data.recent_rebalances;
  setText("rebalanceCount", `${state.data.metrics.rebalance_count} 次调仓`);

  for (const event of events) {
    const selected = event.ranking.filter((item) => item.selected);
    const reference = selected[0] || event.ranking.find((item) => item.rank === 1) || null;
    const row = document.createElement("tr");
    appendCell(row, formatDate(event.date));

    const assetCell = document.createElement("td");
    const symbols = event.selected_symbols.length ? event.selected_symbols : ["CASH"];
    for (const symbol of symbols) {
      const tag = document.createElement("span");
      tag.className = `asset-tag${symbol === "CASH" ? " cash" : ""}`;
      tag.textContent = symbol;
      assetCell.appendChild(tag);
    }
    row.appendChild(assetCell);

    appendCell(row, reference ? formatNumber(reference.score, 3) : "--", "numeric-cell");
    appendCell(row, reference ? formatPercent(reference.momentum) : "--", "numeric-cell");
    appendCell(row, reference ? formatPercent(reference.trend) : "--", "numeric-cell");

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `decision-status ${selected.length ? "invested" : "cash"}`;
    status.textContent = selected.length ? "入选" : "风控空仓";
    statusCell.appendChild(status);
    row.appendChild(statusCell);
    tbody.appendChild(row);
  }
}

function renderConfig() {
  const config = state.data.config;
  const factorMix = document.querySelector("#factorMix");
  factorMix.replaceChildren();
  const weights = config.factor_weights;
  const total = Object.values(weights).reduce((sum, value) => sum + Number(value), 0);

  Object.entries(weights).forEach(([name, rawWeight], index) => {
    const weight = Number(rawWeight) / total;
    const item = document.createElement("div");
    item.className = "factor-item";
    const head = document.createElement("div");
    head.className = "factor-head";
    const label = document.createElement("span");
    label.textContent = FACTOR_LABELS[name] || name;
    const value = document.createElement("strong");
    value.textContent = formatPercent(weight, 0);
    head.append(label, value);
    const track = document.createElement("div");
    track.className = "factor-track";
    const fill = document.createElement("span");
    fill.className = "factor-fill";
    fill.style.width = `${weight * 100}%`;
    fill.style.background = COLORS[index % COLORS.length];
    track.appendChild(fill);
    item.append(head, track);
    factorMix.appendChild(item);
  });

  setText("rebalanceFrequency", `${config.rebalance_frequency} 个交易日`);
  setText("topK", `Top ${config.top_k}`);
  setText("commissionBps", `${formatNumber(config.commission_bps, 1)} bps / 边`);
  setText("trendFilter", config.require_uptrend ? "启用" : "关闭");
  setText("executionCount", `${state.data.metrics.execution_count} 次`);
}

function createSvg(tagName, attributes) {
  const element = document.createElementNS(SVG_NS, tagName);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  return element;
}

function appendCell(row, text, className = "") {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) cell.className = className;
  row.appendChild(cell);
}

function setText(id, value) {
  document.querySelector(`#${id}`).textContent = value;
}

function formatPercent(value, digits = 2) {
  if (!Number.isFinite(Number(value))) return "--";
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

function formatNumber(value, digits = 2) {
  if (!Number.isFinite(Number(value))) return "--";
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

function formatInteger(value) {
  if (!Number.isFinite(Number(value))) return "--";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function formatCurrency(value) {
  if (!Number.isFinite(Number(value))) return "--";
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatDate(value) {
  if (!value) return "--";
  const [year, month, day] = String(value).slice(0, 10).split("-");
  return `${year}/${month}/${day}`;
}

function compactDate(value) {
  const [, month, day] = String(value).slice(0, 10).split("-");
  return `${month}/${day}`;
}

function formatTimestamp(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}
