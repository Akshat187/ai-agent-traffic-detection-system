# WebSense — Architecture & Threat Model Documentation

WebSense is a multi-layered security intelligence and traffic classification platform built to distinguish between **Human Users**, **Traditional Automation**, and **Agentic AI** using browser and behavioral fingerprinting.

---

## 1. System Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                            INSTRUMENTED VISITOR LAYER                             |
|  - E-Commerce Shopping Store (/visitor/shop)                                      |
|  - Flight & Travel Reservation (/visitor/travel)                                  |
|  - CyberSec Community Forum (/visitor/forum)                                      |
|                                                                                   |
|  [collector.js Telemetry Engine]                                                  |
|   -> Mouse Coordinates (x, y, t) throttled to 25ms                               |
|   -> Keystroke Timing (Inter-key Latency, Hold Time - NO Characters Stored)      |
|   -> Scroll Velocity & Jump Ratios                                                |
|   -> Browser Environment Signals (navigator.webdriver, Hardware Concurrency)     |
+------------------------------------------+----------------------------------------+
                                           |
                                 HTTP POST /api/v1/sessions
                                           v
+-----------------------------------------------------------------------------------+
|                             FASTAPI INGESTION SERVICE                             |
|  - Input Validation & Schema Enforcement (Pydantic v2)                            |
|  - Feature Extraction Engine (Kinematics, Jerk, Straightness, CV)                 |
|  - Database Persistence (SQLAlchemy ORM -> SQLite / PostgreSQL)                   |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                        5-LAYER DEFENSE-IN-DEPTH ENGINE                            |
|                                                                                   |
|  [Layer 1: Rule-Based Scoring Engine]                                             |
|   - navigator.webdriver inspection (+50 penalty)                                  |
|   - Zero mouse with clicks (+40 penalty)                                          |
|   - Straightness ratio > 0.96 (+30 penalty)                                       |
|   - Uniform keystroke CV < 0.05 (+35 penalty)                                     |
|                                                                                   |
|  [Layer 2: Behavioral Machine Learning]                                           |
|   - Supervised Random Forest / Logistic Regression                                |
|   - 15 kinematic and timing feature vectors                                       |
|   - Calibrated class probabilities & feature importance                           |
|                                                                                   |
|  [Layer 3: Behavioral Anomaly Detection]                                          |
|   - Isolation Forest & Mahalanobis baseline distance                              |
|   - Detects out-of-distribution deviations from normal human interactions          |
|                                                                                   |
|  [Layer 4: Historical Replay Defense]                                             |
|   - Bounding-box trajectory normalization + equidistant arc-length resampling     |
|   - Windowed Dynamic Time Warping (DTW) similarity matching                       |
|   - Detects pre-recorded human mouse replay attacks (>94% match)                  |
|                                                                                   |
|  [Layer 5: Contextual & Workflow Integrity]                                       |
|   - State-machine validation for task workflows                                   |
|   - DOM coordinate validity & honeypot target traps                               |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                             UNIFIED DECISION ENGINE                               |
|  - Synthesizes verdicts across Layers 1-5                                         |
|  - Assigns: HUMAN | BOT | AI_AGENT | UNCERTAIN                                    |
|  - Computes Calibrated Confidence % (0-100) and Risk Score (0-100)                |
|  - Generates Plain-English Explainability & Contributing/Counter Signal Lists     |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                    SECURITY INTELLIGENCE DASHBOARD (/dashboard)                   |
|  - Real-Time Traffic Distribution & Trend Timeline                                |
|  - Live Sessions Table with Search & Class Filters                                |
|  - 2D Canvas Mouse Trajectory Replay & Kinematics Color-Map                       |
|  - FP-Agent Comparative Benchmark Lab (Browser vs Behavioral vs 5-Layer)          |
|  - Adversarial Attack & Evasion Simulator                                         |
+-----------------------------------------------------------------------------------+
```

---

## 2. Mathematical Kinematics & Feature Formulas

### 2.1 Mouse Path Straightness Ratio ($S$)
Given total path length $D_{path} = \sum_{i=1}^n \sqrt{(x_i - x_{i-1})^2 + (y_i - y_{i-1})^2}$ and direct Euclidean distance $D_{direct} = \sqrt{(x_n - x_0)^2 + (y_n - y_0)^2}$:
$$S = \frac{D_{direct}}{D_{path}}$$
- **Robotic Automation**: $S \approx 1.00$ (linear movements with zero lateral variance)
- **Natural Human Movement**: $S \in [0.45, 0.82]$ (natural physiological curvature)

### 2.2 Keystroke Timing Coefficient of Variation ($CV$)
Given inter-key intervals $\{ \Delta t_1, \Delta t_2, \dots, \Delta t_k \}$:
$$CV = \frac{\sigma_{\Delta t}}{\mu_{\Delta t}}$$
- **Automated Scripts**: $CV < 0.04$ (constant delay intervals)
- **Organic Human Typing**: $CV > 0.25$ (natural cognitive pauses between syllables)

### 2.3 Trajectory Dynamic Time Warping Similarity ($Sim_{DTW}$)
Given normalized resampled trajectories $Q$ and $C$:
$$Sim_{DTW} = \exp\left( -6.0 \cdot \frac{DTW(Q, C)}{|Q| + |C|} \right)$$
- **Replay Attack**: $Sim_{DTW} \ge 0.94$ (verbatim trajectory clone)

---

## 3. Threat Model & Mitigations

| Threat Scenario | Attacker Capability | Detection Mechanism |
| :--- | :--- | :--- |
| **Simple Scripted Bot** | Headless Chrome/Selenium executing rigid form fills | **Layer 1 & 2**: `navigator.webdriver=true`, zero mouse jitter, instantaneous submits. |
| **Synthetic Jitter Bot** | Mathematical Bézier curves with Gaussian noise | **Layer 3 & 2**: Outlier in acceleration/jerk distribution and micro-correction spectrum. |
| **Trajectory Replay** | Replays recorded human mouse movements | **Layer 4**: DTW trajectory matching against sliding historical cache. |
| **Cross-Context Desync** | Replays valid movements on a different page workflow | **Layer 5**: State machine rejects out-of-order actions or clicks on dead DOM targets. |
| **Autonomous AI Agent** | LLM-driven browser automation with planning pauses | **Layer 2 & Unified Engine**: Distinct plan-pause cadence, segmented vectors, and agentic task intervals. |

