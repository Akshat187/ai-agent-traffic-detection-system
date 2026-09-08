# WebSense — AI-Agent Traffic Detection & Behavioral Security Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.124%2B-emerald.svg)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red.svg)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

**WebSense** is an end-to-end cybersecurity intelligence platform designed to classify modern web traffic into **Human**, **Traditional Automation**, and **Agentic AI** (plus an internal **Uncertain** state) using high-resolution browser and behavioral fingerprinting.

Inspired by contemporary research (*FP-Agent: Fingerprinting AI Browsing Agents, 2026*) and modern mouse dynamics threat modeling, WebSense implements a **5-Layer Defense-in-Depth Engine** that proves **behavioral dynamics (mouse kinematics, typing jitter, pause cadence) consistently outperform static browser fingerprints alone.**

---

## ðŸŒŸ Key Capabilities

1. **5-Layer Multi-Defense Engine**:
   - **Layer 1: Rule-Based Heuristics** — Rapid detection of `navigator.webdriver`, zero-movement click events, and impossible sub-second form completion.
   - **Layer 2: Supervised Behavioral ML** — Random Forest and Decision Tree classifiers operating over 15 physical kinematic features (acceleration, jerk, straightness ratio, micro-corrections, typing coefficient of variation).
   - **Layer 3: Behavioral Anomaly Detection** — Isolation Forest & Mahalanobis baseline distance measuring out-of-distribution deviation from organic human interaction.
   - **Layer 4: Historical Replay Defense** — Trajectory bounding-box normalization, equidistant arc-length resampling, and Dynamic Time Warping (DTW) similarity matching to detect synthetic replay attacks (>94% match).
   - **Layer 5: Contextual Task Validation** — Finite-state workflow validation catching out-of-order interactions and clicks landing on non-interactive regions.

2. **Dual Integrated Experiences**:
   - **Instrumented Honey Website** (`/visitor/shop`, `/visitor/travel`, `/visitor/forum`) — Realistic E-commerce, Flight Booking, and Community Forum tasks with privacy-preserving telemetry (`collector.js`).
   - **Enterprise Security Intelligence Dashboard** (`/dashboard`) — Real-time telemetry log, 2D Canvas mouse trajectory replay with velocity color-mapping, FP-Agent comparative benchmark lab, and interactive adversarial simulator.

3. **Privacy-Preserving Telemetry**:
   - Zero keylogging. WebSense captures keystroke *intervals and hold timing* without recording raw text, password characters, or personal information.

---

## ðŸ“ Architecture Overview

```
Visitor Interactions (Shop / Travel / Forum)
                    â”‚
       [collector.js Telemetry Engine]
                    â”‚
            POST /api/v1/sessions
                    â–¼
          [FastAPI Gateway & DB]
                    â”‚
         [Feature Extraction Engine]
  (Velocity, Jerk, Straightness, Keystroke CV)
                    â”‚
     â”Œ──────────────â”´──────────────â”
     â–¼                             â–¼
 [Layer 1: Rules]          [Layer 2: Behavioral ML]
 [Layer 3: Anomaly]        [Layer 4: DTW Replay]
 [Layer 5: Context]        [Unified Decision Engine]
                    â”‚
                    â–¼
       [Classification Output]
 (HUMAN | BOT | AI_AGENT | UNCERTAIN)
 (Confidence % | Risk Score | Explainability)
                    â”‚
                    â–¼
     [Security Dashboard (/dashboard)]
 (Live Feed | 2D Visualizer | Benchmark Lab)
```

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.8+
- Node.js (optional, for browser automation)

### 2. Installation
```bash
# Clone repository
git clone https://github.com/your-org/WebSense.git
cd WebSense

# Create & activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Seed Demo Dataset
Populates the database with 36 reproducible, ground-truth-labeled sessions across Human, Bot, and AI Agent categories:
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

## ðŸ§ª Testing & Verification

Run the comprehensive unit and integration test suite:
```bash
python -m pytest tests/ -v
```

All 15 test suites validate:
- Kinematics & mathematical feature extraction
- Rule engine penalties & bonuses
- Multi-layer decision engine synthesis
- Trajectory Dynamic Time Warping (DTW) similarity
- REST API endpoints and web template rendering

---

## ðŸ”¬ Research Grounding & Honest Framing

> [!NOTE]
> WebSense is a student-scale, open-source engineering implementation and extension of concepts established in recent cybersecurity research:
> - **FP-Agent: Fingerprinting AI Browsing Agents (2026)**
> - **Research on Mouse Dynamics against Sophisticated Web Automation**
> 
> WebSense does not claim to invent AI-agent detection. Its core contribution is an **integrated, explainable 5-layer defense architecture, a reproducible empirical benchmark lab, and real-time 2D trajectory visualization.**

---

## ðŸ“‚ Repository Structure

```
WebSense/
â”œ── apps/
â”‚   â”œ── api/                  # FastAPI Application & REST Routers
â”‚   â”‚   â”œ── main.py           # App lifecycle, routing, static mounting
â”‚   â”‚   â”œ── config.py         # Centralized configuration & thresholds
â”‚   â”‚   â”œ── dependencies.py   # DB & Engine singletons
â”‚   â”‚   â””── routes/           # Session, stats, experiment, adversarial APIs
â”‚   â””── web/                  # Web Experiences
â”‚       â”œ── public/           # Assets, collector.js, dashboard.js, dashboard.css
â”‚       â””── templates/        # dashboard.html, visitor_shop.html, etc.
â”œ── packages/
â”‚   â”œ── core/                 # Kinematics, feature extraction, DTW algorithms
â”‚   â”œ── database/             # SQLAlchemy models, SQLite/Postgres connection, Pydantic schemas
â”‚   â”œ── detection/            # 5-Layer Defense-in-Depth Engine & Decision Module
â”‚   â””── generators/           # Synthetic dataset generator, Bot runner, AI Agent adapter
â”œ── docker/                   # Dockerfile & docker-compose.yml
â”œ── tests/                    # Pytest test suite (15 tests)
â”œ── .github/workflows/        # GitHub Actions CI pipeline
â”œ── Makefile                  # Simple make commands
â”œ── requirements.txt          # Python dependencies
â”œ── ARCHITECTURE.md           # Deep architecture & threat model notes
â””── API.md                    # REST API documentation
```

---

## 🛡️ï¸ License
Released under the [MIT License](LICENSE).

