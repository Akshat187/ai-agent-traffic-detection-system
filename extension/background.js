/**
 * WebSense Sentinel Background Service Worker (Manifest V3)
 * Handles cross-origin telemetry transmission (bypassing page-level CORS and HTTPS mixed-content blocks)
 * and manages badge states per tab with in-memory verdict caching.
 */

const tabVerdicts = new Map();

function updateBadge(tabId, verdict) {
  if (!tabId || !verdict || !verdict.predicted_label) return;

  tabVerdicts.set(tabId, verdict);

  let badgeText = 'HUM';
  let badgeColor = '#10b981'; // green

  switch (verdict.predicted_label) {
    case 'AGENTIC_AI':
      badgeText = 'AI';
      badgeColor = '#8b5cf6'; // purple
      break;
    case 'TRADITIONAL_AUTOMATION':
      badgeText = 'BOT';
      badgeColor = '#ef4444'; // red
      break;
    case 'UNCERTAIN':
      badgeText = 'UNC';
      badgeColor = '#f59e0b'; // amber
      break;
    case 'HUMAN':
    default:
      badgeText = 'HUM';
      badgeColor = '#10b981'; // green
      break;
  }

  try {
    chrome.action.setBadgeText({ tabId, text: badgeText });
    chrome.action.setBadgeBackgroundColor({ tabId, color: badgeColor });
  } catch (_) {}
}

// Reset badge on tab navigation
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'loading') {
    tabVerdicts.delete(tabId);
    try {
      chrome.action.setBadgeText({ tabId, text: '' });
    } catch (_) {}
  }
});

// Clean up badge when tab is closed
chrome.tabs.onRemoved.addListener((tabId) => {
  tabVerdicts.delete(tabId);
});

// Unified message router
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab ? sender.tab.id : null;

  if (message.type === 'GET_CACHED_VERDICT') {
    const targetTabId = message.tabId || tabId;
    const verdict = targetTabId ? tabVerdicts.get(targetTabId) : null;
    sendResponse({ verdict: verdict || null });
    return false;
  }

  if (message.type === 'VERDICT_UPDATE') {
    if (tabId && message.verdict) {
      updateBadge(tabId, message.verdict);
    }
    sendResponse({ received: true });
    return false;
  }

  if (message.type === 'INGEST_TELEMETRY') {
    // Self-contained async execution that GUARANTEES sendResponse is always called
    (async () => {
      try {
        let configuredHost = null;
        try {
          const storage = await chrome.storage.local.get(['websenseHost']);
          if (storage && storage.websenseHost) {
            configuredHost = storage.websenseHost.replace(/\/+$/, '');
          }
        } catch (_) {}

        let endpoint = message.endpoint;
        if (!endpoint || endpoint.includes('localhost:8000') || endpoint.includes('127.0.0.1:8000')) {
          endpoint = configuredHost ? `${configuredHost}/api/v1/sessions` : 'http://127.0.0.1:8000/api/v1/sessions';
        }

        const payloadStr = JSON.stringify(message.payload);

        let resp = null;
        let fetchErr = null;

        // Try primary endpoint
        try {
          resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payloadStr
          });
        } catch (e1) {
          fetchErr = e1;
          // Automatic loopback fallback between 127.0.0.1 and localhost
          try {
            const fallbackUrl = endpoint.includes('127.0.0.1:8000')
              ? endpoint.replace('127.0.0.1:8000', 'localhost:8000')
              : endpoint.replace('localhost:8000', '127.0.0.1:8000');
            resp = await fetch(fallbackUrl, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: payloadStr
            });
            fetchErr = null;
          } catch (e2) {
            fetchErr = e2;
          }
        }

        if (resp && resp.ok) {
          const data = await resp.json();
          if (tabId && data) {
            updateBadge(tabId, data);
          }
          sendResponse({ success: true, verdict: data });
        } else if (resp) {
          const errText = await resp.text();
          console.warn('[WebSense SW] Server returned error ' + resp.status + ':', errText);
          sendResponse({ success: false, status: resp.status, error: errText });
        } else {
          console.warn('[WebSense SW] Fetch failed to reach server:', fetchErr);
          sendResponse({ success: false, error: (fetchErr && fetchErr.message) || 'Network connection failed' });
        }
      } catch (fatalErr) {
        console.error('[WebSense SW] Fatal exception in ingest handler:', fatalErr);
        sendResponse({ success: false, error: fatalErr.message || 'Internal extension error' });
      }
    })();

    return true; // Keep message channel open for asynchronous reply
  }

  return false;
});
