/**
 * WebSense Sentinel Background Service Worker
 */

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'VERDICT_UPDATE' && sender.tab) {
    const verdict = message.verdict;
    const tabId = sender.tab.id;

    if (verdict && verdict.predicted_label) {
      let badgeText = 'HUM';
      let badgeColor = '#10b981'; // green

      if (verdict.predicted_label === 'AGENTIC_AI') {
        badgeText = 'AI';
        badgeColor = '#8b5cf6'; // purple
      } else if (verdict.predicted_label === 'TRADITIONAL_AUTOMATION') {
        badgeText = 'BOT';
        badgeColor = '#ef4444'; // red
      } else if (verdict.predicted_label === 'UNCERTAIN') {
        badgeText = 'UNC';
        badgeColor = '#f59e0b'; // amber
      }

      chrome.action.setBadgeText({ tabId, text: badgeText });
      chrome.action.setBadgeBackgroundColor({ tabId, color: badgeColor });
    }
  }
});
