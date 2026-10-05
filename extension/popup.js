/**
 * WebSense Sentinel Popup Logic
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
      const host = (data && data.websenseHost) || 'http://localhost:8000';
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
      let rawHost = endpointInput.value.trim() || 'http://localhost:8000';
      rawHost = rawHost.replace(/\/+$/, '');
      if (chrome.storage && chrome.storage.local) {
        chrome.storage.local.set({ websenseHost: rawHost }, () => {
          if (btnDashboard) btnDashboard.href = `${rawHost}/dashboard`;
          if (endpointMsg) {
            endpointMsg.style.display = 'block';
            setTimeout(() => { endpointMsg.style.display = 'none'; }, 2000);
          }
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

  chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_STATUS' }, (res) => {
    if (chrome.runtime.lastError || !res) {
      if (verdictBadge) {
        verdictBadge.textContent = 'STANDBY';
        verdictBadge.className = 'verdict-badge';
      }
      if (confidenceText) {
        const errMsg = chrome.runtime.lastError ? chrome.runtime.lastError.message : '';
        if (errMsg && errMsg.includes('Receiving end does not exist')) {
          confidenceText.textContent = 'Reload tab (F5) to activate inspector';
        } else {
          confidenceText.textContent = 'Interact with page to stream';
        }
      }
      return;
    }

    if (sessionVal) sessionVal.textContent = res.sessionId ? res.sessionId.slice(0, 14) + '...' : '—';
    if (res.events) {
      evtMouse.textContent = res.events.mouseTotal ?? res.events.mouse ?? 0;
      evtKeys.textContent = res.events.keysTotal ?? res.events.keys ?? 0;
      evtClicks.textContent = res.events.clicksTotal ?? res.events.clicks ?? 0;
    }

    if (typeof res.activeDurationMs === 'number' && activeTime) {
      activeTime.textContent = (res.activeDurationMs / 1000).toFixed(1) + 's';
    }

    if (res.verdict) {
      const v = res.verdict;
      verdictBadge.textContent = v.predicted_label || 'UNCERTAIN';
      verdictBadge.className = 'verdict-badge ' + (v.predicted_label || '');

      let conf = typeof v.confidence === 'number' ? v.confidence : 0;
      if (conf <= 1.0 && conf > 0) {
        conf = conf * 100;
      }
      confidenceText.textContent = `Confidence: ${Math.round(conf)}%`;
      riskVal.textContent = `${Math.round(v.risk_score || 0)} / 100`;
    } else {
      verdictBadge.textContent = 'STREAMING';
      verdictBadge.className = 'verdict-badge';
      confidenceText.textContent = 'Collecting kinematics...';
    }
  });
});
