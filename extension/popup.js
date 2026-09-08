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

  try {
    const url = new URL(tab.url);
    sitePill.textContent = url.hostname;

    chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_STATUS' }, (res) => {
      if (chrome.runtime.lastError || !res) {
        verdictBadge.textContent = 'STANDBY';
        confidenceText.textContent = 'Interact with page to stream';
        return;
      }

      sessionVal.textContent = res.sessionId ? res.sessionId.slice(0, 12) + '...' : '—';
      if (res.events) {
        evtMouse.textContent = res.events.mouse || 0;
        evtKeys.textContent = res.events.keys || 0;
        evtClicks.textContent = res.events.clicks || 0;
      }

      if (res.verdict) {
        const v = res.verdict;
        verdictBadge.textContent = v.predicted_label || 'UNCERTAIN';
        verdictBadge.className = 'verdict-badge ' + (v.predicted_label || '');
        confidenceText.textContent = `Confidence: ${(v.confidence * 100).toFixed(0)}%`;
        riskVal.textContent = `${Math.round(v.risk_score)} / 100`;
      } else {
        verdictBadge.textContent = 'STREAMING';
        confidenceText.textContent = 'Collecting kinematics...';
      }
    });
  } catch (err) {
    sitePill.textContent = 'Browser Internal';
    verdictBadge.textContent = 'IDLE';
  }
});
