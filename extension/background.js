/**
 * WebSense Sentinel Background Service Worker (Manifest V3)
 * Handles cross-origin telemetry transmission (bypassing page-level CORS and HTTPS mixed-content blocks)
 * and manages badge states per tab.
 */

function updateBadge(tabId, verdict) {
  if (!tabId || !verdict || !verdict.predicted_label) return;

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
    try {
      chrome.action.setBadgeText({ tabId, text: '' });
    } catch (_) {}
  }
});

// Clean up badge when tab is closed
chrome.tabs.onRemoved.addListener((tabId) => {
  // Handled automatically by Chrome
});

// Unified message router
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab ? sender.tab.id : null;

  if (message.type === 'VERDICT_UPDATE') {
    if (tabId && message.verdict) {
      updateBadge(tabId, message.verdict);
    }
    sendResponse({ received: true });
    return false;
  }

  if (message.type === 'INGEST_TELEMETRY') {
    chrome.storage.local.get(['websenseHost'], (storage) => {
      const configuredHost = (storage && storage.websenseHost) ? storage.websenseHost.replace(/\/+$/, '') : null;
      let endpoint = message.endpoint;
      if (!endpoint || endpoint.startsWith('http://localhost:8000')) {
        if (configuredHost) {
          endpoint = `${configuredHost}/api/v1/sessions`;
        } else {
          endpoint = endpoint || 'http://localhost:8000/api/v1/sessions';
        }
      }

      const payload = message.payload;

      fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })
        .then(async (res) => {
          if (!res.ok) {
            const errorText = await res.text();
            sendResponse({ success: false, status: res.status, error: errorText });
            return;
          }
          const data = await res.json();
          if (tabId && data) {
            updateBadge(tabId, data);
          }
          sendResponse({ success: true, verdict: data });
        })
        .catch((err) => {
          sendResponse({ success: false, error: err.message || 'Network error' });
        });
    });

    return true; // Keep sendResponse open for asynchronous reply
  }

  return false;
});
