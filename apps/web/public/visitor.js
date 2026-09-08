/**
 * Meridian Visitor — consent notice manager.
 * Handles the consent notice UI shared across all three Meridian pages.
 * The actual telemetry collection lives entirely in collector.js.
 */

document.addEventListener('DOMContentLoaded', function () {
  'use strict';

  // ─── Consent Notice ─────────────────────────────────────────────────────
  const CONSENT_KEY = 'meridian_telemetry_consent';

  function getConsent() {
    try { return localStorage.getItem(CONSENT_KEY); } catch (_) { return null; }
  }

  const acceptBtn  = document.getElementById('consent-accept');
  const declineBtn = document.getElementById('consent-decline');
  const notice     = document.getElementById('consent-notice');

  if (notice) {
    const existing = getConsent();
    if (!existing) {
      // Show notice after a brief pause (let page settle)
      setTimeout(() => notice.classList.add('visible'), 1800);
    }

    if (acceptBtn) {
      acceptBtn.addEventListener('click', function () {
        notice.classList.remove('visible');
        if (window.WebSense) window.WebSense.grantConsent();
      });
    }

    if (declineBtn) {
      declineBtn.addEventListener('click', function () {
        notice.classList.remove('visible');
        if (window.WebSense) window.WebSense.declineConsent();
      });
    }
  }
});

