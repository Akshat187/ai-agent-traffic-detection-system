"""
Verification tests for the active-duration session fix.

Test 1: Idle-tab simulation
  - Mock: 280,973 s raw tab lifetime, only 42 s of actual events
  - Confirm active_duration_ms reflects the 42-second burst

Test 2: planning_pause_ratio before vs after
  - Same payload: before fix uses raw 280973s, after uses 42s
  - Show ratio difference

Test 3: Two-payload differentiation
  - Bot: near-zero variance, instant actions, no pauses
  - Human: varied intervals, real mouse movement, dwell time
  - Confirm different verdicts
"""
import sys, os, json
sys.path.insert(0, r"d:\RealDevSquad\akshat-projects\ai_agent traffic detection system")
os.chdir(r"d:\RealDevSquad\akshat-projects\ai_agent traffic detection system")

from packages.core.features import extract_all_features
from packages.detection.engine import DecisionEngine

engine = DecisionEngine()

# ─── TEST 1 & 2: Idle-tab simulation ──────────────────────────────────────────
RAW_TAB_MS = 280_973_000   # ~78 hours: a real tab left open in background
ACTIVE_MS  =      42_000  # only 42 seconds of real events

idle_payload = {
    "session_id": "test_idle_tab",
    "site_id": "test_site",
    "task": "shopping",
    "start_time": 1_700_000_000_000,
    "end_time":   1_700_000_042_000,
    "duration_ms": RAW_TAB_MS,
    "active_duration_ms": ACTIVE_MS,
    "data_source": "chrome_extension",
    "browser_signals": {"webdriver": False, "touch_support": False, "hardware_concurrency": 8},
    "mouse_events": [{"x":100,"y":200,"t":1000,"type":"move"},{"x":120,"y":210,"t":3500,"type":"move"},{"x":140,"y":230,"t":7000,"type":"move"}],
    "keyboard_events": [{"t":5000,"interval":320,"hold":120,"is_paste":False},{"t":6200,"interval":280,"hold":95,"is_paste":False}],
    "scroll_events": [{"t":2000,"scroll_y":0,"delta_y":0},{"t":4000,"scroll_y":300,"delta_y":300}],
    "click_events": [{"x":200,"y":300,"t":8000,"target_category":"button"}],
    "task_actions": [{"action":"add_to_cart","t":10000,"details":{}},{"action":"checkout","t":35000,"details":{}}],
}

feats_after = extract_all_features(idle_payload)

# Simulate BEFORE fix: use raw duration_ms instead
idle_payload_before = dict(idle_payload)
del idle_payload_before["active_duration_ms"]
idle_payload_before["duration_ms"] = RAW_TAB_MS

feats_before = extract_all_features(idle_payload_before)

print("=" * 60)
print("TEST 1 & 2 — Idle-tab simulation")
print(f"  Raw tab lifetime:          {RAW_TAB_MS/1000:.1f}s (~78h)")
print(f"  Actual event window:       {ACTIVE_MS/1000:.1f}s")
print()
print(f"  BEFORE fix:")
print(f"    effective duration_ms:   {feats_before['duration_ms']:.0f} ms  (~{feats_before['duration_ms']/1000/3600:.1f}h)")
print(f"    planning_pause_ratio:    {feats_before['planning_pause_ratio']:.6f}  ← collapsed toward 0")
print()
print(f"  AFTER fix:")
print(f"    effective duration_ms:   {feats_after['duration_ms']:.0f} ms  ({feats_after['duration_ms']/1000:.1f}s)")
print(f"    planning_pause_ratio:    {feats_after['planning_pause_ratio']:.6f}  ← meaningful fraction")
print(f"    active_duration_ms:      {feats_after.get('active_duration_ms', 'N/A')}")

ratio_improvement = feats_after["planning_pause_ratio"] - feats_before["planning_pause_ratio"]
print(f"\n  planning_pause_ratio improvement: +{ratio_improvement:.6f} ✓" if ratio_improvement > 0 else f"\n  WARNING: ratio did not improve (diff={ratio_improvement:.6f})")

# ─── TEST 3: Two-payload differentiation ──────────────────────────────────────
print()
print("=" * 60)
print("TEST 3 — Two-payload differentiation")

bot_payload = {
    "session_id": "test_bot",
    "site_id": "test_site",
    "task": "shopping",
    "start_time": 1_700_000_000_000,
    "end_time":   1_700_000_001_500,
    "duration_ms": 1500,
    "active_duration_ms": 1500,
    "data_source": "chrome_extension",
    "browser_signals": {"webdriver": True, "touch_support": False, "hardware_concurrency": 4},
    "mouse_events": [],   # no mouse — DOM clicks only
    "keyboard_events": [
        {"t":100,"interval":50,"hold":20,"is_paste":False},
        {"t":150,"interval":50,"hold":20,"is_paste":False},
        {"t":200,"interval":50,"hold":20,"is_paste":False},
        {"t":250,"interval":50,"hold":20,"is_paste":False},
        {"t":300,"interval":50,"hold":20,"is_paste":False},
    ],
    "scroll_events": [],
    "click_events": [{"x":500,"y":400,"t":100,"target_category":"button"},{"x":500,"y":400,"t":150,"target_category":"button"}],
    "task_actions": [{"action":"add_to_cart","t":200,"details":{}},{"action":"checkout","t":250,"details":{}}],
}

human_payload = {
    "session_id": "test_human",
    "site_id": "test_site",
    "task": "shopping",
    "start_time": 1_700_000_000_000,
    "end_time":   1_700_000_045_000,
    "duration_ms": 45000,
    "active_duration_ms": 45000,
    "data_source": "chrome_extension",
    "browser_signals": {"webdriver": False, "touch_support": False, "hardware_concurrency": 8},
    "mouse_events": [
        {"x":100,"y":200,"t":1200,"type":"move"},{"x":115,"y":207,"t":1260,"type":"move"},
        {"x":130,"y":215,"t":1340,"type":"move"},{"x":152,"y":228,"t":1440,"type":"move"},
        {"x":170,"y":230,"t":2100,"type":"move"},{"x":180,"y":235,"t":5800,"type":"move"},
        {"x":200,"y":240,"t":9200,"type":"move"},{"x":210,"y":240,"t":9280,"type":"move"},
    ],
    "keyboard_events": [
        {"t":3000,"interval":0,"hold":142,"is_paste":False},
        {"t":3340,"interval":340,"hold":118,"is_paste":False},
        {"t":3720,"interval":380,"hold":95,"is_paste":False},
        {"t":4200,"interval":480,"hold":130,"is_paste":False},
        {"t":4890,"interval":690,"hold":108,"is_paste":False},
    ],
    "scroll_events": [
        {"t":2000,"scroll_y":0,"delta_y":0},
        {"t":4500,"scroll_y":250,"delta_y":250},
        {"t":7200,"scroll_y":480,"delta_y":230},
        {"t":12000,"scroll_y":200,"delta_y":-280},
    ],
    "click_events": [
        {"x":200,"y":300,"t":9500,"target_category":"button"},
        {"x":350,"y":420,"t":28000,"target_category":"button"},
    ],
    "task_actions": [
        {"action":"view_product","t":9500,"details":{}},
        {"action":"add_to_cart","t":28000,"details":{}},
    ],
}

bot_feats   = extract_all_features(bot_payload)
human_feats = extract_all_features(human_payload)

bot_result   = engine.evaluate_session("test_bot",   "shopping", bot_payload,   bot_feats)
human_result = engine.evaluate_session("test_human", "shopping", human_payload, human_feats)

print(f"\n  BOT payload:")
print(f"    verdict:     {bot_result.get('predicted_label', bot_result.get('label', '?'))}")
print(f"    confidence:  {bot_result.get('confidence', '?')}")
print(f"    risk_score:  {bot_result.get('risk_score', '?')}")

print(f"\n  HUMAN payload:")
print(f"    verdict:     {human_result.get('predicted_label', human_result.get('label', '?'))}")
print(f"    confidence:  {human_result.get('confidence', '?')}")
print(f"    risk_score:  {human_result.get('risk_score', '?')}")

same_verdict = (
    bot_result.get("predicted_label", bot_result.get("label")) ==
    human_result.get("predicted_label", human_result.get("label"))
)
same_conf = abs(
    float(bot_result.get("confidence", 0)) - float(human_result.get("confidence", 0))
) < 5.0

if not same_verdict:
    print("\n  ✓  Different verdicts — payloads discriminated correctly.")
elif not same_conf:
    print("\n  ~  Same verdict but different confidence — partial discrimination.")
else:
    print("\n  ✗  WARNING: Both payloads returned identical outputs — further investigation needed.")

print()
