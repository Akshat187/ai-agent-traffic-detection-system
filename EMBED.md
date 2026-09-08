# WebSense Sentinel SDK — Embed & Integration Guide

`sentinel.js` is a lightweight, zero-dependency, privacy-first behavioral telemetry script. It enables any external web application to stream anonymized interaction timing and kinematic dynamics to the WebSense AI detection engine to detect bots and autonomous AI agents in real time.

---

## 1. Quick Start

### Step 1: Register Your Site
Register your website domain to generate a unique `site_id` and API key. You can do this via the WebSense REST API or the dashboard:

```bash
curl -X POST https://your-websense-domain.com/api/v1/sites \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Global Store",
    "allowed_origins": "https://acmestore.com,https://staging.acmestore.com"
  }'
```

**Response:**
```json
{
  "site_id": "site_39a48d8b2e1f",
  "name": "Acme Global Store",
  "allowed_origins": "https://acmestore.com,https://staging.acmestore.com",
  "api_key": "ws_live_k9d8...7x2",
  "is_active": true,
  "created_at": "2026-09-02T06:00:00Z",
  "total_sessions": 0
}
```

---

### Step 2: Add the Script Tag to Your Website

Add the following `<script>` tag inside your HTML `<head>` or before the closing `</body>` tag on all pages you want to monitor:

```html
<script 
  src="https://your-websense-domain.com/sentinel.js" 
  data-site-id="site_39a48d8b2e1f" 
  data-task="shopping" 
  async>
</script>
```

#### Script Tag Configuration Attributes

| Attribute | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `src` | **Yes** | — | URL to `sentinel.js` or `/static/sentinel.js` |
| `data-site-id` | **Yes** | `site_meridian_prod` | Your registered Site ID. |
| `data-endpoint` | No | Current Host `/api/v1/sessions` | Custom API ingestion URL if hosting backend on another domain. |
| `data-task` | No | `general` | Context domain: `shopping`, `travel`, `community`, `lead_form`, etc. |
| `data-require-consent` | No | `false` | If `true`, pauses collection until `Sentinel.grantConsent()` is invoked. |

---

## 2. JavaScript SDK API (`window.Sentinel`)

`sentinel.js` automatically exports a global `Sentinel` object on `window`.

### Log Custom Actions & Funnel Milestones
Log high-level domain actions to feed the Layer 5 Contextual Rule Validator:

```javascript
// Example: User added an item to cart
window.Sentinel.logAction('add_to_cart', {
  product_id: 'prod_99182',
  price: 68.00,
  qty: 1
});

// Example: User initiated checkout
window.Sentinel.logAction('checkout_initiated', {
  total: 136.00,
  item_count: 2
});
```

### Manual Telemetry Flush
By default, `sentinel.js` flushes telemetry automatically on page unload or visibility change. You can trigger an explicit flush on completion of a key action:

```javascript
// Submit telemetry and retrieve classification verdict
window.Sentinel.flush('shopping').then(verdict => {
  if (verdict) {
    console.log('Actor Classification:', verdict.predicted_label); // HUMAN | TRADITIONAL_AUTOMATION | AGENTIC_AI | UNCERTAIN
    console.log('Risk Score:', verdict.risk_score); // 0 - 100
  }
});
```

### Privacy & Consent Handling
If `data-require-consent="true"` is configured:

```javascript
// When user accepts cookie/telemetry banner:
window.Sentinel.grantConsent();

// When user declines:
window.Sentinel.declineConsent();
```

---

## 3. Privacy Guarantees

Sentinel is strictly engineered for privacy and security compliance (GDPR / CCPA):
1. **Zero Text Capture**: Keystroke character content, letters, digits, and form inputs are **never** captured.
2. **Timing Only**: Only inter-key latency intervals and key-hold durations are measured.
3. **Password Protection**: Input fields with `type="password"` or `data-private="true"` are completely excluded from all instrumentation.

---

## 4. Multi-Site Analytics on Dashboard

1. Open the Analyst Dashboard at `/dashboard`.
2. Use the **Site Selector** in the top navigation bar to filter overview statistics, live session stream, and experiment metrics specifically for your registered site ID.
