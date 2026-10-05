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

  // Guard 1: Only run in top-level browsing context (never in iframes/subframes)
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
      window.__WEBSENSE_COLLECTOR_ACTIVE__ === true ||
      !!document.querySelector('script[src*="sentinel.js"], script[src*="collector.js"]')
    );
  }

  function yieldToSdk(reason) {
    if (isYieldingToSdk) return;
    isYieldingToSdk = true;
    isCollecting = false;
    if (currentVisit) {
      currentVisit.inFlight = null;
      currentVisit.isFinalized = true;
    }
    console.info('[WebSense Extension] Yielded telemetry collection to native website SDK (' + reason + ').');
    setupMessageResponder();
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
    } else if (event.data && event.data.type === 'WEBSENSE_SDK_ACTIVATED') {
      yieldToSdk('postMessage WEBSENSE_SDK_ACTIVATED');
    }
  });

  // Listen for native SDK activation events
  window.addEventListener('ws:collector_activated', () => {
    yieldToSdk('ws:collector_activated event');
  });

  window.addEventListener('ws:claimed', (e) => {
    if (e.detail && e.detail.owner === 'sdk') {
      yieldToSdk('ws:claimed event');
    }
  });

  // Watch for dynamic injection of collector/sentinel scripts after consent
  try {
    const observer = new MutationObserver((mutations) => {
      if (isYieldingToSdk) {
        observer.disconnect();
        return;
      }
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            const tag = node.tagName ? node.tagName.toLowerCase() : '';
            if (tag === 'script') {
              const src = node.getAttribute('src') || '';
              if (src.includes('sentinel.js') || src.includes('collector.js')) {
                yieldToSdk('dynamic script element added');
                observer.disconnect();
                return;
              }
            }
          }
        }
      }
    });
    observer.observe(document.documentElement || document, { childList: true, subtree: true });
  } catch (_) {}

  if (checkSdkPresence()) {
    yieldToSdk('initial DOM inspection');
    return;
  }

  // Claim ownership if SDK is not present
  document.documentElement.dataset.wsOwner = 'extension';

  // --- Constants & IDs ---
  const VISITOR_KEY = 'ws_visitor_id';
  const JOURNEY_KEY = 'ws_journey_id';
  const JOURNEY_TIME_KEY = 'ws_journey_last_active';
  const PREV_VISIT_KEY = 'ws_prev_visit_id';
  const TAB_KEY = 'ws_tab_id';
  const JOURNEY_MAX_IDLE_MS = 30 * 60 * 1000;
  const INACTIVITY_GAP_MS = 60000;

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

  // --- Page Visit State Factory ---
  function createExtensionVisit(prevVisitId) {
    const sid = generateId('ext_st');
    try {
      sessionStorage.setItem(PREV_VISIT_KEY, sid);
    } catch (_) {}

    return {
      sessionId: sid,
      previousVisitId: prevVisitId,
      transmissionSeq: 1,
      startTime: performance.now(),
      startUnixTime: Date.now(),
      firstEventTime: null,
      lastEventTime: null,
      accumulatedIdleMs: 0,
      totalEventsTransmitted: 0,

      // Delta buffers
      mouseEvents: [],
      keyboardEvents: [],
      scrollEvents: [],
      clickEvents: [],
      taskActions: [],
      activeKeys: new Map(), // code -> pressTime

      // In-flight transmission tracking
      inFlight: null,
      isFlushing: false,
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

  function isTabActive() {
    return document.visibilityState === 'visible' && (typeof document.hasFocus === 'function' ? document.hasFocus() : true);
  }

  let currentVisit = createExtensionVisit(initialPreviousVisitId);
  let isCollecting = isTabActive();
  let lastMouseMoveTime = 0;
  let lastScrollTime = 0;
  let lastKeyDownTime = 0;

  function recordActivity(visit) {
    if (isYieldingToSdk || !isCollecting || !isTabActive() || !visit) return;
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
    return Math.max(0, Math.round(visit.lastEventTime - visit.firstEventTime - visit.accumulatedIdleMs));
  }

  function hasMinimumInteraction(visit) {
    if (!visit) return false;
    if (visit.clickEvents.length >= 1) return true;
    if (visit.keyboardEvents.length >= 2) return true;
    if (visit.scrollEvents.length >= 2) return true;
    if (visit.mouseEvents.length >= 8) {
      const first = visit.mouseEvents[0];
      const last = visit.mouseEvents[visit.mouseEvents.length - 1];
      const dx = last.x - first.x;
      const dy = last.y - first.y;
      if (Math.sqrt(dx * dx + dy * dy) >= 15) return true;
    }
    return (visit.mouseEvents.length + visit.keyboardEvents.length + visit.scrollEvents.length + visit.clickEvents.length) >= 5;
  }

  function hasPendingEvents(visit) {
    if (!visit) return false;
    return (
      visit.mouseEvents.length > 0 ||
      visit.keyboardEvents.length > 0 ||
      visit.scrollEvents.length > 0 ||
      visit.clickEvents.length > 0 ||
      visit.taskActions.length > 0
    );
  }

  // --- Event Listeners ---
  window.addEventListener('mousemove', function (e) {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    const now = performance.now();
    if (now - lastMouseMoveTime < 25) return;
    lastMouseMoveTime = now;
    recordActivity(currentVisit);

    if (currentVisit.mouseEvents.length < 300) {
      currentVisit.mouseEvents.push({
        x: Math.round(e.clientX),
        y: Math.round(e.clientY),
        t: Math.round(now - currentVisit.startTime),
        type: 'move'
      });
    }
  }, { passive: true });

  window.addEventListener('click', function (e) {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    recordActivity(currentVisit);
    const tag = (e.target.tagName || '').toLowerCase();
    let category = 'other';
    const interactive = e.target.closest('button, a, input, select, textarea, [role="button"]');
    if (['button', 'input', 'a'].includes(tag) || interactive) {
      category = tag === 'a' || (interactive && interactive.tagName.toLowerCase() === 'a') ? 'link' : 'button';
    }
    if (currentVisit.clickEvents.length < 50) {
      currentVisit.clickEvents.push({
        x: Math.round(e.clientX),
        y: Math.round(e.clientY),
        t: Math.round(performance.now() - currentVisit.startTime),
        target_category: category
      });
    }

    // Capture semantic DOM task action for meaningful user interactions
    if (interactive && currentVisit.taskActions.length < 50) {
      const el = interactive;
      const elTag = el.tagName.toLowerCase();
      let act = 'element_click';
      if (elTag === 'a') act = 'link_navigate';
      else if (elTag === 'button' || el.getAttribute('role') === 'button') act = 'button_trigger';
      else if (elTag === 'input' && (el.type === 'submit' || el.type === 'button')) act = 'form_action';
      else if (elTag === 'input' || elTag === 'select' || elTag === 'textarea') act = 'input_focus';

      const label = (el.getAttribute('aria-label') || el.name || el.id || el.textContent || '').trim().slice(0, 40);
      currentVisit.taskActions.push({
        action: act,
        t: Math.round(performance.now() - currentVisit.startTime),
        details: { tag: elTag, label: label, trusted: e.isTrusted }
      });
    }
  }, { passive: true });

  window.addEventListener('submit', function (e) {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    recordActivity(currentVisit);
    if (currentVisit.taskActions.length < 50) {
      currentVisit.taskActions.push({
        action: 'form_submitted',
        t: Math.round(performance.now() - currentVisit.startTime),
        details: { target: (e.target.id || e.target.name || 'form').slice(0, 40) }
      });
    }
  }, { passive: true });

  // Keyboard dynamics with per-code hold tracking (P10 Fix)
  window.addEventListener('keydown', function (e) {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    if (e.target && (e.target.type === 'password' || e.target.dataset.private === 'true')) return;
    if (e.repeat) return; // Discard synthetic repeats

    recordActivity(currentVisit);
    const now = performance.now();
    const interval = lastKeyDownTime > 0 ? Math.round(now - lastKeyDownTime) : 0;
    lastKeyDownTime = now;

    const code = e.code || ('k_' + Math.random().toString(36).slice(2, 6));
    currentVisit.activeKeys.set(code, now);

    if (currentVisit.keyboardEvents.length < 200) {
      currentVisit.keyboardEvents.push({
        t: Math.round(now - currentVisit.startTime),
        interval: interval,
        hold: 0,
        is_paste: false,
        _code: code
      });
    }
  }, { passive: true });

  window.addEventListener('keyup', function (e) {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    if (e.target && (e.target.type === 'password' || e.target.dataset.private === 'true')) return;

    const code = e.code;
    if (code && currentVisit.activeKeys.has(code)) {
      const downTime = currentVisit.activeKeys.get(code);
      const hold = Math.max(1, Math.round(performance.now() - downTime));
      currentVisit.activeKeys.delete(code);

      // Attribute hold time to the matching key event (P10 rollover fix)
      for (let i = currentVisit.keyboardEvents.length - 1; i >= 0; i--) {
        if (currentVisit.keyboardEvents[i]._code === code) {
          currentVisit.keyboardEvents[i].hold = hold;
          break;
        }
      }
    }
  }, { passive: true });

  // Paste event detection (P10 Fix)
  window.addEventListener('paste', function (e) {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    if (e.target && (e.target.type === 'password' || e.target.dataset.private === 'true')) return;
    const now = performance.now();
    recordActivity(currentVisit);
    if (currentVisit.keyboardEvents.length < 200) {
      currentVisit.keyboardEvents.push({
        t: Math.round(now - currentVisit.startTime),
        interval: 0,
        hold: 0,
        is_paste: true
      });
    }
  }, { passive: true });

  window.addEventListener('scroll', function () {
    if (isYieldingToSdk || !isCollecting || !currentVisit || currentVisit.isFinalized) return;
    const now = performance.now();
    if (now - lastScrollTime < 50) return;
    recordActivity(currentVisit);
    const lastScrollY = currentVisit.scrollEvents.length > 0
      ? currentVisit.scrollEvents[currentVisit.scrollEvents.length - 1].scroll_y
      : 0;
    const currentY = Math.round(window.scrollY);
    lastScrollTime = now;
    if (currentVisit.scrollEvents.length < 150) {
      currentVisit.scrollEvents.push({
        t: Math.round(now - currentVisit.startTime),
        scroll_y: currentY,
        delta_y: currentY - lastScrollY
      });
    }
  }, { passive: true });

  // Visibility and Window Focus / Blur Lifecycle (True Active Tab Guarantee)
  function updateActiveState() {
    const active = isTabActive();
    if (active) {
      if (!isCollecting) {
        isCollecting = true;
        if (currentVisit && currentVisit.lastEventTime === null) {
          currentVisit.lastEventTime = performance.now();
        }
      }
    } else {
      if (isCollecting && currentVisit && currentVisit.lastEventTime !== null) {
        currentVisit.accumulatedIdleMs += performance.now() - currentVisit.lastEventTime;
        currentVisit.lastEventTime = null;
      }
      isCollecting = false;
      // Transmit intermediate delta when tab is switched or blurred
      if (currentVisit && !isYieldingToSdk) {
        flushTelemetry(currentVisit, false);
      }
    }
  }

  document.addEventListener('visibilitychange', updateActiveState);
  window.addEventListener('focus', updateActiveState);
  window.addEventListener('blur', updateActiveState);

  // --- Build Delta Chunk Payload ---
  function assembleExtensionPayload(visit, seq, isFinal, events) {
    let referrerPath = '';
    try {
      if (document.referrer) referrerPath = new URL(document.referrer).pathname;
    } catch (_) {}

    const cleanKeyboard = events.keyboard.map((k) => ({
      t: k.t,
      interval: k.interval,
      hold: k.hold,
      is_paste: k.is_paste
    }));

    const durationMs = Math.round(performance.now() - visit.startTime);

    return {
      session_id: visit.sessionId,
      page_visit_id: visit.sessionId,
      journey_id: getJourneyId(),
      previous_visit_id: visit.previousVisitId,
      site_id: EXTENSION_SITE_ID,
      visitor_id: visitorId,
      task: 'general',
      seq: seq,
      final: Boolean(isFinal),
      client_context: {
        tab_id: tabId,
        page_path: location.pathname,
        page_title: document.title || '',
        // P11 Fix: omit query string and hash from URL by default
        page_url: (location.origin + location.pathname).slice(0, 512),
        referrer_path: referrerPath,
        visibility_state: document.visibilityState,
        transmission_seq: seq,
        sdk_version: 'extension-2.1'
      },
      start_time: visit.startUnixTime,
      end_time: Date.now(),
      duration_ms: durationMs,
      active_duration_ms: getActiveDurationMs(visit),
      data_source: 'chrome_extension',
      browser_signals: {
        webdriver: Boolean(navigator.webdriver),
        screen_width: window.screen ? window.screen.width : 1920,
        screen_height: window.screen ? window.screen.height : 1080,
        viewport_width: window.innerWidth || 1280,
        viewport_height: window.innerHeight || 720,
        user_agent: navigator.userAgent || ''
      },
      mouse_events: events.mouse,
      keyboard_events: cleanKeyboard,
      scroll_events: events.scroll,
      click_events: events.clicks,
      task_actions: events.actions
    };
  }

  // --- Reliable Flushing Logic (P2, P4, P5 Fix) ---
  function flushTelemetry(visit, isFinal) {
    if (isYieldingToSdk || checkSdkPresence() || window.__WEBSENSE_COLLECTOR_ACTIVE__ || !visit || visit.isFlushing) {
      if (!isYieldingToSdk && (checkSdkPresence() || window.__WEBSENSE_COLLECTOR_ACTIVE__)) {
        yieldToSdk('flush presence check');
      }
      return;
    }

    // P4 Fix: Never create empty sessions for background tabs without interactions
    if (isFinal) {
      if (visit.totalEventsTransmitted === 0 && (!hasPendingEvents(visit) || !hasMinimumInteraction(visit))) {
        return; // Zero interaction tab close — do not transmit empty session
      }
    } else {
      if (visit.totalEventsTransmitted === 0 && !hasMinimumInteraction(visit)) return;
      if (visit.totalEventsTransmitted > 0 && !hasPendingEvents(visit) && !visit.inFlight) return;
    }

    // Assemble new in-flight chunk if none is waiting for retry
    if (!visit.inFlight) {
      if (!hasPendingEvents(visit) && !isFinal) return;

      const seq = visit.transmissionSeq;
      const deltaMouse = visit.mouseEvents.splice(0, visit.mouseEvents.length);
      const deltaKeyboard = visit.keyboardEvents.splice(0, visit.keyboardEvents.length);
      const deltaScroll = visit.scrollEvents.splice(0, visit.scrollEvents.length);
      const deltaClicks = visit.clickEvents.splice(0, visit.clickEvents.length);
      const deltaTasks = visit.taskActions.splice(0, visit.taskActions.length);

      const payload = assembleExtensionPayload(visit, seq, isFinal, {
        mouse: deltaMouse,
        keyboard: deltaKeyboard,
        scroll: deltaScroll,
        clicks: deltaClicks,
        actions: deltaTasks
      });

      visit.inFlight = {
        seq: seq,
        payload: payload,
        isFinal: Boolean(isFinal),
        eventCount: deltaMouse.length + deltaKeyboard.length + deltaScroll.length + deltaClicks.length
      };
    }

    const inFlight = visit.inFlight;
    visit.isFlushing = true;

    try {
      chrome.runtime.sendMessage(
        {
          type: 'INGEST_TELEMETRY',
          endpoint: DEFAULT_ENDPOINT,
          payload: inFlight.payload
        },
        (res) => {
          visit.isFlushing = false;
          if (res && res.success) {
            // Acknowledged: increment seq, advance counters, clear inFlight
            visit.totalEventsTransmitted += inFlight.eventCount;
            visit.transmissionSeq++;
            visit.inFlight = null;

            if (res.verdict) {
              latestVerdict = res.verdict;
            }
          } else if (res && res.status >= 400 && res.status < 500 && res.status !== 429) {
            // Permanent 4xx client rejection: drop chunk and advance
            console.warn('[WebSense Extension] Chunk seq ' + inFlight.seq + ' rejected (' + res.status + '); dropping.');
            visit.transmissionSeq++;
            visit.inFlight = null;
          } else {
            // Transient failure / offline: keep inFlight intact for retry
            console.warn('[WebSense Extension] Telemetry send failed; will retry chunk seq ' + inFlight.seq);
          }
        }
      );
    } catch (_) {
      visit.isFlushing = false;
    }
  }

  // --- SPA Navigation & Route Changes (P5 Fix) ---
  function handlePageVisitTransition() {
    const oldVisit = currentVisit;
    if (oldVisit) {
      oldVisit.isFinalized = true;
      flushTelemetry(oldVisit, true);
    }

    const prevId = oldVisit ? oldVisit.sessionId : null;
    currentVisit = createExtensionVisit(prevId);
  }

  let lastPathname = location.pathname;
  function checkPathChange() {
    if (location.pathname !== lastPathname) {
      lastPathname = location.pathname;
      handlePageVisitTransition();
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
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) {
      handlePageVisitTransition();
    }
  });

  // Periodic flush every 5s while active
  setInterval(() => {
    if (currentVisit && isCollecting) {
      flushTelemetry(currentVisit, false);
    }
  }, 5000);

  // Unload flush with final=true
  window.addEventListener('pagehide', () => {
    if (currentVisit && !currentVisit.isFinalized) {
      flushTelemetry(currentVisit, true);
    }
  });

  setupMessageResponder();

  // --- Message Responder for Extension Popup ---
  function setupMessageResponder() {
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === 'GET_PAGE_STATUS') {
        const visit = currentVisit;
        sendResponse({
          url: (location.origin + location.pathname).slice(0, 512),
          hostname: window.location.hostname,
          sessionId: isYieldingToSdk ? sdkSessionId : (visit ? visit.sessionId : null),
          siteId: isYieldingToSdk ? 'site_meridian_prod' : EXTENSION_SITE_ID,
          source: isYieldingToSdk ? 'sdk_passthrough' : 'chrome_extension',
          events: {
            mouse: visit ? visit.mouseEvents.length : 0,
            keys: visit ? visit.keyboardEvents.length : 0,
            scroll: visit ? visit.scrollEvents.length : 0,
            clicks: visit ? visit.clickEvents.length : 0,
            totalTransmitted: visit ? visit.totalEventsTransmitted : 0
          },
          activeDurationMs: visit ? getActiveDurationMs(visit) : 0,
          isCollecting: isCollecting && !isYieldingToSdk,
          verdict: latestVerdict
        });
      }
    });
  }

})();