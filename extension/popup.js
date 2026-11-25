/**
 * WebSense Sentinel Popup Logic
 * Live telemetry polling and instant verdict display
 */

document.addEventListener('DOMContentLoaded', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return;

  const sitePill = document.getElementById('site-pill');
  const verdictBadge = document.getElementById('verdict-badge');
  const confidenceText = document.getElementById('confidence-text');
  const riskVal = document.getElementById('risk-val');
  const sessionVal = document.getElementById('session-val');
  const evtMouse = document.getElementById('evt-mouse');
  const evtKeys = document.getElementById('evt-keys');
  const evtClicks = document.getElementById('evt-clicks');
  const activeTime = document.getElementById('active-time');

  // Settings Panel & Host Configuration
  const btnSettingsToggle = document.getElementById('btn-settings-toggle');
  const settingsPanel = document.getElementById('settings-panel');
  const endpointInput = document.getElementById('endpoint-input');
  const btnEndpointSave = document.getElementById('btn-endpoint-save');
  const endpointMsg = document.getElementById('endpoint-msg');
  const btnDashboard = document.getElementById('btn-dashboard');

  if (chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(['websenseHost'], (data) => {
      const host = (data && data.websenseHost) || 'http://127.0.0.1:8000';
      if (endpointInput) endpointInput.value = host;
      if (btnDashboard) btnDashboard.href = `${host.replace(/\/+$/, '')}/dashboard`;
    });
  }

  if (btnSettingsToggle && settingsPanel) {
    btnSettingsToggle.addEventListener('click', () => {
      const isHidden = settingsPanel.style.display === 'none';
      settingsPanel.style.display = isHidden ? 'block' : 'none';
    });
  }

  if (btnEndpointSave && endpointInput) {
    btnEndpointSave.addEventListener('click', () => {
      let rawHost = endpointInput.value.trim() || 'http://127.0.0.1:8000';
      rawHost = rawHost.replace(/\/+$/, '');
      if (chrome.storage && chrome.storage.local) {
        chrome.storage.local.set({ websenseHost: rawHost }, () => {
          if (btnDashboard) btnDashboard.href = `${rawHost}/dashboard`;
          if (endpointMsg) {
            endpointMsg.style.display = 'block';
            setTimeout(() => { endpointMsg.style.display = 'none'; }, 2000);
          }
          // Immediate poll after host change
          pollStatus();
        });
      }
    });
  }

  let hostname = 'Web Page';
  let isRestricted = false;

  if (tab.url) {
    try {
      const parsed = new URL(tab.url);
      hostname = parsed.hostname || tab.url;
      if (['chrome:', 'chrome-extension:', 'edge:', 'about:', 'devtools:', 'view-source:'].includes(parsed.protocol)) {
        isRestricted = true;
      }
    } catch (_) {
      hostname = tab.url;
    }
  }

  if (sitePill) sitePill.textContent = hostname;

  if (isRestricted) {
    if (verdictBadge) {
      verdictBadge.textContent = 'RESTRICTED';
      verdictBadge.className = 'verdict-badge';
    }
    if (confidenceText) confidenceText.textContent = 'Open any web page (http/https) to inspect';
    if (riskVal) riskVal.textContent = 'N/A';
    return;
  }

  function renderVerdict(v) {
    if (!v) return;
    const label = v.predicted_label || 'UNCERTAIN';
    verdictBadge.textContent = label;
    verdictBadge.className = 'verdict-badge ' + label;

    let conf = typeof v.confidence === 'number' ? v.confidence : 0;
    if (conf <= 1.0 && conf > 0) {
      conf = conf * 100;
    }
    confidenceText.textContent = `Confidence: ${Math.round(conf)}%`;
    riskVal.textContent = `${Math.round(v.risk_score || 0)} / 100`;
  }

  function pollStatus() {
    chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_STATUS' }, (res) => {
      if (chrome.runtime.lastError || !res) {
        // Fallback: check if service worker has cached verdict for this tab
        chrome.runtime.sendMessage({ type: 'GET_CACHED_VERDICT', tabId: tab.id }, (bgRes) => {
          if (bgRes && bgRes.verdict) {
            renderVerdict(bgRes.verdict);
          } else {
            if (verdictBadge && verdictBadge.textContent === 'ANALYZING...') {
              verdictBadge.textContent = 'STANDBY';
              verdictBadge.className = 'verdict-badge';
            }
            if (confidenceText) {
              const errMsg = chrome.runtime.lastError ? chrome.runtime.lastError.message : '';
              if (errMsg && errMsg.includes('Receiving end does not exist')) {
                confidenceText.textContent = 'Reload page (F5) to activate inspector';
              } else {
                confidenceText.textContent = 'Interact with page to stream';
              }
            }
          }
        });
        return;
      }

      if (sessionVal) sessionVal.textContent = res.sessionId ? res.sessionId.slice(0, 16) + '...' : '—';
      if (res.events) {
        evtMouse.textContent = res.events.mouseTotal ?? res.events.mouse ?? 0;
        evtKeys.textContent = res.events.keysTotal ?? res.events.keys ?? 0;
        evtClicks.textContent = res.events.clicksTotal ?? res.events.clicks ?? 0;
      }

      if (typeof res.activeDurationMs === 'number' && activeTime) {
        activeTime.textContent = (res.activeDurationMs / 1000).toFixed(1) + 's';
      }

      if (res.verdict) {
        renderVerdict(res.verdict);
      } else {
        const totalEvts = (res.events ? (res.events.mouse || 0) + (res.events.clicks || 0) + (res.events.keys || 0) : 0);
        if (totalEvts >= 4) {
          verdictBadge.textContent = 'EVALUATING';
          verdictBadge.className = 'verdict-badge';
          confidenceText.textContent = 'Evaluating behavioral kinematics...';
          // Trigger immediate flush to get the verdict right now!
          chrome.tabs.sendMessage(tab.id, { type: 'TRIGGER_FLUSH' }, (flushRes) => {
            if (flushRes && flushRes.verdict) {
              renderVerdict(flushRes.verdict);
            }
          });
        } else {
          verdictBadge.textContent = 'STREAMING';
          verdictBadge.className = 'verdict-badge';
          confidenceText.textContent = 'Collecting kinematics (move mouse or click)...';
        }
      }
    });
  }

  // Initial poll immediately
  pollStatus();

  // Continuous live polling every 1 second while popup is open
  const pollInterval = setInterval(pollStatus, 1000);
  window.addEventListener('unload', () => {
    clearInterval(pollInterval);
  });
});
