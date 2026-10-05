/**
 * Sentinel Behavioral Intelligence SDK — v1.3.1
 * Unified, zero-dependency embeddable telemetry collector for AI agent and bot detection.
 *
 * Architecture:
 *   - Page-visit identity model: 1 session_id = 1 page visit.
 *   - Isolated per-visit state lifecycle: route transitions cannot mutate or corrupt events.
 *   - Reliable delta transmission: in-flight chunk kept immutable until server acknowledgement.
 *   - Automatic retry: re-sends exact same payload with same seq on network drop or 429/5xx.
 *   - Malformed chunk handling: drops 4xx client errors (e.g. 422) with warning to prevent infinite loops.
 *   - Timeout resilience: 10s fetch timeout ensures sender lock never gets stuck.
 *   - Single collector ownership lock via documentElement.dataset.wsOwner.
 *   - Keystroke hold tracking per e.code, e.repeat filtering, paste detection.
 *   - URL privacy: transmits pathname only by default; query tokens and hash fragments omitted.
 *
 * Privacy Guarantees:
 *   - NEVER records keystroke characters, key codes, or form inputs.
 *   - NEVER captures or interacts with type="password" or data-private fields.
 *   - Captures anonymous timing, physics, and kinematic dynamics ONLY.
 */

(function (window, document) {
  'use strict';

  // Guard 1: Only run in top-level context (never in iframes)
  if (window.top !== window.self) return;

  // Guard 2: Single collector lock.
  // Prevent multiple SDK instances on the same page while allowing SDK to override extension.
  if (window.__WEBSENSE_COLLECTOR_ACTIVE__ || document.documentElement.dataset.wsOwner === 'sdk') {
    return;
  }
  document.documentElement.dataset.wsOwner = 'sdk';
  window.__WEBSENSE_COLLECTOR_ACTIVE__ = true;

  // Notify extension or other observers that SDK owns collection
  try {
    window.dispatchEvent(new CustomEvent('ws:collector_activated', { detail: { owner: 'sdk', timestamp: Date.now() } }));
    window.dispatchEvent(new CustomEvent('ws:claimed', { detail: { owner: 'sdk' } }));
    window.postMessage({ type: 'WEBSENSE_SDK_ACTIVATED' }, '*');
  } catch (_) {}

  // 1. Discover configuration from script tag
  const currentScript = document.currentScript || (function () {
    const scripts = document.getElementsByTagName('script');
    for (let i = scripts.length - 1; i >= 0; i--) {
      const src = scripts[i].src || '';
      if (src.includes('sentinel.js') || src.includes('collector.js')) {
        return scripts[i];
      }
    }
    return null;
  })();

  const scriptSrc = currentScript ? currentScript.src : '';
  let defaultEndpoint = '/api/v1/sessions';
  if (scriptSrc && scriptSrc.startsWith('http')) {
    try {
      const url = new URL(scriptSrc);
      defaultEndpoint = url.origin + '/api/v1/sessions';
    } catch (_) {}
  }

  const siteId = (currentScript && currentScript.getAttribute('data-site-id')) ||
    (document.body && document.body.dataset.siteId) ||
    'site_meridian_prod';

  const apiEndpoint = (currentScript && currentScript.getAttribute('data-endpoint')) || defaultEndpoint;
  let currentTask = (currentScript && currentScript.getAttribute('data-task')) ||
    (document.body && document.body.dataset.task) ||
    'general';

  const requireConsent = currentScript && currentScript.getAttribute('data-require-consent') === 'true';

  // 2. Constants & Storage Keys
  const CONSENT_KEYS = [
    'meridian_telemetry_consent',
    'meridian_consent',
    'ws_consent',
    'ws_sentinel_consent_' + siteId
  ];
  const VISITOR_KEY = 'ws_visitor_id';
  const JOURNEY_KEY = 'ws_journey_id';
  const JOURNEY_TIME_KEY = 'ws_journey_last_active';
  const TAB_KEY = 'ws_tab_id';
  const PREV_VISIT_KEY = 'ws_prev_visit_id';

  const MOUSE_THROTTLE_MS = 25;
  const SCROLL_THROTTLE_MS = 50;
  const MAX_MOUSE_DELTA = 300;
  const MAX_KEYBOARD_DELTA = 200;
  const MAX_SCROLL_DELTA = 150;
  const MAX_CLICK_DELTA = 50;
  const INACTIVITY_GAP_MS = 60000; // 60s inactivity = idle
  const JOURNEY_MAX_IDLE_MS = 30 * 60 * 1000; // 30 min tab idle ends journey

  function generateId(prefix) {
    return prefix + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 9);
  }

  // 3. Persistent Visitor ID & Tab Journey ID
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

  const tabId = (function () {
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

  function getJourneyId() {
    const now = Date.now();
    try {
      const lastActive = parseInt(sessionStorage.getItem(JOURNEY_TIME_KEY) || '0', 10);
      let jid = sessionStorage.getItem(JOURNEY_KEY);
      if (!jid || (now - lastActive > JOURNEY_MAX_IDLE_MS)) {
        jid = generateId('jny');
        sessionStorage.setItem(JOURNEY_KEY, jid);
      }
      sessionStorage.setItem(JOURNEY_TIME_KEY, String(now));
      return jid;
    } catch (_) {
      return generateId('jny');
    }
  }

  // 4. Consent State
  function checkConsent() {
    if (!requireConsent) return true;
    for (let i = 0; i < CONSENT_KEYS.length; i++) {
      try {
        const val = localStorage.getItem(CONSENT_KEYS[i]);
        if (val === 'granted') return true;
        if (val === 'declined') return false;
      } catch (_) {}
    }
    return false;
  }

  let consentGranted = checkConsent();

  // 5. Page Visit State Factory (Encapsulated State Object)
  function createPageVisit(prevVisitId, task) {
    const sid = generateId('st');
    try {
      sessionStorage.setItem(PREV_VISIT_KEY, sid);
    } catch (_) {}

    return {
      sessionId: sid,
      previousVisitId: prevVisitId,
      task: task || currentTask,
      transmissionSeq: 1,
      startTime: performance.now(),
      absoluteStartTime: Date.now(),
      firstEventTime: null,
      lastEventTime: null,
      accumulatedIdleMs: 0,

      // Delta buffers for freshly captured events
      pendingMouse: [],
      pendingKeyboard: [],
      pendingScroll: [],
      pendingClicks: [],
      pendingActions: [],

      // Active keystrokes map (e.code -> { elapsed, pressTime })
      activeKeyCodes: new Map(),

      // Event signal flags
      totalEventsCount: 0,
      hasSignificantSignal: false,

      // In-flight transmission tracking (P2 & P3 fix)
      inFlight: null,
      isSending: false,
      latestVerdict: null,
      isFinalized: false,
    };
  }

  const initialPreviousVisitId = (function () {
    try {
      return sessionStorage.getItem(PREV_VISIT_KEY) || null;
    } catch (_) {
      return null;
    }
  })();

  let currentVisit = createPageVisit(initialPreviousVisitId, currentTask);
  let listenersAttached = false;
  let lastMouseMoveTime = 0;
  let lastScrollTime = 0;
  let lastKeyDownTime = 0;

  function recordActivity(visit) {
    if (!visit) return;
    const now = performance.now();
    if (visit.firstEventTime === null) {
      visit.firstEventTime = now;
    } else if (visit.lastEventTime !== null) {
      const gap = now - visit.lastEventTime;
      if (gap > INACTIVITY_GAP_MS) {
        visit.accumulatedIdleMs += gap;
      }
    }
    visit.lastEventTime = now;
    try {
      sessionStorage.setItem(JOURNEY_TIME_KEY, String(Date.now()));
    } catch (_) {}
  }

  function getActiveDurationMs(visit) {
    if (!visit || visit.firstEventTime === null || visit.lastEventTime === null) return 0;
    return Math.max(0, Math.round((visit.lastEventTime - visit.firstEventTime) - visit.accumulatedIdleMs));
  }

  // 6. Browser Signals & Client Context
  function getBrowserSignals() {
    return {
      webdriver: Boolean(navigator.webdriver),
      screen_width: window.screen ? window.screen.width : 1920,
      screen_height: window.screen ? window.screen.height : 1080,
      viewport_width: window.innerWidth || 1280,
      viewport_height: window.innerHeight || 720,
      device_pixel_ratio: window.devicePixelRatio || 1.0,
      touch_support: ('ontouchstart' in window) || (navigator.maxTouchPoints > 0),
      hardware_concurrency: navigator.hardwareConcurrency || 4,
      platform: navigator.platform || 'unknown',
      language: navigator.language || 'en-US',
      user_agent: navigator.userAgent || '',
      timezone_offset: new Date().getTimezoneOffset(),
    };
  }

  function getClientContext(visit) {
    let referrerPath = '';
    try {
      if (document.referrer) {
        referrerPath = new URL(document.referrer).pathname;
      }
    } catch (_) {}

    return {
      tab_id: tabId,
      page_path: location.pathname,
      page_title: (document.title || '').slice(0, 256),
      // URL privacy (P11): transmit clean origin + pathname without sensitive query parameters or hashes
      page_url: (location.origin + location.pathname).slice(0, 512),
      page_host: location.origin,
      referrer_path: referrerPath,
      visibility_state: document.visibilityState,
      transmission_seq: visit ? visit.transmissionSeq : 1,
      sdk_version: 'sentinel-1.3.1',
      collector: 'sdk',
    };
  }

  // 7. Event Listeners
  function attachListeners() {
    if (listenersAttached || !consentGranted) return;
    listenersAttached = true;

    // Mouse dynamics
    window.addEventListener('mousemove', function (e) {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      const now = performance.now();
      if (now - lastMouseMoveTime < MOUSE_THROTTLE_MS) return;
      lastMouseMoveTime = now;
      recordActivity(currentVisit);

      if (currentVisit.pendingMouse.length < MAX_MOUSE_DELTA) {
        currentVisit.pendingMouse.push({
          x: Math.round(e.clientX),
          y: Math.round(e.clientY),
          t: Math.round(now - currentVisit.startTime),
          type: 'move',
        });
        currentVisit.totalEventsCount++;
        if (currentVisit.pendingMouse.length >= 5) currentVisit.hasSignificantSignal = true;
      }
    }, { passive: true });

    // Click dynamics
    window.addEventListener('click', function (e) {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      const now = performance.now();
      recordActivity(currentVisit);

      const target = e.target;
      let category = 'general';

      if (target && target.closest) {
        if (target.closest("button, .btn, [role='button'], input[type='submit']")) category = 'button';
        else if (target.closest("input, textarea, select")) category = 'input';
        else if (target.closest("a, nav")) category = 'navigation';
        else if (target.closest(".add-cart-btn, #checkout-btn, .flight-card")) category = 'task_action';
      }

      if (currentVisit.pendingClicks.length < MAX_CLICK_DELTA) {
        currentVisit.pendingClicks.push({
          x: Math.round(e.clientX),
          y: Math.round(e.clientY),
          t: Math.round(now - currentVisit.startTime),
          target_category: category,
        });
        currentVisit.totalEventsCount++;
        currentVisit.hasSignificantSignal = true;
      }
    }, { passive: true });

    // Keyboard dynamics (Timing ONLY — NO key names or characters stored)
    window.addEventListener('keydown', function (e) {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      if (e.target && (e.target.type === 'password' || e.target.getAttribute('data-private') === 'true')) return;
      if (e.repeat) return; // Discard auto-repeat events

      const now = performance.now();
      recordActivity(currentVisit);
      const elapsed = Math.round(now - currentVisit.startTime);
      const interval = lastKeyDownTime > 0 ? Math.round(now - lastKeyDownTime) : 0;
      lastKeyDownTime = now;

      const code = e.code || ('k_' + Math.random().toString(36).slice(2, 6));
      currentVisit.activeKeyCodes.set(code, { elapsed: elapsed, pressTime: now });

      if (currentVisit.pendingKeyboard.length < MAX_KEYBOARD_DELTA) {
        currentVisit.pendingKeyboard.push({
          t: elapsed,
          interval: interval,
          hold: 0,
          is_paste: false,
          _code: code,
        });
        currentVisit.totalEventsCount++;
        currentVisit.hasSignificantSignal = true;
      }
    }, { passive: true });

    window.addEventListener('keyup', function (e) {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      if (e.target && e.target.type === 'password') return;

      const now = performance.now();
      const code = e.code;
      if (code && currentVisit.activeKeyCodes.has(code)) {
        const item = currentVisit.activeKeyCodes.get(code);
        currentVisit.activeKeyCodes.delete(code);
        const holdDuration = Math.max(0, Math.round(now - item.pressTime));

        for (let i = currentVisit.pendingKeyboard.length - 1; i >= 0; i--) {
          if (currentVisit.pendingKeyboard[i]._code === code) {
            currentVisit.pendingKeyboard[i].hold = holdDuration;
            break;
          }
        }
      }
    }, { passive: true });

    // Paste event flag (content stripped)
    window.addEventListener('paste', function (e) {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      if (e.target && e.target.type === 'password') return;
      const now = performance.now();
      recordActivity(currentVisit);
      currentVisit.pendingKeyboard.push({
        t: Math.round(now - currentVisit.startTime),
        interval: 0,
        hold: 0,
        is_paste: true,
      });
      currentVisit.totalEventsCount++;
    }, { passive: true });

    // Scroll dynamics
    window.addEventListener('scroll', function () {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      const now = performance.now();
      if (now - lastScrollTime < SCROLL_THROTTLE_MS) return;
      lastScrollTime = now;
      recordActivity(currentVisit);

      if (currentVisit.pendingScroll.length < MAX_SCROLL_DELTA) {
        const scrollY = window.scrollY || window.pageYOffset || 0;
        const lastY = currentVisit.pendingScroll.length > 0
          ? currentVisit.pendingScroll[currentVisit.pendingScroll.length - 1].scroll_y
          : scrollY;

        currentVisit.pendingScroll.push({
          t: Math.round(now - currentVisit.startTime),
          scroll_y: Math.round(scrollY),
          delta_y: Math.round(scrollY - lastY),
        });
        currentVisit.totalEventsCount++;
        if (currentVisit.pendingScroll.length >= 2) currentVisit.hasSignificantSignal = true;
      }
    }, { passive: true });
  }

  // 8. Payload Assembly & Reliable Transmission (P2 & P3 Solution)
  function assemblePayload(visit, seq, isFinal, events) {
    const now = performance.now();
    const durationMs = Math.max(0, Math.round(now - visit.startTime));

    // Strip private internal metadata (_code) from keyboard events
    const cleanKeyboard = events.keyboard.map(function (k) {
      return {
        t: k.t,
        interval: k.interval,
        hold: k.hold,
        is_paste: k.is_paste,
      };
    });

    return {
      session_id: visit.sessionId,
      page_visit_id: visit.sessionId,
      journey_id: getJourneyId(),
      previous_visit_id: visit.previousVisitId,
      site_id: siteId,
      visitor_id: visitorId,
      task: visit.task,
      seq: seq,
      final: Boolean(isFinal),
      start_time: visit.absoluteStartTime,
      end_time: visit.absoluteStartTime + durationMs,
      duration_ms: durationMs,
      active_duration_ms: getActiveDurationMs(visit),
      data_source: 'realtime_sdk',
      client_context: getClientContext(visit),
      browser_signals: getBrowserSignals(),
      mouse_events: events.mouse,
      keyboard_events: cleanKeyboard,
      scroll_events: events.scroll,
      click_events: events.clicks,
      task_actions: events.actions,
    };
  }

  function hasInteractionToSend(visit) {
    if (!visit) return false;
    return (
      visit.pendingMouse.length > 0 ||
      visit.pendingKeyboard.length > 0 ||
      visit.pendingScroll.length > 0 ||
      visit.pendingClicks.length > 0 ||
      visit.pendingActions.length > 0
    );
  }

  async function flushTelemetry(visit, isFinal) {
    if (!consentGranted || !visit) return null;
    if (!hasInteractionToSend(visit) && !isFinal && !visit.inFlight) return null;
    if (visit.isSending) return null;

    // Assemble new in-flight payload only if not currently waiting to retry an unacknowledged chunk
    if (!visit.inFlight) {
      if (!hasInteractionToSend(visit) && !isFinal) return null;

      const seq = visit.transmissionSeq;
      const deltaMouse = visit.pendingMouse.splice(0, visit.pendingMouse.length);
      const deltaKeyboard = visit.pendingKeyboard.splice(0, visit.pendingKeyboard.length);
      const deltaScroll = visit.pendingScroll.splice(0, visit.pendingScroll.length);
      const deltaClicks = visit.pendingClicks.splice(0, visit.pendingClicks.length);
      const deltaActions = visit.pendingActions.splice(0, visit.pendingActions.length);

      const payload = assemblePayload(visit, seq, isFinal, {
        mouse: deltaMouse,
        keyboard: deltaKeyboard,
        scroll: deltaScroll,
        clicks: deltaClicks,
        actions: deltaActions,
      });

      visit.inFlight = {
        seq: seq,
        payload: payload,
        bodyStr: JSON.stringify(payload),
        isFinal: Boolean(isFinal),
      };
    }

    const inFlight = visit.inFlight;
    visit.isSending = true;

    // Timeout guard: 10s timeout ensures isSending never gets permanently stuck
    const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    const timeoutId = setTimeout(function () {
      if (controller) controller.abort();
      visit.isSending = false;
    }, 10000);

    try {
      const resp = await fetch(apiEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Sentinel-Site-ID': siteId,
        },
        body: inFlight.bodyStr,
        signal: controller ? controller.signal : undefined,
        keepalive: true,
      });

      clearTimeout(timeoutId);
      visit.isSending = false;

      if (resp.ok) {
        const data = await resp.json();
        visit.latestVerdict = data;

        // Successfully acknowledged: advance seq and clear in-flight chunk
        visit.transmissionSeq++;
        visit.inFlight = null;

        // Broadcast verdict to window observers (such as the Chrome Extension)
        window.postMessage({
          type: 'WEBSENSE_VERDICT_UPDATE',
          verdict: data,
          sessionId: visit.sessionId,
          pageVisitId: visit.sessionId,
          seq: inFlight.seq,
        }, '*');

        return data;
      } else if (resp.status >= 400 && resp.status < 500 && resp.status !== 429) {
        // Permanent 4xx client rejection (e.g. 422 schema validation)
        // Log and drop this chunk so the client does not get stuck retrying forever
        console.warn('[WebSense Sentinel] Chunk seq ' + inFlight.seq + ' rejected by server (' + resp.status + '); dropping chunk.');
        visit.transmissionSeq++;
        visit.inFlight = null;
        return null;
      } else {
        // 429 (Rate limited) or 5xx (Server error) - keep visit.inFlight intact to retry the same payload with same seq
        console.warn('[WebSense Sentinel] Transient failure (' + resp.status + ') for chunk seq ' + inFlight.seq + '; will retry.');
        return null;
      }
    } catch (err) {
      clearTimeout(timeoutId);
      visit.isSending = false;

      // Network offline or fetch aborted - keep visit.inFlight intact for next retry
      if (isFinal && navigator.sendBeacon) {
        try {
          const blob = new Blob([inFlight.bodyStr], { type: 'application/json' });
          navigator.sendBeacon(apiEndpoint, blob);
        } catch (_) {}
      }
      return null;
    }
  }

  // 9. Lifecycle Management (SPA, bfcache, Page Unload)
  function handlePageVisitTransition(newPath) {
    const oldVisit = currentVisit;

    // 1. Flush previous visit as final asynchronously (bound to oldVisit state)
    if (oldVisit) {
      oldVisit.isFinalized = true;
      flushTelemetry(oldVisit, true);
    }

    // 2. Instantiate completely isolated NEW visit state (P3 fix)
    const prevId = oldVisit ? oldVisit.sessionId : null;
    currentVisit = createPageVisit(prevId, currentTask);
  }

  // SPA Route Change Interception (pushState / replaceState / popstate)
  let lastPathname = location.pathname;

  function checkPathChange() {
    if (location.pathname !== lastPathname) {
      lastPathname = location.pathname;
      handlePageVisitTransition(location.pathname);
    }
  }

  const origPushState = history.pushState;
  if (origPushState) {
    history.pushState = function () {
      origPushState.apply(history, arguments);
      checkPathChange();
    };
  }

  const origReplaceState = history.replaceState;
  if (origReplaceState) {
    history.replaceState = function () {
      origReplaceState.apply(history, arguments);
      checkPathChange();
    };
  }

  window.addEventListener('popstate', checkPathChange);

  // Back-Forward Cache (bfcache) restore
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) {
      handlePageVisitTransition(location.pathname);
    }
  });

  // Visibility and Pagehide Lifecycle
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden' && currentVisit) {
      flushTelemetry(currentVisit, false);
    }
  });

  window.addEventListener('pagehide', function () {
    if (currentVisit && !currentVisit.isFinalized) {
      flushTelemetry(currentVisit, true);
    }
  });

  // Periodic delta flush every 5 seconds if interaction has occurred or retry is pending
  setInterval(function () {
    if (document.visibilityState === 'visible' && currentVisit) {
      if (hasInteractionToSend(currentVisit) || currentVisit.inFlight) {
        flushTelemetry(currentVisit, false);
      }
    }
  }, 5000);

  // 10. Public API
  const Sentinel = {
    version: '1.3.1',
    siteId: siteId,
    getSessionId: function () { return currentVisit ? currentVisit.sessionId : null; },
    getPageVisitId: function () { return currentVisit ? currentVisit.sessionId : null; },
    getVisitorId: function () { return visitorId; },
    getJourneyId: function () { return getJourneyId(); },
    getTabId: function () { return tabId; },
    getClientContext: function () { return getClientContext(currentVisit); },
    getLatestVerdict: function () { return currentVisit ? currentVisit.latestVerdict : null; },

    logAction: function (action, details) {
      if (!consentGranted || !currentVisit || currentVisit.isFinalized) return;
      recordActivity(currentVisit);
      currentVisit.pendingActions.push({
        action: action,
        t: Math.round(performance.now() - currentVisit.startTime),
        details: details || {},
      });
      currentVisit.totalEventsCount++;
    },

    grantConsent: function () {
      consentGranted = true;
      for (let i = 0; i < CONSENT_KEYS.length; i++) {
        try { localStorage.setItem(CONSENT_KEYS[i], 'granted'); } catch (_) {}
      }
      attachListeners();
    },

    declineConsent: function () {
      consentGranted = false;
      for (let i = 0; i < CONSENT_KEYS.length; i++) {
        try { localStorage.setItem(CONSENT_KEYS[i], 'declined'); } catch (_) {}
      }
    },

    setTask: function (task) {
      currentTask = task || 'general';
      if (currentVisit) {
        currentVisit.task = currentTask;
      }
    },

    flush: function (overrideTask) {
      if (overrideTask) Sentinel.setTask(overrideTask);
      return flushTelemetry(currentVisit, false);
    },

    init: function () {
      if (consentGranted) {
        attachListeners();
      }
    },
  };

  window.Sentinel = Sentinel;
  window.WebSense = Sentinel; // Backward compatibility alias

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', Sentinel.init);
  } else {
    Sentinel.init();
  }

})(window, document);
