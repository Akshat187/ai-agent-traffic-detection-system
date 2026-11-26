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
    currentVerdict = v;
    if (v.session_id && !currentSessionId) {
      currentSessionId = v.session_id;
    }
    const label = v.predicted_label || 'UNCERTAIN';
    verdictBadge.textContent = label;
    verdictBadge.className = 'verdict-badge ' + label;

    let conf = typeof v.confidence === 'number' ? v.confidence : 0;
    if (conf <= 1.0 && conf > 0) {
      conf = conf * 100;
    }
    confidenceText.textContent = `Confidence: ${Math.round(conf)}%`;
    riskVal.textContent = `${Math.round(v.risk_score || 0)} / 100`;
    updateFeedbackStrip();
  }

  const feedbackStrip = document.getElementById('feedback-strip');
  const fbPrompt = document.getElementById('fb-prompt');
  const fbPicker = document.getElementById('fb-picker');
  const fbStatus = document.getElementById('fb-status');
  const btnFbYes = document.getElementById('btn-fb-yes');
  const btnFbNo = document.getElementById('btn-fb-no');

  let currentSessionId = null;
  let currentVerdict = null;
  const verifiedCache = new Map();
  const checkedSessions = new Set();

  function showFeedbackStatus(text, isCorrected) {
    if (!feedbackStrip) return;
    feedbackStrip.style.display = 'block';
    if (fbPrompt) fbPrompt.style.display = 'none';
    if (fbPicker) fbPicker.style.display = 'none';
    if (fbStatus) {
      fbStatus.textContent = text;
      fbStatus.style.color = isCorrected ? '#a78bfa' : '#34d399';
      fbStatus.style.display = 'block';
    }
  }

  function updateFeedbackStrip() {
    if (!feedbackStrip || !currentSessionId || !currentVerdict || !currentVerdict.predicted_label) return;
    if (verifiedCache.has(currentSessionId)) {
      const cached = verifiedCache.get(currentSessionId);
      const msg = cached.is_correct
        ? `✓ Confirmed as ${cached.analyst_label}`
        : `✓ Corrected to ${cached.analyst_label}`;
      showFeedbackStatus(msg, !cached.is_correct);
      return;
    }
    if (!checkedSessions.has(currentSessionId)) {
      checkedSessions.add(currentSessionId);
      chrome.runtime.sendMessage({ type: 'CHECK_FEEDBACK', sessionId: currentSessionId }, (res) => {
        if (res && res.success && res.data && res.data.verified && res.data.feedback) {
          verifiedCache.set(currentSessionId, res.data.feedback);
          updateFeedbackStrip();
        }
      });
    }
    feedbackStrip.style.display = 'block';
    if (fbStatus && fbStatus.style.display === 'block') return;
    if (fbPicker && fbPicker.style.display === 'block') return;
    if (fbPrompt) fbPrompt.style.display = 'block';
  }

  function submitPopupFeedback(analystLabel, isCorrect) {
    if (!currentSessionId) return;
    chrome.runtime.sendMessage(
      {
        type: 'SUBMIT_FEEDBACK',
        sessionId: currentSessionId,
        payload: { analyst_label: analystLabel, is_correct: isCorrect, notes: 'Chrome extension popup verification' }
      },
      (res) => {
        if (res && res.success && res.data) {
          verifiedCache.set(currentSessionId, res.data);
          const msg = isCorrect
            ? `✓ Confirmed as ${analystLabel}`
            : `✓ Corrected to ${analystLabel}`;
          showFeedbackStatus(msg, !isCorrect);
        }
      }
    );
  }

  if (btnFbYes) {
    btnFbYes.addEventListener('click', () => {
      if (!currentVerdict || !currentVerdict.predicted_label) return;
      submitPopupFeedback(currentVerdict.predicted_label, true);
    });
  }

  if (btnFbNo) {
    btnFbNo.addEventListener('click', () => {
      if (fbPrompt) fbPrompt.style.display = 'none';
      if (fbPicker) {
        fbPicker.style.display = 'block';
        const pred = currentVerdict ? currentVerdict.predicted_label : '';
        fbPicker.querySelectorAll('[data-label]').forEach((btn) => {
          btn.style.display = btn.getAttribute('data-label') === pred ? 'none' : 'inline-block';
        });
      }
    });
  }

  if (fbPicker) {
    fbPicker.querySelectorAll('[data-label]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const chosen = btn.getAttribute('data-label');
        submitPopupFeedback(chosen, false);
      });
    });
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

      if (res.sessionId) {
        currentSessionId = res.sessionId;
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
      } else if (res.lastError) {
        verdictBadge.textContent = 'ERROR';
        verdictBadge.className = 'verdict-badge TRADITIONAL_AUTOMATION';
        confidenceText.textContent = res.lastError;
      } else {
        const totalEvts = res.events
          ? (res.events.mouseTotal ?? res.events.mouse ?? 0) +
            (res.events.clicksTotal ?? res.events.clicks ?? 0) +
            (res.events.keysTotal ?? res.events.keys ?? 0)
          : 0;
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
