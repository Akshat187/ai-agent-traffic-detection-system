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
let selectedSource = "ALL";
let registeredSites = [];
let selectedInstallSite = null;
let apiKeyRevealed = false;

let _syncingHistory = false;
let pendingExplorerSessionId = null;
let explorerLoadToken = 0;

document.addEventListener("DOMContentLoaded", function () {
  initTabs();
  initCharts();

  const initialState = parseDashboardStateFromUrl();
  syncDashboardHistory(initialState, { replace: true });
  applyDashboardNavState(initialState, { refreshTabData: false });

  fetchSites();
  fetchOverviewStats();
  fetchSessions();
  initWebSocket();

  // Fallback poll every 15 seconds (WebSocket pushes live updates instantaneously)
  setInterval(() => {
    if (document.visibilityState === "visible") {
      fetchOverviewStats();
      fetchSessions();
    }
  }, 15000);

  // When the user switches back to this tab, refresh immediately
  // so data isn't stale from while the tab was hidden
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      fetchOverviewStats();
      fetchSessions();
    }
  });

  // Setup Event Listeners
  const siteSelect = document.getElementById("global-site-select");
  if (siteSelect) {
    siteSelect.addEventListener("change", function(e) {
      setSiteFilter(e.target.value);
    });
  }

  const sourceSelect = document.getElementById("global-source-select");
  if (sourceSelect) {
    sourceSelect.addEventListener("change", function(e) {
      setSourceFilter(e.target.value);
    });
  }

  const sessionSiteFilter = document.getElementById("session-filter-site");
  if (sessionSiteFilter) {
    sessionSiteFilter.addEventListener("change", function(e) {
      setSiteFilter(e.target.value);
    });
  }

  const sessionSourceFilter = document.getElementById("session-filter-source");
  if (sessionSourceFilter) {
    sessionSourceFilter.addEventListener("change", function(e) {
      setSourceFilter(e.target.value);
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
  if (explorerSelect) {
    explorerSelect.addEventListener("change", (e) => {
      const sessionId = e.target.value;
      if (!sessionId) {
        resetExplorerView();
        syncDashboardHistory({ tab: "tab-explorer", session: null });
        return;
      }
      syncDashboardHistory({ tab: "tab-explorer", session: sessionId });
      selectExplorerSession(sessionId);
    });
  }

  const explorerBackBtn = document.getElementById("explorer-back-btn");
  if (explorerBackBtn) explorerBackBtn.addEventListener("click", navigateExplorerBack);

  const playBtn = document.getElementById("trajectory-play-btn");
  if (playBtn) playBtn.addEventListener("click", playTrajectoryAnimation);

  const resetBtn = document.getElementById("trajectory-reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", drawStaticTrajectory);

  const benchmarkBtn = document.getElementById("run-benchmark-btn");
  if (benchmarkBtn) benchmarkBtn.addEventListener("click", runBenchmark);

  const registerSiteForm = document.getElementById("register-site-form");
  if (registerSiteForm) registerSiteForm.addEventListener("submit", handleRegisterSite);

  const installTaskSelect = document.getElementById("install-snippet-task");
  if (installTaskSelect) {
    installTaskSelect.addEventListener("change", () => {
      if (selectedInstallSite) showSiteInstallSnippet(selectedInstallSite, installTaskSelect.value);
    });
  }

  const copySnippetBtn = document.getElementById("copy-snippet-btn");
  if (copySnippetBtn) {
    copySnippetBtn.addEventListener("click", () => {
      const code = document.getElementById("install-snippet-code")?.textContent || "";
      copyTextToClipboard(code, copySnippetBtn, "Copy Tag");
    });
  }

  const toggleKeyBtn = document.getElementById("toggle-api-key-btn");
  if (toggleKeyBtn) {
    toggleKeyBtn.addEventListener("click", () => {
      apiKeyRevealed = !apiKeyRevealed;
      updateInstallApiKeyDisplay();
    });
  }

  const copyKeyBtn = document.getElementById("copy-api-key-btn");
  if (copyKeyBtn) {
    copyKeyBtn.addEventListener("click", () => {
      if (selectedInstallSite?.api_key) {
        copyTextToClipboard(selectedInstallSite.api_key, copyKeyBtn, "Copy");
      }
    });
  }

  // Preload latest experiment lab benchmarks
  loadLabData();
});

function buildFilterQuery(extra = {}) {
  const params = new URLSearchParams(extra);
  if (selectedSite && selectedSite !== "ALL") params.set("site_id", selectedSite);
  if (selectedSource && selectedSource !== "ALL") params.set("source", selectedSource);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function setSiteFilter(value) {
  selectedSite = value || "ALL";
  const globalSel = document.getElementById("global-site-select");
  const sessionSel = document.getElementById("session-filter-site");
  if (globalSel && globalSel.value !== selectedSite) globalSel.value = selectedSite;
  if (sessionSel && sessionSel.value !== selectedSite) sessionSel.value = selectedSite;
  fetchOverviewStats();
  fetchSessions();
}

function setSourceFilter(value) {
  selectedSource = value || "ALL";
  const globalSel = document.getElementById("global-source-select");
  const sessionSel = document.getElementById("session-filter-source");
  if (globalSel && globalSel.value !== selectedSource) globalSel.value = selectedSource;
  if (sessionSel && sessionSel.value !== selectedSource) sessionSel.value = selectedSource;
  fetchOverviewStats();
  fetchSessions();
}

function isDemoSession(s) {
  const src = (s.data_source || "").toLowerCase();
  return !!(s.is_synthetic || src === "synthetic_demo" || src.startsWith("synthetic"));
}

// Load Registered Sites
async function fetchSites() {
  try {
    const res = await fetch("/api/v1/sites");
    if (!res.ok) return;
    const data = await res.json();
    registeredSites = data.sites || [];
    const selects = [
      document.getElementById("global-site-select"),
      document.getElementById("session-filter-site"),
    ].filter(Boolean);

    selects.forEach(select => {
      const currentVal = select.value || selectedSite || "ALL";
      select.innerHTML = '<option value="ALL">All Sites</option>';

      registeredSites.forEach(site => {
        const opt = document.createElement("option");
        opt.value = site.site_id;
        opt.textContent = `${site.name} (${site.site_id.substring(0, 10)})`;
        select.appendChild(opt);
      });

      // Preserve selection if still present; otherwise fall back to ALL
      const hasCurrent = Array.from(select.options).some(o => o.value === currentVal);
      select.value = hasCurrent ? currentVal : "ALL";
    });

    selectedSite = document.getElementById("global-site-select")?.value || "ALL";
    renderSitesTable(registeredSites);

    if (selectedInstallSite) {
      const refreshed = registeredSites.find(s => s.site_id === selectedInstallSite.site_id);
      if (refreshed) {
        showSiteInstallSnippet(refreshed, document.getElementById("install-snippet-task")?.value);
      }
    } else if (registeredSites.length > 0) {
      showSiteInstallSnippet(registeredSites[0], "general");
    }
  } catch (err) {
    console.warn("Failed to fetch sites:", err);
  }
}

function buildSiteSnippet(site, taskOverride) {
  const task = (taskOverride || "general").trim() || "general";
  if (site && site.embed_snippet) {
    if (/data-task="[^"]*"/.test(site.embed_snippet)) {
      return site.embed_snippet.replace(/data-task="[^"]*"/, `data-task="${task}"`);
    }
    return site.embed_snippet.replace(/async><\/script>$/, `data-task="${task}" async></script>`);
  }
  const origin = window.location.origin.replace(/\/$/, "");
  return `<script src="${origin}/sentinel.js" data-site-id="${site.site_id}" data-task="${task}" async></script>`;
}

function updateInstallApiKeyDisplay() {
  const keyValEl = document.getElementById("install-api-key-value");
  const toggleBtn = document.getElementById("toggle-api-key-btn");
  const wrapEl = document.getElementById("install-api-key-wrap");
  if (!keyValEl || !wrapEl) return;

  const key = selectedInstallSite?.api_key || "";
  if (!key) {
    wrapEl.classList.add("hidden");
    return;
  }
  wrapEl.classList.remove("hidden");
  keyValEl.textContent = apiKeyRevealed ? key : `${key.slice(0, 8)}••••••••••••`;
  if (toggleBtn) toggleBtn.textContent = apiKeyRevealed ? "Hide" : "Reveal";
}

function showSiteInstallSnippet(site, taskOverride) {
  if (!site) return;
  selectedInstallSite = site;

  const emptyEl = document.getElementById("install-snippet-empty");
  const activeEl = document.getElementById("install-snippet-active");
  const badgeEl = document.getElementById("install-site-badge");
  const idEl = document.getElementById("install-site-id");
  const originsEl = document.getElementById("install-site-origins");
  const taskSelect = document.getElementById("install-snippet-task");
  const codeEl = document.getElementById("install-snippet-code");
  const localWarnEl = document.getElementById("install-localhost-warning");
  const originPreviewEl = document.getElementById("install-origin-preview");

  if (emptyEl) emptyEl.classList.add("hidden");
  if (activeEl) activeEl.classList.remove("hidden");
  if (badgeEl) {
    badgeEl.textContent = site.name || site.site_id;
    badgeEl.classList.remove("hidden");
  }
  if (idEl) idEl.textContent = site.site_id;
  if (originsEl) {
    originsEl.textContent = site.allowed_origins || "*";
    originsEl.title = site.allowed_origins || "*";
  }

  const chosenTask = taskOverride || taskSelect?.value || "general";
  if (taskSelect && taskSelect.value !== chosenTask) {
    taskSelect.value = chosenTask;
  }

  const snippet = buildSiteSnippet(site, chosenTask);
  if (codeEl) codeEl.textContent = snippet;

  const srcMatch = snippet.match(/src="([^"]+)\/sentinel\.js"/);
  const resolvedOrigin = srcMatch ? srcMatch[1] : window.location.origin;
  const isLocalOrigin = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$/i.test(resolvedOrigin);
  if (localWarnEl) localWarnEl.classList.toggle("hidden", !isLocalOrigin);
  if (originPreviewEl) originPreviewEl.textContent = resolvedOrigin;

  updateInstallApiKeyDisplay();
}

function selectSiteForInstall(siteId) {
  const site = registeredSites.find(s => s.site_id === siteId);
  if (!site) return;
  apiKeyRevealed = false;
  showSiteInstallSnippet(site, document.getElementById("install-snippet-task")?.value || "general");
  document.getElementById("install-snippet-active")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function filterDashboardBySite(siteId) {
  setSiteFilter(siteId);
  activateTab("tab-overview");
  syncDashboardHistory({ tab: "tab-overview", session: null });
}

function renderSitesTable(sites) {
  const tbody = document.getElementById("sites-table-tbody");
  if (!tbody) return;
  if (!sites || sites.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="py-8 text-center text-slate-400">No sites registered yet.</td></tr>';
    return;
  }

  tbody.innerHTML = sites.map(site => {
    const mode = String(site.enforcement_mode || "monitor");
    const threshold = site.risk_threshold ?? 80;
    const modeBadgeClass =
      mode === "block" ? "bg-rose-50 text-rose-700 border-rose-200" :
      mode === "challenge" ? "bg-amber-50 text-amber-700 border-amber-200" :
      "bg-slate-100 text-slate-700 border-slate-200";

    return `
      <tr>
        <td class="py-3 px-3.5 font-semibold text-slate-900">${escapeHTML(String(site.name || site.site_id))}</td>
        <td class="py-3 px-3.5 font-mono text-[11px] text-indigo-700">${escapeHTML(String(site.site_id))}</td>
        <td class="py-3 px-3.5 font-mono text-[11px] text-slate-600 max-w-[220px] truncate" title="${escapeHTML(String(site.allowed_origins || "*"))}">${escapeHTML(String(site.allowed_origins || "*"))}</td>
        <td class="py-3 px-3.5">
          <span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${modeBadgeClass}">${escapeHTML(mode.toUpperCase())}</span>
          <span class="text-[11px] font-mono text-slate-500 ml-1">&ge;${escapeHTML(String(threshold))}</span>
        </td>
        <td class="py-3 px-3.5 font-mono font-semibold text-slate-800">${escapeHTML(String(site.total_sessions ?? 0))}</td>
        <td class="py-3 px-3.5 text-right whitespace-nowrap space-x-1.5">
          <button type="button" onclick="selectSiteForInstall('${escapeHTML(String(site.site_id))}')"
                  class="px-2.5 py-1 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 text-[11px] font-semibold transition">
            Install Snippet
          </button>
          <button type="button" onclick="filterDashboardBySite('${escapeHTML(String(site.site_id))}')"
                  class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-semibold transition">
            Filter
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

async function handleRegisterSite(event) {
  event.preventDefault();
  const nameInput = document.getElementById("reg-site-name");
  const originsInput = document.getElementById("reg-site-origins");
  const taskSelect = document.getElementById("reg-site-task");
  const modeSelect = document.getElementById("reg-site-mode");
  const thresholdInput = document.getElementById("reg-site-threshold");
  const webhookInput = document.getElementById("reg-site-webhook");
  const errEl = document.getElementById("reg-site-error");
  const submitBtn = document.getElementById("register-site-submit-btn");

  if (errEl) {
    errEl.textContent = "";
    errEl.classList.add("hidden");
  }

  const name = (nameInput?.value || "").trim();
  const allowedOrigins = (originsInput?.value || "").trim() || "*";
  const defaultTask = taskSelect?.value || "general";
  const enforcementMode = modeSelect?.value || "monitor";
  const riskThreshold = parseInt(thresholdInput?.value || "80", 10);
  const webhookUrl = (webhookInput?.value || "").trim() || null;

  if (name.length < 2) {
    if (errEl) {
      errEl.textContent = "Site Name must be at least 2 characters.";
      errEl.classList.remove("hidden");
    }
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Registering...";
  }

  try {
    const res = await fetch("/api/v1/sites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        allowed_origins: allowedOrigins,
        enforcement_mode: enforcementMode,
        risk_threshold: Number.isNaN(riskThreshold) ? 80 : riskThreshold,
        webhook_url: webhookUrl,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "Registration failed");
      if (errEl) {
        errEl.textContent = msg;
        errEl.classList.remove("hidden");
      }
      return;
    }

    apiKeyRevealed = false;
    await fetchSites();
    showSiteInstallSnippet(data, defaultTask);
    if (nameInput) nameInput.value = "";
    if (originsInput) originsInput.value = "";
    if (webhookInput) webhookInput.value = "";
  } catch (err) {
    if (errEl) {
      errEl.textContent = `Failed to register site: ${err}`;
      errEl.classList.remove("hidden");
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Register Site & Generate Snippet";
    }
  }
}

async function copyTextToClipboard(text, btn, defaultLabel) {
  if (!text) return;
  let copied = false;
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (_) {}
  }
  if (!copied) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      copied = document.execCommand("copy");
    } catch (_) {}
    document.body.removeChild(ta);
  }
  if (btn && copied) {
    btn.textContent = "✓ Copied!";
    setTimeout(() => {
      btn.textContent = defaultLabel;
    }, 2000);
  }
}

function openSitesTab() {
  activateTab("tab-sites");
  syncDashboardHistory({ tab: "tab-sites", session: null });
  document.getElementById("reg-site-name")?.focus();
}

// Fetch Overview Stats
async function fetchOverviewStats() {
  try {
    const url = `/api/v1/stats/overview${buildFilterQuery()}`;

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

    if (timelineChart && Array.isArray(data.detection_timeline) && data.detection_timeline.length > 0) {
      timelineChart.data.labels = data.detection_timeline.map(b => b.bucket);
      timelineChart.data.datasets[0].data = data.detection_timeline.map(b => b.human || 0);
      timelineChart.data.datasets[1].data = data.detection_timeline.map(b => b.automation || 0);
      timelineChart.data.datasets[2].data = data.detection_timeline.map(b => b.agentic || 0);
      timelineChart.update();
    }

    renderRecentOverviewTable(data.recent_activity || []);
    fetchFeedbackStats();
  } catch (err) {
    console.warn("Failed to fetch stats:", err);
  }
}

async function fetchFeedbackStats() {
  try {
    const res = await fetch("/api/v1/stats/feedback");
    if (!res.ok) return;
    const fb = await res.json();
    const el = document.getElementById("stat-live-accuracy");
    if (el) {
      const acc = fb.accuracy_pct !== null && fb.accuracy_pct !== undefined ? `${fb.accuracy_pct.toFixed(1)}%` : "--";
      el.textContent = `Verified Accuracy: ${acc} (${fb.correct_count}/${fb.total_verified})`;
    }
  } catch (_) {}
}

function formatTabPageCell(s) {
  const title = s.page_title || s.page_path || '—';
  const path = s.page_path && s.page_title ? s.page_path : '';
  const tabShort = s.tab_id ? s.tab_id.substring(0, 8) : '';
  const seqBadge = s.transmission_seq > 1
    ? `<span class="ml-1 px-1.5 py-0.5 rounded text-[9px] bg-amber-50 text-amber-700 border border-amber-200 font-bold">#${s.transmission_seq}</span>`
    : '';
  return `
    <div class="font-medium text-slate-800 truncate max-w-[140px]" title="${escapeHTML(title)}">${escapeHTML(title)}</div>
    ${path ? `<div class="text-[10px] text-slate-500 font-mono truncate max-w-[140px]">${escapeHTML(path)}</div>` : ''}
    ${tabShort ? `<div class="text-[10px] text-indigo-500 font-mono">tab:${escapeHTML(tabShort)}${seqBadge}</div>` : ''}
  `;
}

function shortActorLabel(label) {
  if (label === "HUMAN") return "Human";
  if (label === "TRADITIONAL_AUTOMATION") return "Bot";
  if (label === "AGENTIC_AI") return "AI Agent";
  return "Uncertain";
}

function renderVerifyCell(s) {
  const sid = escapeHTML(s.session_id);
  const pred = escapeHTML(s.predicted_label || "UNCERTAIN");

  if (s.feedback_is_correct === true) {
    return `
      <div class="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">✓ Correct</span>
        <button onclick="openCorrectionPicker(this, '${sid}', '${pred}', true)" class="text-[10px] text-slate-400 hover:text-indigo-600 underline">Edit</button>
      </div>
    `;
  }

  if (s.feedback_is_correct === false && s.feedback_label) {
    return `
      <div class="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-200">✗ Actually: ${shortActorLabel(s.feedback_label)}</span>
        <button onclick="openCorrectionPicker(this, '${sid}', '${pred}', true)" class="text-[10px] text-slate-400 hover:text-indigo-600 underline">Edit</button>
      </div>
    `;
  }

  return `
    <div class="inline-flex items-center gap-1 whitespace-nowrap">
      <button onclick="submitVerification('${sid}', '${pred}', true)"
              title="Mark prediction as correct"
              class="px-2 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200 text-[11px] font-bold transition">
        ✓
      </button>
      <button onclick="openCorrectionPicker(this, '${sid}', '${pred}', false)"
              title="Mark prediction as wrong and pick correct class"
              class="px-2 py-1 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 text-[11px] font-bold transition">
        ✗
      </button>
    </div>
  `;
}

function openCorrectionPicker(btn, sessionId, predictedLabel, includeAll) {
  const cell = btn.closest("td");
  if (!cell) return;

  const options = [
    { value: "HUMAN", label: "Human", cls: "bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-200" },
    { value: "TRADITIONAL_AUTOMATION", label: "Bot", cls: "bg-rose-50 hover:bg-rose-100 text-rose-700 border-rose-200" },
    { value: "AGENTIC_AI", label: "AI Agent", cls: "bg-amber-50 hover:bg-amber-100 text-amber-700 border-amber-200" },
  ].filter(o => includeAll || o.value !== predictedLabel);

  cell.innerHTML = `
    <div class="flex flex-wrap items-center gap-1">
      ${options.map(o => `
        <button onclick="submitVerification('${sessionId}', '${o.value}', ${o.value === predictedLabel})"
                class="px-2 py-0.5 rounded-md border text-[10px] font-bold transition ${o.cls}">
          ${o.label}
        </button>
      `).join("")}
      <button onclick="fetchOverviewStats(); fetchSessions();"
              class="px-1.5 py-0.5 text-[10px] text-slate-400 hover:text-slate-700">✕</button>
    </div>
  `;
}

async function submitVerification(sessionId, trueLabel, isCorrect) {
  try {
    const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analyst_label: trueLabel,
        is_correct: isCorrect,
        notes: isCorrect ? "Confirmed via dashboard" : "Corrected via dashboard",
      }),
    });
    if (!res.ok) {
      console.error("Feedback failed:", await res.text());
      return;
    }
    await Promise.all([fetchOverviewStats(), fetchSessions()]);
  } catch (err) {
    console.error("Failed to submit verification:", err);
  }
}

function renderRecentOverviewTable(sessions) {
  const tbody = document.getElementById("overview-recent-tbody");
  if (!tbody) return;

  if (sessions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="py-8 text-center text-slate-400">No sessions recorded yet for this site. Interact with the Honey Sites or embedded pages!</td></tr>`;
    return;
  }

  tbody.innerHTML = sessions.slice(0, 7).map(s => {
    const badgeClass = getBadgeClass(s.predicted_label);
    const riskColor = s.risk_score > 60 ? 'text-rose-600 font-bold' : s.risk_score > 30 ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold';
    const isSynthetic = isDemoSession(s);
    const srcTag = isSynthetic
      ? `<span class="px-2 py-0.5 rounded-full text-[10px] bg-slate-100 text-slate-500 font-bold border border-slate-200">DEMO</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[10px] bg-emerald-50 text-emerald-700 font-bold border border-emerald-200">LIVE SDK</span>`;

    return `
      <tr class="hover:bg-slate-50 transition border-b border-slate-100">
        <td class="py-3 px-3.5 font-mono font-bold text-indigo-600 cursor-pointer hover:underline" onclick="inspectSession('${s.session_id}')">${s.session_id.substring(0, 16)}... ${srcTag}</td>
        <td class="py-3 px-3.5">${formatTabPageCell(s)}</td>
        <td class="py-3 px-3.5 font-mono text-[11px] text-slate-600 whitespace-nowrap">${s.created_at ? formatActivityTimestamp(s.created_at) : '—'}</td>
        <td class="py-3 px-3.5 capitalize font-medium text-slate-800">${s.task}</td>
        <td class="py-3 px-3.5"><span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold ${badgeClass}">${s.predicted_label}</span></td>
        <td class="py-3 px-3.5">${renderVerifyCell(s)}</td>
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

// Fetch All Sessions (respects selectedSite / selectedSource global filters)
async function fetchSessions() {
  try {
    const url = `/api/v1/sessions${buildFilterQuery({ limit: "100" })}`;
    const res = await fetch(url);
    if (!res.ok) return;
    allSessions = await res.json();
    applySessionFilters();
    updateExplorerDropdown(allSessions);
    syncSourceOptionsFromSessions(allSessions);
  } catch (err) {
    console.warn("Failed to fetch sessions:", err);
  }
}

function syncSourceOptionsFromSessions(sessions) {
  const known = new Set(["ALL", "LIVE", "DEMO", "realtime_sdk", "chrome_extension", "synthetic_demo"]);
  const extras = [...new Set(sessions.map(s => s.data_source).filter(Boolean))]
    .filter(src => !known.has(src))
    .sort();

  ["global-source-select", "session-filter-source"].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const current = select.value || selectedSource || "ALL";

    // Keep the static options; append any newly observed sources
    extras.forEach(src => {
      if (![...select.options].some(o => o.value === src)) {
        const opt = document.createElement("option");
        opt.value = src;
        opt.textContent = src;
        select.appendChild(opt);
      }
    });

    if ([...select.options].some(o => o.value === current)) {
      select.value = current;
    }
  });
}

function applySessionFilters() {
  const filterClass = document.getElementById("session-filter-class")?.value || "ALL";
  const search = document.getElementById("session-search-input")?.value.toLowerCase().trim() || "";

  const filtered = allSessions.filter(s => {
    if (filterClass !== "ALL" && s.predicted_label !== filterClass) return false;

    // Site / Source are primarily applied server-side, but keep client guards
    // so local searches stay consistent if the user changes filters mid-render.
    if (selectedSite !== "ALL" && s.site_id !== selectedSite) return false;
    if (selectedSource === "LIVE" && isDemoSession(s)) return false;
    if (selectedSource === "DEMO" && !isDemoSession(s)) return false;
    if (selectedSource !== "ALL" && selectedSource !== "LIVE" && selectedSource !== "DEMO"
        && (s.data_source || "") !== selectedSource) return false;

    if (search && !s.session_id.toLowerCase().includes(search) && !s.task.toLowerCase().includes(search)
        && !(s.page_path || '').toLowerCase().includes(search) && !(s.page_title || '').toLowerCase().includes(search)
        && !(s.tab_id || '').toLowerCase().includes(search) && !(s.visitor_id || '').toLowerCase().includes(search)
        && !(s.site_id || '').toLowerCase().includes(search)
        && !(s.data_source || '').toLowerCase().includes(search)) return false;
    return true;
  });

  const tbody = document.getElementById("sessions-table-tbody");
  if (!tbody) return;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="13" class="py-8 text-center text-slate-400">No matching sessions found.</td></tr>`;
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
    const isSynthetic = isDemoSession(s);
    const srcTag = isSynthetic
      ? `<span class="px-2 py-0.5 rounded-full text-[10px] bg-slate-100 text-slate-500 font-bold border border-slate-200">DEMO</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[10px] bg-emerald-50 text-emerald-700 font-bold border border-emerald-200">LIVE SDK</span>`;

    const siteDisplay = s.site_id ? s.site_id.substring(0, 14) : "default";
    const sourceLabel = s.data_source || (isSynthetic ? "synthetic_demo" : "realtime_sdk");

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
        <td class="py-3 px-3.5">${formatTabPageCell(s)}</td>
        <td class="py-3 px-3.5 font-mono text-[11px] text-slate-600 whitespace-nowrap">${s.created_at ? formatActivityTimestamp(s.created_at) : '—'}</td>
        <td class="py-3 px-3.5 font-mono text-[11px] text-slate-600"><span class="font-semibold text-slate-800" title="${escapeHTML(s.site_id || '')}">${escapeHTML(siteDisplay)}</span><br>${srcTag}<br><span class="text-[10px] text-slate-400">${escapeHTML(sourceLabel)}</span></td>
        <td class="py-3 px-3.5 capitalize font-medium text-slate-800">${s.task}</td>
        <td class="py-3 px-3.5">${durationCell}</td>
        <td class="py-3 px-3.5">${gtBadge}</td>
        <td class="py-3 px-3.5"><span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold ${badgeClass}">${s.predicted_label}</span></td>
        <td class="py-3 px-3.5">${renderVerifyCell(s)}</td>
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

// Tab & Browser History Navigation
const DEFAULT_TAB_ID = "tab-overview";
const VALID_TAB_IDS = new Set([
  "tab-overview",
  "tab-sessions",
  "tab-explorer",
  "tab-experiments",
  "tab-adversarial",
  "tab-health",
  "tab-sites",
]);

function normalizeTabId(rawTab) {
  if (!rawTab) return DEFAULT_TAB_ID;
  const trimmed = String(rawTab).trim();
  const candidate = trimmed.startsWith("tab-") ? trimmed : `tab-${trimmed}`;
  return VALID_TAB_IDS.has(candidate) ? candidate : DEFAULT_TAB_ID;
}

function tabIdToSlug(tabId) {
  return normalizeTabId(tabId).replace(/^tab-/, "");
}

function normalizeNavState(state) {
  const tab = normalizeTabId(state?.tab);
  const session = tab === "tab-explorer" && state?.session ? String(state.session) : null;
  return { tab, session };
}

function getDashboardNavState() {
  const activeTab = document.querySelector(".nav-tab.active");
  const tab = normalizeTabId(activeTab?.dataset?.target);
  const select = document.getElementById("explorer-session-select");
  const rawSession = select?.value || pendingExplorerSessionId || null;
  return normalizeNavState({ tab, session: tab === "tab-explorer" ? rawSession : null });
}

function buildDashboardUrl(state) {
  const nextState = normalizeNavState(state);
  const params = new URLSearchParams();
  if (nextState.tab !== DEFAULT_TAB_ID) {
    params.set("tab", tabIdToSlug(nextState.tab));
  }
  if (nextState.tab === "tab-explorer" && nextState.session) {
    params.set("session", nextState.session);
  }
  const qs = params.toString();
  const basePath =
    window.location.pathname && window.location.pathname !== "/"
      ? window.location.pathname
      : "/dashboard";
  return qs ? `${basePath}?${qs}` : basePath;
}

function parseDashboardStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const tab = normalizeTabId(params.get("tab"));
  const rawSession = params.get("session");
  return normalizeNavState({
    tab,
    session: tab === "tab-explorer" && rawSession ? rawSession : null,
  });
}

function syncDashboardHistory(state, { replace = false } = {}) {
  if (_syncingHistory || !window.history) return;
  const nextState = normalizeNavState(state);
  const nextUrl = buildDashboardUrl(nextState);
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  const currState = window.history.state;
  const sameState =
    currState &&
    currState.tab === nextState.tab &&
    (currState.session || null) === nextState.session;

  if (!replace && currentUrl === nextUrl && sameState) {
    return;
  }

  if (replace) {
    window.history.replaceState(nextState, "", nextUrl);
  } else {
    window.history.pushState(nextState, "", nextUrl);
  }
}

function resetExplorerView() {
  explorerLoadToken += 1;
  selectedSession = null;
  pendingExplorerSessionId = null;
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }

  const select = document.getElementById("explorer-session-select");
  if (select) select.value = "";

  const idEl = document.getElementById("explorer-session-id");
  if (idEl) idEl.textContent = "No session selected";

  const badge = document.getElementById("explorer-verdict-badge");
  if (badge) {
    badge.textContent = "—";
    badge.className = "px-2.5 py-0.5 rounded-full text-[10px] font-bold badge-uncertain";
  }

  const timeWrap = document.getElementById("explorer-session-time");
  const timeVal = document.getElementById("explorer-session-time-value");
  if (timeWrap) timeWrap.classList.add("hidden");
  if (timeVal) timeVal.textContent = "—";

  const promptEl = document.getElementById("explorer-fb-prompt");
  const pickerEl = document.getElementById("explorer-fb-picker");
  const statusEl = document.getElementById("explorer-fb-status");
  if (promptEl) promptEl.classList.remove("hidden");
  if (pickerEl) pickerEl.classList.add("hidden");
  if (statusEl) {
    statusEl.textContent = "";
    statusEl.classList.add("hidden");
  }

  const ctxBlock = document.getElementById("explorer-client-context");
  if (ctxBlock) ctxBlock.classList.add("hidden");
  [
    "ctx-tab-id",
    "ctx-page-title",
    "ctx-page-path",
    "ctx-transmission-seq",
    "ctx-visibility",
    "ctx-referrer",
    "ctx-sdk-version",
    "ctx-visitor-id",
  ].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "—";
  });
  const visitorEl = document.getElementById("ctx-visitor-id");
  if (visitorEl) visitorEl.onclick = null;

  const pointCountEl = document.getElementById("canvas-point-count");
  const pathLenEl = document.getElementById("canvas-path-len");
  const straightEl = document.getElementById("canvas-straightness");
  if (pointCountEl) pointCountEl.textContent = "0";
  if (pathLenEl) pathLenEl.textContent = "0px";
  if (straightEl) straightEl.textContent = "1.00";

  const canvas = document.getElementById("trajectory-canvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.fillStyle = "#090d16";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
  }

  if (keystrokeChart) {
    keystrokeChart.data.labels = [];
    keystrokeChart.data.datasets[0].data = [];
    keystrokeChart.update();
  }

  ["l1-badge", "l2-badge", "l3-badge", "l4-badge", "l5-badge"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = "—";
      el.className = "font-bold text-slate-500 px-2.5 py-1 rounded-lg bg-slate-100 border border-slate-200";
    }
  });

  const explEl = document.getElementById("explorer-explanation-text");
  if (explEl) {
    explEl.textContent = "Select a session to see detailed model rationale and kinematic indicators.";
  }
  const sigList = document.getElementById("explorer-signals-list");
  if (sigList) sigList.innerHTML = "";

  ["f-mean-vel", "f-straightness", "f-micro-corr", "f-key-cv"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
}

function selectExplorerSession(sessionId) {
  pendingExplorerSessionId = sessionId;
  const select = document.getElementById("explorer-session-select");
  if (select) {
    ensureExplorerOption(select, sessionId);
    select.value = sessionId;
  }
  return loadSessionDetails(sessionId);
}

function applyDashboardNavState(state, { refreshTabData = true } = {}) {
  const nextState = normalizeNavState(state);
  activateTab(nextState.tab, { refresh: refreshTabData });

  if (nextState.tab === "tab-explorer") {
    if (nextState.session) {
      return selectExplorerSession(nextState.session);
    }
    resetExplorerView();
  }
  return Promise.resolve();
}

function navigateExplorerBack() {
  if (window.history && window.history.length > 1) {
    window.history.back();
    return;
  }
  activateTab("tab-sessions");
  syncDashboardHistory({ tab: "tab-sessions", session: null });
}

function activateTab(tabId, { refresh = true } = {}) {
  const resolvedId = normalizeTabId(tabId);
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(t => {
    t.classList.toggle("active", t.dataset.target === resolvedId);
  });

  document.querySelectorAll(".tab-content").forEach(content => {
    if (content.id === resolvedId) {
      content.classList.remove("hidden");
      content.classList.add("animate-fade-in");
      if (refresh) {
        // Refresh data when entering a tab that depends on live API state
        if (resolvedId === "tab-overview") {
          fetchOverviewStats();
          fetchSessions();
        } else if (resolvedId === "tab-sessions") {
          fetchSessions();
          fetchOverviewStats();
        } else if (resolvedId === "tab-experiments") {
          loadLabData();
        } else if (resolvedId === "tab-sites") {
          fetchSites();
        }
      }
    } else {
      content.classList.add("hidden");
    }
  });

  if (resolvedId === "tab-explorer" && selectedSession) {
    requestAnimationFrame(() => drawStaticTrajectory());
  }
}

function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", function () {
      activateTab(this.dataset.target);
      syncDashboardHistory(getDashboardNavState());
    });
  });
}

window.addEventListener("popstate", function (event) {
  const state =
    event.state && event.state.tab
      ? normalizeNavState(event.state)
      : parseDashboardStateFromUrl();
  _syncingHistory = true;
  try {
    applyDashboardNavState(state);
  } finally {
    _syncingHistory = false;
  }
});

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
function renderClientContext(session) {
  const block = document.getElementById("explorer-client-context");
  const ctx = session.client_context || {};
  const hasContext = session.tab_id || session.page_path || session.page_title || ctx.tab_id;
  if (!block) return;
  if (!hasContext) {
    block.classList.add("hidden");
    return;
  }
  block.classList.remove("hidden");
  document.getElementById("ctx-tab-id").textContent = session.tab_id || ctx.tab_id || '—';
  document.getElementById("ctx-page-title").textContent = session.page_title || ctx.page_title || '—';
  document.getElementById("ctx-page-path").textContent = session.page_path || ctx.page_url || ctx.page_path || '—';
  document.getElementById("ctx-transmission-seq").textContent = session.transmission_seq || ctx.transmission_seq || '—';
  document.getElementById("ctx-visibility").textContent = ctx.visibility_state || '—';
  document.getElementById("ctx-referrer").textContent = ctx.referrer_path || '—';
  document.getElementById("ctx-sdk-version").textContent = ctx.sdk_version || '—';
  const visitorEl = document.getElementById("ctx-visitor-id");
  if (visitorEl) {
    visitorEl.textContent = session.visitor_id || '—';
    visitorEl.onclick = session.visitor_id ? () => filterByVisitor(session.visitor_id) : null;
  }
}

function filterByVisitor(visitorId) {
  const searchInput = document.getElementById("session-search-input");
  activateTab("tab-sessions");
  if (searchInput) {
    searchInput.value = visitorId;
    applySessionFilters();
  }
  syncDashboardHistory({ tab: "tab-sessions", session: null });
}

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

function formatActivityTimestamp(createdAt, { short = false } = {}) {
  if (!createdAt) return "";
  // Server formats as "YYYY-MM-DD HH:MM:SS" UTC (naive). Convert to IST (Asia/Kolkata).
  const raw = String(createdAt).trim();
  const iso = raw.includes("T") ? raw : raw.replace(" ", "T");
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return `${raw} UTC`;

  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value || "";
  const formatted = `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
  if (short) return formatted.replace(/^\d{4}-/, ""); // MM-DD HH:MM:SS
  return `${formatted} IST`;
}

function ensureExplorerOption(select, sessionId) {
  if (!select || !sessionId) return;
  const exists = Array.from(select.options).some(o => o.value === sessionId);
  if (!exists) {
    const opt = document.createElement("option");
    opt.value = sessionId;
    opt.textContent = sessionId;
    select.appendChild(opt);
  }
}

function updateExplorerDropdown(sessions) {
  const select = document.getElementById("explorer-session-select");
  if (!select) return;
  const curr = select.value || pendingExplorerSessionId || selectedSession?.session?.session_id || "";
  select.innerHTML = '<option value="">Choose session to explore...</option>' +
    sessions.map(s => {
      const shortId = s.session_id.length > 16 ? `${s.session_id.substring(0, 16)}…` : s.session_id;
      const when = s.created_at ? formatActivityTimestamp(s.created_at, { short: true }) : "";
      const meta = [s.predicted_label, s.task, when].filter(Boolean).join(" · ");
      return `<option value="${escapeHTML(s.session_id)}">${escapeHTML(shortId)}${meta ? ` — ${escapeHTML(meta)}` : ""}</option>`;
    }).join("");
  if (curr) {
    ensureExplorerOption(select, curr);
    select.value = curr;
  }
}

// Session Explorer Logic
async function inspectSession(sessionId) {
  if (!sessionId) return;
  activateTab("tab-explorer");
  syncDashboardHistory({ tab: "tab-explorer", session: sessionId });
  await selectExplorerSession(sessionId);
}

async function loadSessionDetails(sessionId) {
  if (!sessionId) return;
  const requestToken = ++explorerLoadToken;
  try {
    const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
    if (!res.ok) {
      if (requestToken === explorerLoadToken) pendingExplorerSessionId = null;
      return;
    }
    const detail = await res.json();
    if (requestToken !== explorerLoadToken) return;
    selectedSession = detail;
    pendingExplorerSessionId = null;

    const select = document.getElementById("explorer-session-select");
    if (select && detail.session?.session_id) {
      ensureExplorerOption(select, detail.session.session_id);
      select.value = detail.session.session_id;
    }

    document.getElementById("explorer-session-id").textContent = detail.session.session_id;
    renderClientContext(detail.session);
    const badge = document.getElementById("explorer-verdict-badge");
    if (badge) {
      badge.textContent = detail.session.predicted_label;
      badge.className = `px-2.5 py-0.5 rounded-full text-[10px] font-bold ${getBadgeClass(detail.session.predicted_label)}`;
    }
    loadExplorerFeedbackState(detail.session.session_id, detail.session.predicted_label);

    const timeWrap = document.getElementById("explorer-session-time");
    const timeVal = document.getElementById("explorer-session-time-value");
    const activityTs = formatActivityTimestamp(detail.session.created_at);
    if (timeWrap && timeVal) {
      if (activityTs) {
        timeVal.textContent = activityTs;
        timeWrap.classList.remove("hidden");
      } else {
        timeVal.textContent = "—";
        timeWrap.classList.add("hidden");
      }
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
    if (requestToken === explorerLoadToken) pendingExplorerSessionId = null;
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
      <svg class="animate-spin h-3.5 w-3.5 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <span class="hidden sm:inline">Seeding…</span>
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
      btn.innerHTML = origHtml || '<span aria-hidden="true">⚡</span><span class="hidden sm:inline">Sample Data</span>';
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

function initWebSocket() {
  try {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const siteParam = encodeURIComponent(selectedSite || "ALL");
    const ws = new WebSocket(`${proto}${location.host}/ws/sessions?site_id=${siteParam}`);

    ws.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (!msg || !msg.session_id) return;

        // Prepend or update live session in allSessions without full-page refresh
        const idx = allSessions.findIndex((s) => s.session_id === msg.session_id);
        const entry = {
          session_id: msg.session_id,
          site_id: msg.site_id || selectedSite,
          task: "live",
          predicted_label: msg.predicted_label,
          risk_score: msg.risk_score,
          confidence: msg.confidence,
          duration_ms: 0,
          data_source: "realtime_sdk",
          action: msg.action || "ALLOW",
        };
        if (idx >= 0) {
          allSessions[idx] = Object.assign({}, allSessions[idx], entry);
        } else {
          allSessions.unshift(entry);
          if (allSessions.length > 200) allSessions.pop();
          const totalEl = document.getElementById("kpi-total");
          if (totalEl) totalEl.textContent = String((parseInt(totalEl.textContent, 10) || 0) + 1);
          const lblMap = {
            HUMAN: "kpi-human",
            TRADITIONAL_AUTOMATION: "kpi-bot",
            AGENTIC_AI: "kpi-agent",
          };
          const kpiId = lblMap[msg.predicted_label];
          if (kpiId) {
            const el = document.getElementById(kpiId);
            if (el) el.textContent = String((parseInt(el.textContent, 10) || 0) + 1);
          }
        }
        if (typeof applySessionFilters === "function") {
          applySessionFilters();
        }
      } catch (_) {}
    };

    ws.onclose = function () {
      setTimeout(initWebSocket, 5000);
    };
  } catch (_) {}
}

async function loadExplorerFeedbackState(sessionId, predictedLabel) {
  const promptEl = document.getElementById("explorer-fb-prompt");
  const pickerEl = document.getElementById("explorer-fb-picker");
  const statusEl = document.getElementById("explorer-fb-status");
  if (!promptEl || !pickerEl || !statusEl) return;

  promptEl.classList.remove("hidden");
  pickerEl.classList.add("hidden");
  statusEl.classList.add("hidden");

  try {
    const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}/feedback`);
    if (res.ok) {
      const data = await res.json();
      if (selectedSession?.session?.session_id !== sessionId) return;
      if (data.verified && data.feedback) {
        promptEl.classList.add("hidden");
        pickerEl.classList.add("hidden");
        statusEl.textContent = data.feedback.is_correct
          ? `✓ Confirmed as ${data.feedback.analyst_label}`
          : `✓ Corrected to ${data.feedback.analyst_label}`;
        statusEl.className = data.feedback.is_correct
          ? "text-[10px] font-bold text-emerald-700 px-2"
          : "text-[10px] font-bold text-indigo-700 px-2";
        statusEl.classList.remove("hidden");
      }
    }
  } catch (_) {}
}

function openExplorerCorrectionPicker() {
  const promptEl = document.getElementById("explorer-fb-prompt");
  const pickerEl = document.getElementById("explorer-fb-picker");
  const pred = selectedSession && selectedSession.session ? selectedSession.session.predicted_label : "";
  if (promptEl) promptEl.classList.add("hidden");
  if (pickerEl) {
    pickerEl.classList.remove("hidden");
    pickerEl.querySelectorAll("[data-fb-cls]").forEach((btn) => {
      btn.style.display = btn.getAttribute("data-fb-cls") === pred ? "none" : "inline-block";
    });
  }
}

function confirmExplorerVerdict() {
  if (!selectedSession || !selectedSession.session) return;
  submitExplorerFeedback(selectedSession.session.predicted_label, true);
}

async function submitExplorerFeedback(analystLabel, isCorrect) {
  const sidEl = document.getElementById("explorer-session-id");
  const sessionId = (selectedSession && selectedSession.session && selectedSession.session.session_id) || (sidEl ? sidEl.textContent.trim() : "");
  if (!sessionId || sessionId === "No session selected") return;
  try {
    const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analyst_label: analystLabel, is_correct: isCorrect, notes: "Dashboard Session Explorer verification" }),
    });
    if (res.ok) {
      await loadExplorerFeedbackState(sessionId, analystLabel);
      fetchFeedbackStats();
      fetchSessions();
      fetchOverviewStats();
    }
  } catch (_) {}
}

async function triggerModelRetrain() {
  const btn = document.getElementById("btn-retrain-model");
  const statusEl = document.getElementById("retrain-status");
  if (btn) btn.disabled = true;
  if (statusEl) {
    statusEl.textContent = "Retraining & validating against regression gate...";
    statusEl.classList.remove("hidden");
  }
  try {
    const res = await fetch("/api/v1/model/retrain", { method: "POST" });
    const data = await res.json();
    if (statusEl) {
      const f1Info = typeof data.candidate_f1 === "number" ? ` (Candidate F1: ${data.candidate_f1.toFixed(4)})` : "";
      statusEl.textContent = data.promoted
        ? `✓ Model promoted & hot-reloaded${f1Info}`
        : `⚠ Kept existing model — failed regression gate${f1Info}`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = `Retrain failed: ${err}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Global Window Exports for Inline HTML Handlers
window.submitVerification = submitVerification;
window.openCorrectionPicker = openCorrectionPicker;
window.confirmExplorerVerdict = confirmExplorerVerdict;
window.openExplorerCorrectionPicker = openExplorerCorrectionPicker;
window.submitExplorerFeedback = submitExplorerFeedback;
window.triggerModelRetrain = triggerModelRetrain;
window.submitLabelOverride = (lbl) => submitExplorerFeedback(lbl, false);
window.runAdversarialSimulation = runAdversarialSimulation;
window.inspectSession = inspectSession;
window.activateTab = activateTab;
window.navigateExplorerBack = navigateExplorerBack;
window.handleSeedDemo = handleSeedDemo;
window.runBenchmark = runBenchmark;
window.openSitesTab = openSitesTab;
window.selectSiteForInstall = selectSiteForInstall;
window.filterDashboardBySite = filterDashboardBySite;
window.fetchSites = fetchSites;



