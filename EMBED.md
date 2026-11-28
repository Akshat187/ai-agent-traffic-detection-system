# SentinelTrace SDK — Embed & Integration Guide

`sentinel.js` is a lightweight, zero-dependency, privacy-first behavioral telemetry script hosted directly by your deployed SentinelTrace server. It enables any external web application to stream anonymized interaction timing and kinematic dynamics to the SentinelTrace engine to detect bots and autonomous AI agents in real time.

> **How deployment works (Customers vs. Analysts):**
> - **Customer websites (production):** Site owners **never** install a Chrome extension and **never** copy or vendor `sentinel.js` source code. You register your site once, receive a copy-paste `<script>` tag pointing at your deployed SentinelTrace origin (`https://<your-sentineltrace-origin>/sentinel.js`), and paste it into your HTML like an analytics snippet. End visitors install nothing.
> - **Chrome extension (`extension/`):** Analyst and demo tool **only**—used by security teams or researchers to observe third-party sites where they cannot edit HTML.

---

## 1. Quick Start

### Step 1: Register Your Site
Register your website domain to generate a unique `site_id`, copy-paste `embed_snippet`, and server-side API key. You can do this via the **Sites & Embed** tab on `/dashboard` or the SentinelTrace REST API:

```bash
# Replace <your-sentineltrace-origin> with your deployed server (e.g. https://detect.example.com, or http://localhost:8000 locally)
curl -X POST https://<your-sentineltrace-origin>/api/v1/sites \
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
  "webhook_url": null,
  "risk_threshold": 80,
  "enforcement_mode": "monitor",
  "is_active": true,
  "created_at": "2026-09-02T06:00:00Z",
  "total_sessions": 0,
  "embed_snippet": "<script src=\"https://<your-sentineltrace-origin>/sentinel.js\" data-site-id=\"site_39a48d8b2e1f\" data-task=\"general\" async></script>"
}
```

> **Security note:** Keep `api_key` strictly on your backend (for server-to-server calls using `Authorization: Bearer <api_key>`). Browser pages authenticate using `data-site-id` + `Origin` (`allowed_origins`)—never embed `api_key` in HTML.

---

### Step 2: Paste the Hosted Script Tag on Your Website

Paste the returned `<script>` tag inside your HTML `<head>` or before the closing `</body>` tag on all pages you want to monitor:

```html
<script
  src="https://<your-sentineltrace-origin>/sentinel.js"
  data-site-id="site_39a48d8b2e1f"
  data-task="shopping"
  async>
</script>
```

`sentinel.js` automatically infers the ingestion endpoint (`<origin>/api/v1/sessions`) from its own `src` URL and is served with cross-origin headers (`Access-Control-Allow-Origin: *`, `Cross-Origin-Resource-Policy: cross-origin`) and public cache revalidation (`Cache-Control: public, max-age=3600, stale-while-revalidate=86400`). Optionally set `PUBLIC_BASE_URL` on the server so generated snippets always advertise your canonical public origin behind reverse proxies.

#### Script Tag Configuration Attributes

| Attribute | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `src` | **Yes** | — | Hosted URL on your deployed SentinelTrace origin (`https://<your-sentineltrace-origin>/sentinel.js`) |
| `data-site-id` | **Yes** | `site_meridian_prod` | Your registered Site ID. |
| `data-endpoint` | No | Inferred from `src` origin (`/api/v1/sessions`) | Override API ingestion URL only if self-hosting `sentinel.js` on a separate domain. |
| `data-task` | No | `general` | Context domain: `general`, `shopping`, `travel`, `forum`, `custom`. |
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
