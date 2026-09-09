/**
 * Sentinel Behavioral Intelligence SDK — v1.2.0
 * Standalone, zero-dependency embeddable script for AI agent and bot detection.
 *
 * Usage:
 *   <script src="https://api.yourdomain.com/sentinel.js" data-site-id="site_xxxx" async></script>
 *
 * Privacy Guarantees:
 *   - NEVER records keystroke characters, key codes, or form inputs.
 *   - NEVER captures or interacts with type="password" fields.
 *   - Captures anonymous timing and kinematic dynamics ONLY.
 */

(function (window, document) {
  'use strict';

  // 1. Discover configuration from script tag
  const currentScript = document.currentScript || (function() {
    const scripts = document.getElementsByTagName('script');
    for (let i = scripts.length - 1; i >= 0; i--) {
      if (scripts[i].src && (scripts[i].src.includes('sentinel.js') || scripts[i].src.includes('collector.js'))) {
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

  const siteId = (currentScript && currentScript.getAttribute('data-site-id')) || 'site_meridian_prod';
  const apiEndpoint = (currentScript && currentScript.getAttribute('data-endpoint')) || defaultEndpoint;
  const taskName = (currentScript && currentScript.getAttribute('data-task')) || (document.body ? document.body.dataset.task : 'general') || 'general';
  const requireConsent = currentScript && currentScript.getAttribute('data-require-consent') === 'true';

  // 2. Constants & Storage Keys
  const CONSENT_STORAGE_KEY = 'ws_sentinel_consent_' + siteId;
  const SESSION_KEY = 'ws_sentinel_session_' + siteId;
  const VISITOR_KEY = 'ws_visitor_id';
  const LEGACY_VISITOR_KEYS = ['ws_sentinel_visitor_id', 'meridian_visitor_id'];
  const TAB_KEY = 'ws_tab_id';
  const SEQ_KEY = 'ws_transmission_seq';

  const MOUSE_THROTTLE_MS = 25;
  const SCROLL_THROTTLE_MS = 50;
  const MAX_MOUSE_EVENTS = 600;
  const MAX_KEYBOARD_EVENTS = 400;
  const MAX_SCROLL_EVENTS = 250;
  const MAX_CLICK_EVENTS = 100;

  // 3. State
  let consentGranted = !requireConsent;
  const savedConsent = (function() {
    try { return localStorage.getItem(CONSENT_STORAGE_KEY); } catch(_) { return null; }
  })();
  if (savedConsent === 'granted') consentGranted = true;
  if (savedConsent === 'declined') consentGranted = false;

  let listenersAttached = false;
  let isTransmitted = false;

  const mouseEvents = [];
  const keyboardEvents = [];
  const scrollEvents = [];
  const clickEvents = [];
  const taskActions = [];

  let lastMouseMoveTime = 0;
  let lastScrollTime = 0;
  let lastKeyDownTime = 0;
  const activeKeys = new Map();

  // --- Active-Duration Tracking ---
  // Measures the true active engagement window, not raw tab lifetime.
  // Gaps > INACTIVITY_GAP_MS between events are treated as idle and excluded
  // so a tab left open idle in the background does not inflate ratio features.
  const INACTIVITY_GAP_MS = 60000; // 60 s of silence = idle, not counted
  let firstEventTime = null;
  let lastEventTime  = null;
  let accumulatedIdleMs = 0;

  function recordActivity() {
    const now = performance.now();
    if (firstEventTime === null) {
      firstEventTime = now;
    } else if (lastEventTime !== null) {
      const gap = now - lastEventTime;
      if (gap > INACTIVITY_GAP_MS) accumulatedIdleMs += gap;
    }
    lastEventTime = now;
  }

  function getActiveDurationMs() {
    if (firstEventTime === null || lastEventTime === null) return 0;
    return Math.max(0, Math.round((lastEventTime - firstEventTime) - accumulatedIdleMs));
  }

  function generateId(prefix) {
    return prefix + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 9);
  }

  let sessionId = (function() {
    try {
      let s = sessionStorage.getItem(SESSION_KEY);
      if (!s) {
        s = generateId('st');
        sessionStorage.setItem(SESSION_KEY, s);
      }
      return s;
    } catch (_) {
      return generateId('st');
    }
  })();

  let visitorId = (function() {
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
      sdk_version: 'sentinel-1.2.0',
    };
  }

  const startTime = performance.now();
  const absoluteStartTime = Date.now();

  // 4. Browser Environment Signals
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

  // 5. Behavioral Event Listeners
  function attachListeners() {
    if (listenersAttached || !consentGranted) return;
    listenersAttached = true;

    // Mouse movement dynamics
    window.addEventListener('mousemove', function (e) {
      if (!consentGranted) return;
      const now = performance.now();
      if (now - lastMouseMoveTime < MOUSE_THROTTLE_MS) return;
      lastMouseMoveTime = now;
      recordActivity();
      if (mouseEvents.length < MAX_MOUSE_EVENTS) {
        mouseEvents.push({
          x: Math.round(e.clientX),
          y: Math.round(e.clientY),
          t: Math.round(now - startTime),
          type: 'move',
        });
      }
    }, { passive: true });

    // Click categorization (no sensitive form contents)
    window.addEventListener('click', function (e) {
      if (!consentGranted) return;
      const now = performance.now();
      const target = e.target;
      recordActivity();
      let category = 'general';

      if (target.closest("button, .btn, [role='button'], input[type='submit']")) category = 'button';
      else if (target.closest("input, textarea, select")) category = 'input';
      else if (target.closest('a, nav')) category = 'navigation';
      else if (target.closest('.add-cart-btn, #checkout-btn, .flight-card')) category = 'task_action';

      if (clickEvents.length < MAX_CLICK_EVENTS) {
        clickEvents.push({
          x: Math.round(e.clientX),
          y: Math.round(e.clientY),
          t: Math.round(now - startTime),
          target_category: category,
        });
      }
    }, { passive: true });

    // Keyboard dynamics (TIMING ONLY — no characters, never password fields)
    window.addEventListener('keydown', function (e) {
      if (!consentGranted) return;
      if (e.target && (e.target.type === 'password' || e.target.getAttribute('data-private') === 'true')) return;

      const now = performance.now();
      recordActivity();
      const elapsed = Math.round(now - startTime);
      const interval = lastKeyDownTime > 0 ? Math.round(now - lastKeyDownTime) : 0;
      lastKeyDownTime = now;

      activeKeys.set(elapsed, now);

      if (keyboardEvents.length < MAX_KEYBOARD_EVENTS) {
        keyboardEvents.push({
          t: elapsed,
          interval: interval,
          hold: 0,
          is_paste: false,
        });
      }
    }, { passive: true });

    window.addEventListener('keyup', function (e) {
      if (!consentGranted) return;
      if (e.target && e.target.type === 'password') return;

      const now = performance.now();
      if (keyboardEvents.length > 0) {
        const last = keyboardEvents[keyboardEvents.length - 1];
        const downTime = activeKeys.get(last.t);
        if (downTime && last.hold === 0) {
          last.hold = Math.round(now - downTime);
        }
      }
    }, { passive: true });

    // Paste event indicator (flag only, content ignored)
    window.addEventListener('paste', function (e) {
      if (!consentGranted) return;
      if (e.target && e.target.type === 'password') return;
      const now = performance.now();
      keyboardEvents.push({
        t: Math.round(now - startTime),
        interval: 0,
        hold: 0,
        is_paste: true,
      });
    }, { passive: true });

    // Scroll dynamics
    window.addEventListener('scroll', function () {
      if (!consentGranted) return;
      const now = performance.now();
      if (now - lastScrollTime < SCROLL_THROTTLE_MS) return;
      lastScrollTime = now;
      recordActivity();
      if (scrollEvents.length < MAX_SCROLL_EVENTS) {
        const scrollY = window.scrollY || window.pageYOffset || 0;
        const lastY = scrollEvents.length > 0 ? scrollEvents[scrollEvents.length - 1].scroll_y : scrollY;
        scrollEvents.push({
          t: Math.round(now - startTime),
          scroll_y: Math.round(scrollY),
          delta_y: Math.round(scrollY - lastY),
        });
      }
    }, { passive: true });
  }

  // 6. Payload Assembly & Telemetry Flush
  function buildPayload(overrideTask) {
    const now = performance.now();
    const durationMs = Math.round(now - startTime);

    return {
      session_id: sessionId,
      site_id: siteId,
      visitor_id: visitorId,
      task: overrideTask || taskName,
      start_time: Math.round(absoluteStartTime / 1000),
      end_time: Math.round((absoluteStartTime + durationMs) / 1000),
      duration_ms: durationMs,
      // Bounded active engagement window: excludes idle gaps > 60 s.
      // The detection engine uses this field for all ratio-based features.
      active_duration_ms: getActiveDurationMs(),
      data_source: 'realtime_sdk',
      client_context: getClientContext(),
      browser_signals: getBrowserSignals(),
      mouse_events: mouseEvents,
      keyboard_events: keyboardEvents,
      scroll_events: scrollEvents,
      click_events: clickEvents,
      task_actions: taskActions,
    };
  }

  async function flushTelemetry(overrideTask) {
    if (!consentGranted) return Promise.resolve(null);
    if (mouseEvents.length === 0 && keyboardEvents.length === 0 && scrollEvents.length === 0 && clickEvents.length === 0) {
      return Promise.resolve(null);
    }

    const payload = buildPayload(overrideTask);
    const bodyStr = JSON.stringify(payload);

    try {
      const resp = await fetch(apiEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Sentinel-Site-ID': siteId
        },
        body: bodyStr,
        keepalive: true,
      });
      if (resp.ok) {
        isTransmitted = true;
        return await resp.json();
      }
    } catch (err) {
      // Fallback via sendBeacon on unload
      if (navigator.sendBeacon) {
        navigator.sendBeacon(apiEndpoint, bodyStr);
      }
    }
    return null;
  }

  // 7. Auto Flush on Page Lifecycle
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      flushTelemetry();
    }
  });

  window.addEventListener('beforeunload', function () {
    if (!isTransmitted && consentGranted) {
      const payload = buildPayload();
      const body = JSON.stringify(payload);
      if (navigator.sendBeacon) {
        navigator.sendBeacon(apiEndpoint, body);
      }
    }
  });

  // 8. Public SDK API
  const Sentinel = {
    version: '1.2.0',
    siteId: siteId,
    getSessionId: function() { return sessionId; },
    getVisitorId: function() { return visitorId; },
    getTabId: function() {
      try {
        let tabId = sessionStorage.getItem(TAB_KEY);
        if (!tabId) {
          tabId = 'tab_' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 16) : generateId('tab').slice(4));
          sessionStorage.setItem(TAB_KEY, tabId);
        }
        return tabId;
      } catch (_) {
        return generateId('tab');
      }
    },
    getClientContext: function() { return getClientContext(); },
    
    logAction: function (action, details) {
      if (!consentGranted) return;
      taskActions.push({
        action: action,
        t: Math.round(performance.now() - startTime),
        details: details || {},
      });
    },

    grantConsent: function () {
      consentGranted = true;
      try { localStorage.setItem(CONSENT_STORAGE_KEY, 'granted'); } catch (_) {}
      attachListeners();
    },

    declineConsent: function () {
      consentGranted = false;
      try { localStorage.setItem(CONSENT_STORAGE_KEY, 'declined'); } catch (_) {}
    },

    flush: function (task) {
      return flushTelemetry(task);
    },

    init: function () {
      if (consentGranted) {
        attachListeners();
      }
    }
  };

  // Expose global SDK
  window.Sentinel = Sentinel;
  window.WebSense = Sentinel; // Backward compatibility alias for Meridian honey-sites

  // Auto-initialize if DOM is ready or on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', Sentinel.init);
  } else {
    Sentinel.init();
  }

})(window, document);
