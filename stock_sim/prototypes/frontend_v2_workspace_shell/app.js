/* THROWAWAY PROTOTYPE — Frontend V2 workspace shell, GitHub issue #30.
 * Three variants, switchable via ?variant=, on a standalone prototype route.
 */

const variants = [
  { key: "A", name: "Journey Rail" },
  { key: "B", name: "Focus Ribbon" },
  { key: "C", name: "Research Chronicle" },
];

const journey = [
  { id: "strategy", label: "策略库", short: "Strategy Library" },
  { id: "scenario", label: "场景实验室", short: "Scenario Lab" },
  { id: "tasks", label: "诊断任务", short: "Diagnostic Tasks" },
  { id: "monitor", label: "运行监控", short: "Run Monitoring" },
  { id: "evidence", label: "证据与结论", short: "Evidence & Findings" },
  { id: "health", label: "系统健康", short: "System Health" },
];

const tasks = [
  {
    id: "breakout-liquidity",
    name: "Breakout v4.2 · 流动性压力",
    shortName: "Breakout v4.2",
    strategy: "CN Breakout",
    strategyVersion: "v4.2 · 7ec31a",
    scenario: "2021 Q1 / 流动性压力 × 1.8",
    recipe: "SR-018 · v3",
    recipeState: "Approved · immutable",
    runId: "DGN-24-0719-A",
    type: "Formal Diagnostic Campaign",
    status: "running",
    statusLabel: "运行中",
    progress: 75,
    stage: 3,
    replicas: "18 / 24",
    simulationTime: "Day 42 · 13:30",
    freshness: "2.4 s",
    manifest: "rmf_7ec31a…b882",
    guardrail: "GP-BREAKOUT-04",
    alerts: 2,
    evidence: 11,
    updated: "刚刚",
  },
  {
    id: "mean-reversion-sweep",
    name: "Mean Reversion v2.8 · 波动率扫描",
    shortName: "Mean Reversion v2.8",
    strategy: "Mean Reversion",
    strategyVersion: "v2.8 · a901fd",
    scenario: "2018 H2 / 波动率 0.8–2.0",
    recipe: "SR-011 · v6",
    recipeState: "Approved · immutable",
    runId: "DGN-24-0718-C",
    type: "Formal Diagnostic Campaign",
    status: "queued",
    statusLabel: "待启动",
    progress: 0,
    stage: 2,
    replicas: "0 / 30",
    simulationTime: "尚未开始",
    freshness: "manifest ready",
    manifest: "rmf_a901fd…09dd",
    guardrail: "GP-MR-02",
    alerts: 0,
    evidence: 0,
    updated: "12 分钟前",
  },
  {
    id: "momentum-gap",
    name: "Momentum v3.1 · 跳空恢复",
    shortName: "Momentum v3.1",
    strategy: "Sector Momentum",
    strategyVersion: "v3.1 · c4217e",
    scenario: "2020 Q1 / 跳空与恢复",
    recipe: "SR-006 · v2",
    recipeState: "Approved · immutable",
    runId: "DGN-24-0715-B",
    type: "Formal Diagnostic Campaign",
    status: "completed",
    statusLabel: "已完成",
    progress: 100,
    stage: 4,
    replicas: "24 / 24",
    simulationTime: "Day 60 · close",
    freshness: "sealed",
    manifest: "rmf_c4217e…6ac0",
    guardrail: "GP-MOM-03",
    alerts: 1,
    evidence: 18,
    updated: "2 天前",
  },
];

const stageBriefs = [
  {
    kicker: "01 · Strategy under test",
    title: "确认要诊断的策略版本",
    lede:
      "从版本、参数变化与 Strategy Guardrail Profile 出发，而不是从账户或行情面板出发。",
    next: "带入场景实验室",
  },
  {
    kicker: "02 · Market scenario",
    title: "批准可复现的场景配方",
    lede:
      "AI 只能起草；Recipe Validator 通过后仍需研究者明确批准，批准版本不可变。",
    next: "组装诊断任务",
  },
  {
    kicker: "03 · Campaign design",
    title: "让诊断结构先于运行参数",
    lede:
      "Formal Diagnostic Campaign 明确包含基线、孤立敏感性与复合压力三层，Quick Experiment 不冒充正式诊断。",
    next: "进入运行监控",
  },
  {
    kicker: "04 · Live campaign",
    title: "观察实验，而不是操纵市场",
    lede:
      "进度、异常和数据健康围绕当前 Strategy Run 组织。行情、账户、持仓、订单和成交仅是只读证据上下文。",
    next: "审阅证据与结论",
  },
  {
    kicker: "05 · Evidence review",
    title: "从可追溯证据形成诊断结论",
    lede:
      "收益风险、交易行为、执行侵蚀和环境敏感性并列呈现；不存在掩盖权衡的万能分数。",
    next: "检查系统健康",
  },
  {
    kicker: "06 · Operational confidence",
    title: "确认结论所依赖的系统健康",
    lede:
      "数据 freshness、任务恢复、事件延迟和证据完整性是结论可信度的一部分，而不是另一个运维面板孤岛。",
    next: "返回策略库",
  },
];

const params = new URLSearchParams(window.location.search);
const requestedVariant = (params.get("variant") || "A").toUpperCase();
const initialTask = tasks.find((task) => task.id === params.get("task")) || tasks[0];
const requestedStage = Number.parseInt(params.get("stage") || "", 10);

const state = {
  variant: variants.some((variant) => variant.key === requestedVariant)
    ? requestedVariant
    : "A",
  taskId: initialTask.id,
  stage:
    Number.isInteger(requestedStage) && requestedStage >= 0 && requestedStage < journey.length
      ? requestedStage
      : initialTask.stage,
  density: params.get("density") === "compact" ? "compact" : "comfortable",
  taskModalOpen: false,
};

const app = document.querySelector("#app");
const overlayRoot = document.querySelector("#overlay-root");
const isPrototype =
  ["127.0.0.1", "localhost"].includes(window.location.hostname) ||
  window.location.pathname.includes("frontend_v2_workspace_shell");

function currentTask() {
  return tasks.find((task) => task.id === state.taskId) || tasks[0];
}

function stageClass(task, index) {
  if (index === state.stage) return "active";
  if (index < task.stage || task.status === "completed") return "done";
  return "";
}

function statusTone(task) {
  if (task.status === "running") return "accent";
  if (task.status === "queued") return "warning";
  return "";
}

function updateUrl() {
  const next = new URLSearchParams(window.location.search);
  next.set("variant", state.variant);
  next.set("task", state.taskId);
  next.set("stage", String(state.stage));
  next.set("density", state.density);
  window.history.replaceState(null, "", `${window.location.pathname}?${next.toString()}`);
}

function topbar(task) {
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
      <button class="context-switch" type="button" data-open-task-switcher aria-haspopup="dialog">
        <span class="dot ${task.status === "running" ? "healthy" : "degraded"}"></span>
        <span class="context-switch-copy">
          <strong>${task.name}</strong>
          <small>${task.runId} · ${task.type}</small>
        </span>
        <span class="chevron" aria-hidden="true">⌄</span>
      </button>
      <div class="topbar-spacer"></div>
      <div class="status-cluster" aria-label="全局状态">
        <span class="status-chip healthy runtime"><span class="dot"></span>Runtime healthy</span>
        <span class="status-chip ${task.status === "running" ? "healthy" : "degraded"}">
          <span class="dot"></span>${task.freshness}
        </span>
        <button class="density-button" type="button" data-toggle-density title="切换信息密度">
          ${state.density === "compact" ? "紧凑" : "舒适"}
        </button>
      </div>
    </header>
  `;
}

function journeyButtons(mode, task) {
  return journey
    .map((item, index) => {
      const current = index === state.stage ? 'aria-current="page"' : "";
      if (mode === "rail") {
        const hint =
          index === task.stage && task.status === "running"
            ? `${task.progress}% · active`
            : index < task.stage || task.status === "completed"
              ? "context retained"
              : "available";
        return `
          <button class="journey-item ${stageClass(task, index)}" type="button" data-stage="${index}" ${current}>
            <span class="journey-item-index">${index + 1}</span>
            <span class="journey-item-copy">
              <strong>${item.label}</strong>
              <small>${hint}</small>
            </span>
          </button>
        `;
      }
      if (mode === "ribbon") {
        return `
          <button class="ribbon-step ${stageClass(task, index)}" type="button" data-stage="${index}" ${current}>
            <span>0${index + 1}</span>
            <strong>${item.label}</strong>
          </button>
        `;
      }
      return `
        <button class="${index === state.stage ? "active" : ""}" type="button" data-stage="${index}" ${current}>
          <span>0${index + 1}</span>
          <strong>${item.label}</strong>
        </button>
      `;
    })
    .join("");
}

function breadcrumbs(task) {
  return `
    <div class="breadcrumbs" aria-label="当前诊断上下文">
      <strong>${task.strategyVersion}</strong>
      <span>›</span>
      <span>${task.recipe}</span>
      <span>›</span>
      <span>${task.runId}</span>
      <span>›</span>
      <span>${journey[state.stage].label}</span>
    </div>
  `;
}

function metricRow(task) {
  return `
    <section class="metric-row" aria-label="诊断任务摘要">
      <div class="metric"><span>Scenario replicas</span><strong>${task.replicas}</strong></div>
      <div class="metric"><span>Simulation time</span><strong>${task.simulationTime}</strong></div>
      <div class="metric"><span>Guardrail signals</span><strong class="${task.alerts ? "warning" : "positive"}">${task.alerts}</strong></div>
      <div class="metric"><span>Evidence items</span><strong>${task.evidence}</strong></div>
    </section>
  `;
}

function campaignLayers(task) {
  return `
    <section>
      <div class="focus-section-head">
        <h2>Formal Diagnostic Campaign</h2>
        <span class="badge ${statusTone(task)}">${task.statusLabel}</span>
      </div>
      <div class="stage-grid">
        <article class="stage-cell" style="--cell-color: var(--green)">
          <div class="stage-cell-head"><h3>Baseline</h3><span class="badge">8 / 8</span></div>
          <div>
            <p>未变换历史片段；执行条件作为控制组固定。</p>
            <div class="thin-progress" style="--progress: 100%"><span></span></div>
          </div>
        </article>
        <article class="stage-cell" style="--cell-color: var(--accent)">
          <div class="stage-cell-head"><h3>Isolated sensitivity</h3><span class="badge accent">10 / 12</span></div>
          <div>
            <p>单独扫描流动性与滑点参数，寻找 Sensitivity Breakpoint。</p>
            <div class="thin-progress" style="--progress: 83%"><span></span></div>
          </div>
        </article>
        <article class="stage-cell" style="--cell-color: var(--amber)">
          <div class="stage-cell-head"><h3>Compound stress</h3><span class="badge warning">0 / 4</span></div>
          <div>
            <p>待孤立扫描完成后进入复合压力，不用于单因果归因。</p>
            <div class="thin-progress" style="--progress: 0%"><span></span></div>
          </div>
        </article>
      </div>
    </section>
  `;
}

function recentEvents() {
  return `
    <section>
      <div class="focus-section-head">
        <h2>需要解释的信号</h2>
        <button class="link-button" type="button" data-stage="4">查看全部证据 →</button>
      </div>
      <div class="event-list">
        <div class="event-row">
          <span class="event-time">13:30:00</span>
          <span class="event-copy">
            <strong>成交率在流动性 × 1.6 后快速下降</strong>
            <span>隔离扫描 replica LQ-08；与基线差异 −18.4 pp。</span>
          </span>
          <span class="badge warning">Breakpoint</span>
        </div>
        <div class="event-row">
          <span class="event-time">13:00:00</span>
          <span class="event-copy">
            <strong>账户利用率触及策略 Guardrail</strong>
            <span>只读账户上下文；关联 9 个策略动作和 7 笔成交证据。</span>
          </span>
          <span class="badge">Context</span>
        </div>
        <div class="event-row">
          <span class="event-time">12:30:00</span>
          <span class="event-copy">
            <strong>Reference Market Path checksum 已验证</strong>
            <span>所有可比 Scenario Replica 继续读取同一物化路径。</span>
          </span>
          <span class="badge accent">Verified</span>
        </div>
      </div>
    </section>
  `;
}

function strategyWorkspace(task) {
  return `
    ${metricRow(task)}
    <section class="next-action">
      <div class="next-action-copy">
        <span class="eyebrow">Selected Strategy Under Test</span>
        <strong>${task.strategyVersion}</strong>
        <p>版本内容固定；参数差异与上一个批准版本可追溯。Guardrail Profile 为 ${task.guardrail}，不被跨策略单一分数替代。</p>
      </div>
      <div><span class="badge accent">Validated</span> <span class="badge">PTrade surface v1</span></div>
    </section>
    ${eventsForStage(0)}
  `;
}

function scenarioWorkspace(task) {
  return `
    <section>
      <div class="focus-section-head"><h2>Scenario Recipe approval path</h2><span class="badge accent">${task.recipe}</span></div>
      <div class="stage-grid">
        <article class="stage-cell" style="--cell-color: var(--blue)">
          <div class="stage-cell-head"><h3>Draft</h3><span class="badge">AI assisted</span></div>
          <p>意图转成结构化 draft；此阶段不可运行。</p>
        </article>
        <article class="stage-cell" style="--cell-color: var(--green)">
          <div class="stage-cell-head"><h3>Validated</h3><span class="badge accent">Deterministic</span></div>
          <p>schema、边界、数据可用性和因果约束全部通过。</p>
        </article>
        <article class="stage-cell" style="--cell-color: var(--accent)">
          <div class="stage-cell-head"><h3>Approved</h3><span class="badge accent">Immutable v3</span></div>
          <p>由研究者明确批准；任何编辑都创建新版本。</p>
        </article>
      </div>
    </section>
    ${eventsForStage(1)}
  `;
}

function taskWorkspace(task) {
  return `
    ${metricRow(task)}
    ${campaignLayers(task)}
    <section class="context-note">
      当前任务固定 Reproduction Manifest <span class="mono">${task.manifest}</span>。页面切换只改变观察位置，不改变任务生命周期。
    </section>
  `;
}

function monitoringWorkspace(task) {
  return `
    ${metricRow(task)}
    ${campaignLayers(task)}
    ${recentEvents()}
  `;
}

function evidenceWorkspace(task) {
  return `
    ${metricRow(task)}
    <section class="event-list" aria-label="Diagnostic Findings">
      <div class="event-row">
        <span class="event-time">Finding 01</span>
        <span class="event-copy">
          <strong>利润来源集中在趋势延续而非开盘跳空</strong>
          <span>引用 baseline B-03/B-05、isolated trend T-04/T-07 与 6 项确定性证据。</span>
        </span>
        <span class="badge accent">Supported</span>
      </div>
      <div class="event-row">
        <span class="event-time">Finding 02</span>
        <span class="event-copy">
          <strong>流动性 × 1.6–1.8 是执行侵蚀断点区间</strong>
          <span>成交率、滑点、未成交策略动作与 Guardrail 交叉验证；不是未来收益承诺。</span>
        </span>
        <span class="badge warning">Sensitivity</span>
      </div>
      <div class="event-row">
        <span class="event-time">Compare</span>
        <span class="event-copy">
          <strong>Leaderboard 仅作定位，不构成研究结论</strong>
          <span>跨策略比较保留收益风险、交易行为、执行侵蚀和环境敏感性四个维度。</span>
        </span>
        <span class="badge">No score</span>
      </div>
    </section>
  `;
}

function healthWorkspace(task) {
  return `
    <section class="metric-row">
      <div class="metric"><span>Runtime event lag</span><strong class="positive">41 ms</strong></div>
      <div class="metric"><span>View state freshness</span><strong>${task.freshness}</strong></div>
      <div class="metric"><span>Evidence completeness</span><strong class="positive">100%</strong></div>
      <div class="metric"><span>Recovery checkpoint</span><strong>13:30</strong></div>
    </section>
    <section class="event-list">
      <div class="event-row">
        <span class="event-time">Healthy</span>
        <span class="event-copy"><strong>Reference path and manifest</strong><span>checksum verified · ${task.manifest}</span></span>
        <span class="badge accent">Authoritative</span>
      </div>
      <div class="event-row">
        <span class="event-time">Degraded</span>
        <span class="event-copy"><strong>Two market-context snapshots are stale</strong><span>Last reliable values retained; findings that depend on them are visibly marked.</span></span>
        <span class="badge warning">Stale</span>
      </div>
      <div class="event-row">
        <span class="event-time">Healthy</span>
        <span class="event-copy"><strong>Background task recovery</strong><span>Run observation can be reconstructed after leaving and returning to this workspace.</span></span>
        <span class="badge accent">Recoverable</span>
      </div>
    </section>
  `;
}

function eventsForStage(stage) {
  const copy = [
    [
      "Version diff reviewed",
      "参数变化、代码 hash 与 Strategy Guardrail Profile 已固定。",
    ],
    [
      "Approval recorded",
      "Recipe Validator 结果和研究者批准者身份写入审计记录。",
    ],
  ][stage];
  return `
    <section class="event-list">
      <div class="event-row">
        <span class="event-time">Checkpoint</span>
        <span class="event-copy"><strong>${copy[0]}</strong><span>${copy[1]}</span></span>
        <span class="badge accent">Complete</span>
      </div>
    </section>
  `;
}

function workspaceBody(task) {
  const renderers = [
    strategyWorkspace,
    scenarioWorkspace,
    taskWorkspace,
    monitoringWorkspace,
    evidenceWorkspace,
    healthWorkspace,
  ];
  return renderers[state.stage](task);
}

function nextStageIndex() {
  return (state.stage + 1) % journey.length;
}

function workspaceHeading(task, compact = false) {
  const brief = stageBriefs[state.stage];
  return `
    ${breadcrumbs(task)}
    <div class="workspace-heading">
      <div>
        <span class="eyebrow">${brief.kicker}</span>
        <h1 class="section-title">${brief.title}</h1>
        ${compact ? "" : `<p class="section-lede">${brief.lede}</p>`}
      </div>
      <div class="workspace-heading-actions">
        ${state.stage > 0 ? `<button class="btn ghost" type="button" data-stage="${state.stage - 1}">返回上一步</button>` : ""}
        <button class="btn primary" type="button" data-stage="${nextStageIndex()}">${brief.next} →</button>
      </div>
    </div>
  `;
}

function contextInspector(task) {
  return `
    <aside class="context-inspector" aria-label="固定诊断上下文">
      <div class="inspector-head">
        <strong>固定诊断上下文</strong>
        <span class="badge accent">Pinned</span>
      </div>
      <dl class="context-definition">
        <div><dt>Strategy Under Test</dt><dd>${task.strategyVersion}</dd></div>
        <div><dt>Market Scenario</dt><dd>${task.scenario}</dd></div>
        <div><dt>Recipe Version</dt><dd>${task.recipe}<br><span class="muted">${task.recipeState}</span></dd></div>
        <div><dt>Strategy Run</dt><dd class="mono">${task.runId}</dd></div>
        <div><dt>Reproduction Manifest</dt><dd class="mono">${task.manifest}</dd></div>
        <div><dt>Simulation Time</dt><dd>${task.simulationTime}</dd></div>
        <div><dt>Data freshness</dt><dd><span class="positive">${task.freshness}</span> · last reliable retained</dd></div>
      </dl>
      <div class="context-note">
        行情、账户、持仓、订单和成交均为此 Strategy Run 的只读证据上下文；本工作区没有主观手动订单能力。
      </div>
    </aside>
  `;
}

function renderVariantA(task) {
  return `
    ${topbar(task)}
    <div class="shell-a">
      <nav class="journey-rail" aria-label="诊断旅程">
        <div class="rail-label">Diagnostic journey</div>
        <div class="journey-list">${journeyButtons("rail", task)}</div>
        <div class="rail-footer">
          <span class="prototype-only">Context invariant</span>
          <p>改变工作区不会改变 Strategy Run；切换任务必须显式确认。</p>
        </div>
      </nav>
      <section class="workspace-main">
        ${workspaceHeading(task)}
        <div class="workspace-stack">${workspaceBody(task)}</div>
      </section>
      ${contextInspector(task)}
    </div>
  `;
}

function evidenceHorizon(task) {
  return `
    <div class="evidence-horizon">
      <div class="horizon-row">
        <span class="dot degraded"></span>
        <span class="horizon-row-copy"><strong>${task.alerts} 个 Guardrail 信号</strong><span>都能回到 replica、策略动作与执行证据。</span></span>
      </div>
      <div class="horizon-row">
        <span class="dot healthy"></span>
        <span class="horizon-row-copy"><strong>${task.evidence} 项证据已封装</strong><span>收益风险、交易行为、执行侵蚀、环境敏感性。</span></span>
      </div>
      <div class="horizon-row">
        <span class="dot healthy"></span>
        <span class="horizon-row-copy"><strong>Manifest 可复现</strong><span class="mono">${task.manifest}</span></span>
      </div>
    </div>
  `;
}

function contextDock(task) {
  return `
    <aside class="focus-context-dock" aria-label="折叠式固定上下文">
      <div class="dock-title">Pinned context</div>
      <div class="dock-field"><span>Strategy</span><strong>${task.strategyVersion}</strong></div>
      <div class="dock-field"><span>Scenario</span><strong>${task.recipe} · ${task.scenario}</strong></div>
      <div class="dock-field"><span>Run</span><strong class="mono">${task.runId}</strong></div>
      <div class="dock-field"><span>Freshness</span><strong class="positive">${task.freshness}</strong></div>
      <button class="icon-button dock-action" type="button" data-open-task-switcher aria-label="切换诊断任务">⌄</button>
    </aside>
  `;
}

function renderVariantB(task) {
  const brief = stageBriefs[state.stage];
  return `
    ${topbar(task)}
    <nav class="focus-ribbon" aria-label="诊断旅程">${journeyButtons("ribbon", task)}</nav>
    <div class="shell-b">
      <section class="focus-canvas">
        <header class="focus-hero">
          <div>
            ${breadcrumbs(task)}
            <span class="eyebrow">${brief.kicker}</span>
            <h1 class="focus-hero-title">${brief.title}</h1>
          </div>
          <div class="focus-hero-meta">
            <span class="badge ${statusTone(task)}">${task.statusLabel}</span>
            <span>${task.updated}更新</span>
          </div>
        </header>
        <div class="focus-grid">
          <div class="focus-primary">
            <section class="next-action">
              <div class="next-action-copy">
                <span class="eyebrow">Current research question</span>
                <strong>${brief.lede}</strong>
                <p>当前上下文被固定在 ${task.runId}。前进、回退或切换工作区不会触碰诊断任务生命周期。</p>
              </div>
              <div>
                ${state.stage > 0 ? `<button class="btn ghost" type="button" data-stage="${state.stage - 1}">返回</button>` : ""}
                <button class="btn primary" type="button" data-stage="${nextStageIndex()}">${brief.next} →</button>
              </div>
            </section>
            ${workspaceBody(task)}
          </div>
          <aside class="focus-secondary">
            <div class="focus-section-head"><h2>Evidence horizon</h2><span class="badge">Read only</span></div>
            ${evidenceHorizon(task)}
            <div class="context-note">Leaderboard 可以帮助定位异常，但不能替代 Diagnostic Finding。</div>
          </aside>
        </div>
        ${contextDock(task)}
      </section>
    </div>
  `;
}

function taskIndex(task) {
  return tasks
    .map(
      (item) => `
        <button class="task-index-item ${item.id === task.id ? "active" : ""}" type="button" data-task="${item.id}">
          <span class="task-index-item-top">
            <span class="badge ${statusTone(item)}">${item.statusLabel}</span>
            <span class="quiet mono">${item.progress}%</span>
          </span>
          <strong>${item.name}</strong>
          <small>${item.runId}<br>${item.updated}更新</small>
          <span class="thin-progress" style="--progress: ${item.progress}%"><span></span></span>
        </button>
      `,
    )
    .join("");
}

function chronicleEntries(task) {
  const current = stageBriefs[state.stage];
  const priorIndex = Math.max(0, state.stage - 1);
  const prior = stageBriefs[priorIndex];
  return `
    <article class="chronicle-entry">
      <div class="entry-meta"><strong>NOW</strong><span>${journey[state.stage].short}</span><span>${task.simulationTime}</span></div>
      <div class="entry-body">
        <span class="eyebrow">${current.kicker}</span>
        <h2>${current.title}</h2>
        <p>${current.lede}</p>
        <div class="entry-facts">
          <div class="entry-fact"><span>Run</span><strong>${task.runId}</strong></div>
          <div class="entry-fact"><span>Replicas</span><strong>${task.replicas}</strong></div>
          <div class="entry-fact"><span>Freshness</span><strong>${task.freshness}</strong></div>
        </div>
        <div>${workspaceBody(task)}</div>
        <div>
          ${state.stage > 0 ? `<button class="btn ghost" type="button" data-stage="${state.stage - 1}">回到 ${journey[state.stage - 1].label}</button>` : ""}
          <button class="btn primary" type="button" data-stage="${nextStageIndex()}">${current.next} →</button>
        </div>
      </div>
    </article>
    <article class="chronicle-entry">
      <div class="entry-meta"><strong>PREVIOUS</strong><span>${journey[priorIndex].short}</span><span>context retained</span></div>
      <div class="entry-body">
        <h2>${prior.title}</h2>
        <p>该工作区的决策仍作为当前任务上下文保留。返回查看不会重新执行、修改或停止 ${task.runId}。</p>
        <div class="chronicle-callout">
          <strong>Reproduction anchor</strong>
          <p><span class="mono">${task.manifest}</span> · ${task.recipeState}</p>
        </div>
      </div>
    </article>
  `;
}

function renderVariantC(task) {
  return `
    ${topbar(task)}
    <div class="shell-c">
      <aside class="task-index" aria-label="诊断任务索引">
        <div class="task-index-head">
          <h2>研究任务</h2>
          <button class="icon-button" type="button" data-open-task-switcher aria-label="打开任务切换器">⌄</button>
        </div>
        <div class="task-index-list">${taskIndex(task)}</div>
        <div class="context-note">任务切换是显式动作；每个条目保留独立 Strategy Run 和 Reproduction Manifest。</div>
      </aside>
      <main class="chronicle">
        <header class="chronicle-masthead">
          <div class="chronicle-title-row">
            <div>
              <span class="eyebrow">Research chronicle · ${task.runId}</span>
              <h1 class="chronicle-title">${task.name}</h1>
            </div>
            <span class="badge ${statusTone(task)}">${task.statusLabel}</span>
          </div>
          <nav class="journey-index-inline" aria-label="研究记录章节">${journeyButtons("inline", task)}</nav>
          <div class="breadcrumbs">
            <strong>${task.strategyVersion}</strong><span>·</span><span>${task.scenario}</span><span>·</span><span>${task.recipe}</span><span>·</span><span class="positive">${task.freshness}</span>
          </div>
        </header>
        ${chronicleEntries(task)}
      </main>
    </div>
  `;
}

function prototypeSwitcher(task) {
  if (!isPrototype) return "";
  const variant = variants.find((item) => item.key === state.variant);
  return `
    <aside class="prototype-switcher" aria-label="原型方案切换器">
      <button type="button" data-cycle-variant="-1" aria-label="上一个方案">←</button>
      <div class="switcher-copy">
        <strong>${variant.key} — ${variant.name}</strong>
        <span>${task.shortName} · ${journey[state.stage].label} · ${state.density}</span>
      </div>
      <button type="button" data-cycle-variant="1" aria-label="下一个方案">→</button>
    </aside>
  `;
}

function renderTaskModal(task) {
  if (!state.taskModalOpen) {
    overlayRoot.innerHTML = "";
    return;
  }
  overlayRoot.innerHTML = `
    <div class="modal-backdrop" data-modal-backdrop>
      <section class="task-modal" role="dialog" aria-modal="true" aria-labelledby="task-modal-title" data-entering="true">
        <header class="modal-head">
          <div class="modal-head-copy">
            <span class="prototype-only">Explicit context switch</span>
            <h2 id="task-modal-title">切换诊断任务</h2>
            <p>选择后会同时切换 Strategy Under Test、Market Scenario、Strategy Run 与证据上下文。</p>
          </div>
          <button class="icon-button" type="button" data-close-task-switcher aria-label="关闭">×</button>
        </header>
        <div class="modal-task-list">
          ${tasks
            .map(
              (item) => `
                <button class="modal-task ${item.id === task.id ? "active" : ""}" type="button" data-task="${item.id}">
                  <span class="modal-task-copy">
                    <strong>${item.name}</strong>
                    <span>${item.runId} · ${item.type}</span>
                  </span>
                  <span class="badge ${statusTone(item)}">${item.statusLabel}</span>
                </button>
              `,
            )
            .join("")}
        </div>
        <footer class="modal-foot">
          <span>Esc 关闭 · 上下文不会隐式合并</span>
          <span class="mono">${task.manifest}</span>
        </footer>
      </section>
    </div>
  `;
  window.requestAnimationFrame(() => {
    overlayRoot.querySelector(".task-modal")?.setAttribute("data-entering", "false");
    overlayRoot.querySelector("[data-close-task-switcher]")?.focus();
  });
}

function bindInteractions() {
  document.querySelectorAll("[data-stage]").forEach((button) => {
    button.addEventListener("click", () => {
      state.stage = Number(button.dataset.stage);
      render();
    });
  });

  document.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => {
      const task = tasks.find((item) => item.id === button.dataset.task);
      if (!task) return;
      state.taskId = task.id;
      state.stage = task.stage;
      state.taskModalOpen = false;
      render();
    });
  });

  document.querySelectorAll("[data-open-task-switcher]").forEach((button) => {
    button.addEventListener("click", () => {
      state.taskModalOpen = true;
      renderTaskModal(currentTask());
      bindModalInteractions();
    });
  });

  document.querySelector("[data-toggle-density]")?.addEventListener("click", () => {
    state.density = state.density === "compact" ? "comfortable" : "compact";
    render();
  });

  document.querySelectorAll("[data-cycle-variant]").forEach((button) => {
    button.addEventListener("click", () => cycleVariant(Number(button.dataset.cycleVariant)));
  });
}

function bindModalInteractions() {
  overlayRoot.querySelector("[data-close-task-switcher]")?.addEventListener("click", closeTaskModal);
  overlayRoot.querySelector("[data-modal-backdrop]")?.addEventListener("click", (event) => {
    if (event.target.matches("[data-modal-backdrop]")) closeTaskModal();
  });
  overlayRoot.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => {
      const task = tasks.find((item) => item.id === button.dataset.task);
      if (!task) return;
      state.taskId = task.id;
      state.stage = task.stage;
      state.taskModalOpen = false;
      render();
    });
  });
}

function closeTaskModal() {
  state.taskModalOpen = false;
  renderTaskModal(currentTask());
  document.querySelector("[data-open-task-switcher]")?.focus();
}

function cycleVariant(direction) {
  const index = variants.findIndex((variant) => variant.key === state.variant);
  state.variant = variants[(index + direction + variants.length) % variants.length].key;
  render();
}

function render() {
  const task = currentTask();
  const renderers = { A: renderVariantA, B: renderVariantB, C: renderVariantC };
  app.innerHTML = `
    <div class="prototype-app" data-density="${state.density}" data-variant="${state.variant}">
      ${renderers[state.variant](task)}
      ${prototypeSwitcher(task)}
    </div>
  `;
  renderTaskModal(task);
  bindInteractions();
  if (state.taskModalOpen) bindModalInteractions();
  updateUrl();
}

window.addEventListener("keydown", (event) => {
  const target = event.target;
  const isEditable =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    target?.isContentEditable;

  if (event.key === "Escape" && state.taskModalOpen) {
    event.preventDefault();
    closeTaskModal();
    return;
  }
  if (isEditable || state.taskModalOpen) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    cycleVariant(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    cycleVariant(1);
  }
});

render();
