/* THROWAWAY PROTOTYPE — issue #32.
 * Three variants of run monitoring → evidence interpretation, switchable via
 * ?variant=A|B|C on the existing Journey Rail prototype shell.
 */

const evidenceVariants = [
  { key: "A", name: "Interpretation Funnel" },
  { key: "B", name: "Sensitivity Field" },
  { key: "C", name: "Finding Notebook" },
];

const journeyStages = [
  ["策略库", "context retained"],
  ["场景实验室", "context retained"],
  ["诊断任务", "context retained"],
  ["运行监控", "live evidence"],
  ["证据与结论", "interpretation"],
  ["系统健康", "available"],
];

const runStates = {
  running: {
    label: "Running",
    tone: "running",
    progress: 67,
    completed: "12 / 18 replicas",
    headline: "诊断仍在运行；当前只能形成临时观察，不能形成 Diagnostic Finding。",
    detail: "Hidden-world 与 low-liquidity replicas 尚未完成。比较值会继续变化。",
    phase: "Simulation and evidence runners",
    viewRevision: "revision 5184",
  },
  partial: {
    label: "Partial",
    tone: "partial",
    progress: 83,
    completed: "15 / 18 replicas",
    headline: "部分证据可解释，但 3 项缺失或 not_available；结论保持锁定。",
    detail: "已完成结果仍可审阅。缺失不是通过，也不会被排行榜填补。",
    phase: "Evidence debt resolution",
    viewRevision: "revision 5211",
  },
  failed: {
    label: "Failed",
    tone: "failed",
    progress: 71,
    completed: "13 / 18 replicas",
    headline: "任务在 hidden-world evaluation 失败；已完成证据被保留。",
    detail: "失败发生在证据生产，不等于策略表现为负；Research Acceptance Lock 保持关闭。",
    phase: "Stopped · evidence retained",
    viewRevision: "revision 5217",
  },
  completed: {
    label: "Completed · No-Go",
    tone: "complete",
    progress: 100,
    completed: "18 / 18 replicas",
    headline: "运行已完成，但证据不支持研究推广：Research Acceptance Lock 关闭。",
    detail: "排名第一的 MODEL-B17 在 hidden evaluation 与 fee sensitivity 上失败。",
    phase: "Interpretation ready",
    viewRevision: "revision 5240",
  },
};

const candidates = [
  {
    id: "MODEL-B17",
    model: "ppo_lstm_v1.gen4",
    rank: 1,
    return: "+12.4%",
    drawdown: "−8.7%",
    score: "0.814",
    overall: "fail",
    lock: "locked",
    claim: "not eligible",
    breakpoint: "fee 1.6×",
    evidence: {
      baseline: "pass",
      calibration: "pass",
      hidden: "fail",
      exploit: "pass",
      sensitivity: "fail",
    },
  },
  {
    id: "MODEL-A03",
    model: "ppo_lstm_v1.gen4",
    rank: 2,
    return: "+9.2%",
    drawdown: "−6.1%",
    score: "0.763",
    overall: "missing",
    lock: "locked",
    claim: "not eligible",
    breakpoint: "latency 180 ms",
    evidence: {
      baseline: "pass",
      calibration: "pass",
      hidden: "missing",
      exploit: "pass",
      sensitivity: "warning",
    },
  },
  {
    id: "BASE-TWAP",
    model: "twap_baseline_v1",
    rank: 3,
    return: "+6.8%",
    drawdown: "−4.9%",
    score: "0.641",
    overall: "pass",
    lock: "reference",
    claim: "baseline only",
    breakpoint: "none",
    evidence: {
      baseline: "pass",
      calibration: "pass",
      hidden: "pass",
      exploit: "pass",
      sensitivity: "pass",
    },
  },
  {
    id: "MODEL-C08",
    model: "ppo_lstm_v1.gen4",
    rank: 4,
    return: "−1.1%",
    drawdown: "−14.2%",
    score: "0.298",
    overall: "fail",
    lock: "locked",
    claim: "not eligible",
    breakpoint: "impact 1.3×",
    evidence: {
      baseline: "fail",
      calibration: "warning",
      hidden: "fail",
      exploit: "pass",
      sensitivity: "fail",
    },
  },
];

const findings = [
  {
    id: "F-01",
    title: "收益领先不能升级为研究结论",
    status: "blocked",
    confidence: "High confidence",
    candidate: "MODEL-B17",
    summary:
      "MODEL-B17 在可见场景排名第一，但 hidden evaluation 低于强基线，且费用升至 1.6× 后相对优势穿越零点。",
    claim:
      "Observed return leadership is not robust enough for a research claim or parent promotion.",
    supports: [
      "18 / 18 Scenario Replicas completed",
      "Baseline and calibration artifacts pass strict source/hash checks",
      "Exploit probes pass all six required categories",
    ],
    contradicts: [
      "Hidden-world win rate vs TWAP/VWAP/AC-lite: 0.42 < 0.55 gate",
      "Fee sensitivity advantage: +2.1% → −0.3% at 1.6×",
      "Research Acceptance Lock: locked",
    ],
    next: "Keep MODEL-B17 as an engineering candidate; revise reward/action space and rerun hidden + paired sensitivity.",
    artifact: "hidden_eval_artifact_v1",
    sourceRun: "run-hidden-0719-b17",
    hash: "a64e…91c2",
  },
  {
    id: "F-02",
    title: "费用是第一处稳定性断点",
    status: "sensitivity",
    confidence: "Medium confidence",
    candidate: "MODEL-B17",
    summary:
      "从 base 到 high-fee 的退化不是平滑减弱，而是在 1.6× 附近发生符号反转；impact 与 latency 尚未出现更早断点。",
    claim: "The first observed robustness breakpoint is transaction fee at 1.6× the scenario baseline.",
    supports: [
      "Paired candidate and baseline paths share seeds and scenario replicas",
      "Base, 1.2×, 1.6×, and 2.0× fee points are available",
      "Degradation curve is monotonic after the breakpoint",
    ],
    contradicts: [
      "Only one Formal Diagnostic Campaign observed",
      "Low-liquidity replication remains partial in the Partial state",
    ],
    next: "Repeat the paired sensitivity campaign with two additional seed sets before promoting the breakpoint to a stable finding.",
    artifact: "paired_sensitivity_artifact_v1",
    sourceRun: "run-sensitivity-0719-b17",
    hash: "c02f…471a",
  },
  {
    id: "F-03",
    title: "LQ-08 集中了执行侵蚀",
    status: "observed",
    confidence: "Medium confidence",
    candidate: "MODEL-A03",
    summary:
      "LQ-08 的成交延迟和滑点共同解释了该 replica 的收益偏离；同一标的可进入 #31 Market/Symbol Detail 追溯。",
    claim: "Execution erosion in replica LQ-08 is concentrated around activation latency and shallow depth.",
    supports: [
      "Execution erosion: −37 bp vs campaign median −12 bp",
      "Activation-to-fill latency: 182 ms",
      "Market context trace links 4 strategy-originated fills",
    ],
    contradicts: ["Hidden evidence for MODEL-A03 is missing", "Causal attribution remains replica-local"],
    next: "Inspect linked Market context, then rerun the replica with latency fixed and depth unchanged.",
    artifact: "execution_trace_v1",
    sourceRun: "run-lq08-0719-a03",
    hash: "02b1…a7e9",
  },
];

const runEvents = [
  {
    time: "09:31",
    title: "Campaign materialized",
    detail: "18 Scenario Replicas · 4 candidates · deterministic seeds verified",
    tone: "pass",
  },
  {
    time: "10:14",
    title: "Replica LQ-08 execution drift",
    detail: "Activation-to-fill latency crossed 180 ms; Market context linked",
    tone: "warning",
  },
  {
    time: "11:02",
    title: "Fee breakpoint detected",
    detail: "MODEL-B17 relative advantage crossed zero at fee 1.6×",
    tone: "warning",
  },
  {
    time: "11:18",
    title: "Hidden evaluation blocked claim",
    detail: "win_rate_vs_baselines below 0.55 gate",
    tone: "fail",
  },
  {
    time: "11:24",
    title: "Campaign complete",
    detail: "18 / 18 replicas retained · Research Acceptance Lock closed",
    tone: "complete",
  },
];

const breakpoints = {
  "fee-base": {
    label: "Fee · base",
    value: "+2.1%",
    status: "pass",
    detail: "Candidate advantage remains positive against the paired baseline.",
  },
  "fee-1.2": {
    label: "Fee · 1.2×",
    value: "+1.0%",
    status: "warning",
    detail: "Advantage narrows but remains above zero.",
  },
  "fee-1.6": {
    label: "Fee · 1.6×",
    value: "−0.3%",
    status: "fail",
    detail: "First sign change. This is the observed sensitivity breakpoint.",
  },
  "fee-2.0": {
    label: "Fee · 2.0×",
    value: "−2.2%",
    status: "fail",
    detail: "Degradation continues after the breakpoint.",
  },
  "impact-base": {
    label: "Impact · base",
    value: "+2.1%",
    status: "pass",
    detail: "Reference paired path.",
  },
  "impact-1.2": {
    label: "Impact · 1.2×",
    value: "+1.6%",
    status: "pass",
    detail: "No observed sign change.",
  },
  "impact-1.6": {
    label: "Impact · 1.6×",
    value: "+0.7%",
    status: "warning",
    detail: "Approaching zero; not yet a breakpoint.",
  },
  "impact-2.0": {
    label: "Impact · 2.0×",
    value: "+0.2%",
    status: "warning",
    detail: "Small positive advantage remains.",
  },
  "latency-base": {
    label: "Latency · base",
    value: "+2.1%",
    status: "pass",
    detail: "Reference paired path.",
  },
  "latency-1.2": {
    label: "Latency · 1.2×",
    value: "+1.8%",
    status: "pass",
    detail: "No material degradation.",
  },
  "latency-1.6": {
    label: "Latency · 1.6×",
    value: "+1.1%",
    status: "pass",
    detail: "Advantage remains positive.",
  },
  "latency-2.0": {
    label: "Latency · 2.0×",
    value: "+0.5%",
    status: "warning",
    detail: "Weakening, but no sign change.",
  },
};

const urlParams = new URLSearchParams(window.location.search);
const requestedVariant = (urlParams.get("variant") || "A").toUpperCase();
const requestedRun = urlParams.get("run") || "completed";
const requestedCandidate = urlParams.get("candidate") || candidates[0].id;
const requestedFinding = urlParams.get("finding") || findings[0].id;

const evidenceState = {
  variant: evidenceVariants.some((item) => item.key === requestedVariant) ? requestedVariant : "A",
  run: Object.hasOwn(runStates, requestedRun) ? requestedRun : "completed",
  density: urlParams.get("density") === "compact" ? "compact" : "comfortable",
  selectedCandidate: candidates.some((item) => item.id === requestedCandidate)
    ? requestedCandidate
    : candidates[0].id,
  selectedFinding: findings.some((item) => item.id === requestedFinding)
    ? requestedFinding
    : findings[0].id,
  selectedBreakpoint: urlParams.get("breakpoint") || "fee-1.6",
  provenanceOpen: false,
};

const evidenceApp = document.querySelector("#evidence-app");
const evidenceOverlayRoot = document.querySelector("#evidence-overlay-root");

function activeRun() {
  return runStates[evidenceState.run];
}

function interpretationMode() {
  const modes = {
    running: {
      verdict: "Pending",
      verdictDetail: "final gates not evaluated",
      findingHeading: "Provisional observations",
      findingCount: "2 live observations · no finding yet",
      recordLabel: "Provisional observation",
      notebookStatus: "Running / Pending",
      lockDetail: "No conclusion until the campaign completes",
      timelineCap: 2,
    },
    partial: {
      verdict: "Locked",
      verdictDetail: "3 evidence debts",
      findingHeading: "Provisional findings",
      findingCount: "3 provisional · 3 evidence debts",
      recordLabel: "Provisional finding",
      notebookStatus: "Partial / Locked",
      lockDetail: "Missing evidence keeps the research lock closed",
      timelineCap: 3,
    },
    failed: {
      verdict: "Stopped",
      verdictDetail: "evidence production failed",
      findingHeading: "Retained observations",
      findingCount: "3 retained · no campaign verdict",
      recordLabel: "Retained observation",
      notebookStatus: "Failed / Stopped",
      lockDetail: "Completed evidence is retained; no verdict is issued",
      timelineCap: 4,
    },
    completed: {
      verdict: "No-Go",
      verdictDetail: "2 blocking findings",
      findingHeading: "Diagnostic Findings",
      findingCount: "3 findings · 2 blockers",
      recordLabel: "Diagnostic Finding",
      notebookStatus: "Complete / No-Go",
      lockDetail: "Research Acceptance Lock closed",
      timelineCap: 5,
    },
  };
  return modes[evidenceState.run];
}

function activeCandidate() {
  return candidates.find((item) => item.id === evidenceState.selectedCandidate) || candidates[0];
}

function activeFinding() {
  return findings.find((item) => item.id === evidenceState.selectedFinding) || findings[0];
}

function activeBreakpoint() {
  return breakpoints[evidenceState.selectedBreakpoint] || breakpoints["fee-1.6"];
}

function visibleFindings() {
  return evidenceState.run === "running" ? findings.slice(0, 2) : findings;
}

function candidateView(candidate) {
  if (evidenceState.run === "completed") {
    return candidate;
  }
  if (evidenceState.run === "running") {
    return {
      ...candidate,
      overall: "running",
      lock: "locked",
      claim: "pending",
      breakpoint: "not evaluated",
      evidence: {
        baseline: "pass",
        calibration: "running",
        hidden: "running",
        exploit: "running",
        sensitivity: "running",
      },
    };
  }
  if (evidenceState.run === "partial") {
    return {
      ...candidate,
      overall: "missing",
      lock: "locked",
      claim: "not eligible",
      breakpoint: "provisional",
      evidence: {
        ...candidate.evidence,
        hidden: "missing",
        sensitivity: "warning",
      },
    };
  }
  return {
    ...candidate,
    overall: "not_available",
    lock: "locked",
    claim: "no verdict",
    breakpoint: "retained signal",
    evidence: {
      ...candidate.evidence,
      hidden: "not_available",
      sensitivity: "warning",
    },
  };
}

function phaseClass(index) {
  const states = {
    running: ["done", "active", "", ""],
    partial: ["done", "done", "active", ""],
    failed: ["done", "done", "blocked", ""],
    completed: ["done", "done", "done", "blocked"],
  };
  return states[evidenceState.run][index];
}

function updateEvidenceUrl() {
  const next = new URLSearchParams();
  next.set("variant", evidenceState.variant);
  next.set("run", evidenceState.run);
  next.set("density", evidenceState.density);
  next.set("candidate", evidenceState.selectedCandidate);
  next.set("finding", evidenceState.selectedFinding);
  next.set("breakpoint", evidenceState.selectedBreakpoint);
  window.history.replaceState(null, "", `${window.location.pathname}?${next.toString()}`);
}

function statusBadge(status, label = status) {
  return `<span class="evidence-status ${status}"><span class="status-dot"></span>${label}</span>`;
}

function topbar() {
  const run = activeRun();
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
      <button class="context-switch" type="button" data-open-provenance>
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
        <span class="status-chip ${run.tone === "failed" ? "degraded" : "healthy"}">
          <span class="dot"></span>${run.label}
        </span>
        <button class="density-button" type="button" data-toggle-evidence-density>
          ${evidenceState.density === "compact" ? "紧凑" : "舒适"}
        </button>
      </div>
    </header>
  `;
}

function journeyRail() {
  const activeIndex = evidenceState.run === "completed" ? 4 : 3;
  return `
    <nav class="journey-rail" aria-label="诊断旅程">
      <div class="rail-label">Diagnostic journey</div>
      <div class="journey-list">
        ${journeyStages
          .map(
            ([label, hint], index) => `
              <button class="journey-item ${index === activeIndex ? "active" : index < activeIndex ? "done" : ""}" type="button" data-journey-stage="${index}" ${index === activeIndex ? 'aria-current="page"' : ""}>
                <span class="journey-item-index">${index + 1}</span>
                <span class="journey-item-copy"><strong>${label}</strong><small>${hint}</small></span>
              </button>
            `,
          )
          .join("")}
      </div>
      <div class="rail-footer">
        <span class="prototype-only">Interpretation flow</span>
        <p>运行状态、比较信号与证据解释属于同一 Strategy Run，不再拆成 Arena、排行榜和 Evidence Board 工作台。</p>
      </div>
    </nav>
  `;
}

function contextInspector() {
  const run = activeRun();
  return `
    <aside class="context-inspector evidence-inspector" aria-label="固定诊断上下文">
      <div class="inspector-head">
        <strong>固定诊断上下文</strong>
        <span class="badge accent">Pinned</span>
      </div>
      <dl class="context-definition">
        <div><dt>Strategy Under Test</dt><dd>Breakout v4.2 · 7ec31a</dd></div>
        <div><dt>Market Scenario</dt><dd>2021 Q1 / 流动性压力 × 1.8</dd></div>
        <div><dt>Formal Campaign</dt><dd class="mono">FDC-24-0719</dd></div>
        <div><dt>Strategy Run</dt><dd class="mono">DGN-24-0719-A</dd></div>
        <div><dt>Scenario Replicas</dt><dd>18 deterministic seeds</dd></div>
        <div><dt>Simulation Time</dt><dd>Day 42 · ${run.label}</dd></div>
        <div><dt>ViewState</dt><dd>${statusBadge(run.tone, run.label)}<br><span class="muted">${run.viewRevision}</span></dd></div>
      </dl>
      <div class="inspector-note">
        <strong>Research Acceptance Lock v2</strong>
        <span>只有 live source、可重算 hash、明确 pass_gate 且无缺失证据时才允许形成研究结论。</span>
      </div>
    </aside>
  `;
}

function runStateSwitch() {
  return `
    <div class="run-state-switch" aria-label="原型运行状态">
      ${Object.entries(runStates)
        .map(
          ([key, value]) => `
            <button type="button" data-run-state="${key}" class="${evidenceState.run === key ? "active" : ""}" aria-pressed="${evidenceState.run === key}">
              ${value.label.replace(" · No-Go", "")}
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function runBanner() {
  const run = activeRun();
  return `
    <section class="run-banner ${run.tone}" aria-label="诊断任务状态">
      <div class="run-banner-main">
        <span class="eyebrow">Formal Diagnostic Campaign · ${run.phase}</span>
        <strong>${run.headline}</strong>
        <span>${run.detail}</span>
      </div>
      <div class="run-progress">
        <div><strong>${run.progress}%</strong><span>${run.completed}</span></div>
        <progress max="100" value="${run.progress}">${run.progress}%</progress>
      </div>
    </section>
  `;
}

function findingButton(finding, compact = false) {
  const selected = finding.id === evidenceState.selectedFinding;
  return `
    <button class="finding-row ${selected ? "selected" : ""} ${compact ? "compact" : ""}" type="button" data-finding="${finding.id}" aria-pressed="${selected}">
      <span class="finding-id">${finding.id}</span>
      <span class="finding-row-copy">
        <strong>${finding.title}</strong>
        <small>${finding.summary}</small>
      </span>
      ${statusBadge(finding.status, finding.confidence)}
    </button>
  `;
}

function findingSummary(finding) {
  const mode = interpretationMode();
  return `
    <article class="finding-summary">
      <header>
        <div>
          <span class="eyebrow">${mode.recordLabel} · ${finding.id}</span>
          <h2>${finding.title}</h2>
        </div>
        ${statusBadge(finding.status, finding.confidence)}
      </header>
      <p class="finding-claim">${finding.claim}</p>
      <div class="reasoning-grid">
        <section>
          <span class="reason-label support">Supporting evidence</span>
          <ul>${finding.supports.map((item) => `<li>${item}</li>`).join("")}</ul>
        </section>
        <section>
          <span class="reason-label contradict">Contradicting / limiting evidence</span>
          <ul>${finding.contradicts.map((item) => `<li>${item}</li>`).join("")}</ul>
        </section>
      </div>
      <footer class="finding-next">
        <span>Next diagnostic action</span>
        <strong>${finding.next}</strong>
        <button type="button" class="text-action" data-open-provenance>查看证据出处与 hash →</button>
      </footer>
    </article>
  `;
}

function findingDetail(finding) {
  if (evidenceState.run !== "running") {
    return findingSummary(finding);
  }
  return `
    <article class="provisional-block">
      <span class="eyebrow">Interpretation locked while running</span>
      <h2>No Diagnostic Finding yet</h2>
      <p>当前只保留可复查的临时观察；剩余 6 个 Scenario Replicas 与最终 gate 可能改变方向和置信度。</p>
      <dl>
        <div><dt>Live observation</dt><dd>LQ-08 activation-to-fill latency crossed 180 ms.</dd></div>
        <div><dt>Live observation</dt><dd>Fee 1.6× is approaching a relative-advantage sign change.</dd></div>
        <div><dt>Next</dt><dd>Wait for hidden-world and low-liquidity replicas, then evaluate the full evidence contract.</dd></div>
      </dl>
    </article>
  `;
}

function eventTimeline(limit = runEvents.length) {
  const visibleLimit = Math.min(limit, interpretationMode().timelineCap);
  return `
    <ol class="run-event-list" aria-label="运行事件与异常">
      ${runEvents
        .slice(0, visibleLimit)
        .map(
          (event) => `
            <li class="${event.tone}">
              <time>${event.time}</time>
              <span class="event-node"></span>
              <span><strong>${event.title}</strong><small>${event.detail}</small></span>
            </li>
          `,
        )
        .join("")}
    </ol>
  `;
}

function evidenceCells(candidate) {
  return Object.entries(candidate.evidence)
    .map(([name, status]) => `<span class="matrix-evidence-cell ${status}" title="${name}: ${status}">${name.slice(0, 3)} · ${status}</span>`)
    .join("");
}

function rankingTable({ selectable = true, compact = false } = {}) {
  const mode = interpretationMode();
  return `
    <section class="ranking-signal ${compact ? "compact" : ""}">
      <header class="section-head">
        <div>
          <span class="eyebrow">${evidenceState.run === "completed" ? "Comparison" : "Live comparison"} signal · not a conclusion</span>
          <h2>Return ranking</h2>
        </div>
        <span class="ranking-warning">${mode.verdict}: rank never opens the Research Acceptance Lock</span>
      </header>
      <div class="table-scroll">
        <table class="evidence-table" aria-label="收益排名，仅作比较信号">
          <thead><tr><th>Rank</th><th>Candidate</th><th>Return</th><th>Drawdown</th><th>Evidence</th><th>Research lock</th></tr></thead>
          <tbody>
            ${candidates
              .map((candidate) => {
                const view = candidateView(candidate);
                return `
                  <tr class="${candidate.id === evidenceState.selectedCandidate ? "selected" : ""}" ${selectable ? `tabindex="0" data-candidate="${candidate.id}"` : ""} aria-selected="${candidate.id === evidenceState.selectedCandidate}">
                    <td>${candidate.rank}</td>
                    <td><strong>${candidate.id}</strong><small>${candidate.model}</small></td>
                    <td class="mono">${candidate.return}</td>
                    <td class="mono">${candidate.drawdown}</td>
                    <td>${statusBadge(view.overall, view.overall)}</td>
                    <td>${view.lock}</td>
                  </tr>
                `;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function selectedCandidateGate() {
  const candidate = candidateView(activeCandidate());
  return `
    <section class="candidate-gate">
      <header class="section-head">
        <div><span class="eyebrow">Selected candidate</span><h2>${candidate.id}</h2></div>
        ${statusBadge(candidate.overall)}
      </header>
      <div class="gate-metrics">
        <div><span>Return rank</span><strong>#${candidate.rank} · ${candidate.return}</strong></div>
        <div><span>First breakpoint</span><strong>${candidate.breakpoint}</strong></div>
        <div><span>Research claim</span><strong>${candidate.claim}</strong></div>
      </div>
      <div class="evidence-cell-grid">${evidenceCells(candidate)}</div>
      <button type="button" class="progressive-trigger" data-open-provenance>
        <span><strong>展开失败原因、source run 与 artifact hash</strong><small>Evidence Board 详情按需出现，不把 8 列 gate 状态堆在主屏</small></span>
        <span aria-hidden="true">↗</span>
      </button>
    </section>
  `;
}

function variantA() {
  const finding = activeFinding();
  const mode = interpretationMode();
  return `
    <section class="interpretation-funnel">
      <header class="interpretation-question">
        <div>
          <span class="eyebrow">Current research question</span>
          <h1>这次收益提升，能否形成可复现的诊断结论？</h1>
          <p>先读任务完整性与最强反证，再读候选排名。完成运行不等于通过研究门禁。</p>
        </div>
        <div class="verdict-stamp ${activeRun().tone}">
          <span>Current verdict</span>
          <strong>${mode.verdict}</strong>
          <small>${mode.verdictDetail}</small>
        </div>
      </header>
      <div class="funnel-layout">
        <main class="funnel-primary">
          <section class="progress-section">
            <div class="section-head">
              <div><span class="eyebrow">From monitoring to interpretation</span><h2>任务完整性与异常</h2></div>
              <span class="quiet-note">${activeRun().completed}</span>
            </div>
            <div class="phase-strip" aria-label="诊断阶段进度">
              <span class="${phaseClass(0)}"><b>1</b>Materialize</span>
              <span class="${phaseClass(1)}"><b>2</b>Simulate</span>
              <span class="${phaseClass(2)}"><b>3</b>Evaluate</span>
              <span class="${phaseClass(3)}"><b>4</b>Interpret</span>
            </div>
            ${eventTimeline(5)}
          </section>
          <section class="findings-section">
            <div class="section-head">
              <div><span class="eyebrow">Interpretation, not raw output</span><h2>${mode.findingHeading}</h2></div>
              <span class="quiet-note">${mode.findingCount}</span>
            </div>
            <div class="finding-list">${visibleFindings().map((item) => findingButton(item)).join("")}</div>
          </section>
          ${findingDetail(finding)}
        </main>
        <aside class="funnel-secondary">
          ${rankingTable({ compact: true })}
          ${selectedCandidateGate()}
          <div class="deleted-surface">
            <strong>旧 Arena 不迁移</strong>
            <span>Create/Start/Stop/Evaluate 控件、原始 ID 表、独立 leaderboard 页面与 8 列 gate 表不再并列成工作台。</span>
          </div>
        </aside>
      </div>
    </section>
  `;
}

function sensitivityMatrix() {
  const rows = [
    ["Fee", "fee"],
    ["Market impact", "impact"],
    ["Activation latency", "latency"],
  ];
  const columns = ["base", "1.2", "1.6", "2.0"];
  return `
    <div class="sensitivity-matrix" role="grid" aria-label="MODEL-B17 敏感性断点矩阵">
      <div class="matrix-corner">Relative advantage</div>
      ${columns.map((column) => `<div class="matrix-column">${column === "base" ? "Base" : `${column}×`}</div>`).join("")}
      ${rows
        .map(
          ([label, key]) => `
            <div class="matrix-row-label">${label}</div>
            ${columns
              .map((column) => {
                const id = `${key}-${column}`;
                const point = breakpoints[id];
                return `
                  <button type="button" class="sensitivity-cell ${point.status} ${evidenceState.selectedBreakpoint === id ? "selected" : ""}" data-breakpoint="${id}" aria-pressed="${evidenceState.selectedBreakpoint === id}">
                    <strong>${point.value}</strong><small>${point.status}</small>
                  </button>
                `;
              })
              .join("")}
          `,
        )
        .join("")}
    </div>
  `;
}

function replicaStrip() {
  const replicas = [
    ["BASE-01", "+2.4", "pass"],
    ["FEE-12", "+1.0", "pass"],
    ["FEE-16", "−0.3", "fail"],
    ["LQ-08", "−1.2", "warning"],
    ["LAT-18", "+0.5", "warning"],
    ["HID-03", "−2.7", "fail"],
  ];
  return `
    <div class="replica-strip" aria-label="关键 Scenario Replicas">
      ${replicas
        .map(
          ([id, value, status]) => `
            <div class="${status}"><span>${id}</span><strong>${value}%</strong><small>${status}</small></div>
          `,
        )
        .join("")}
    </div>
  `;
}

function variantB() {
  const point = activeBreakpoint();
  const mode = interpretationMode();
  const candidate = candidateView(activeCandidate());
  return `
    <section class="sensitivity-field">
      <header class="field-header">
        <div>
          <span class="eyebrow">Sensitivity-first interpretation</span>
          <h1>优势在哪里失效？</h1>
          <p>把候选与基线放在同一组 Scenario Replica 和扰动轴上；收益排名只在解释断点之后出现。</p>
        </div>
        <div class="field-candidate">
          <span>Selected candidate · ${mode.verdict}</span>
          <strong>${candidate.id}</strong>
          <small>${mode.verdictDetail}</small>
        </div>
      </header>
      <div class="field-layout">
        <main class="field-primary">
          <section class="matrix-panel">
            <div class="section-head">
              <div><span class="eyebrow">Paired sensitivity artifact</span><h2>Robustness field</h2></div>
              <span class="quiet-note">shared seeds · paired baselines</span>
            </div>
            ${sensitivityMatrix()}
            <div class="breakpoint-reading ${point.status}">
              <span class="eyebrow">Selected point · ${point.label}</span>
              <strong>${point.value}</strong>
              <p>${point.detail}</p>
              <button type="button" class="text-action" data-open-provenance>检查 paired artifact →</button>
            </div>
          </section>
          <section class="replica-panel">
            <div class="section-head">
              <div><span class="eyebrow">Scenario Replica comparison</span><h2>关键路径</h2></div>
              <span class="quiet-note">not a watchlist</span>
            </div>
            ${replicaStrip()}
            ${eventTimeline(5)}
          </section>
        </main>
        <aside class="field-secondary">
          ${selectedCandidateGate()}
          ${rankingTable({ compact: true })}
        </aside>
      </div>
    </section>
  `;
}

function findingIndex() {
  const mode = interpretationMode();
  return `
    <nav class="finding-index" aria-label="Diagnostic Findings">
      <div class="finding-index-head">
        <span class="eyebrow">Evidence & Findings</span>
        <strong>${mode.findingHeading}</strong>
        <small>${mode.findingCount}</small>
      </div>
      ${visibleFindings().map((finding) => findingButton(finding, true)).join("")}
      <div class="finding-index-note">
        <strong>Finding ≠ leaderboard row</strong>
        <span>每个 finding 必须陈述 claim、支持证据、反证、适用范围和下一步。</span>
      </div>
    </nav>
  `;
}

function provenanceSummary(finding) {
  return `
    <aside class="notebook-provenance">
      <div class="section-head">
        <div><span class="eyebrow">Traceability</span><h2>Evidence provenance</h2></div>
        ${statusBadge(finding.status)}
      </div>
      <dl class="provenance-list">
        <div><dt>Artifact</dt><dd>${finding.artifact}</dd></div>
        <div><dt>Source</dt><dd>live_postgresql_runtime</dd></div>
        <div><dt>Source run</dt><dd>${finding.sourceRun}</dd></div>
        <div><dt>Artifact hash</dt><dd>${finding.hash}</dd></div>
        <div><dt>Runner</dt><dd>evidence-runner v1.7</dd></div>
        <div><dt>Point-in-Time</dt><dd>Day 42 · 11:24</dd></div>
      </dl>
      <button type="button" class="progressive-trigger" data-open-provenance>
        <span><strong>打开完整证据追溯</strong><small>包含 failure_type、blocking_metrics 与 next_action</small></span>
        <span aria-hidden="true">↗</span>
      </button>
    </aside>
  `;
}

function variantC() {
  const finding = activeFinding();
  const mode = interpretationMode();
  return `
    <section class="finding-notebook">
      <header class="notebook-header">
        <div>
          <span class="eyebrow">Finding-first research record</span>
          <h1>先读结论边界，再回到运行与比较证据</h1>
        </div>
        <div class="notebook-verdict ${activeRun().tone}">
          <span>Campaign status</span>
          <strong>${mode.notebookStatus}</strong>
          <small>${mode.lockDetail}</small>
        </div>
      </header>
      <div class="notebook-layout">
        ${findingIndex()}
        <main class="notebook-article">
          ${findingDetail(finding)}
          <section class="scope-block">
            <div><span>Applies to</span><strong>FDC-24-0719 · Breakout v4.2 · LQ family</strong></div>
            <div><span>Does not claim</span><strong>real-market transfer, alpha validity, or cross-campaign stability</strong></div>
          </section>
          <details class="comparison-appendix">
            <summary>查看 Return ranking 附录（仅作比较信号）</summary>
            ${rankingTable({ selectable: false, compact: true })}
          </details>
        </main>
        <aside class="notebook-side">
          <section class="mini-run-monitor">
            <div class="section-head">
              <div><span class="eyebrow">Run monitor</span><h2>${activeRun().label}</h2></div>
              <strong>${activeRun().progress}%</strong>
            </div>
            <progress max="100" value="${activeRun().progress}">${activeRun().progress}%</progress>
            ${eventTimeline(3)}
          </section>
          ${provenanceSummary(finding)}
        </aside>
      </div>
    </section>
  `;
}

function prototypeSwitcher() {
  const variant = evidenceVariants.find((item) => item.key === evidenceState.variant);
  const mode = interpretationMode();
  return `
    <aside class="prototype-switcher evidence-switcher" aria-label="运行与证据原型方案切换器">
      <button type="button" data-cycle-evidence-variant="-1" aria-label="上一个运行证据方案">←</button>
      <div class="switcher-copy">
        <span><strong>${variant.key} — ${variant.name}</strong><span>${evidenceState.run} · ${evidenceState.density}</span></span>
        <span class="switcher-verdict">${mode.verdict} · ${mode.verdictDetail}</span>
      </div>
      <button type="button" data-cycle-evidence-variant="1" aria-label="下一个运行证据方案">→</button>
    </aside>
  `;
}

function provenanceDialog() {
  if (!evidenceState.provenanceOpen) {
    evidenceOverlayRoot.innerHTML = "";
    return;
  }
  const finding = activeFinding();
  const candidate = activeCandidate();
  evidenceOverlayRoot.innerHTML = `
    <div class="provenance-backdrop" data-provenance-backdrop>
      <section class="provenance-dialog" role="dialog" aria-modal="true" aria-labelledby="provenance-title" data-entering="true">
        <header class="provenance-dialog-head">
          <div>
            <span class="prototype-only">Read-only diagnostic evidence</span>
            <h2 id="provenance-title">${finding.id} · ${finding.title}</h2>
            <p>${candidate.id} · Strategy Run DGN-24-0719-A · Formal Campaign FDC-24-0719</p>
          </div>
          <button class="icon-button" type="button" data-close-provenance aria-label="关闭证据追溯">×</button>
        </header>
        <div class="provenance-dialog-body">
          <section>
            <div class="section-head"><div><span class="eyebrow">Failure detail contract</span><h3>${finding.artifact}</h3></div>${statusBadge(finding.status)}</div>
            <dl class="provenance-list">
              <div><dt>failure_type</dt><dd>${finding.id === "F-01" ? "underperform_baseline" : finding.id === "F-02" ? "sensitivity_breakpoint" : "execution_erosion"}</dd></div>
              <div><dt>blocking_metrics</dt><dd>${finding.id === "F-01" ? "win_rate_vs_baselines" : finding.id === "F-02" ? "relative_advantage" : "activation_to_fill_latency"}</dd></div>
              <div><dt>source</dt><dd>live_postgresql_runtime</dd></div>
              <div><dt>source_run_ids</dt><dd>${finding.sourceRun}</dd></div>
              <div><dt>artifact_hash</dt><dd>${finding.hash}</dd></div>
              <div><dt>runner_version</dt><dd>evidence-runner v1.7</dd></div>
            </dl>
          </section>
          <section>
            <div class="section-head"><div><span class="eyebrow">Interpretation boundary</span><h3>Why the lock stays closed</h3></div></div>
            <p class="dialog-explanation">${finding.summary}</p>
            <div class="dialog-next"><span>next_action</span><strong>${finding.next}</strong></div>
            <div class="dialog-debt">
              <strong>Missing / not_available are evidence debt</strong>
              <span>owner: evidence_runner · required input: paired_sensitivity_artifact_v1 · planned task: #94</span>
            </div>
          </section>
        </div>
        <footer class="provenance-dialog-foot">
          该视图只能审阅证据。它不能重跑实验、覆盖 gate、推广 checkpoint，也不包含任何手动下单能力。
        </footer>
      </section>
    </div>
  `;
  window.requestAnimationFrame(() => {
    evidenceOverlayRoot.querySelector(".provenance-dialog")?.setAttribute("data-entering", "false");
    evidenceOverlayRoot.querySelector("[data-close-provenance]")?.focus();
  });
}

function renderEvidence() {
  const renderers = { A: variantA, B: variantB, C: variantC };
  evidenceApp.innerHTML = `
    <div class="evidence-prototype" data-evidence-variant="${evidenceState.variant}" data-evidence-density="${evidenceState.density}" data-run-state="${evidenceState.run}">
      ${topbar()}
      <div class="evidence-shell">
        ${journeyRail()}
        <main class="evidence-workspace">
          <div class="evidence-breadcrumb">
            <strong>DGN-24-0719-A</strong><span>›</span><span>${evidenceState.run === "completed" ? "证据与结论" : "运行监控"}</span><span>›</span><span>理解诊断结果</span>
          </div>
          <div class="evidence-toolbar">
            <div>
              <strong>Run Monitoring → Evidence Interpretation</strong>
              <span>原型状态切换只改变 deterministic ViewState，不连接真实 runtime。</span>
            </div>
            ${runStateSwitch()}
          </div>
          ${runBanner()}
          ${renderers[evidenceState.variant]()}
          <footer class="prototype-boundary">
            <strong>Prototype boundary</strong>
            <span>没有 Create/Start/Stop/Evaluate、checkpoint promotion、gate override 或手动订单控件；所有交互只改变本地只读 ViewState。</span>
          </footer>
        </main>
        ${contextInspector()}
      </div>
      ${prototypeSwitcher()}
    </div>
  `;
  provenanceDialog();
  bindEvidenceInteractions();
  updateEvidenceUrl();
}

function bindEvidenceInteractions() {
  document.querySelectorAll(".run-state-switch [data-run-state]").forEach((button) => {
    button.addEventListener("click", () => {
      evidenceState.run = button.dataset.runState;
      renderEvidence();
    });
  });

  document.querySelector("[data-toggle-evidence-density]")?.addEventListener("click", () => {
    evidenceState.density = evidenceState.density === "compact" ? "comfortable" : "compact";
    renderEvidence();
  });

  document.querySelectorAll("[data-cycle-evidence-variant]").forEach((button) => {
    button.addEventListener("click", () => cycleEvidenceVariant(Number(button.dataset.cycleEvidenceVariant)));
  });

  document.querySelectorAll("[data-finding]").forEach((button) => {
    button.addEventListener("click", () => {
      evidenceState.selectedFinding = button.dataset.finding;
      const finding = activeFinding();
      evidenceState.selectedCandidate = finding.candidate;
      renderEvidence();
    });
  });

  document.querySelectorAll("[data-candidate]").forEach((row) => {
    const choose = () => {
      evidenceState.selectedCandidate = row.dataset.candidate;
      renderEvidence();
    };
    row.addEventListener("click", choose);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
  });

  document.querySelectorAll("[data-breakpoint]").forEach((button) => {
    button.addEventListener("click", () => {
      evidenceState.selectedBreakpoint = button.dataset.breakpoint;
      renderEvidence();
    });
  });

  document.querySelectorAll("[data-open-provenance]").forEach((button) => {
    button.addEventListener("click", () => {
      evidenceState.provenanceOpen = true;
      provenanceDialog();
      bindProvenanceDialog();
    });
  });
}

function bindProvenanceDialog() {
  evidenceOverlayRoot.querySelector("[data-close-provenance]")?.addEventListener("click", closeProvenanceDialog);
  evidenceOverlayRoot.querySelector("[data-provenance-backdrop]")?.addEventListener("click", (event) => {
    if (event.target.matches("[data-provenance-backdrop]")) closeProvenanceDialog();
  });
}

function closeProvenanceDialog() {
  evidenceState.provenanceOpen = false;
  provenanceDialog();
  document.querySelector("[data-open-provenance]")?.focus();
}

function cycleEvidenceVariant(direction) {
  const index = evidenceVariants.findIndex((item) => item.key === evidenceState.variant);
  evidenceState.variant =
    evidenceVariants[(index + direction + evidenceVariants.length) % evidenceVariants.length].key;
  renderEvidence();
}

window.addEventListener("keydown", (event) => {
  const target = event.target;
  const editable =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    target?.isContentEditable;

  if (event.key === "Escape" && evidenceState.provenanceOpen) {
    event.preventDefault();
    closeProvenanceDialog();
    return;
  }
  if (editable || evidenceState.provenanceOpen) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    cycleEvidenceVariant(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    cycleEvidenceVariant(1);
  }
});

renderEvidence();
