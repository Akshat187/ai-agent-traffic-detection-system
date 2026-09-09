/**
 * WebSense Sentinel Content Script (Chrome Extension Manifest V3)
 * Runs on any visited web page to capture telemetry and report AI/Bot classifications.
 *
 * Collection and transmission are gated to the active (visible) tab only.
 * Background tabs do not record events or flush telemetry to the backend.
 */

(function () {
  'use strict';

  // Prevent multiple injections
  if (window.__WEBSENSE_SENTINEL_INJECTED__) return;
  window.__WEBSENSE_SENTINEL_INJECTED__ = true;

  const DEFAULT_ENDPOINT = 'http://localhost:8000/api/v1/sessions';
  const siteId = 'site_chrome_ext_' + window.location.hostname.replace(/[^a-zA-Z0-9]/g, '_');
  const SESSION_KEY = 'ws_ext_session_id';
  const VISITOR_KEY = 'ws_visitor_id';
  const LEGACY_VISITOR_KEYS = ['ws_sentinel_visitor_id', 'meridian_visitor_id'];
  const TAB_KEY = 'ws_tab_id';
  const SEQ_KEY = 'ws_transmission_seq';

  function generateId(prefix) {
    return prefix + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
  }

  let sessionId = (function () {
    try {
      let s = sessionStorage.getItem(SESSION_KEY);
      if (!s) {
        s = 'ext_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
        sessionStorage.setItem(SESSION_KEY, s);
      }
      return s;
    } catch (_) {
      return 'ext_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
    }
  })();

  let visitorId = (function () {
    try {
      let v = localStorage.getItem(VISITOR_KEY);
      if (!v) {
        for (let i = 0; i < LEGACY_VISITOR_KEYS.length; i++) {
          v = localStorage.getItem(LEGACY_VISITOR_KEYS[i]);
          if (v) break;
        }
      }
      if (!v) v = generateId('vis');
      localStorage.setItem(VISITOR_KEY, v);
      return v;
    } catch (_) {
      return generateId('vis');
    }
  })();

  function getClientContext() {
    let tabId;
    try {
      tabId = sessionStorage.getItem(TAB_KEY);
      if (!tabId) {
        tabId = 'tab_' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 16) : generateId('tab').slice(4));
        sessionStorage.setItem(TAB_KEY, tabId);
      }
    } catch (_) {
      tabId = generateId('tab');
    }
    let seq = 1;
    try {
      seq = parseInt(sessionStorage.getItem(SEQ_KEY) || '0', 10) + 1;
      sessionStorage.setItem(SEQ_KEY, String(seq));
    } catch (_) {}
    let referrerPath = '';
    try {
      if (document.referrer) referrerPath = new URL(document.referrer).pathname;
    } catch (_) {}
    return {
      tab_id: tabId,
      page_path: location.pathname,
      page_title: document.title || '',
      page_url: location.pathname + location.search,
      referrer_path: referrerPath,
      visibility_state: document.visibilityState,
      transmission_seq: seq,
      sdk_version: 'extension-1.0',
    };
  }

  const startTime = performance.now();

  const mouseEvents = [];
  const keyboardEvents = [];
  const scrollEvents = [];
  const clickEvents = [];
  const taskActions = [];

  let lastMouseMoveTime = 0;
  let lastScrollTime = 0;
  let lastKeyDownTime = 0;
  const activeKeys = new Map();
  let latestVerdict = null;

  // --- Active-Duration Tracking ---
  // Measures true active engagement, not raw tab lifetime.
  // Gaps > INACTIVITY_GAP_MS between events are treated as idle and excluded
  // so a tab left open idle in the background does not inflate the value
  // the detection engine uses for ratio-based features (planning_pause_ratio, etc.).
  const INACTIVITY_GAP_MS = 60000; // 60 s of silence = idle, not counted
  let firstEventTime = null;  // performance.now() of first real user event
  let lastEventTime  = null;  // performance.now() of most recent user event
  let accumulatedIdleMs = 0;  // total idle-gap time subtracted from active window

  // --- Active-Tab Gating ---
  // Only the foreground tab collects events and sends telemetry.
  let isCollecting = document.visibilityState === 'visible';

  function isTabVisible() {
    return document.visibilityState === 'visible';
  }

  function onTabHidden() {
    isCollecting = false;
    // Exclude time spent in the background from active engagement metrics.
    if (lastEventTime !== null) {
      accumulatedIdleMs += performance.now() - lastEventTime;
      lastEventTime = null;
    }
  }

  function onTabVisible() {
    isCollecting = true;
  }

  document.addEventListener('visibilitychange', function () {
    if (isTabVisible()) {
      onTabVisible();
    } else {
      onTabHidden();
    }
  });

  function recordActivity() {
    if (!isCollecting) return;
    const now = performance.now();
    if (firstEventTime === null) {
      firstEventTime = now;
    } else if (lastEventTime !== null) {
      const gap = now - lastEventTime;
      if (gap > INACTIVITY_GAP_MS) {
        accumulatedIdleMs += gap;
      }
    }
    lastEventTime = now;
  }

  function getActiveDurationMs() {
    if (firstEventTime === null || lastEventTime === null) return 0;
    return Math.max(0, Math.round((lastEventTime - firstEventTime) - accumulatedIdleMs));
  }

  // --- Mouse Movement ---
  window.addEventListener('mousemove', function (e) {
    if (!isCollecting) return;
    const now = performance.now();
    if (now - lastMouseMoveTime < 25) return;
    lastMouseMoveTime = now;
    recordActivity();
    if (mouseEvents.length < 500) {
      mouseEvents.push({
        x: Math.round(e.clientX),
        y: Math.round(e.clientY),
        t: Math.round(now - startTime),
        type: 'move'
      });
    }
  }, { passive: true });

  // --- Click Events ---
  window.addEventListener('click', function (e) {
    if (!isCollecting) return;
    recordActivity();
    const tag = (e.target.tagName || '').toLowerCase();
    let category = 'other';
    if (['button', 'input', 'a'].includes(tag) || e.target.closest('button, a')) {
      category = tag === 'a' || e.target.closest('a') ? 'link' : 'button';
    }
    clickEvents.push({
      x: Math.round(e.clientX),
      y: Math.round(e.clientY),
      t: Math.round(performance.now() - startTime),
      target_category: category
    });
  }, { passive: true });

  // --- Keyboard Timing (Zero text / characters) ---
  window.addEventListener('keydown', function (e) {
    if (!isCollecting) return;
    if (e.target && (e.target.type === 'password' || e.target.dataset.private === 'true')) return;
    recordActivity();
    const now = performance.now();
    const interval = lastKeyDownTime > 0 ? Math.round(now - lastKeyDownTime) : 0;
    lastKeyDownTime = now;
    activeKeys.set(e.code, now);

    if (keyboardEvents.length < 300) {
      keyboardEvents.push({
        t: Math.round(now - startTime),
        interval: interval,
        hold: 50.0,
        is_paste: false
      });
    }
  }, { passive: true });

  window.addEventListener('keyup', function (e) {
    if (!isCollecting) return;
    if (activeKeys.has(e.code)) {
      const downTime = activeKeys.get(e.code);
      const hold = Math.round(performance.now() - downTime);
      activeKeys.delete(e.code);
      if (keyboardEvents.length > 0) {
        keyboardEvents[keyboardEvents.length - 1].hold = hold;
      }
    }
  }, { passive: true });

  // --- Scroll Dynamics ---
  window.addEventListener('scroll', function () {
    if (!isCollecting) return;
    const now = performance.now();
    if (now - lastScrollTime < 50) return;
    recordActivity();
    const lastScrollY = scrollEvents.length > 0 ? scrollEvents[scrollEvents.length - 1].scroll_y : 0;
    const currentY = Math.round(window.scrollY);
    lastScrollTime = now;
    if (scrollEvents.length < 200) {
      scrollEvents.push({
        t: Math.round(now - startTime),
        scroll_y: currentY,
        delta_y: currentY - lastScrollY
      });
    }
  }, { passive: true });

  // --- Build & Transmit Telemetry ---
  function buildPayload() {
    return {
      session_id: sessionId,
      site_id: siteId,
      visitor_id: visitorId,
      task: 'general',
      client_context: getClientContext(),
      // start_time = approximate page-load unix time in ms
      start_time: Date.now() - Math.round(performance.now() - startTime),
      end_time: Date.now(),
      // Raw tab-open lifetime (kept for diagnostics; may include background idle time)
      duration_ms: Math.round(performance.now() - startTime),
      // Bounded active engagement window: excludes idle gaps > 60 s.
      // The detection engine uses this field for all ratio-based features.
      active_duration_ms: getActiveDurationMs(),
      data_source: 'chrome_extension',
      browser_signals: {
        webdriver: !!navigator.webdriver,
        screen_width: window.screen.width,
        screen_height: window.screen.height,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        user_agent: navigator.userAgent
      },
      mouse_events: mouseEvents,
      keyboard_events: keyboardEvents,
      scroll_events: scrollEvents,
      click_events: clickEvents,
      task_actions: taskActions
    };
  }

  async function flushTelemetry(force) {
    if (!force && !isTabVisible()) return;
    if (mouseEvents.length < 2 && keyboardEvents.length === 0 && clickEvents.length === 0) return;
    try {
      const response = await fetch(DEFAULT_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload())
      });
      if (response.ok) {
        latestVerdict = await response.json();
        chrome.runtime.sendMessage({
          type: 'VERDICT_UPDATE',
          url: window.location.href,
          hostname: window.location.hostname,
          verdict: latestVerdict,
          counts: {
            mouse: mouseEvents.length,
            keys: keyboardEvents.length,
            scroll: scrollEvents.length,
            clicks: clickEvents.length
          }
        });
      }
    } catch (err) {
      // Backend offline or unreachable
    }
  }

  // Periodic flush every 5 seconds (active tab only) & on unload
  setInterval(function () { flushTelemetry(false); }, 5000);
  window.addEventListener('pagehide', function () { flushTelemetry(true); });

  // Message listener for popup requests
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'GET_PAGE_STATUS') {
      sendResponse({
        url: window.location.href,
        hostname: window.location.hostname,
        sessionId: sessionId,
        siteId: siteId,
        events: {
          mouse: mouseEvents.length,
          keys: keyboardEvents.length,
          scroll: scrollEvents.length,
          clicks: clickEvents.length
        },
        activeDurationMs: getActiveDurationMs(),
        isCollecting: isCollecting,
        verdict: latestVerdict
      });
    }
  });

})();