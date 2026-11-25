# SentinelTrace — AI-Agent Traffic Detection & Behavioral Security Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-emerald.svg)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red.svg)](https://www.sqlalchemy.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-67%20Passed-brightgreen.svg)](tests/)

**SentinelTrace** is an end-to-end behavioral security intelligence and active mitigation platform designed to classify modern web traffic into **Human**, **Traditional Automation**, and **Agentic AI** (plus an internal **Uncertain** state) using high-resolution browser, kinematic, and agency-cadence fingerprinting.

Inspired by contemporary research (*FP-Agent: Fingerprinting AI Browsing Agents, 2026*) and modern mouse dynamics threat modeling, SentinelTrace implements a **5-Layer Defense-in-Depth Engine** with sub-10ms mean inference latency, real-time WebSocket threat streaming, and active policy enforcement (`ALLOW | CHALLENGE | BLOCK`).

---

## ✨ Key Capabilities

1. **5-Layer Multi-Defense Engine (`v1.2.1-actor-inference`)**:
   - **Layer 1: Rule-Based Heuristics** — Detects `navigator.webdriver`, linear trajectories, synthetic typing cadence, and impossible sub-second completions, with built-in **Mobile/Touch & Accessibility (a11y)** exemptions so touchscreen and keyboard-only users are never penalized.
   - **Layer 2: Temperature-Calibrated Behavioral ML** — Random Forest / Native Ensemble over **26 kinematic, agency, and environmental features** (Fitts's law target deceleration, jerk-to-velocity ratio, LLM inference pause burstiness, cursor teleportation, keystroke CV), persisted via `make train` (`models/behavioral_v1.2.joblib`).
   - **Layer 3: Behavioral Anomaly Detection** — Multi-variate Mahalanobis baseline distance and kinematic outlier scoring.
   - **Layer 4: Fast Historical Replay Defense** — Bounding-box aspect-ratio & length pre-filtering with windowed Dynamic Time Warping (DTW) similarity matching.
   - **Layer 5: Contextual Task Validation** — Finite-state workflow validation catching out-of-order interactions.

2. **Real-Time Threat Stream & Active Mitigation**:
   - **WebSocket Live Feed (`WS /ws/sessions`)** — Streams incoming session verdicts instantaneously to `/dashboard` without full-page refreshes.
   - **Policy Engine & Signed Webhooks** — Per-site `risk_threshold` and `enforcement_mode` (`monitor | challenge | block`) returning `ALLOW | CHALLENGE | BLOCK` in `POST /api/v1/sessions` and dispatching **HMAC-SHA256** signed webhook alerts via `BackgroundTasks`.
   - **Multi-Site Auth & Tenant-Isolated Rate Limiting** — Enforces `site_id` + `Origin` (browser SDK) or `Authorization: Bearer ws_live_...` (server-to-server) with per-`(site_id, client_ip)` sliding-window rate limits.

3. **Hardened SDK, Honey Sites & Air-Gapped Dashboard**:
   - **`sentinel.js` SDK** — Tracks `pointerType` (`mouse | touch | pen`), caps buffered mouse deltas at 500 points per flush, and uses `navigator.sendBeacon()` (with `fetch(..., { keepalive: true })` fallback) for reliable unload delivery.
   - **Instrumented Honey Websites** (`/visitor/shop`, `/visitor/travel`, `/visitor/forum`) + **Chrome Extension (Manifest V3)**.
   - **Offline-Ready Dashboard (`/dashboard`)** — Static CSS design system (zero Tailwind CDN dependency), 2D Canvas mouse trajectory replay, 6-experiment ablation lab, and interactive adversarial simulator.

4. **Continuous ML & Production Operations**:
   - **Active Learning Loop** — Analyst label overrides via `POST /api/v1/sessions/{session_id}/feedback` (`session_feedback` table) and regression-gated retraining via `make retrain` (`scripts/retrain_model.py`).
   - **Alembic Migrations** — Schema management via `alembic upgrade head` (`make migrate`).
   - **GDPR/CCPA Telemetry Pruning** — `scripts/prune_telemetry.py` (`make prune`) strips raw `mouse_events`, `click_events`, `keyboard_events`, and `scroll_events` past a configurable TTL (default 14 days) while preserving anonymized verdicts and metrics.
   - **Observability** — Structured JSON logging with `session_id` and `site_id` correlation IDs and Prometheus metrics at `GET /metrics` (HTTP requests/errors, verdict counts, and L1–L5 layer latencies).

---

## 📊 Empirical Benchmark (600 Traces)

Evaluated across **600 persistent holdout traces** (200 per class, including hard-negative human subtypes: `fast_power_user`, `mobile_touch`, `copy_paste_filler`, `slow_network_lag`) — see [BENCHMARK.md](BENCHMARK.md):

| Metric | Measured | Target |
| :--- | :---: | :---: |
| **Overall Accuracy** | **95.00%** (570/600) | $\ge 95.0\%$ |
| **Macro-Averaged F1** | **0.9499** | $\ge 0.9500$ |
| **Expected Calibration Error (ECE)** | **0.0002** | $\le 0.1000$ |
| **Mean Inference Latency** | **8.52 ms** | $\le 50.0\text{ ms}$ |
| **P95 Inference Latency** | **25.97 ms** | $\le 100.0\text{ ms}$ |

---

## 🚀 Quickstart & Setup

### 1. Installation
```bash
git clone https://github.com/Akshat187/ai-agent-traffic-detection-system.git
cd ai-agent-traffic-detection-system

python -m venv .venv
# Windows (PowerShell): .\.venv\Scripts\activate
# Linux/macOS:         source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Database Migrations, Model Training & Demo Seed
```bash
make migrate   # Runs alembic upgrade head
make train     # Trains & saves models/behavioral_v1.2.joblib
make seed      # Populates demo sessions across HUMAN, TRADITIONAL_AUTOMATION, AGENTIC_AI
```

### 3. Start the Application
```bash
make dev       # Starts FastAPI on http://localhost:8000
```

Open in your browser:
- **Security Dashboard**: [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
- **Honey Sites**: `/visitor/shop`, `/visitor/travel`, `/visitor/forum`
- **OpenAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Prometheus Metrics**: [http://localhost:8000/metrics](http://localhost:8000/metrics)

---

## 🧪 Testing, Benchmarking & Maintenance

```bash
make test          # Run full pytest suite (67 tests)
make evaluate      # Run detection unit tests
make retrain       # Merge analyst feedback & promote model if Macro-F1 & ECE improve
make prune         # Strip raw coordinate/keystroke telemetry older than 14 days
make lint          # Strict flake8 syntax/undefined-name check
make format-check  # Verify Black formatting
```

---

## 📁 Repository Structure

```text
ai-agent-traffic-detection-system/
├── alembic/                  # Alembic database migrations
├── apps/
│   ├── api/                  # FastAPI application, observability, and REST/WS routers
│   │   ├── main.py           # App lifecycle, structured JSON logging, /metrics
│   │   ├── observability.py  # Correlation IDs & Prometheus MetricsRegistry
│   │   ├── config.py         # Centralized configuration & thresholds
│   │   └── routes/           # sessions, sites, ws, stats, experiments, adversarial, seed
│   └── web/                  # Static CSS/JS (sentinel.js, dashboard.js) & HTML templates
├── packages/
│   ├── core/                 # Kinematics, 26-feature extraction, fast 2D DTW
│   ├── database/             # SQLAlchemy models, Alembic-ready DB setup, Pydantic schemas
│   ├── detection/            # 5-Layer Defense-in-Depth Engine & BehavioralClassifier
│   └── generators/           # Synthetic session generator & agent adapters
├── scripts/
│   ├── generate_benchmarks.py # 600-trace benchmark generator (with hard negatives)
│   ├── benchmark_evaluation.py# Empirical evaluation & BENCHMARK.md generator
│   ├── train_model.py        # Visitor-grouped training & joblib serialization
│   ├── retrain_model.py      # Active-learning retrain with regression gate
│   └── prune_telemetry.py    # GDPR/CCPA TTL raw telemetry pruning job
├── models/                   # Persisted Layer-2 model artifacts (behavioral_v1.2.joblib)
├── extension/                # Chrome Extension (Manifest V3)
├── tests/                    # Pytest suite (67 tests)
├── API.md                    # REST API reference (v1.2.1)
├── ARCHITECTURE.md           # Architecture & threat model documentation
├── BENCHMARK.md              # 600-trace benchmark report
└── EMBED.md                  # sentinel.js embed & multi-site integration guide
```

---

## 🛡️ License

Released under the [MIT License](LICENSE).
