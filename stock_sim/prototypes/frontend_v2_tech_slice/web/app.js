/* THROWAWAY PROTOTYPE — issue #33 embedded Web vertical slice. */

const ui = {
  app: document.querySelector("#app"),
  stateButtons: document.querySelector("#state-buttons"),
  stateLabel: document.querySelector("#state-label"),
  headline: document.querySelector("#status-headline"),
  detail: document.querySelector("#status-detail"),
  progress: document.querySelector("#progress"),
  progressValue: document.querySelector("#progress-value"),
  replicas: document.querySelector("#replicas"),
  filter: document.querySelector("#filter"),
  rows: document.querySelector("#candidate-rows"),
  canvas: document.querySelector("#timeline"),
  chartSummary: document.querySelector("#chart-summary"),
  semanticRows: document.querySelector("#semantic-rows"),
  details: document.querySelector("#details"),
  detailsTitle: document.querySelector("#details-title"),
  detailsCopy: document.querySelector("#details-copy"),
};

const view = {
  bridge: null,
  state: null,
  timeline: null,
  semanticRows: [],
  selectedCandidate: "",
  sortKey: "rank",
  descending: false,
  filter: "",
};

function filteredRows() {
  const needle = view.filter.trim().toLowerCase();
  const rows = [...(view.state?.candidates ?? [])];
  const selected = needle
    ? rows.filter((row) =>
        [
          row.candidateId,
          row.model,
          row.evidenceStatus,
          row.scenarioFamily,
        ]
          .join(" ")
          .toLowerCase()
          .includes(needle),
      )
    : rows;
  selected.sort((left, right) => {
    const a = left[view.sortKey];
    const b = right[view.sortKey];
    const order = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
    return view.descending ? -order : order;
  });
  return selected;
}

function renderStateButtons() {
  ui.stateButtons.replaceChildren(
    ...view.state.stateNames.map((stateName) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = stateName;
      button.setAttribute("aria-pressed", String(view.state.uiState === stateName));
      button.setAttribute("aria-label", `Show ${stateName} state`);
      button.addEventListener("click", () => view.bridge.setState(stateName));
      return button;
    }),
  );
}

function renderRows() {
  const rows = filteredRows();
  if (!rows.some((row) => row.candidateId === view.selectedCandidate)) {
    view.selectedCandidate = rows[0]?.candidateId ?? "";
  }
  ui.rows.replaceChildren(
    ...rows.map((row) => {
      const tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.dataset.candidate = row.candidateId;
      tr.setAttribute("aria-selected", String(row.candidateId === view.selectedCandidate));
      tr.setAttribute(
        "aria-label",
        `${row.rank} ${row.candidateId} ${row.returnPct} ${row.evidenceStatus} ${row.researchLock}`,
      );
      tr.innerHTML = `
        <td class="number">${row.rank}</td>
        <td><strong>${row.candidateId}</strong></td>
        <td>${row.model}</td>
        <td class="number">${row.returnPct >= 0 ? "+" : ""}${row.returnPct.toFixed(2)}%</td>
        <td class="number">${row.drawdownPct.toFixed(2)}%</td>
        <td class="status-${row.evidenceStatus}">${row.evidenceStatus}</td>
        <td>${row.researchLock}</td>
      `;
      tr.addEventListener("click", () => selectCandidate(row.candidateId));
      tr.addEventListener("dblclick", () => openDetails(row, false));
      tr.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          openDetails(row, true);
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const direction = event.key === "ArrowDown" ? 1 : -1;
          const next = rows[Math.max(0, Math.min(rows.length - 1, rows.indexOf(row) + direction))];
          selectCandidate(next.candidateId);
          requestAnimationFrame(() =>
            ui.rows.querySelector(`[data-candidate="${next.candidateId}"]`)?.focus(),
          );
        }
      });
      return tr;
    }),
  );
}

function selectCandidate(candidateId) {
  view.selectedCandidate = candidateId;
  for (const row of ui.rows.querySelectorAll("tr")) {
    row.setAttribute("aria-selected", String(row.dataset.candidate === candidateId));
  }
}

function openDetails(row, keyboard) {
  ui.details.classList.toggle("no-motion", keyboard);
  ui.detailsTitle.textContent = `${row.candidateId} · ${row.evidenceStatus}`;
  ui.detailsCopy.textContent =
    `${row.scenarioFamily}. Return ${row.returnPct >= 0 ? "+" : ""}${row.returnPct.toFixed(2)}% ` +
    `does not override the ${row.researchLock} Research Acceptance Lock. ` +
    "The claim, support, contradiction, scope, provenance, and next action remain read-only.";
  ui.details.showModal();
  if (keyboard) {
    requestAnimationFrame(() => ui.details.classList.remove("no-motion"));
  }
}

function renderSemanticRows() {
  ui.semanticRows.replaceChildren(
    ...view.semanticRows.map((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.step}</td><td>${row.candidate}</td><td>${row.baseline}</td><td>${row.stress}</td>`;
      return tr;
    }),
  );
}

function drawTimeline() {
  if (!view.timeline) return;
  const ratio = window.devicePixelRatio || 1;
  const rect = ui.canvas.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width * ratio));
  const height = Math.max(1, Math.floor(rect.height * ratio));
  if (ui.canvas.width !== width || ui.canvas.height !== height) {
    ui.canvas.width = width;
    ui.canvas.height = height;
  }
  const context = ui.canvas.getContext("2d");
  context.clearRect(0, 0, width, height);
  const series = [
    [view.timeline.candidate, "#82dec0", 1.4],
    [view.timeline.baseline, "#9fbfff", 1],
    [view.timeline.stress, "#ff928d", 1],
  ];
  const all = series.flatMap(([values]) => values);
  const minimum = Math.min(...all);
  const maximum = Math.max(...all);
  const span = Math.max(0.001, maximum - minimum);
  context.strokeStyle = "#24303b";
  context.lineWidth = 1;
  for (const fraction of [0.25, 0.5, 0.75]) {
    context.beginPath();
    context.moveTo(0, height * fraction);
    context.lineTo(width, height * fraction);
    context.stroke();
  }
  for (const [values, color, lineWidth] of series) {
    context.beginPath();
    context.strokeStyle = color;
    context.lineWidth = lineWidth * ratio;
    values.forEach((value, index) => {
      const x = (index / Math.max(1, values.length - 1)) * width;
      const y = height - ((value - minimum) / span) * height;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
  }
  const candidate = view.timeline.candidate;
  const baseline = view.timeline.baseline;
  const stress = view.timeline.stress;
  ui.chartSummary.textContent =
    `Text equivalent: ${view.timeline.sourcePointCount.toLocaleString()} source points; ` +
    `candidate ${Math.min(...candidate).toFixed(2)}–${Math.max(...candidate).toFixed(2)}; ` +
    `baseline ${Math.min(...baseline).toFixed(2)}–${Math.max(...baseline).toFixed(2)}; ` +
    `stress ${Math.min(...stress).toFixed(2)}–${Math.max(...stress).toFixed(2)}; first fee breakpoint 1.6×.`;
}

function renderState(state, eventId = 0) {
  const timeline = view.timeline;
  const stateNames = view.state?.stateNames ?? state.stateNames;
  view.state = { ...state, stateNames };
  view.timeline = timeline ?? state.timeline;
  view.semanticRows = view.semanticRows.length ? view.semanticRows : (state.semanticRows ?? []);
  ui.stateLabel.textContent = `${state.uiState.toUpperCase()} · revision ${state.revision} · ${state.freshness}`;
  ui.headline.textContent = state.headline;
  ui.detail.textContent = state.detail;
  ui.progress.value = state.progressPct;
  ui.progressValue.textContent = `${state.progressPct}%`;
  ui.replicas.textContent = `${state.replicas} replicas`;
  renderStateButtons();
  renderRows();
  drawTimeline();
  renderSemanticRows();
  ui.app.setAttribute("aria-busy", "false");
  if (eventId) {
    requestAnimationFrame(() => view.bridge.reportPaint(eventId));
  }
}

ui.filter.addEventListener("input", () => {
  view.filter = ui.filter.value;
  renderRows();
});

for (const button of document.querySelectorAll("[data-sort]")) {
  button.addEventListener("click", () => {
    const key = button.dataset.sort;
    if (view.sortKey === key) view.descending = !view.descending;
    else {
      view.sortKey = key;
      view.descending = false;
    }
    renderRows();
  });
}

document.querySelector("#close-details").addEventListener("click", () => ui.details.close());
document.querySelector("#previous-tech").addEventListener("click", () => view.bridge.chooseTechnology("qml"));
document.querySelector("#next-tech").addEventListener("click", () => view.bridge.chooseTechnology("widgets"));

document.addEventListener("keydown", (event) => {
  const editing = event.target.matches("input, textarea, [contenteditable]");
  if (event.ctrlKey && event.key.toLowerCase() === "k") {
    event.preventDefault();
    ui.filter.focus();
  }
  if (!editing && event.key === "ArrowLeft") view.bridge.chooseTechnology("qml");
  if (!editing && event.key === "ArrowRight") view.bridge.chooseTechnology("widgets");
  if (!editing && event.key === "Escape" && ui.details.open) ui.details.close();
});

window.addEventListener("resize", () => requestAnimationFrame(drawTimeline));

new QWebChannel(qt.webChannelTransport, (channel) => {
  view.bridge = channel.objects.sliceBridge;
  const initial = JSON.parse(view.bridge.initialPayload);
  view.timeline = initial.timeline;
  view.semanticRows = initial.semanticRows;
  renderState(initial);
  view.bridge.stateReady.connect((payload, eventId) => {
    renderState(JSON.parse(payload), eventId);
  });
  view.bridge.ready();
});
