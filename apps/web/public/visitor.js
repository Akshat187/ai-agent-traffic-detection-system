/**
 * Meridian Visitor — consent notice manager.
 * Handles the consent notice UI shared across all three Meridian pages.
 * The actual telemetry collection lives entirely in sentinel.js.
 */

document.addEventListener('DOMContentLoaded', function () {
  'use strict';

  // ─── Consent Notice ─────────────────────────────────────────────────────
  const CONSENT_KEY = 'meridian_telemetry_consent';
  const LEGACY_KEY = 'meridian_consent';

  function getConsent() {
    try {
      return localStorage.getItem(CONSENT_KEY) || localStorage.getItem(LEGACY_KEY);
    } catch (_) {
      return null;
    }
  }

  const acceptBtn  = document.getElementById('consent-accept');
  const declineBtn = document.getElementById('consent-decline');
  const notice     = document.getElementById('consent-notice') || document.getElementById('consent-banner');

  if (notice) {
    const existing = getConsent();
    if (!existing) {
      // Show notice after a brief pause (let page settle)
      setTimeout(() => notice.classList.add('visible'), 1800);
    }

    if (acceptBtn) {
      acceptBtn.addEventListener('click', function () {
        notice.classList.remove('visible');
        try {
          localStorage.setItem(CONSENT_KEY, 'granted');
          localStorage.setItem(LEGACY_KEY, 'granted');
        } catch (_) {}
        if (window.Sentinel && window.Sentinel.grantConsent) window.Sentinel.grantConsent();
        else if (window.WebSense && window.WebSense.grantConsent) window.WebSense.grantConsent();
      });
    }

    if (declineBtn) {
      declineBtn.addEventListener('click', function () {
        notice.classList.remove('visible');
        try {
          localStorage.setItem(CONSENT_KEY, 'declined');
          localStorage.setItem(LEGACY_KEY, 'declined');
        } catch (_) {}
        if (window.Sentinel && window.Sentinel.declineConsent) window.Sentinel.declineConsent();
        else if (window.WebSense && window.WebSense.declineConsent) window.WebSense.declineConsent();
      });
    }
  }
});

