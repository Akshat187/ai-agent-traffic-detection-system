/**
 * WebSense Sentinel Content Script (Chrome Extension Manifest V3)
 * Collects interaction telemetry on web pages and transmits via service worker to avoid
 * HTTPS mixed-content and CORS blocks.
 *
 * Implements cooperative single-collector ownership:
 * - If Sentinel SDK is active on the page, the extension yields collection and acts
 *   as a passthrough bridge for the SDK's verdict updates.
 * - Otherwise, the extension claims ownership and captures client kinematics.
 */

(function () {
  'use strict';

  // Guard 1: Only run in the top-level browsing context (never in iframes/subframes)
  if (window.top !== window.self) return;

  // Guard 2: Prevent multiple injections into the same window context
  if (window.__WEBSENSE_SENTINEL_INJECTED__) return;
  window.__WEBSENSE_SENTINEL_INJECTED__ = true;

  const DEFAULT_ENDPOINT = 'http://localhost:8000/api/v1/sessions';
  const EXTENSION_SITE_ID = 'site_chrome_extension';

  let latestVerdict = null;
  let sdkSessionId = null;
  let isYieldingToSdk = false;

  // --- Check for Native SDK Presence ---
  function checkSdkPresence() {
    return (
      document.documentElement.dataset.wsOwner === 'sdk' ||
      !!document.querySelector('script[src*="sentinel.js"], script[src*="collector.js"]')
    );
  }

  // Listen for SDK verdict broadcasts via postMessage
  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'WEBSENSE_VERDICT_UPDATE') {
      latestVerdict = event.data.verdict;
      sdkSessionId = event.data.sessionId;

      try {
        chrome.runtime.sendMessage({
          type: 'VERDICT_UPDATE',
          verdict: latestVerdict
        });
      } catch (_) {}
    }
  });

  if (checkSdkPresence()) {
    isYieldingToSdk = true;
    setupMessageResponder();
    return;
  }

  // Claim ownership if SDK is not present
  document.documentElement.dataset.wsOwner = 'extension';

  // Listen in case SDK is injected asynchronously later
  window.addEventListener('ws:claimed', (e) => {
    if (e.detail && e.detail.owner === 'sdk') {
      isYieldingToSdk = true;
    }
  });

  // --- Session & Journey Architecture ---
  const SESSION_KEY = 'ws_ext_session_id';
  const VISITOR_KEY = 'ws_visitor_id';
  const JOURNEY_KEY = 'ws_journey_id';
  const JOURNEY_TIME_KEY = 'ws_journey_last_active';
  const PREV_VISIT_KEY = 'ws_prev_visit_id';
  const TAB_KEY = 'ws_tab_id';
  const JOURNEY_MAX_IDLE_MS = 30 * 60 * 1000;

  function generateId(prefix) {
    return prefix + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  }

  // Persistent visitor ID across visits
  const visitorId = (function () {
    try {
      let v = localStorage.getItem(VISITOR_KEY);
      if (!v) {
        v = generateId('vis');
        localStorage.setItem(VISITOR_KEY, v);
      }
      return v;
    } catch (_) {
      return generateId('vis');
    }
  })();

  // 1 session = 1 page visit
  const sessionId = generateId('ext_st');

  // Tab journey ID grouping page visits
  function getJourneyId() {
    const now = Date.now();
    try {
      const lastActive = parseInt(sessionStorage.getItem(JOURNEY_TIME_KEY) || '0', 10);
      let jid = sessionStorage.getItem(JOURNEY_KEY);
      if (!jid || now - lastActive > JOURNEY_MAX_IDLE_MS) {
        jid = generateId('jny');
        sessionStorage.setItem(JOURNEY_KEY, jid);
      }
      sessionStorage.setItem(JOURNEY_TIME_KEY, String(now));
      return jid;
    } catch (_) {
      return generateId('jny');
    }
  }

  const journeyId = getJourneyId();
  let previousVisitId = (function () {
    try {
      return sessionStorage.getItem(PREV_VISIT_KEY) || null;
    } catch (_) {
      return null;
    }
  })();

  try {
    sessionStorage.setItem(PREV_VISIT_KEY, sessionId);
  } catch (_) {}

  let tabId = (function () {
    try {
      let t = sessionStorage.getItem(TAB_KEY);
      if (!t) {
        t = 'tab_' + (window.crypto && crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 16) : generateId('tab').slice(4));
        sessionStorage.setItem(TAB_KEY, t);
      }
      return t;
    } catch (_) {
      return generateId('tab');
    }
  })();

  // --- Monotonic Chunk Sequence ---
  let transmissionSeq = 0;
  const startTime = performance.now();
  const startUnixTime = Date.now();

  // --- Event Buffers (Sliced per chunk) ---
  const mouseEvents = [];
  const keyboardEvents = [];
  const scrollEvents = [];
  const clickEvents = [];
  const taskActions = [];

  let totalEventsTransmitted = 0;
  let lastMouseMoveTime = 0;
  let lastScrollTime = 0;
  let lastKeyDownTime = 0;
  const activeKeys = new Map();

  // --- Active Duration Tracking (idle > 60s excluded) ---
  const INACTIVITY_GAP_MS = 60000;
  let firstEventTime = null;
  let lastEventTime = null;
  let accumulatedIdleMs = 0;
  let isCollecting = document.visibilityState === 'visible';

  function isTabVisible() {
    return document.visibilityState === 'visible';
  }

  function onTabHidden() {
    isCollecting = false;
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
      // Transmit intermediate delta when tab is switched
      flushTelemetry(false);
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
    return Math.max(0, Math.round(lastEventTime - firstEventTime - accumulatedIdleMs));
  }

  // --- Event Listeners ---
  window.addEventListener('mousemove', function (e) {
    if (isYieldingToSdk || !isCollecting) return;
    const now = performance.now();
    if (now - lastMouseMoveTime < 25) return;
    lastMouseMoveTime = now;
    recordActivity();
    if (mouseEvents.length < 300) {
      mouseEvents.push({
        x: Math.round(e.clientX),
        y: Math.round(e.clientY),
        t: Math.round(now - startTime),
        type: 'move'
      });
    }
  }, { passive: true });

  window.addEventListener('click', function (e) {
    if (isYieldingToSdk || !isCollecting) return;
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

  window.addEventListener('keydown', function (e) {
    if (isYieldingToSdk || !isCollecting) return;
    if (e.target && (e.target.type === 'password' || e.target.dataset.private === 'true')) return;
    if (e.repeat) return; // Discard synthetic repeats

    recordActivity();
    const now = performance.now();
    const interval = lastKeyDownTime > 0 ? Math.round(now - lastKeyDownTime) : 0;
    lastKeyDownTime = now;
    activeKeys.set(e.code, now);

    if (keyboardEvents.length < 200) {
      keyboardEvents.push({
        t: Math.round(now - startTime),
        interval: interval,
        hold: 50.0,
        is_paste: false
      });
    }
  }, { passive: true });

  window.addEventListener('keyup', function (e) {
    if (isYieldingToSdk || !isCollecting) return;
    if (activeKeys.has(e.code)) {
      const downTime = activeKeys.get(e.code);
      const hold = Math.max(1, Math.round(performance.now() - downTime));
      activeKeys.delete(e.code);
      if (keyboardEvents.length > 0) {
        keyboardEvents[keyboardEvents.length - 1].hold = hold;
      }
    }
  }, { passive: true });

  window.addEventListener('scroll', function () {
    if (isYieldingToSdk || !isCollecting) return;
    const now = performance.now();
    if (now - lastScrollTime < 50) return;
    recordActivity();
    const lastScrollY = scrollEvents.length > 0 ? scrollEvents[scrollEvents.length - 1].scroll_y : 0;
    const currentY = Math.round(window.scrollY);
    lastScrollTime = now;
    if (scrollEvents.length < 150) {
      scrollEvents.push({
        t: Math.round(now - startTime),
        scroll_y: currentY,
        delta_y: currentY - lastScrollY
      });
    }
  }, { passive: true });

  // --- Minimum Interaction Threshold ---
  function hasMinimumInteraction() {
    if (clickEvents.length > 0) return true;
    if (keyboardEvents.length > 0) return true;
    if (scrollEvents.length >= 2) return true;
    if (mouseEvents.length >= 5) {
      const first = mouseEvents[0];
      const last = mouseEvents[mouseEvents.length - 1];
      const dx = last.x - first.x;
      const dy = last.y - first.y;
      if (Math.sqrt(dx * dx + dy * dy) >= 15) return true;
    }
    return mouseEvents.length + keyboardEvents.length + scrollEvents.length + clickEvents.length >= 5;
  }

  // --- Build Delta Chunk Payload ---
  function buildChunkPayload(isFinal) {
    transmissionSeq += 1;

    // Drain event buffers as delta
    const deltaMouse = mouseEvents.splice(0, mouseEvents.length);
    const deltaKeyboard = keyboardEvents.splice(0, keyboardEvents.length);
    const deltaScroll = scrollEvents.splice(0, scrollEvents.length);
    const deltaClicks = clickEvents.splice(0, clickEvents.length);
    const deltaTasks = taskActions.splice(0, taskActions.length);

    totalEventsTransmitted += deltaMouse.length + deltaKeyboard.length + deltaScroll.length + deltaClicks.length;

    let referrerPath = '';
    try {
      if (document.referrer) referrerPath = new URL(document.referrer).pathname;
    } catch (_) {}

    return {
      session_id: sessionId,
      page_visit_id: sessionId,
      journey_id: journeyId,
      previous_visit_id: previousVisitId,
      site_id: EXTENSION_SITE_ID,
      visitor_id: visitorId,
      task: 'general',
      seq: transmissionSeq,
      final: !!isFinal,
      client_context: {
        tab_id: tabId,
        page_path: location.pathname,
        page_title: document.title || '',
        page_url: location.href,
        referrer_path: referrerPath,
        visibility_state: document.visibilityState,
        transmission_seq: transmissionSeq,
        sdk_version: 'extension-2.0'
      },
      start_time: startUnixTime,
      end_time: Date.now(),
      duration_ms: Math.round(performance.now() - startTime),
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
      mouse_events: deltaMouse,
      keyboard_events: deltaKeyboard,
      scroll_events: deltaScroll,
      click_events: deltaClicks,
      task_actions: deltaTasks
    };
  }

  // --- Transmission via Background Service Worker ---
  let isFlushing = false;

  function flushTelemetry(isFinal) {
    if (isYieldingToSdk) return;
    if (!isFinal && !isTabVisible()) return;

    const hasNewEvents = mouseEvents.length > 0 || keyboardEvents.length > 0 || scrollEvents.length > 0 || clickEvents.length > 0;
    if (!isFinal && transmissionSeq === 0 && !hasMinimumInteraction()) return;
    if (!isFinal && transmissionSeq > 0 && !hasNewEvents) return;
    if (isFlushing && !isFinal) return;

    isFlushing = true;
    const payload = buildChunkPayload(isFinal);

    try {
      chrome.runtime.sendMessage(
        {
          type: 'INGEST_TELEMETRY',
          endpoint: DEFAULT_ENDPOINT,
          payload: payload
        },
        (res) => {
          isFlushing = false;
          if (res && res.success && res.verdict) {
            latestVerdict = res.verdict;
          }
        }
      );
    } catch (_) {
      isFlushing = false;
    }
  }

  // Periodic flush every 5s while active
  setInterval(() => {
    flushTelemetry(false);
  }, 5000);

  // Unload flush with final=true
  window.addEventListener('pagehide', () => {
    flushTelemetry(true);
  });

  setupMessageResponder();

  // --- Message Responder for Extension Popup ---
  function setupMessageResponder() {
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === 'GET_PAGE_STATUS') {
        sendResponse({
          url: window.location.href,
          hostname: window.location.hostname,
          sessionId: isYieldingToSdk ? sdkSessionId : sessionId,
          siteId: isYieldingToSdk ? 'site_meridian_prod' : EXTENSION_SITE_ID,
          source: isYieldingToSdk ? 'sdk_passthrough' : 'chrome_extension',
          events: {
            mouse: mouseEvents.length,
            keys: keyboardEvents.length,
            scroll: scrollEvents.length,
            clicks: clickEvents.length,
            totalTransmitted: totalEventsTransmitted
          },
          activeDurationMs: getActiveDurationMs(),
          isCollecting: isCollecting && !isYieldingToSdk,
          verdict: latestVerdict
        });
      }
    });
  }

})();