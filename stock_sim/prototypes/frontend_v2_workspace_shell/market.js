/* THROWAWAY PROTOTYPE — Market/Symbol Detail diagnostic context, issue #31.
 * The global shell is fixed to the #30 Journey Rail decision.
 * Only the local Market/Symbol Detail structure varies via ?variant=A|B|C.
 */

const marketVariants = [
  { key: "A", name: "Evidence Lens" },
  { key: "B", name: "Temporal Trace" },
  { key: "C", name: "Scenario Universe" },
];

const journeyStages = [
  ["策略库", "context retained"],
  ["场景实验室", "context retained"],
  ["诊断任务", "context retained"],
  ["运行监控", "active context"],
  ["证据与结论", "available"],
  ["系统健康", "available"],
];

const healthStates = {
  fresh: {
    label: "Fresh",
    tone: "healthy",
    age: "2.4 s",
    overall: "verified",
    message: "所有显示值来自当前 Strategy Run 的最新可靠 ViewState。",
    source: "Reference Market Path · snapshot batch 7ec31a:4412",
  },
  stale: {
    label: "Stale",
    tone: "stale",
    age: "48 s",
    overall: "degraded",
    message: "行情上下文已超过 15 s 阈值；保留最后可靠值，暂停形成新的证据判断。",
    source: "Last reliable snapshot · 13:29:12 · reconnecting",
  },
  disconnected: {
    label: "Disconnected",
    tone: "disconnected",
    age: "3 m 08 s",
    overall: "failed",
    message: "实时订阅已断开；历史证据仍可审阅，但当前价格、盘口与成交不再视为最新。",
    source: "Last reliable state retained · subscription unavailable",
  },
};

const universe = [
  {
    symbol: "600519.SH",
    name: "贵州茅台",
    price: 181.72,
    change: "+1.84%",
    signal: "Breakout",
    relevance: "High",
    position: "8.2%",
    execution: "−24 bp",
    health: "fresh",
    seed: 0,
  },
  {
    symbol: "000858.SZ",
    name: "五粮液",
    price: 146.38,
    change: "+0.62%",
    signal: "Watch",
    relevance: "Medium",
    position: "4.1%",
    execution: "−11 bp",
    health: "fresh",
    seed: 2,
  },
  {
    symbol: "600809.SH",
    name: "山西汾酒",
    price: 118.91,
    change: "−1.07%",
    signal: "Exit",
    relevance: "High",
    position: "0.0%",
    execution: "−37 bp",
    health: "stale",
    seed: 4,
  },
  {
    symbol: "000568.SZ",
    name: "泸州老窖",
    price: 92.44,
    change: "+0.18%",
    signal: "None",
    relevance: "Low",
    position: "0.0%",
    execution: "—",
    health: "fresh",
    seed: 6,
  },
  {
    symbol: "600702.SH",
    name: "舍得酒业",
    price: 67.28,
    change: "−2.31%",
    signal: "Rejected",
    relevance: "High",
    position: "0.0%",
    execution: "fill limit",
    health: "fresh",
    seed: 8,
  },
];

const urlParams = new URLSearchParams(window.location.search);
const requestedMarketVariant = (urlParams.get("variant") || "A").toUpperCase();
const requestedHealth = urlParams.get("health") || "fresh";
const requestedSymbol = urlParams.get("symbol") || universe[0].symbol;

const marketState = {
  variant: marketVariants.some((item) => item.key === requestedMarketVariant)
    ? requestedMarketVariant
    : "A",
  health: Object.hasOwn(healthStates, requestedHealth) ? requestedHealth : "fresh",
  density: urlParams.get("density") === "compact" ? "compact" : "comfortable",
  selectedSymbol: universe.some((item) => item.symbol === requestedSymbol)
    ? requestedSymbol
    : universe[0].symbol,
  evidenceDialogOpen: false,
};

const marketApp = document.querySelector("#market-app");
const marketOverlayRoot = document.querySelector("#market-overlay-root");

function selectedInstrument() {
  return universe.find((item) => item.symbol === marketState.selectedSymbol) || universe[0];
}

function activeHealth() {
  return healthStates[marketState.health];
}

function updateMarketUrl() {
  const next = new URLSearchParams();
  next.set("variant", marketState.variant);
  next.set("health", marketState.health);
  next.set("density", marketState.density);
  next.set("symbol", marketState.selectedSymbol);
  window.history.replaceState(null, "", `${window.location.pathname}?${next.toString()}`);
}

function marketTopbar() {
  const health = activeHealth();
  return `
    <header class="topbar">
      <div class="brand" aria-label="UTI Strategy Diagnostics">
        <div class="brand-mark" aria-hidden="true">U</div>
        <div class="brand-copy">
          <span class="brand-title">UTI Diagnostics</span>
          <span class="brand-subtitle">Research workspace</span>
        </div>
      </div>
      <div class="topbar-separator" aria-hidden="true"></div>
      <button class="context-switch" type="button" data-show-run-context>
        <span class="dot healthy"></span>
        <span class="context-switch-copy">
          <strong>Breakout v4.2 · 流动性压力</strong>
          <small>DGN-24-0719-A · Formal Diagnostic Campaign</small>
        </span>
        <span class="chevron" aria-hidden="true">⌄</span>
      </button>
      <div class="topbar-spacer"></div>
      <div class="status-cluster" aria-label="全局状态">
        <span class="status-chip healthy runtime"><span class="dot"></span>Runtime healthy</span>
        <span class="status-chip ${health.tone === "healthy" ? "healthy" : "degraded"}">
          <span class="dot"></span>${health.label} · ${health.age}
        </span>
        <button class="density-button" type="button" data-toggle-market-density>
          ${marketState.density === "compact" ? "紧凑" : "舒适"}
        </button>
      </div>
    </header>
  `;
}

function marketJourneyRail() {
  return `
    <nav class="journey-rail" aria-label="诊断旅程">
      <div class="rail-label">Diagnostic journey</div>
      <div class="journey-list">
        ${journeyStages
          .map(
            ([label, hint], index) => `
              <button class="journey-item ${index === 3 ? "active" : index < 3 ? "done" : ""}" type="button" data-journey-stage="${index}" ${index === 3 ? 'aria-current="page"' : ""}>
                <span class="journey-item-index">${index + 1}</span>
                <span class="journey-item-copy"><strong>${label}</strong><small>${hint}</small></span>
              </button>
            `,
          )
          .join("")}
      </div>
      <div class="rail-footer">
        <span class="prototype-only">Context page</span>
        <p>Market 与 Symbol Detail 从当前 Strategy Run 进入，不成为全局交易工作台。</p>
      </div>
    </nav>
  `;
}

function marketContextInspector() {
  const health = activeHealth();
  return `
    <aside class="context-inspector" aria-label="固定诊断上下文">
      <div class="inspector-head">
        <strong>固定诊断上下文</strong>
        <span class="badge accent">Pinned</span>
      </div>
      <dl class="context-definition">
        <div><dt>Strategy Under Test</dt><dd>Breakout v4.2 · 7ec31a</dd></div>
        <div><dt>Market Scenario</dt><dd>2021 Q1 / 流动性压力 × 1.8</dd></div>
        <div><dt>Strategy Run</dt><dd class="mono">DGN-24-0719-A</dd></div>
        <div><dt>Scenario Replica</dt><dd class="mono">LQ-08 · isolated sensitivity</dd></div>
        <div><dt>Simulation Time</dt><dd>Day 42 · 13:30</dd></div>
        <div><dt>ViewState</dt><dd><span class="${health.tone === "healthy" ? "positive" : "warning"}">${health.label} · ${health.age}</span><br><span class="muted">revision 4412</span></dd></div>
      </dl>
      <div class="context-note">
        所有订单、成交和持仓都是策略产生的只读诊断证据；没有主观手动订单能力。
      </div>
    </aside>
  `;
}

function healthSwitch() {
  return `
    <div class="health-switch" aria-label="原型数据健康状态">
      ${Object.entries(healthStates)
        .map(
          ([key, value]) => `
            <button class="${marketState.health === key ? "active" : ""}" type="button" data-health="${key}" aria-pressed="${marketState.health === key}">
              ${value.label}
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function freshnessBanner() {
  const health = activeHealth();
  return `
    <div class="freshness-banner ${health.tone}" role="status">
      <span class="dot ${health.tone === "healthy" ? "healthy" : "degraded"}"></span>
      <span><strong>${health.label} · ${health.age}</strong> — ${health.message}</span>
      <span class="freshness-source mono">${health.source}</span>
    </div>
  `;
}

function instrumentHeader(instrument) {
  const positive = !instrument.change.startsWith("−");
  return `
    <header class="instrument-header">
      <div class="instrument-title">
        <span class="eyebrow">Scenario context · Strategy Selection</span>
        <div class="instrument-title-row">
          <h1>${instrument.name}</h1>
          <span class="symbol">${instrument.symbol}</span>
          <span class="badge accent">${instrument.signal}</span>
        </div>
        <p>进入原因：10:30 Strategy Decision 触发突破信号；当前页面用于解释信号、执行与持仓影响，不用于发出交易指令。</p>
      </div>
      <div class="instrument-quote">
        <strong>${instrument.price.toFixed(2)}</strong>
        <span class="${positive ? "positive" : "danger"}">${instrument.change} · scenario path</span>
      </div>
    </header>
  `;
}

function priceSeries(instrument) {
  const base = instrument.price;
  const wave = [
    -4.4, -3.8, -4.1, -3.2, -2.9, -2.1, -2.6, -1.4, -0.8, -1.2, -0.3, 0.7,
    0.4, 1.3, 1.9, 1.2, 2.5, 2.2, 3.4, 3.9, 3.1, 4.2, 4.7, 4.1, 5.2, 4.8,
    5.7, 6.1,
  ];
  return wave.map((value, index) => base + value * 0.72 + Math.sin(index + instrument.seed) * 0.45);
}

function chartSvg(instrument, compact = false) {
  const values = priceSeries(instrument);
  const width = 820;
  const height = compact ? 245 : 350;
  const top = 36;
  const bottom = height - 30;
  const min = Math.min(...values) - 1.4;
  const max = Math.max(...values) + 1.4;
  const plotHeight = bottom - top;
  const xFor = (index) => 30 + index * ((width - 72) / (values.length - 1));
  const yFor = (value) => top + ((max - value) / (max - min)) * plotHeight;

  const candles = values
    .map((close, index) => {
      const open = close + Math.sin(index * 1.71 + instrument.seed) * 0.62;
      const high = Math.max(open, close) + 0.4 + (index % 3) * 0.08;
      const low = Math.min(open, close) - 0.42 - (index % 2) * 0.1;
      const x = xFor(index);
      const yOpen = yFor(open);
      const yClose = yFor(close);
      const bodyY = Math.min(yOpen, yClose);
      const bodyHeight = Math.max(2, Math.abs(yOpen - yClose));
      const className = close >= open ? "kline-candle-up" : "kline-candle-down";
      return `
        <line class="${className}" x1="${x.toFixed(1)}" y1="${yFor(high).toFixed(1)}" x2="${x.toFixed(1)}" y2="${yFor(low).toFixed(1)}" />
        <rect class="${className}" x="${(x - 4.3).toFixed(1)}" y="${bodyY.toFixed(1)}" width="8.6" height="${bodyHeight.toFixed(1)}" rx="1" />
      `;
    })
    .join("");

  const pricePath = values
    .map((value, index) => `${index === 0 ? "M" : "L"} ${xFor(index).toFixed(1)} ${yFor(value).toFixed(1)}`)
    .join(" ");

  const positionValues = values.map((_, index) => {
    if (index < 9) return min + 1.1;
    if (index < 20) return min + 2.2 + (index - 9) * 0.11;
    return min + 3.4 - (index - 20) * 0.08;
  });
  const positionPath = positionValues
    .map((value, index) => `${index === 0 ? "M" : "L"} ${xFor(index).toFixed(1)} ${yFor(value).toFixed(1)}`)
    .join(" ");

  const markers = [
    { index: 9, label: "DECIDE 10:30" },
    { index: 11, label: "FILL 10:32" },
    { index: 20, label: "REDUCE 13:00" },
  ]
    .map(({ index, label }, markerIndex) => {
      const x = xFor(index);
      const y = yFor(values[index]) - 15 - (markerIndex % 2) * 16;
      return `
        <line x1="${x.toFixed(1)}" y1="${(y + 9).toFixed(1)}" x2="${x.toFixed(1)}" y2="${yFor(values[index]).toFixed(1)}" stroke="var(--market-action)" stroke-dasharray="2 3" />
        <circle class="action-marker" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" />
        <text class="action-marker-text" x="${(x + 8).toFixed(1)}" y="${(y + 3).toFixed(1)}">${label}</text>
      `;
    })
    .join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${instrument.symbol} K 线与策略动作叠加图">
      <line class="kline-grid" x1="30" y1="${top}" x2="${width - 30}" y2="${top}" />
      <line class="kline-grid" x1="30" y1="${((top + bottom) / 2).toFixed(1)}" x2="${width - 30}" y2="${((top + bottom) / 2).toFixed(1)}" />
      <line class="kline-grid" x1="30" y1="${bottom}" x2="${width - 30}" y2="${bottom}" />
      ${candles}
      <path class="kline-price" d="${pricePath}" />
      <path class="kline-position" d="${positionPath}" />
      ${markers}
    </svg>
  `;
}

function chartBlock(instrument, className = "") {
  return `
    <div class="market-chart ${className} ${activeHealth().tone}">
      <div class="chart-legend">
        <span class="legend-item"><i class="legend-line price"></i>Reference Market Path</span>
        <span class="legend-item"><i class="legend-line"></i>Strategy actions</span>
        <span class="legend-item"><i class="legend-line position"></i>Position exposure</span>
      </div>
      ${chartSvg(instrument, className.includes("drawer-chart"))}
      <span class="chart-axis-note">Simulation Time · Day 42</span>
    </div>
  `;
}

function impactStrip(instrument) {
  return `
    <section class="impact-strip" aria-label="当前标的诊断影响">
      <div class="impact-cell"><span>Strategy position</span><strong>${instrument.position}</strong></div>
      <div class="impact-cell"><span>Execution erosion</span><strong class="warning">${instrument.execution}</strong></div>
      <div class="impact-cell"><span>Realized contribution</span><strong class="positive">+1.4%</strong></div>
      <div class="impact-cell"><span>Guardrail proximity</span><strong>72%</strong></div>
    </section>
  `;
}

function evidenceChain() {
  return `
    <div class="evidence-chain" aria-label="策略动作到持仓影响的证据链">
      <div class="chain-step">
        <span class="chain-index">1</span>
        <span class="chain-copy"><strong>Strategy Decision · 10:30</strong><span>突破过滤通过；Point-in-Time Data 截止 10:30。</span></span>
      </div>
      <div class="chain-step">
        <span class="chain-index">2</span>
        <span class="chain-copy"><strong>Signed Share Order</strong><span>+3,000 shares，经 Execution Policy 校验后于下一市场节点激活。</span></span>
      </div>
      <div class="chain-step">
        <span class="chain-index">3</span>
        <span class="chain-copy"><strong>Execution · 10:32</strong><span>2 笔成交，平均 178.44；滑点高于请求假设 24 bp。</span></span>
      </div>
      <div class="chain-step">
        <span class="chain-index">4</span>
        <span class="chain-copy"><strong>Position impact</strong><span>组合暴露 +3.2 pp；对本 replica 收益贡献 +1.4%。</span></span>
      </div>
    </div>
  `;
}

function microstructureSummary() {
  return `
    <section class="microstructure">
      <div class="micro-block">
        <div class="market-section-head"><h3>盘口摘要</h3><span>snapshot-derived · 2.4 s</span></div>
        <table class="book-table" aria-label="五档盘口摘要">
          <thead><tr><th>Side</th><th>Price</th><th>Qty</th></tr></thead>
          <tbody>
            <tr><td class="ask">Ask 1</td><td>181.76</td><td>8,900</td></tr>
            <tr><td class="ask">Ask 2</td><td>181.81</td><td>12,300</td></tr>
            <tr><td class="bid">Bid 1</td><td>181.69</td><td>10,100</td></tr>
            <tr><td class="bid">Bid 2</td><td>181.64</td><td>15,800</td></tr>
          </tbody>
        </table>
      </div>
      <div class="micro-block">
        <div class="market-section-head"><h3>最近成交与策略关联</h3><span>runtime trade log</span></div>
        <table class="trade-table" aria-label="最近成交">
          <thead><tr><th>Time</th><th>Price</th><th>Qty</th><th>Evidence link</th></tr></thead>
          <tbody>
            <tr><td>13:29:58</td><td>181.72</td><td>400</td><td>market only</td></tr>
            <tr><td>13:29:41</td><td>181.70</td><td>1,200</td><td>market only</td></tr>
            <tr class="strategy-linked"><td>10:32:04</td><td>178.44</td><td>1,800</td><td>Strategy Run fill</td></tr>
            <tr class="strategy-linked"><td>10:31:48</td><td>178.42</td><td>1,200</td><td>Strategy Run fill</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function removedCapabilities() {
  return `
    <div class="removed-capabilities">
      <strong>明确删除，不迁移</strong>
      <span>Create Instrument、Buy/Sell、手动改单/撤单、以 watchlist 作为产品主导航、独立账户/订单工作台。</span>
    </div>
  `;
}

function progressiveTrigger(label = "展开完整盘口、逐笔成交与数据出处") {
  return `
    <button class="progressive-trigger" type="button" data-open-market-evidence>
      <span><strong>${label}</strong><br>默认只显示与当前研究问题相关的摘要</span>
      <span aria-hidden="true">↗</span>
    </button>
  `;
}

function variantA(instrument) {
  return `
    <div class="lens-layout">
      <div class="lens-primary">
        <section>
          <div class="market-section-head"><h2>价格路径与策略动作</h2><span>1m · 120 bars · overlays on</span></div>
          ${chartBlock(instrument)}
        </section>
        ${impactStrip(instrument)}
        <section class="market-panel">
          ${microstructureSummary()}
          ${progressiveTrigger()}
        </section>
      </div>
      <aside class="lens-rail">
        <section class="why-symbol">
          <span class="eyebrow">Why this symbol?</span>
          <p>它由当前 Strategy Under Test 从 Market Scenario 的 Eligible Universe 中选择；不是研究者自选股。</p>
          <span><span class="badge accent">Strategy Selection</span> <span class="badge">LQ-08</span></span>
        </section>
        <section>
          <div class="market-section-head"><h2>证据链</h2><span>traceable</span></div>
          ${evidenceChain()}
        </section>
        ${removedCapabilities()}
      </aside>
    </div>
  `;
}

function traceBoard(instrument) {
  return `
    <section class="trace-board">
      <div class="trace-chart ${activeHealth().tone}">
        ${chartSvg(instrument, false)}
      </div>
      <div class="trace-lanes">
        <div class="trace-lane">
          <div class="trace-lane-label">Strategy actions</div>
          <div class="trace-lane-track">
            <span class="trace-event" style="--event-left: 31%; --event-color: var(--market-action)"><strong>Decision +3,000</strong><span>10:30</span></span>
            <span class="trace-event" style="--event-left: 70%; --event-color: var(--market-action)"><strong>Reduce −1,000</strong><span>13:00</span></span>
          </div>
        </div>
        <div class="trace-lane">
          <div class="trace-lane-label">Execution</div>
          <div class="trace-lane-track">
            <span class="trace-event" style="--event-left: 36%; --event-color: var(--amber)"><strong>2 fills · 178.44</strong><span>−24 bp</span></span>
          </div>
        </div>
        <div class="trace-lane">
          <div class="trace-lane-label">Position impact</div>
          <div class="trace-lane-track">
            <span class="trace-event" style="--event-left: 40%; --event-color: var(--market-position)"><strong>Exposure +3.2 pp</strong><span>P&L +1.4%</span></span>
          </div>
        </div>
        <div class="trace-lane">
          <div class="trace-lane-label">Health</div>
          <div class="trace-lane-track">
            <span class="trace-event" style="--event-left: 55%; --event-color: var(--green)"><strong>Manifest verified</strong><span>12:30</span></span>
          </div>
        </div>
      </div>
      <div class="trace-time-axis"><span>09:30</span><span>10:30</span><span>11:30</span><span>13:00</span><span>15:00</span></div>
    </section>
  `;
}

function variantB(instrument) {
  return `
    <div class="trace-layout">
      <header class="trace-header">
        <div class="trace-question">
          <span class="eyebrow">Temporal diagnostic question</span>
          <strong>这次突破信号如何变成仓位与执行侵蚀？</strong>
          <span>以 Simulation Time 对齐市场路径、Strategy Decision、订单激活、成交与持仓影响。</span>
        </div>
        <button class="btn primary" type="button" data-open-market-evidence>检查 10:30–10:33 →</button>
      </header>
      ${traceBoard(instrument)}
      <div class="trace-detail-strip">
        <div>${impactStrip(instrument)}</div>
        <div>
          <div class="market-section-head"><h2>当前因果链</h2><span>4 linked records</span></div>
          ${evidenceChain()}
        </div>
      </div>
      <section class="market-panel">
        ${progressiveTrigger("按时间点展开盘口与逐笔成交")}
      </section>
      ${removedCapabilities()}
    </div>
  `;
}

function universeTable(instrument) {
  return `
    <section class="universe-panel">
      <header class="universe-head">
        <strong>Scenario Eligible Universe</strong>
        <span>42 symbols · 7 Strategy Selections · 按诊断相关性排序，不是 watchlist</span>
      </header>
      <table class="compare-table" aria-label="场景标的诊断比较">
        <thead>
          <tr><th>Symbol</th><th>Signal</th><th>Position</th><th>Exec.</th><th>Health</th></tr>
        </thead>
        <tbody>
          ${universe
            .map(
              (item) => `
                <tr data-symbol="${item.symbol}" class="${item.symbol === instrument.symbol ? "selected" : ""}" tabindex="0" aria-selected="${item.symbol === instrument.symbol}">
                  <td><strong>${item.name}</strong><span>${item.symbol} · ${item.change}</span></td>
                  <td><span class="context-score ${item.relevance === "High" ? "signal" : ""}">${item.signal.slice(0, 3)}</span></td>
                  <td>${item.position}</td>
                  <td>${item.execution}</td>
                  <td><span class="${item.health === "fresh" ? "positive" : "warning"}">${item.health}</span></td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
      <button class="progressive-trigger" type="button" data-open-market-evidence>
        <span><strong>查看比较口径与所有 42 个标的</strong><br>当前列表只保留与研究问题相关的行</span><span>↗</span>
      </button>
    </section>
  `;
}

function variantC(instrument) {
  return `
    <div class="compare-layout">
      ${universeTable(instrument)}
      <section class="symbol-drawer">
        <div>
          <div class="market-section-head"><h2>${instrument.name} · 诊断摘要</h2><span>${instrument.symbol}</span></div>
          ${chartBlock(instrument, "drawer-chart")}
        </div>
        <div class="drawer-context">
          <div><span>Strategy signal</span><strong>${instrument.signal}</strong></div>
          <div><span>Position</span><strong>${instrument.position}</strong></div>
          <div><span>Execution</span><strong>${instrument.execution}</strong></div>
        </div>
        <section>
          <div class="market-section-head"><h2>证据链</h2><span>selected symbol only</span></div>
          ${evidenceChain()}
        </section>
        ${removedCapabilities()}
      </section>
    </div>
  `;
}

function marketSwitcher() {
  const variant = marketVariants.find((item) => item.key === marketState.variant);
  return `
    <aside class="prototype-switcher market-switcher" aria-label="Market 原型方案切换器">
      <button type="button" data-cycle-market-variant="-1" aria-label="上一个 Market 方案">←</button>
      <div class="switcher-copy">
        <span>
          <strong>${variant.key} — ${variant.name}</strong>
          <span>${selectedInstrument().symbol} · ${marketState.density}</span>
        </span>
        <span class="switcher-health">${activeHealth().label} · ${activeHealth().age}</span>
      </div>
      <button type="button" data-cycle-market-variant="1" aria-label="下一个 Market 方案">→</button>
    </aside>
  `;
}

function evidenceDialog() {
  if (!marketState.evidenceDialogOpen) {
    marketOverlayRoot.innerHTML = "";
    return;
  }
  const instrument = selectedInstrument();
  marketOverlayRoot.innerHTML = `
    <div class="evidence-dialog-backdrop" data-evidence-backdrop>
      <section class="evidence-dialog" role="dialog" aria-modal="true" aria-labelledby="evidence-dialog-title" data-entering="true">
        <header class="evidence-dialog-head">
          <div>
            <span class="prototype-only">Read-only diagnostic evidence</span>
            <h2 id="evidence-dialog-title">${instrument.name} · 市场微观结构与执行证据</h2>
            <p>Simulation Time 10:30–10:33 · Strategy Run DGN-24-0719-A · Scenario Replica LQ-08</p>
          </div>
          <button class="icon-button" type="button" data-close-market-evidence aria-label="关闭证据详情">×</button>
        </header>
        <div class="evidence-dialog-body">
          <section class="evidence-dialog-section">
            <div class="market-section-head"><h3>五档盘口</h3><span>snapshot-derived</span></div>
            <table class="book-table">
              <thead><tr><th>Side</th><th>Price</th><th>Qty</th></tr></thead>
              <tbody>
                <tr><td class="ask">Ask 1</td><td>178.47</td><td>8,900</td></tr>
                <tr><td class="ask">Ask 2</td><td>178.52</td><td>12,300</td></tr>
                <tr><td class="ask">Ask 3</td><td>178.58</td><td>6,400</td></tr>
                <tr><td class="bid">Bid 1</td><td>178.42</td><td>10,100</td></tr>
                <tr><td class="bid">Bid 2</td><td>178.37</td><td>15,800</td></tr>
                <tr><td class="bid">Bid 3</td><td>178.31</td><td>9,600</td></tr>
              </tbody>
            </table>
          </section>
          <section class="evidence-dialog-section">
            <div class="market-section-head"><h3>策略动作与成交关联</h3><span>runtime trade log</span></div>
            <table class="trade-table">
              <thead><tr><th>Time</th><th>Record</th><th>Qty</th><th>Price / result</th></tr></thead>
              <tbody>
                <tr class="strategy-linked"><td>10:30:00</td><td>Strategy Decision</td><td>+3,000</td><td>activation 10:31</td></tr>
                <tr><td>10:31:00</td><td>Order activated</td><td>3,000</td><td>limit 178.48</td></tr>
                <tr class="strategy-linked"><td>10:31:48</td><td>Trade</td><td>1,200</td><td>178.42</td></tr>
                <tr class="strategy-linked"><td>10:32:04</td><td>Trade</td><td>1,800</td><td>178.44</td></tr>
                <tr><td>10:33:00</td><td>Position impact</td><td>3,000</td><td>exposure +3.2 pp</td></tr>
              </tbody>
            </table>
          </section>
        </div>
        <footer class="evidence-dialog-foot">
          数据出处、authoritative 状态、freshness 与关联 ID 始终可见；此对话框没有任何下单或订单修改控件。
        </footer>
      </section>
    </div>
  `;
  window.requestAnimationFrame(() => {
    marketOverlayRoot.querySelector(".evidence-dialog")?.setAttribute("data-entering", "false");
    marketOverlayRoot.querySelector("[data-close-market-evidence]")?.focus();
  });
}

function runContextDialog() {
  marketState.evidenceDialogOpen = true;
  evidenceDialog();
  bindEvidenceDialog();
}

function renderMarket() {
  const instrument = selectedInstrument();
  const renderers = { A: variantA, B: variantB, C: variantC };
  marketApp.innerHTML = `
    <div class="market-prototype" data-market-variant="${marketState.variant}" data-market-density="${marketState.density}" data-market-health="${marketState.health}">
      ${marketTopbar()}
      <div class="market-shell">
        ${marketJourneyRail()}
        <main class="market-workspace">
          <div class="market-breadcrumb">
            <strong>DGN-24-0719-A</strong><span>›</span><span>运行监控</span><span>›</span><span>Market context</span><span>›</span><span>${instrument.symbol}</span>
          </div>
          <div class="market-toolbar">
            <div class="market-toolbar-copy">
              <strong>Market / Symbol Detail · 当前 Strategy Run 的诊断上下文</strong>
              <span>原型状态切换只改变 ViewState，不连接真实 runtime。</span>
            </div>
            ${healthSwitch()}
          </div>
          ${freshnessBanner()}
          ${instrumentHeader(instrument)}
          ${renderers[marketState.variant](instrument)}
        </main>
        ${marketContextInspector()}
      </div>
      ${marketSwitcher()}
    </div>
  `;
  evidenceDialog();
  bindMarketInteractions();
  updateMarketUrl();
}

function bindMarketInteractions() {
  document.querySelectorAll("[data-health]").forEach((button) => {
    button.addEventListener("click", () => {
      marketState.health = button.dataset.health;
      renderMarket();
    });
  });

  document.querySelector("[data-toggle-market-density]")?.addEventListener("click", () => {
    marketState.density = marketState.density === "compact" ? "comfortable" : "compact";
    renderMarket();
  });

  document.querySelectorAll("[data-cycle-market-variant]").forEach((button) => {
    button.addEventListener("click", () => cycleMarketVariant(Number(button.dataset.cycleMarketVariant)));
  });

  document.querySelectorAll("[data-open-market-evidence]").forEach((button) => {
    button.addEventListener("click", () => {
      marketState.evidenceDialogOpen = true;
      evidenceDialog();
      bindEvidenceDialog();
    });
  });

  document.querySelector("[data-show-run-context]")?.addEventListener("click", runContextDialog);

  document.querySelectorAll("[data-symbol]").forEach((row) => {
    const choose = () => {
      marketState.selectedSymbol = row.dataset.symbol;
      renderMarket();
    };
    row.addEventListener("click", choose);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
  });
}

function bindEvidenceDialog() {
  marketOverlayRoot.querySelector("[data-close-market-evidence]")?.addEventListener("click", closeEvidenceDialog);
  marketOverlayRoot.querySelector("[data-evidence-backdrop]")?.addEventListener("click", (event) => {
    if (event.target.matches("[data-evidence-backdrop]")) closeEvidenceDialog();
  });
}

function closeEvidenceDialog() {
  marketState.evidenceDialogOpen = false;
  evidenceDialog();
  document.querySelector("[data-open-market-evidence]")?.focus();
}

function cycleMarketVariant(direction) {
  const index = marketVariants.findIndex((item) => item.key === marketState.variant);
  marketState.variant =
    marketVariants[(index + direction + marketVariants.length) % marketVariants.length].key;
  renderMarket();
}

window.addEventListener("keydown", (event) => {
  const target = event.target;
  const editable =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    target?.isContentEditable;

  if (event.key === "Escape" && marketState.evidenceDialogOpen) {
    event.preventDefault();
    closeEvidenceDialog();
    return;
  }
  if (editable || marketState.evidenceDialogOpen) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    cycleMarketVariant(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    cycleMarketVariant(1);
  }
});

renderMarket();
