# SentinelTrace — Audit Report
**Date:** 2026-08-31  
**Auditor:** Antigravity  
**Scope:** Full repository — frontend, backend, database, telemetry, ML pipeline, tests, deployment, documentation

---

## Executive Summary

The project has a solid structural foundation and several genuinely good decisions (visitor-grouped train/test split, privacy-preserving keyboard events, shared action vocabulary to prevent task→class leakage). However, five categories of problems prevent it from meeting the acceptance criteria:

1. **Test failures** — 5 of 15 tests fail; two are detection-correctness failures (bot session classified as HUMAN, agent classified as TRADITIONAL_AUTOMATION).
2. **Label/terminology drift** — tests still assert legacy labels (`BOT`, `AI_AGENT`); the engine now emits `TRADITIONAL_AUTOMATION`/`AGENTIC_AI`.
3. **Agent adapter is a stub** — `agent_adapter.py` returns a fixed hardcoded action-plan list. No real `AgentProvider` hierarchy exists.
4. **Public-facing pages reveal the experiment** — no consent notice, no shared navigation, three different brand names across three visitor pages.
5. **Experiments endpoint returns 422** on empty DB — `test_experiments_benchmark_endpoint` does not seed data before calling the endpoint.

---

## 1. Correctness Problems (BLOCKING)

### 1.1 Test failures

**`test_rule_engine_triggers`** — Asserts `"AUTOMATED_BROWSER_WEBDRIVER_ACTIVE"` in flags. Engine now emits `"AUTOMATION_BROWSER_ENV_DETECTED"` + `"NOTE_ENV_SIGNAL_SUPPORTING_ONLY"`. **Stale assertion.**

**`test_decision_engine_on_bot_session`** — A BOT session generates features where agentic fields (`planning_pause_ratio`, `nav_segment_count`, `adaptation_score`) all default to 0.0. The engine's fallback branch `(risk_score ≤ 30 and ml_pred == HUMAN)` fires because the untrained ML model returns HUMAN. **Genuine classification bug.**

**`test_decision_engine_on_ai_agent_session`** — Engine outputs `"TRADITIONAL_AUTOMATION"` for an `AI_AGENT` session. `is_automation_profile` fires before `is_agentic_profile` because `rule_score ≥ 45` triggers from the linear mouse path. **Genuine classification bug.**

**`test_web_page_rendering`** — Asserts `"AeroTech" in res_shop.text`. Shop page is now "Meridian Shop" with different product names. **Stale assertion.**

**`test_experiments_benchmark_endpoint`** — Calls `POST /api/v1/experiments/run` on an empty DB → gets HTTP 422. **Test setup missing.**

### 1.2 Feature-detection gap: agentic features not extracted from task_actions

`planning_pause_ratio`, `nav_segment_count`, `adaptation_score`, and `action_interval_variance` are defined in `FEATURE_NAMES` and used in the classification logic, but `features.py` computes them primarily from mouse trajectory gaps — not from `task_actions` timestamps where the AI agent's LLM inference delays (1–5 s) appear most clearly.

### 1.3 Classification logic priority inversion

`engine.py` checks `is_automation_profile` before `is_agentic_profile`. Since `rule_score ≥ 45` is part of `is_automation_profile`, any session with a high behavioral risk score (including some agent sessions with linear segment movement) gets classified as traditional automation before the agentic profile check runs.

---

## 2. Experimental Validity Problems

### 2.1 Action vocabulary is over-abstracted

`SHARED_ACTIONS` lists identical vocabulary across all three tasks. Good intent (prevent task→class leakage), but the actions are now meaningless for debugging.  Better: keep task-specific action names in raw telemetry, but strip them before they enter the behavioral feature vector.

### 2.2 No class/task balance verification script

No script counts (class, task) pairs. Not possible to prove balance without manually querying the DB.

### 2.3 No metadata-leakage check script

No automated check that a task-metadata-only classifier scores ≤ 40% on the test set.

### 2.4 Agent adapter is a stub

`AIAgentAdapter.plan_next_action()` returns a fixed hardcoded action list. It never inspects page state, never calls a model API. There is no `LocalDemoAgent` / `LLMAgentAdapter` / `BrowserController` hierarchy.

---

## 3. Engineering Problems

### 3.1 Legacy label names in tests

`test_detection.py` asserts `verdict["final_verdict"] == "BOT"` and `in ("AI_AGENT", "BOT")`. Engine emits `TRADITIONAL_AUTOMATION` and `AGENTIC_AI`. Test terminology not updated.

### 3.2 Dashboard JS / experiments.py key mismatch

`experiments.py` runs 6 experiments with keys: `browser_only`, `mouse_only`, `keyboard_only`, `scroll_click_only`, `behavioral_all`, `combined`. `dashboard.js` searches for `"behavioral_only"` and `"defense_in_depth"` — neither exists. Charts silently show no data.

### 3.3 No consent banner on visitor pages

None of the three visitor pages have a first-visit consent notice. The spec requires one with a working Decline path that actually disables telemetry.

### 3.4 No shared navigation between visitor pages

Each visitor page is a standalone island. No consistent `Home / Shop / Travel / Community / About` nav.

### 3.5 Three different brand names

Shop = "Meridian", Travel appears to be "SkyHorizon", Forum appears to be "CyberSec Pulse". Three brands across one "website" destroys the fiction.

### 3.6 `collector.js` exposes experiment identity

Comments in `collector.js` say "WebSense Telemetry Engine" — visible in browser DevTools. For a realistic public-facing experiment, this should use neutral identifiers.

### 3.7 CORS wildcard in config

`CORS_ORIGINS: list = ["*"]` — fine for dev, not for production. Should be env-var configurable.

### 3.8 No rate limiting on telemetry endpoint

`POST /api/v1/sessions` is unprotected. A single client can flood the DB.

### 3.9 `model_version` DB default is stale

`models.py` defaults `model_version` to `"v1.1.0-defense-in-depth"`, but engine now returns `"v1.2.0-actor-inference"`. If the session insertion code does not overwrite this, stored predictions reference the wrong model version.

### 3.10 No privacy test for keyboard content

Spec requires an automated test asserting no raw keystroke characters ever reach the database. `KeyboardEventSchema` is correctly designed, but no negative test exists.

---

## 4. Design Problems

### 4.1 Tailwind CDN + custom CSS in dashboard

`dashboard.html` loads TailwindCSS from CDN AND links `dashboard.css`. Architecturally inconsistent; Tailwind CDN is a development convenience.

### 4.2 Dashboard initializes with hardcoded "92.4%" confidence stat

`id="stat-conf"` in `dashboard.html` shows a hardcoded number briefly before JS replaces it. Minor but inconsistent with the "no fabricated numbers" requirement.

---

## 5. Privacy & Security

### 5.1 No automated privacy test — MISSING

Required by spec. Need a test that POSTs session data with simulated keyboard events and asserts the DB contains no character content.

### 5.2 No secrets in source — PASS

All API keys use environment variables.

### 5.3 No raw stack traces to users — PASS

FastAPI default error handling is safe.

---

## 6. What's Working Well (Do Not Break)

- Visitor-grouped train/test split (`_group_split`) — correct anti-leakage design
- Privacy-safe `KeyboardEventSchema` — no character fields
- Shared action vocabulary — good intent
- Structured 5-layer verdict with contributing/counter signals
- `data_source` provenance field — correctly demarcates synthetic vs. real
- 6-experiment ablation suite — real computation, no hardcoding
- Native Python fallback when sklearn unavailable
- `UNCERTAIN` state in classification output
- Collector.js throttle/batching

---

## 7. Fix Priority (Correctness → Validity → Engineering → Design → Polish)

| # | Problem | Files | Severity |
|---|---------|-------|----------|
| 1 | Update stale test assertions (label names, flag names, brand names) | `tests/test_detection.py`, `tests/test_api.py` | Critical |
| 2 | Fix bot classified as HUMAN — detection logic gap | `packages/detection/engine.py` | Critical |
| 3 | Fix agent classified as TRADITIONAL_AUTOMATION — priority inversion | `packages/detection/engine.py` | Critical |
| 4 | Extract agentic features from task_actions timestamps | `packages/core/features.py` | Critical |
| 5 | Fix test setup for experiments endpoint | `tests/test_api.py` | High |
| 6 | Align dashboard.js experiment keys with experiments.py | `apps/web/public/dashboard.js` | High |
| 7 | Add class/task balance verification script | NEW `scripts/check_balance.py` | High |
| 8 | Add metadata leakage check script | NEW `scripts/check_leakage.py` | High |
| 9 | Build real AgentProvider hierarchy | `packages/generators/agent_adapter.py` | High |
| 10 | Add consent banner with working Decline | visitor HTML templates | High |
| 11 | Unified brand identity + shared navigation | visitor HTML templates | Medium |
| 12 | Write privacy test for keyboard events | `tests/test_privacy.py` | Medium |
| 13 | Fix model_version written to DB | `apps/api/routes/sessions.py` | Medium |
| 14 | Add rate limiting to telemetry endpoint | `apps/api/main.py` | Medium |
| 15 | Make CORS configurable via env var | `apps/api/config.py` | Medium |
| 16 | Remove Tailwind CDN from dashboard | `apps/web/templates/dashboard.html` | Low |

---

## 8. Changes Log (updated as fixes are applied)

| Phase | File | Change | Status |
|-------|------|--------|--------|
| Audit | `AUDIT.md` | Initial audit created | ✓ Done |
