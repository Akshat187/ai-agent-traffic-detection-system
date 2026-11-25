# SentinelTrace REST API Reference

The SentinelTrace backend exposes clean, OpenAPI-compliant REST endpoints for multi-site registration, session telemetry ingestion, classification, statistics, and experiments.

Interactive Swagger documentation is available at:
`http://localhost:8000/docs`

---

## 1. Sessions API

### Ingest Session Telemetry
`POST /api/v1/sessions`

**Request Body:**
```json
{
  "session_id": "st_session_12345",
  "visitor_id": "vis_98765",
  "task": "shopping",
  "start_time": 1724900000000,
  "end_time": 1724900006200,
  "duration_ms": 6200,
  "browser_signals": {
    "webdriver": false,
    "screen_width": 1920,
    "screen_height": 1080,
    "hardware_concurrency": 8
  },
  "mouse_events": [
    { "x": 120, "y": 240, "t": 40, "type": "move" },
    { "x": 280, "y": 380, "t": 120, "type": "move" }
  ],
  "keyboard_events": [
    { "t": 450, "interval": 140, "hold": 65, "is_paste": false }
  ],
  "click_events": [
    { "x": 280, "y": 380, "t": 125, "target_category": "button" }
  ],
  "task_actions": [
    { "action": "add_to_cart", "t": 125, "details": { "product_id": "prod_1" } }
  ]
}
```

**Response (200 OK):**
```json
{
  "session_id": "st_session_12345",
  "predicted_label": "HUMAN",
  "confidence": 94.2,
  "risk_score": 12.0,
  "l1_rule_score": 0.0,
  "l2_ml_pred": "HUMAN",
  "l3_is_anomaly": false,
  "l4_is_replay": false,
  "l5_context_valid": true,
  "contributing_signals": [],
  "counter_signals": [
    "Natural human trajectory curvature with 4 micro-corrections",
    "Organic typing rhythm variation (CV: 0.32)"
  ],
  "human_explanation": "Classified as Human (94% confidence) with low risk (12/100). Demonstrated organic motor variability...",
  "model_version": "v1.2.1-actor-inference"
}
```

---

### List Recent Sessions
`GET /api/v1/sessions?limit=50&offset=0&label=ALL`

**Query Parameters:**
- `limit` (int, default=50)
- `offset` (int, default=0)
- `label` (string, optional: `HUMAN`, `TRADITIONAL_AUTOMATION`, `AGENTIC_AI`, `UNCERTAIN`)

---

### Get Session Detail & Trajectories
`GET /api/v1/sessions/{session_id}`

Returns complete session summary, full extracted feature vector, 5-layer verdict breakdown, and raw coordinate telemetry for 2D visualizer playback.

---

## 2. Multi-Site Registration API

### Register a Site
`POST /api/v1/sites`

Registers a new site for the SentinelTrace embeddable SDK (`sentinel.js`), returning a `site_id` and `api_key` (`ws_live_...`).

**Request Body:**
```json
{
  "name": "Acme Global Store",
  "allowed_origins": "https://acmestore.com,https://staging.acmestore.com"
}
```

### List Registered Sites
`GET /api/v1/sites`

Returns all registered sites and their session counts.

### Get Site Details
`GET /api/v1/sites/{site_id}`

Returns metadata and configuration for a specific registered site.

---

## 3. Statistics API

### Get Platform Overview Metrics
`GET /api/v1/stats/overview`

Returns aggregated counts, class percentages, average confidence, average risk score, and recent activity log.

---

## 4. Experiments & Adversarial API

### Run 6-Experiment Ablation Suite
`POST /api/v1/experiments/run`

Runs the 6-experiment comparative evaluation and ablation suite (Browser Only vs Behavioral Only vs Full 5-Layer Defense-in-Depth, Feature Importance, Calibration, and Evasive Resistance) and returns Confusion Matrix and Feature Importance rankings.

### Simulate Adversarial Attack
`POST /api/v1/adversarial/simulate`

**Request Body:**
```json
{
  "attack_type": "synthetic_jitter"
}
```
*Supported `attack_type` values: `simple_bot`, `synthetic_jitter`, `trajectory_replay`, `cross_context`.*

---

## 4. Health Endpoints

- `GET /healthz` - Liveness status check
- `GET /readyz` - Database readiness probe

