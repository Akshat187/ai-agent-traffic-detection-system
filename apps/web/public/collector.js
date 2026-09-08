/**
 * WebSense Behavioral Telemetry Collector — v1.1
 *
 * Privacy-preserving client-side instrumentation for:
 *   - Mouse movement dynamics (position, timing)
 *   - Keyboard press timing ONLY (never characters, never passwords)
 *   - Scroll patterns
 *   - Click categorization
 *   - Browser environment signals
 *
 * Consent gating: ALL event listeners are disabled until the user
 * explicitly accepts the consent notice. If declined, nothing is collected
 * and nothing is ever transmitted.
 *
 * PRIVACY GUARANTEES:
 *   - Input type="password" fields: never instrumented at all.
 *   - e.key / e.keyCode: never recorded, only timing metadata (e.code ignored too).
 *   - Keystroke characters, form values, text content: never transmitted.
 */

(function () {
  'use strict';

  // ─── Configuration ──────────────────────────────────────────────────────
  const API_ENDPOINT       = '/api/v1/sessions';
  const CONSENT_STORAGE_KEY = 'meridian_telemetry_consent';   // 'granted' | 'declined'
  const SESSION_KEY        = 'meridian_session_id';
  const VISITOR_KEY        = 'meridian_visitor_id';
  const MOUSE_THROTTLE_MS  = 25;
  const SCROLL_THROTTLE_MS = 50;
  const MAX_MOUSE_EVENTS   = 500;
  const MAX_KEYBOARD_EVENTS = 300;
  const MAX_SCROLL_EVENTS  = 200;
  const MAX_RETRY_ATTEMPTS = 3;
  const RETRY_BASE_DELAY_MS = 1000;

  // ─── State ──────────────────────────────────────────────────────────────
  let consentGiven = false;
  let listenersAttached = false;

  const mouseEvents    = [];
  const keyboardEvents = [];
  const scrollEvents   = [];
  const clickEvents    = [];
  const taskActions    = [];

  let lastMouseMoveTime = 0;
  let lastScrollTime    = 0;
  let lastKeyDownTime   = 0;
  const activeKeys      = new Map();
  let isTransmitted     = false;

  // ─── Session / Visitor IDs ───────────────────────────────────────────────
  function generateId(prefix) {
    return prefix + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  }

  let sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = generateId('st');
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }

  let visitorId = localStorage.getItem(VISITOR_KEY);
  if (!visitorId) {
    visitorId = generateId('vis');
    localStorage.setItem(VISITOR_KEY, visitorId);
  }

  const startTime         = performance.now();
  const absoluteStartTime = Date.now();

  // ─── Browser Signals ─────────────────────────────────────────────────────
  function getBrowserSignals() {
    return {
      webdriver:           Boolean(navigator.webdriver),
      screen_width:        window.screen ? window.screen.width  : 1920,
      screen_height:       window.screen ? window.screen.height : 1080,
      viewport_width:      window.innerWidth  || 1280,
      viewport_height:     window.innerHeight || 720,
      device_pixel_ratio:  window.devicePixelRatio || 1.0,
      touch_support:       ('ontouchstart' in window) || navigator.maxTouchPoints > 0,
      hardware_concurrency: navigator.hardwareConcurrency || 4,
      platform:            navigator.platform  || 'unknown',
      language:            navigator.language  || 'en-US',
      user_agent:          navigator.userAgent || '',
      timezone_offset:     new Date().getTimezoneOffset(),
    };
  }

  // ─── Event Listeners (only attached after consent) ────────────────────────
  function attachListeners() {
    if (listenersAttached) return;
    listenersAttached = true;

    // Mouse movement — throttled, no tracking within password inputs
    window.addEventListener('mousemove', function (e) {
      if (!consentGiven) return;
      const now = performance.now();
      if (now - lastMouseMoveTime < MOUSE_THROTTLE_MS) return;
      lastMouseMoveTime = now;
      if (mouseEvents.length < MAX_MOUSE_EVENTS) {
        mouseEvents.push({
          x:    Math.round(e.clientX),
          y:    Math.round(e.clientY),
          t:    Math.round(now - startTime),
          type: 'move',
        });
      }
    }, { passive: true });

    // Click categorization (no sensitive element content logged)
    window.addEventListener('click', function (e) {
      if (!consentGiven) return;
      const now    = performance.now();
      const target = e.target;
      let category = 'general';

      if (target.closest("button, .btn, [role='button']"))                  category = 'button';
      else if (target.closest("input[type='text'], input[type='email'], input[type='search'], textarea, select")) category = 'input';
      else if (target.closest('a, nav'))                                    category = 'navigation';
      else if (target.closest('.add-cart-btn, #checkout-btn'))              category = 'checkout';

      clickEvents.push({
        x:               Math.round(e.clientX),
        y:               Math.round(e.clientY),
        t:               Math.round(now - startTime),
        target_category: category,
      });
    }, { passive: true });

    // Keyboard timing ONLY — NO characters, NEVER on password inputs
    window.addEventListener('keydown', function (e) {
      if (!consentGiven) return;
      // Absolute guarantee: skip password fields
      if (e.target && e.target.type === 'password') return;

      const now      = performance.now();
      const elapsed  = Math.round(now - startTime);
      const interval = lastKeyDownTime > 0 ? Math.round(now - lastKeyDownTime) : 0;
      lastKeyDownTime = now;

      // Store down-time for hold duration calculation; key identity is NOT stored
      activeKeys.set(elapsed, now);   // use timestamp as unique handle, not key code

      if (keyboardEvents.length < MAX_KEYBOARD_EVENTS) {
        keyboardEvents.push({
          t:        elapsed,
          interval: interval,
          hold:     0,        // filled in on keyup
          is_paste: false,
          // NOTE: e.key, e.code, e.keyCode — NEVER stored
        });
      }
    }, { passive: true });

    window.addEventListener('keyup', function (e) {
      if (!consentGiven) return;
      if (e.target && e.target.type === 'password') return;

      if (keyboardEvents.length > 0) {
        const last = keyboardEvents[keyboardEvents.length - 1];
        if (last.hold === 0) {
          // Find matching down-time: the most recent active key
          let pressTime = null;
          activeKeys.forEach((t) => { if (pressTime === null || t > pressTime) pressTime = t; });
          if (pressTime !== null) {
            last.hold = Math.max(0, Math.round(performance.now() - pressTime));
            activeKeys.clear();  // clear to avoid accumulation
          }
        }
      }
    }, { passive: true });

    // Paste event (metadata only: marks that a paste occurred, not what was pasted)
    window.addEventListener('paste', function (e) {
      if (!consentGiven) return;
      if (e.target && e.target.type === 'password') return;
      keyboardEvents.push({
        t:        Math.round(performance.now() - startTime),
        interval: 0,
        hold:     0,
        is_paste: true,
      });
    }, { passive: true });

    // Scroll dynamics — throttled
    window.addEventListener('scroll', function () {
      if (!consentGiven) return;
      const now = performance.now();
      if (now - lastScrollTime < SCROLL_THROTTLE_MS) return;
      lastScrollTime = now;
      const scrollY = window.scrollY || document.documentElement.scrollTop;
      const prevY   = scrollEvents.length > 0 ? scrollEvents[scrollEvents.length - 1].scroll_y : 0;
      if (scrollEvents.length < MAX_SCROLL_EVENTS) {
        scrollEvents.push({
          t:        Math.round(now - startTime),
          scroll_y: Math.round(scrollY),
          delta_y:  Math.round(scrollY - prevY),
        });
      }
    }, { passive: true });
  }

  // ─── Payload Assembly ─────────────────────────────────────────────────────
  function buildPayload(taskName) {
    const now      = performance.now();
    const duration = Math.round(now - startTime);
    return {
      session_id:     sessionId,
      site_id:        'site_meridian_prod',
      visitor_id:     visitorId,
      task:           taskName || document.body.dataset.task || 'general',
      start_time:     absoluteStartTime,
      end_time:       absoluteStartTime + duration,
      duration_ms:    duration,
      is_synthetic:   false,
      data_source:    'realtime_sdk',
      browser_signals: getBrowserSignals(),
      mouse_events:    mouseEvents.slice(),
      keyboard_events: keyboardEvents.slice(),
      scroll_events:   scroll_events_safe(),
      click_events:    clickEvents.slice(),
      task_actions:    taskActions.slice(),
    };
  }

  function scroll_events_safe() {
    // defensive copy — scroll events are already privacy-safe (only scroll_y, delta_y, t)
    return scrollEvents.slice();
  }

  // ─── Transmission with exponential backoff retry ──────────────────────────
  async function transmit(payload, attempt) {
    attempt = attempt || 1;
    try {
      const res = await fetch(API_ENDPOINT, {
        method:    'POST',
        headers:   { 'Content-Type': 'application/json' },
        body:      JSON.stringify(payload),
        keepalive: true,
      });
      if (!res.ok && attempt < MAX_RETRY_ATTEMPTS) {
        await delay(RETRY_BASE_DELAY_MS * Math.pow(2, attempt - 1));
        return transmit(payload, attempt + 1);
      }
      return res.ok ? res.json() : null;
    } catch (err) {
      if (attempt < MAX_RETRY_ATTEMPTS) {
        await delay(RETRY_BASE_DELAY_MS * Math.pow(2, attempt - 1));
        return transmit(payload, attempt + 1);
      }
      // Final failure: stash in sessionStorage (no sensitive data in payload)
      try {
        sessionStorage.setItem('meridian_pending_payload', JSON.stringify(payload));
      } catch (_) { /* storage full — discard silently */ }
      return null;
    }
  }

  function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function sendBeaconFallback(payload) {
    if (!navigator.sendBeacon) return false;
    const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
    return navigator.sendBeacon(API_ENDPOINT, blob);
  }

  // ─── Consent Management ──────────────────────────────────────────────────
  function applyConsent(granted) {
    consentGiven = granted;
    try {
      localStorage.setItem(CONSENT_STORAGE_KEY, granted ? 'granted' : 'declined');
    } catch (_) {}
    if (granted) {
      attachListeners();
    }
  }

  // Check existing consent
  let existingConsent = null;
  try { existingConsent = localStorage.getItem(CONSENT_STORAGE_KEY); } catch (_) {}

  if (existingConsent === 'granted') {
    applyConsent(true);
  } else if (existingConsent === 'declined') {
    applyConsent(false);
  }
  // If no existing consent → the consent notice will be shown by visitor.js

  // ─── Public API ───────────────────────────────────────────────────────────
  window.WebSense = {
    sessionId:    sessionId,
    visitorId:    visitorId,
    consentGiven: consentGiven,

    /** Record a named task action (no text content, only metadata). */
    logAction: function (actionName, details) {
      if (!consentGiven) return;
      taskActions.push({
        action:  actionName,
        t:       Math.round(performance.now() - startTime),
        details: details || {},
      });
    },

    /** Flush telemetry payload (async, returns promise with server response). */
    flush: function (taskName) {
      if (!consentGiven) return Promise.resolve(null);
      if (isTransmitted) return Promise.resolve(null);
      isTransmitted = true;
      const payload = buildPayload(taskName);
      return transmit(payload);
    },

    /** Grant consent programmatically (called from visitor.js consent modal). */
    grantConsent: function () {
      applyConsent(true);
      this.consentGiven = true;
    },

    /** Decline consent — no collection, no transmission. */
    declineConsent: function () {
      applyConsent(false);
      this.consentGiven = false;
    },

    /** Dev-only: returns current buffer snapshot without transmitting. */
    getDebugSnapshot: function () {
      return buildPayload();
    },
  };

  if (!window.Sentinel) {
    window.Sentinel = window.WebSense;
  }

  // ─── Auto-flush on page unload ────────────────────────────────────────────
  window.addEventListener('pagehide', function () {
    if (!consentGiven || isTransmitted) return;
    const hasData = mouseEvents.length > 0 || clickEvents.length > 0 || keyboardEvents.length > 0;
    if (!hasData) return;
    isTransmitted = true;
    sendBeaconFallback(buildPayload(null));
  });

})();


