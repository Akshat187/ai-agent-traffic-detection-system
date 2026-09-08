# WebSense — AI-Agent Traffic Detection & Behavioral Security Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.124%2B-emerald.svg)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red.svg)](https://www.sqlalchemy.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-28%20Passed-brightgreen.svg)](tests/)

**WebSense** is an end-to-end cybersecurity intelligence platform designed to classify modern web traffic into **Human**, **Traditional Automation**, and **Agentic AI** (plus an internal **Uncertain** state) using high-resolution browser and behavioral fingerprinting.

Inspired by contemporary research (*FP-Agent: Fingerprinting AI Browsing Agents, 2026*) and modern mouse dynamics threat modeling, WebSense implements a **5-Layer Defense-in-Depth Engine** demonstrating that **behavioral dynamics (mouse kinematics, typing jitter, pause cadence) consistently outperform static browser fingerprints alone.**

---

## ✨ Key Capabilities

1. **5-Layer Multi-Defense Engine**:
   - **Layer 1: Rule-Based Heuristics** — Rapid detection of `navigator.webdriver`, zero-movement click events, and impossible sub-second form completion.
   - **Layer 2: Supervised Behavioral ML** — Random Forest and Decision Tree classifiers operating over 15 physical kinematic features (acceleration, jerk, straightness ratio, micro-corrections, typing coefficient of variation).
   - **Layer 3: Behavioral Anomaly Detection** — Isolation Forest & Mahalanobis baseline distance measuring out-of-distribution deviation from organic human interaction.
   - **Layer 4: Historical Replay Defense** — Trajectory bounding-box normalization, equidistant arc-length resampling, and Dynamic Time Warping (DTW) similarity matching to detect synthetic replay attacks (>94% match).
   - **Layer 5: Contextual Task Validation** — Finite-state workflow validation catching out-of-order interactions and clicks landing on non-interactive regions.

2. **Dual Integrated Experiences**:
   - **Instrumented Honey Websites** (`/visitor/shop`, `/visitor/travel`, `/visitor/forum`) — Realistic E-commerce, Flight Booking, and Community Forum tasks with privacy-preserving client telemetry (`collector.js`).
   - **Enterprise Security Intelligence Dashboard** (`/dashboard`) — Real-time telemetry log, 2D Canvas mouse trajectory replay with velocity color-mapping, FP-Agent comparative benchmark lab, and interactive adversarial simulator.
   - **Chrome Extension (Manifest V3)** — Standalone browser extension that injects background passive telemetry capture across any external site.

3. **Privacy-Preserving Telemetry**:
   - **Zero Keylogging**: WebSense captures keystroke *intervals and hold timing* without recording raw text, password characters, or personal information.
   - Input fields of type `password` are completely bypassed.

---

## 📐 Architecture Overview

```text
Visitor Interactions (Shop / Travel / Forum / External via Extension)
                                │
                  [collector.js Telemetry Engine]
                                │
                      POST /api/v1/sessions
                                ▼
                      [FastAPI Gateway & DB]
                                │
                    [Feature Extraction Engine]
             (Velocity, Jerk, Straightness, Keystroke CV)
                                │
         ┌──────────────────────┴──────────────────────┐
         ▼                                             ▼
  [Layer 1: Rules]                            [Layer 2: Behavioral ML]
  [Layer 3: Anomaly]                          [Layer 4: DTW Replay]
  [Layer 5: Context]                          [Decision Engine Synthesis]
                                │
                                ▼
                     [Classification Output]
               (HUMAN | TRADITIONAL_AUTOMATION | AGENTIC_AI | UNCERTAIN)
               (Confidence % | Risk Score | Explainability Signals)
                                │
                                ▼
                 [Security Dashboard (/dashboard)]
             (Live Feed | 2D Visualizer | Benchmark Lab)
```

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.8+
- Git

### 2. Installation
```bash
# Clone repository
git clone https://github.com/Akshat187/ai-agent-traffic-detection-system.git
cd ai-agent-traffic-detection-system

# Create & activate virtual environment
python -m venv .venv

# On Windows (PowerShell):
.\.venv\Scripts\activate

# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Seed Demo Dataset
Populates the database with reproducible, ground-truth-labeled sessions across Human, Bot, and AI Agent categories:
```bash
python demo_seed.py
```

### 4. Start the Application
```bash
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser:
- **Security Dashboard**: [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
- **E-Commerce Honey Site**: [http://localhost:8000/visitor/shop](http://localhost:8000/visitor/shop)
- **Travel Booking Honey Site**: [http://localhost:8000/visitor/travel](http://localhost:8000/visitor/travel)
- **Community Forum Honey Site**: [http://localhost:8000/visitor/forum](http://localhost:8000/visitor/forum)
- **Interactive OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🧪 Testing & Verification

Run the comprehensive unit and integration test suite:
```bash
pytest tests/ -v
```

The 28 test suites validate:
- Kinematics & mathematical feature extraction
- Rule engine penalties & bonuses
- Multi-layer decision engine synthesis
- Trajectory Dynamic Time Warping (DTW) similarity
- Privacy guarantees (zero text/password keylogging)
- REST API endpoints and web template rendering

---

## 🔬 Research Grounding & Honest Framing

> [!NOTE]
> WebSense is an open-source engineering implementation and extension of concepts established in recent cybersecurity research:
> - **FP-Agent: Fingerprinting AI Browsing Agents (2026)**
> - **Research on Mouse Dynamics against Sophisticated Web Automation**
> 
> WebSense's core contribution is an **integrated, explainable 5-layer defense architecture, a reproducible empirical benchmark lab, and real-time 2D trajectory visualization.**

---

## 📁 Repository Structure

```text
ai-agent-traffic-detection-system/
├── apps/
│   ├── api/                  # FastAPI Application & REST Routers
│   │   ├── main.py           # App lifecycle, routing, static mounting
│   │   ├── config.py         # Centralized configuration & thresholds
│   │   ├── dependencies.py   # DB & Engine singletons
│   │   └── routes/           # Session, stats, experiment, adversarial APIs
│   └── web/                  # Web Experiences
│       ├── public/           # Assets, collector.js, dashboard.js, dashboard.css
│       └── templates/        # dashboard.html, visitor_shop.html, etc.
├── packages/
│   ├── core/                 # Kinematics, feature extraction, DTW algorithms
│   ├── database/             # SQLAlchemy models, SQLite connection, Pydantic schemas
│   ├── detection/            # 5-Layer Defense-in-Depth Engine & Decision Module
│   └── generators/           # Synthetic dataset generator, Bot runner, AI Agent adapter
├── extension/                # Chrome Extension (Manifest V3) for external sites
├── docker/                   # Dockerfile & docker-compose.yml
├── tests/                    # Pytest test suite (28 test cases)
├── .github/workflows/        # GitHub Actions CI pipeline
├── Makefile                  # Helper make commands
├── requirements.txt          # Python dependencies
├── ARCHITECTURE.md           # Deep architecture & threat model notes
└── API.md                    # REST API documentation
```

---

## 🛡️ License

Released under the [MIT License](LICENSE).
