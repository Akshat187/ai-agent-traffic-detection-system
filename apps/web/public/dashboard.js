/**
 * WebSense Dashboard Client Application
 * Powers real-time analytics, 2D mouse trajectory visualizer,
 * FP-Agent Experiment Lab, and Adversarial Attack Simulation.
 */

let timelineChart = null;
let distributionChart = null;
let keystrokeChart = null;

let allSessions = [];
let selectedSession = null;
let animationFrameId = null;

let selectedSite = "ALL";

document.addEventListener("DOMContentLoaded", function () {
  initTabs();
  initCharts();
  fetchSites();
  fetchOverviewStats();
  fetchSessions();

  // Poll for updates every 4 seconds
  setInterval(() => {
    fetchOverviewStats();
    fetchSessions();
  }, 4000);

  // Setup Event Listeners
  const siteSelect = document.getElementById("global-site-select");
  if (siteSelect) {
    siteSelect.addEventListener("change", function(e) {
      selectedSite = e.target.value;
      fetchOverviewStats();
      fetchSessions();
    });
  }

  const seedBtn = document.getElementById("seed-demo-btn");
  if (seedBtn) seedBtn.addEventListener("click", handleSeedDemo);

  const filterSelect = document.getElementById("session-filter-class");
  if (filterSelect) filterSelect.addEventListener("change", applySessionFilters);

  const searchInput = document.getElementById("session-search-input");
  if (searchInput) searchInput.addEventListener("input", applySessionFilters);

  const refreshBtn = document.getElementById("refresh-sessions-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", () => { fetchSessions(); fetchOverviewStats(); });

  const explorerSelect = document.getElementById("explorer-session-select");
  if (explorerSelect) explorerSelect.addEventListener("change", (e) => loadSessionDetails(e.target.value));

  const playBtn = document.getElementById("trajectory-play-btn");
  if (playBtn) playBtn.addEventListener("click", playTrajectoryAnimation);

  const resetBtn = document.getElementById("trajectory-reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", drawStaticTrajectory);

  const benchmarkBtn = document.getElementById("run-benchmark-btn");
  if (benchmarkBtn) benchmarkBtn.addEventListener("click", runBenchmark);

  // Preload latest experiment lab benchmarks
  loadLabData();
});

// Load Registered Sites
async function fetchSites() {
  try {
    const res = await fetch("/api/v1/sites");
    if (!res.ok) return;
    const data = await res.json();
    const select = document.getElementById("global-site-select");
    if (!select) return;

    const currentVal = select.value || "ALL";
    select.innerHTML = '<option value="ALL">All Registered Sites</option>';

    (data.sites || []).forEach(site => {
      const opt = document.createElement("option");
      opt.value = site.site_id;
      opt.textContent = `${site.name} (${site.site_id.substring(0, 10)})`;
      select.appendChild(opt);
    });

    select.value = currentVal;
  } catch (err) {
    console.warn("Failed to fetch sites:", err);
  }
}

// Fetch Overview Stats
async function fetchOverviewStats() {
  try {
    const url = selectedSite && selectedSite !== "ALL" 
      ? `/api/v1/stats/overview?site_id=${encodeURIComponent(selectedSite)}`
      : "/api/v1/stats/overview";

    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("stat-total").textContent = data.total_sessions || 0;
    document.getElementById("stat-human").textContent = `${data.human_count} (${data.human_pct.toFixed(1)}%)`;
    document.getElementById("stat-bot").textContent = `${(data.automation_count ?? data.bot_count)} (${(data.automation_pct ?? data.bot_pct).toFixed(1)}%)`;
    document.getElementById("stat-agent").textContent = `${(data.agentic_count ?? data.ai_agent_count)} (${(data.agentic_pct ?? data.ai_agent_pct).toFixed(1)}%)`;
    document.getElementById("stat-conf").textContent = `${data.avg_confidence.toFixed(1)}%`;
    document.getElementById("stat-risk").textContent = `Avg Risk: ${data.avg_risk_score.toFixed(0)} / 100`;

    document.getElementById("dist-human-val").textContent = `${data.human_pct.toFixed(0)}%`;
    document.getElementById("dist-bot-val").textContent = `${(data.automation_pct ?? data.bot_pct).toFixed(0)}%`;
    document.getElementById("dist-agent-val").textContent = `${(data.agentic_pct ?? data.ai_agent_pct).toFixed(0)}%`;

    if (distributionChart) {
      distributionChart.data.datasets[0].data = [
        data.human_count,
        (data.automation_count ?? data.bot_count),
        (data.agentic_count ?? data.ai_agent_count),
        data.uncertain_count
      ];
      distributionChart.update();
    }

    renderRecentOverviewTable(data.recent_activity || []);
  } catch (err) {
    console.warn("Failed to fetch stats:", err);
  }
}

function renderRecentOverviewTable(sessions) {
  const tbody = document.getElementById("overview-recent-tbody");
  if (!tbody) return;

  if (sessions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="py-8 text-center text-slate-400">No sessions recorded yet for this site. Interact with the Honey Sites or embedded pages!</td></tr>`;
    return;
  }

  tbody.innerHTML = sessions.slice(0, 7).map(s => {
    const badgeClass = getBadgeClass(s.predicted_label);
    const riskColor = s.risk_score > 60 ? 'text-rose-600 font-bold' : s.risk_score > 30 ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold';
    const isSynthetic = s.is_synthetic || s.data_source === "synthetic_demo";
    const srcTag = isSynthetic
      ? `<span class="px-2 py-0.5 rounded-full text-[10px] bg-slate-100 text-slate-500 font-bold border border-slate-200">DEMO</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[10px] bg-emerald-50 text-emerald-700 font-bold border border-emerald-200">LIVE SDK</span>`;

    return `
      <tr class="hover:bg-slate-50 transition border-b border-slate-100">
        <td class="py-3 px-3.5 font-mono font-bold text-indigo-600 cursor-pointer hover:underline" onclick="inspectSession('${s.session_id}')">${s.session_id.substring(0, 16)}... ${srcTag}</td>
        <td class="py-3 px-3.5 capitalize font-medium text-slate-800">${s.task}</td>
        <td class="py-3 px-3.5"><span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold ${badgeClass}">${s.predicted_label}</span></td>
        <td class="py-3 px-3.5 font-mono text-slate-700">${s.confidence.toFixed(1)}%</td>
        <td class="py-3 px-3.5 font-mono ${riskColor}">${s.risk_score.toFixed(0)}/100</td>
        <td class="py-3 px-3.5 font-mono text-xs">${s.webdriver_flag ? '<span class="text-rose-600 font-bold">TRUE</span>' : '<span class="text-slate-400">false</span>'}</td>
        <td class="py-3 px-3.5 text-slate-600 truncate max-w-xs">${escapeHTML(s.explanation_snippet || '')}</td>
        <td class="py-3 px-3.5 text-right">
          <button onclick="inspectSession('${s.session_id}')" class="px-3 py-1.5 bg-slate-100 hover:bg-indigo-50 border border-slate-200 text-slate-700 hover:text-indigo-600 rounded-xl text-xs font-semibold transition shadow-sm">Inspect</button>
        </td>
      </tr>
    `;
  }).join("");
}

// Fetch All Sessions (respects selectedSite global filter)
async function fetchSessions() {
  try {
    const url = selectedSite && selectedSite !== "ALL"
      ? `/api/v1/sessions?limit=100&site_id=${encodeURIComponent(selectedSite)}`
      : "/api/v1/sessions?limit=100";

    const res = await fetch(url);
    if (!res.ok) return;
    allSessions = await res.json();
    applySessionFilters();
    updateExplorerDropdown(allSessions);
  } catch (err) {
    console.warn("Failed to fetch sessions:", err);
  }
}

function applySessionFilters() {
  const filterClass = document.getElementById("session-filter-class")?.value || "ALL";
  const search = document.getElementById("session-search-input")?.value.toLowerCase().trim() || "";

  const filtered = allSessions.filter(s => {
    if (filterClass !== "ALL" && s.predicted_label !== filterClass) return false;
    if (search && !s.session_id.toLowerCase().includes(search) && !s.task.toLowerCase().includes(search)) return false;
    return true;
  });

  const tbody = document.getElementById("sessions-table-tbody");
  if (!tbody) return;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="py-8 text-center text-slate-400">No matching sessions found.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(s => {
    // Client-side integrity assertion: badge vs explanation must agree.
    assertVerdictConsistency(s);
    const badgeClass = getBadgeClass(s.predicted_label);
    const gtBadge = s.ground_truth_label
      ? `<span class="px-2 py-0.5 rounded-full text-[10px] bg-slate-100 text-slate-700 border border-slate-200 font-mono font-semibold">${s.ground_truth_label}</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[10px] bg-amber-50 text-amber-700 border border-amber-200 font-semibold" title="Real visitor — no ground-truth label available">LIVE &middot; UNVERIFIED</span>`;
    const riskColor = s.risk_score > 60 ? 'text-rose-600 font-bold' : s.risk_score > 30 ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold';
    const isSynthetic = s.is_synthetic || s.data_source === "synthetic_demo";
    const srcTag = isSynthetic
      ? `<span class="px-2 py-0.5 rounded-full text-[10px] bg-slate-100 text-slate-500 font-bold border border-slate-200">DEMO</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[10px] bg-emerald-50 text-emerald-700 font-bold border border-emerald-200">LIVE SDK</span>`;

    const siteDisplay = s.site_id ? s.site_id.substring(0, 14) : "default";

    // Duration display: prefer active_duration_ms; show raw tab time in tooltip if it diverges
    const activeSec = s.active_duration_ms != null ? s.active_duration_ms / 1000 : s.duration_ms / 1000;
    const rawSec    = s.duration_ms / 1000;
    const showTabLine = s.active_duration_ms != null && rawSec > activeSec * 1.2 && rawSec > 30;
    const tabLabel = showTabLine
      ? `<br><span class="text-slate-400 text-[10px]" title="Raw tab lifetime">Tab: ${rawSec >= 3600 ? (rawSec/3600).toFixed(1)+'h' : rawSec >= 60 ? (rawSec/60).toFixed(1)+'m' : rawSec.toFixed(0)+'s'}</span>`
      : '';
    const durationCell = `<span class="font-mono text-slate-700">Active: ${activeSec >= 60 ? (activeSec/60).toFixed(1)+'m' : activeSec.toFixed(1)+'s'}</span>${tabLabel}`;


    return `
      <tr class="hover:bg-slate-50 transition border-b border-slate-100">
        <td class="py-3 px-3.5 font-mono font-bold text-indigo-600 cursor-pointer hover:underline" onclick="inspectSession('${s.session_id}')">${s.session_id}</td>
        <td class="py-3 px-3.5 font-mono text-[11px] text-slate-600"><span class="font-semibold text-slate-800">${siteDisplay}</span><br>${srcTag}</td>
        <td class="py-3 px-3.5 capitalize font-medium text-slate-800">${s.task}</td>
        <td class="py-3 px-3.5">${durationCell}</td>
        <td class="py-3 px-3.5">${gtBadge}</td>
        <td class="py-3 px-3.5"><span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold ${badgeClass}">${s.predicted_label}</span></td>
        <td class="py-3 px-3.5 font-mono text-slate-700">${s.confidence.toFixed(1)}%</td>
        <td class="py-3 px-3.5 font-mono ${riskColor}">${s.risk_score.toFixed(0)}/100</td>
        <td class="py-3 px-3.5 text-slate-600 truncate max-w-xs">${escapeHTML(s.explanation_snippet || '')}</td>
        <td class="py-3 px-3.5 text-right">
          <button onclick="inspectSession('${s.session_id}')" class="px-3 py-1.5 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 text-indigo-700 rounded-xl text-xs font-semibold transition shadow-sm">Explore</button>
        </td>
      </tr>
    `;
  }).join("");
}

// Tab Navigation
function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", function () {
      tabs.forEach(t => t.classList.remove("active"));
      this.classList.add("active");
      const targetId = this.dataset.target;
      document.querySelectorAll(".tab-content").forEach(content => {
        if (content.id === targetId) {
          content.classList.remove("hidden");
          content.classList.add("animate-fade-in");
          if (targetId === "tab-experiments") {
            loadLabData();
          }
        } else {
          content.classList.add("hidden");
        }
      });
    });
  });
}

// Chart Initializations
function initCharts() {
  // 1. Timeline Chart
  const ctxTimeline = document.getElementById("chart-timeline");
  if (ctxTimeline) {
    timelineChart = new Chart(ctxTimeline, {
      type: "line",
      data: {
        labels: ["T-5", "T-4", "T-3", "T-2", "T-1", "Now"],
        datasets: [
          { label: "Human", data: [4, 6, 8, 5, 9, 12], borderColor: "#059669", backgroundColor: "rgba(5, 150, 105, 0.1)", tension: 0.3, fill: false, borderWidth: 2.5 },
          { label: "Traditional Automation", data: [2, 3, 5, 2, 4, 3], borderColor: "#dc2626", backgroundColor: "rgba(220, 38, 38, 0.1)", tension: 0.3, fill: false, borderWidth: 2.5 },
          { label: "Agentic AI", data: [1, 2, 4, 3, 5, 7], borderColor: "#d97706", backgroundColor: "rgba(217, 119, 6, 0.1)", tension: 0.3, fill: false, borderWidth: 2.5 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { 
          legend: { 
            labels: { 
              color: "#475569", 
              font: { family: "'Plus Jakarta Sans', sans-serif", size: 12, weight: 600 },
              usePointStyle: true,
              pointStyle: 'circle'
            } 
          } 
        },
        scales: {
          x: { grid: { color: "#f1f5f9" }, ticks: { color: "#64748b", font: { family: "'JetBrains Mono', monospace", size: 11 } } },
          y: { grid: { color: "#f1f5f9" }, ticks: { color: "#64748b", font: { family: "'JetBrains Mono', monospace", size: 11 }, stepSize: 1 } }
        }
      }
    });
  }

  // 2. Distribution Doughnut Chart
  const ctxDist = document.getElementById("chart-distribution");
  if (ctxDist) {
    distributionChart = new Chart(ctxDist, {
      type: "doughnut",
      data: {
        labels: ["Human", "Automation", "Agentic AI", "Uncertain"],
        datasets: [{
          data: [45, 30, 20, 5],
          backgroundColor: ["#10b981", "#ef4444", "#f59e0b", "#94a3b8"],
          borderWidth: 3,
          borderColor: "#ffffff"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        cutout: "72%"
      }
    });
  }

  // 3. Keystroke Chart
  const ctxKey = document.getElementById("chart-keystrokes");
  if (ctxKey) {
    keystrokeChart = new Chart(ctxKey, {
      type: "bar",
      data: {
        labels: ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8"],
        datasets: [{
          label: "Latency (ms)",
          data: [120, 150, 110, 240, 130, 180, 95, 140],
          backgroundColor: "#6366f1",
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#64748b", font: { family: "'JetBrains Mono', monospace", size: 10 } } },
          y: { grid: { color: "#f1f5f9" }, ticks: { color: "#64748b", font: { family: "'JetBrains Mono', monospace", size: 10 } } }
        }
      }
    });
  }
}

// assertVerdictConsistency — checks that the badge label (predicted_label) matches
// the explanation text for a given session summary. Logs a warning if they diverge.
// This is a client-side guard that complements the server-side integrity check added
// to the ingest endpoint.
function assertVerdictConsistency(session) {
  const label = (session.predicted_label || '').toUpperCase();
  const explanation = (session.explanation_snippet || '').toLowerCase();
  const labelPhrases = {
    'HUMAN': 'human',
    'TRADITIONAL_AUTOMATION': 'traditional automation',
    'AGENTIC_AI': 'agentic',
    'UNCERTAIN': 'uncertain',
  };
  const expected = labelPhrases[label];
  if (expected && explanation && !explanation.includes(expected)) {
    console.error(
      '[VERDICT MISMATCH] session=%s badge=%s explanation_snippet=%s',
      session.session_id, label, explanation.substring(0, 120)
    );
    return false;
  }
  return true;
}

function updateExplorerDropdown(sessions) {
  const select = document.getElementById("explorer-session-select");
  if (!select) return;
  const curr = select.value;
  select.innerHTML = '<option value="">Choose session to explore...</option>' +
    sessions.map(s => `<option value="${s.session_id}">${s.session_id.substring(0, 18)}... (${s.predicted_label} - ${s.task})</option>`).join("");
  if (curr) select.value = curr;
}

// Session Explorer Logic
async function inspectSession(sessionId) {
  const explorerTab = document.querySelector("[data-target='tab-explorer']");
  if (explorerTab) explorerTab.click();
  const select = document.getElementById("explorer-session-select");
  if (select) select.value = sessionId;
  await loadSessionDetails(sessionId);
}

async function loadSessionDetails(sessionId) {
  if (!sessionId) return;
  try {
    const res = await fetch(`/api/v1/sessions/${sessionId}`);
    if (!res.ok) return;
    const detail = await res.json();
    selectedSession = detail;

    document.getElementById("explorer-session-id").textContent = detail.session.session_id;
    const badge = document.getElementById("explorer-verdict-badge");
    if (badge) {
      badge.textContent = detail.session.predicted_label;
      badge.className = `px-2.5 py-0.5 rounded-full text-xs font-bold ${getBadgeClass(detail.session.predicted_label)}`;
    }

    // 5 Layer summary
    const v = detail.verdict;
    document.getElementById("l1-badge").textContent = `Score: ${v.l1_rule_score}`;
    document.getElementById("l1-badge").className = v.l1_rule_score > 50 ? "font-bold text-rose-700 px-2.5 py-1 rounded-lg bg-rose-50 border border-rose-200" : "font-bold text-emerald-700 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200";
    
    document.getElementById("l2-badge").textContent = `Pred: ${v.l2_ml_pred}`;
    document.getElementById("l2-badge").className = v.l2_ml_pred === "HUMAN" ? "font-bold text-emerald-700 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200" : "font-bold text-indigo-700 px-2.5 py-1 rounded-lg bg-indigo-50 border border-indigo-200";

    document.getElementById("l3-badge").textContent = v.l3_is_anomaly ? "OUTLIER" : `Normal (${v.l3_anomaly_score > 0 ? '+' : ''}${v.l3_anomaly_score})`;
    document.getElementById("l3-badge").className = v.l3_is_anomaly ? "font-bold text-rose-700 px-2.5 py-1 rounded-lg bg-rose-50 border border-rose-200" : "font-bold text-slate-700 px-2.5 py-1 rounded-lg bg-slate-100 border border-slate-200";

    document.getElementById("l4-badge").textContent = v.l4_is_replay ? `REPLAY (${(v.l4_replay_similarity * 100).toFixed(0)}%)` : "No Replay";
    document.getElementById("l4-badge").className = v.l4_is_replay ? "font-bold text-rose-700 px-2.5 py-1 rounded-lg bg-rose-50 border border-rose-200" : "font-bold text-emerald-700 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200";

    document.getElementById("l5-badge").textContent = v.l5_context_valid ? "Valid ✓" : "Violation ⚠️";
    document.getElementById("l5-badge").className = v.l5_context_valid ? "font-bold text-emerald-700 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200" : "font-bold text-rose-700 px-2.5 py-1 rounded-lg bg-rose-50 border border-rose-200";

    // Explainability
    document.getElementById("explorer-explanation-text").textContent = v.human_explanation;
    const sigList = document.getElementById("explorer-signals-list");
    if (sigList) {
      const pos = (v.contributing_signals || []).map(s => `<div class="text-rose-700 font-semibold">+ ${escapeHTML(s)}</div>`).join("");
      const neg = (v.counter_signals || []).map(s => `<div class="text-emerald-700 font-semibold">- ${escapeHTML(s)}</div>`).join("");
      sigList.innerHTML = pos + neg || '<div class="text-slate-500">No strong anomalies flagged.</div>';
    }

    // Kinematic Feature Grid
    const f = detail.features;
    document.getElementById("f-mean-vel").textContent = `${f.mean_velocity || 0} px/s`;
    document.getElementById("f-straightness").textContent = f.straightness_ratio || "1.00";
    document.getElementById("f-micro-corr").textContent = f.micro_corrections || 0;
    document.getElementById("f-key-cv").textContent = f.key_latency_cv || "0.00";

    // Update Keystroke Chart
    const kbEvents = detail.telemetry?.keyboard_events || [];
    if (keystrokeChart && kbEvents.length > 0) {
      const latencies = kbEvents.slice(0, 15).map((k, i) => k.interval || 100);
      keystrokeChart.data.labels = latencies.map((_, i) => `K${i + 1}`);
      keystrokeChart.data.datasets[0].data = latencies;
      keystrokeChart.update();
    }

    drawStaticTrajectory();
  } catch (err) {
    console.warn("Failed to load details:", err);
  }
}

// 2D Mouse Trajectory Replay (Canvas)
function drawStaticTrajectory() {
  if (animationFrameId) cancelAnimationFrame(animationFrameId);
  const canvas = document.getElementById("trajectory-canvas");
  if (!canvas || !selectedSession) return;
  const ctx = canvas.getContext("2d");
  
  canvas.width = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;

  ctx.fillStyle = "#090d16";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const mouseEvents = selectedSession.telemetry?.mouse_events || [];
  const clicks = selectedSession.telemetry?.click_events || [];

  document.getElementById("canvas-point-count").textContent = mouseEvents.length;
  document.getElementById("canvas-path-len").textContent = `${selectedSession.features?.path_length || 0}px`;
  document.getElementById("canvas-straightness").textContent = selectedSession.features?.straightness_ratio || "1.00";

  if (mouseEvents.length < 2) {
    ctx.fillStyle = "#64748b";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No mouse trajectory data recorded for this session", canvas.width / 2, canvas.height / 2);
    return;
  }

  // Draw grid
  drawCanvasGrid(ctx, canvas.width, canvas.height);

  // Normalize coordinates to canvas space
  const minX = Math.min(...mouseEvents.map(e => e.x));
  const maxX = Math.max(...mouseEvents.map(e => e.x));
  const minY = Math.min(...mouseEvents.map(e => e.y));
  const maxY = Math.max(...mouseEvents.map(e => e.y));
  const rangeX = Math.max(10, maxX - minX);
  const rangeY = Math.max(10, maxY - minY);

  function mapX(x) { return 40 + ((x - minX) / rangeX) * (canvas.width - 80); }
  function mapY(y) { return 40 + ((y - minY) / rangeY) * (canvas.height - 80); }

  // Draw Path Segments with velocity gradient
  ctx.lineWidth = 2.5;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  for (let i = 1; i < mouseEvents.length; i++) {
    const p1 = mouseEvents[i - 1];
    const p2 = mouseEvents[i];
    const dt = Math.max(1, p2.t - p1.t);
    const dist = Math.hypot(p2.x - p1.x, p2.y - p1.y);
    const vel = (dist / dt) * 1000;

    ctx.beginPath();
    ctx.moveTo(mapX(p1.x), mapY(p1.y));
    ctx.lineTo(mapX(p2.x), mapY(p2.y));

    // Color by velocity
    if (vel < 200) ctx.strokeStyle = "#38bdf8"; // sky blue / low speed
    else if (vel < 700) ctx.strokeStyle = "#10b981"; // emerald / cruising
    else ctx.strokeStyle = "#f43f5e"; // rose / fast spike

    ctx.stroke();
  }

  // Draw Clicks
  clicks.forEach(clk => {
    const cx = mapX(clk.x);
    const cy = mapY(clk.y);
    ctx.beginPath();
    ctx.arc(cx, cy, 6, 0, 2 * Math.PI);
    ctx.fillStyle = "#f59e0b";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
  });
}

function playTrajectoryAnimation() {
  if (!selectedSession) return;
  const mouseEvents = selectedSession.telemetry?.mouse_events || [];
  if (mouseEvents.length < 2) return;

  const canvas = document.getElementById("trajectory-canvas");
  const ctx = canvas.getContext("2d");
  
  canvas.width = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;

  const minX = Math.min(...mouseEvents.map(e => e.x));
  const maxX = Math.max(...mouseEvents.map(e => e.x));
  const minY = Math.min(...mouseEvents.map(e => e.y));
  const maxY = Math.max(...mouseEvents.map(e => e.y));
  const rangeX = Math.max(10, maxX - minX);
  const rangeY = Math.max(10, maxY - minY);

  function mapX(x) { return 40 + ((x - minX) / rangeX) * (canvas.width - 80); }
  function mapY(y) { return 40 + ((y - minY) / rangeY) * (canvas.height - 80); }

  let currIdx = 0;
  const total = mouseEvents.length;

  function step() {
    ctx.fillStyle = "#090d16";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawCanvasGrid(ctx, canvas.width, canvas.height);

    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";

    for (let i = 1; i <= currIdx; i++) {
      const p1 = mouseEvents[i - 1];
      const p2 = mouseEvents[i];
      ctx.beginPath();
      ctx.moveTo(mapX(p1.x), mapY(p1.y));
      ctx.lineTo(mapX(p2.x), mapY(p2.y));
      ctx.strokeStyle = "#38bdf8";
      ctx.stroke();
    }

    // Current cursor circle
    const curr = mouseEvents[currIdx];
    ctx.beginPath();
    ctx.arc(mapX(curr.x), mapY(curr.y), 5, 0, 2 * Math.PI);
    ctx.fillStyle = "#38bdf8";
    ctx.fill();

    currIdx += 2;
    if (currIdx < total) {
      animationFrameId = requestAnimationFrame(step);
    } else {
      drawStaticTrajectory();
    }
  }

  step();
}

function drawCanvasGrid(ctx, w, h) {
  ctx.strokeStyle = "#1e293b";
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += 40) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = 0; y < h; y += 40) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
}

// Seed Demo Data with Active Spinner & Progress State
async function handleSeedDemo() {
  const btn = document.getElementById("seed-demo-btn");
  const origHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `
      <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <span>Synthesizing & Classifying 90 Sessions...</span>
    `;
    btn.classList.add("opacity-80", "cursor-not-allowed");
  }
  try {
    const res = await fetch("/api/v1/seed/demo", { method: "POST" });
    const data = await res.json();
    await fetchOverviewStats();
    await fetchSessions();
    await loadLabData();
    
    // Quick notification banner/toast
    const notice = document.createElement("div");
    notice.className = "fixed bottom-5 right-5 bg-white border border-emerald-300 text-emerald-900 px-5 py-3.5 rounded-2xl shadow-xl z-50 flex items-center gap-3 animate-fade-in font-medium";
    notice.innerHTML = `<span class="text-emerald-600 font-bold text-lg">✓</span><span>Generated <strong>${data.count || 90}</strong> ground-truth sessions across all archetypes and tasks!</span>`;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 4000);
  } catch (err) {
    alert("Failed to seed demo data: " + err);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("opacity-80", "cursor-not-allowed");
      btn.innerHTML = origHtml || '<span>⚡</span><span>Load Sample Data (Offline Demo)</span>';
    }
  }
}

// Render Experiment Lab Data (Cards, Confusion Matrix, Feature Importance)
function renderExperimentData(data) {
  if (!data) return;

  // Update experiment metric cards
  if (data.experiments && data.experiments.length > 0) {
    const expA = data.experiments.find(e => e.feature_set === "browser_only");
    const expB = data.experiments.find(e => e.feature_set === "mouse_only" || e.feature_set === "behavioral_all");
    const expC = data.experiments.find(e => e.feature_set === "combined");
    const expD = data.experiments.find(e => e.id === data.best_experiment) || data.experiments[data.experiments.length - 1];

    if (expA) {
      const accEl = document.getElementById("exp-a-acc");
      const f1El = document.getElementById("exp-a-f1");
      if (accEl) accEl.textContent = `${(expA.accuracy * 100).toFixed(1)}%`;
      if (f1El) f1El.textContent = (expA.f1_macro || 0).toFixed(2);
    }
    if (expB) {
      const accEl = document.getElementById("exp-b-acc");
      const f1El = document.getElementById("exp-b-f1");
      if (accEl) accEl.textContent = `${(expB.accuracy * 100).toFixed(1)}%`;
      if (f1El) f1El.textContent = (expB.f1_macro || 0).toFixed(2);
    }
    if (expC) {
      const accEl = document.getElementById("exp-c-acc");
      const f1El = document.getElementById("exp-c-f1");
      if (accEl) accEl.textContent = `${(expC.accuracy * 100).toFixed(1)}%`;
      if (f1El) f1El.textContent = (expC.f1_macro || 0).toFixed(2);
    }
    if (expD) {
      const accEl = document.getElementById("exp-d-acc");
      const f1El = document.getElementById("exp-d-f1");
      if (accEl) accEl.textContent = `${(expD.accuracy * 100).toFixed(1)}%`;
      if (f1El) f1El.textContent = (expD.f1_macro || 0).toFixed(2);
    }
  }

  // Update Confusion Matrix if available
  if (data.confusion_matrix && data.confusion_matrix.length >= 3) {
    const cm = data.confusion_matrix;
    const setCell = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    setCell("cm-hh", cm[0]?.[0] ?? 0);
    setCell("cm-hb", cm[0]?.[1] ?? 0);
    setCell("cm-ha", cm[0]?.[2] ?? 0);

    setCell("cm-bh", cm[1]?.[0] ?? 0);
    setCell("cm-bb", cm[1]?.[1] ?? 0);
    setCell("cm-ba", cm[1]?.[2] ?? 0);

    setCell("cm-ah", cm[2]?.[0] ?? 0);
    setCell("cm-ab", cm[2]?.[1] ?? 0);
    setCell("cm-aa", cm[2]?.[2] ?? 0);
  }

  // Update Feature Importance Bars
  const featContainer = document.getElementById("feature-importance-bars");
  if (featContainer && data.feature_importance && data.feature_importance.length > 0) {
    const maxImp = Math.max(...data.feature_importance.map(f => f.importance || 0), 0.01);
    featContainer.innerHTML = data.feature_importance.slice(0, 8).map(f => {
      const pct = (f.importance * 100).toFixed(1);
      const barWidth = Math.max(4, Math.min(100, ((f.importance || 0) / maxImp) * 100));
      return `
        <div class="space-y-1.5">
          <div class="flex justify-between text-xs">
            <span class="font-mono text-slate-700 font-semibold">${escapeHTML(f.feature)}</span>
            <span class="text-indigo-600 font-mono font-bold">${pct}%</span>
          </div>
          <div class="w-full h-2.5 bg-slate-200 rounded-full overflow-hidden">
            <div class="h-full bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full transition-all duration-500" style="width: ${barWidth}%"></div>
          </div>
        </div>
      `;
    }).join("");
  }
}

// Automatically load latest lab benchmark metrics
async function loadLabData() {
  try {
    const res = await fetch("/api/v1/experiments/latest");
    if (!res.ok) return;
    const data = await res.json();
    renderExperimentData(data);
  } catch (err) {
    console.warn("Could not auto-load experiment lab data:", err);
  }
}

// Experiment Lab Benchmark Runner
async function runBenchmark() {
  const btn = document.getElementById("run-benchmark-btn");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `
      <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <span>Evaluating 6-Way Comparative Benchmark...</span>
    `;
  }
  try {
    const res = await fetch("/api/v1/experiments/run", { method: "POST" });
    if (!res.ok) {
      const errData = await res.json();
      alert(`Benchmark error: ${errData.detail?.message || res.statusText}`);
      return;
    }
    const data = await res.json();
    renderExperimentData(data);
    alert(`Benchmark completed! Evaluated on ${data.total_sessions} real sessions across visitor-grouped splits.`);
  } catch (err) {
    alert("Benchmark failed: " + err);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⚡ Run Full Benchmark";
    }
  }
}


// Adversarial Attack Simulation
async function runAdversarialSimulation(attackType) {
  const resultsBox = document.getElementById("adversarial-results-box");
  if (!resultsBox) return;

  resultsBox.classList.remove("hidden");
  resultsBox.scrollIntoView({ behavior: "smooth" });

  // Attacks 1–4 intend to look like bots/humans to evade detection.
  // Attack 5 (simulated_agent) is "caught" if classified as AGENTIC_AI.
  const ATTACK_CATCH_VERDICT = {
    simple_bot:         "TRADITIONAL_AUTOMATION",
    synthetic_jitter:   "TRADITIONAL_AUTOMATION",
    jitter_evasion:     "TRADITIONAL_AUTOMATION",
    cross_context:      "TRADITIONAL_AUTOMATION",
    evasive_bot:        "TRADITIONAL_AUTOMATION",
    trajectory_replay:  "TRADITIONAL_AUTOMATION",
    simulated_agent:    "AGENTIC_AI",
  };

  try {
    const res = await fetch("/api/v1/adversarial/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attack_type: attackType })
    });
    const data = await res.json();

    document.getElementById("adv-attack-name").textContent = data.attack_name;
    const badge = document.getElementById("adv-final-badge");
    const expectedCatch = ATTACK_CATCH_VERDICT[attackType] || "TRADITIONAL_AUTOMATION";
    const wasCaught = data.final_verdict === expectedCatch;
    // Use accurate language: "DETECTED" when caught, "EVADED DETECTION" when it slipped through
    badge.textContent = wasCaught
      ? `✓ DETECTED: ${data.final_verdict}`
      : `⚠ EVADED DETECTION: ${data.final_verdict}`;
    badge.className = `px-3 py-1 rounded-full text-xs font-bold ${
      wasCaught ? getBadgeClass(data.final_verdict) : "badge-uncertain"
    }`;

    document.getElementById("adv-l1").textContent = data.l1_result;
    document.getElementById("adv-l1").className = data.l1_result.includes("TRIGGER") ? "font-bold text-rose-700 mt-1" : "font-bold text-slate-400 mt-1";

    document.getElementById("adv-l2").textContent = data.l2_result;
    document.getElementById("adv-l2").className = data.l2_result.includes("BOT") || data.l2_result.includes("TRADITIONAL_AUTOMATION") || data.l2_result.includes("AGENT") ? "font-bold text-rose-700 mt-1" : "font-bold text-slate-400 mt-1";

    document.getElementById("adv-l3").textContent = data.l3_result;
    document.getElementById("adv-l3").className = data.l3_result.includes("OUTLIER") ? "font-bold text-rose-700 mt-1" : "font-bold text-slate-400 mt-1";

    document.getElementById("adv-l4").textContent = data.l4_result;
    document.getElementById("adv-l4").className = data.l4_result.includes("REPLAY") ? "font-bold text-rose-700 mt-1" : "font-bold text-slate-400 mt-1";

    document.getElementById("adv-l5").textContent = data.l5_result;
    document.getElementById("adv-l5").className = data.l5_result.includes("VIOLATION") ? "font-bold text-rose-700 mt-1" : "font-bold text-slate-400 mt-1";

    document.getElementById("adv-explanation").textContent = data.explanation;
  } catch (err) {
    alert("Adversarial simulation error: " + err);
  }
}

function getBadgeClass(label) {
  if (label === "HUMAN") return "badge-human";
  if (label === "TRADITIONAL_AUTOMATION" || label === "BOT") return "badge-bot";
  if (label === "AGENTIC_AI" || label === "AI_AGENT") return "badge-agent";
  return "badge-uncertain";
}

function escapeHTML(str) {
  return str.replace(/[&<>'"]/g, tag => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[tag] || tag));
}

// Global Window Exports for Inline HTML Handlers
window.runAdversarialSimulation = runAdversarialSimulation;
window.inspectSession = inspectSession;
window.handleSeedDemo = handleSeedDemo;
window.runBenchmark = runBenchmark;



