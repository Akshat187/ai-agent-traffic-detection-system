"""
AI Browsing Agent Adapter — Honest, Hierarchical Implementation.

Provider hierarchy:
  AgentProvider (abstract base)
    ├── LocalDemoAgent     — deterministic decision tree, no external calls
    │                        source = "simulated_agent_demo"
    └── LLMAgentAdapter    — calls a real LLM if AGENT_API_KEY is set
                             source = "llm_agent_real"

IMPORTANT: Neither implementation drives a real browser. They produce
structured action plans that the session generator uses to construct
realistic telemetry. The LLMAgentAdapter is a minimal proof-of-concept
and should NOT be presented as a production agent framework.

Data labeling guarantee:
  - Sessions produced by LocalDemoAgent:  data_source = "simulated_agent_demo"
  - Sessions produced by LLMAgentAdapter: data_source = "llm_agent_real"
  - These values are written to the DB and must be preserved through the
    ingestion pipeline so researchers can filter by source.
"""

import os
import json
import time
import random
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ── Shopping task vocabulary ────────────────────────────────────────────────

SHOPPING_STEPS = [
    {
        "step":   0,
        "action": "page_inspected",
        "target": "body",
        "notes":  "Scanned visible products and navigation",
    },
    {
        "step":   1,
        "action": "search_query",
        "target": "#shop-search",
        "text":   "QuantumBook Pro",
        "notes":  "Typed search query based on task objective",
    },
    {
        "step":   2,
        "action": "product_selected",
        "target": ".product-card:first-child",
        "notes":  "Selected first relevant search result",
    },
    {
        "step":   3,
        "action": "add_to_cart",
        "target": ".add-cart-btn",
        "notes":  "Added item to cart",
    },
    {
        "step":   4,
        "action": "checkout_complete",
        "target": "#checkout-btn",
        "notes":  "Completed checkout flow",
    },
]

TRAVEL_STEPS = [
    {
        "step":   0,
        "action": "page_inspected",
        "target": "body",
        "notes":  "Identified search form structure",
    },
    {
        "step":   1,
        "action": "origin_entered",
        "target": "#origin-input",
        "text":   "London",
        "notes":  "Entered departure city",
    },
    {
        "step":   2,
        "action": "destination_entered",
        "target": "#destination-input",
        "text":   "New York",
        "notes":  "Entered arrival city",
    },
    {
        "step":   3,
        "action": "flight_search",
        "target": "#search-btn",
        "notes":  "Submitted flight search",
    },
    {
        "step":   4,
        "action": "flight_booked",
        "target": ".book-flight-btn",
        "notes":  "Selected and booked cheapest option",
    },
]

FORUM_STEPS = [
    {
        "step":   0,
        "action": "page_inspected",
        "target": "body",
        "notes":  "Browsed thread list",
    },
    {
        "step":   1,
        "action": "thread_opened",
        "target": ".thread-link:first-child",
        "notes":  "Opened first relevant thread",
    },
    {
        "step":   2,
        "action": "content_read",
        "target": ".post-body",
        "notes":  "Read post content before replying",
    },
    {
        "step":   3,
        "action": "reply_composed",
        "target": "#forum-reply-form",
        "text":   "Interesting perspective — behavioral timing patterns do reveal decision architecture.",
        "notes":  "Composed reply based on thread context",
    },
    {
        "step":   4,
        "action": "reply_posted",
        "target": "#submit-reply-btn",
        "notes":  "Submitted reply",
    },
]

TASK_PLANS = {
    "shopping": SHOPPING_STEPS,
    "travel":   TRAVEL_STEPS,
    "forum":    FORUM_STEPS,
}


# ── Abstract base ───────────────────────────────────────────────────────────

class AgentProvider(ABC):
    """
    Abstract base for all agent adapters.
    Subclasses produce action plans from page state;
    they do NOT drive a real browser.
    """

    @property
    @abstractmethod
    def source_label(self) -> str:
        """data_source value to write to session metadata."""

    @abstractmethod
    def plan_next_action(self, current_page_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Given the current page state, return the next action dict.
        Returns:
            {
              "action":  str   — action name from task vocabulary,
              "target":  str   — CSS selector or description,
              "text":    str   — optional input text,
              "delay_ms": int  — realistic delay before this action fires,
              "notes":   str   — human-readable reasoning for this action,
            }
        """

    def plan_session(
        self,
        task: str,
        max_steps: int = 5,
        error_rate: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Produces a full sequence of actions for a task.
        Subclasses may override for more sophisticated planning.
        """
        steps = TASK_PLANS.get(task, SHOPPING_STEPS)
        results = []
        for i, step_def in enumerate(steps[:max_steps]):
            state = {"task": task, "step": i, "visible_steps": steps}
            action = self.plan_next_action(state)
            action["step_index"] = i
            results.append(action)
        return results


# ── LocalDemoAgent ──────────────────────────────────────────────────────────

class LocalDemoAgent(AgentProvider):
    """
    Deterministic decision-tree agent. No external API calls.
    Simulates variable LLM-like delays using a configurable range.

    This is clearly labeled in session data as source="simulated_agent_demo".
    Do NOT display results from this adapter as real agent data.
    """

    source_label = "simulated_agent_demo"

    def __init__(
        self,
        min_delay_ms: int = 800,
        max_delay_ms: int = 2500,
        seed: Optional[int] = None,
    ):
        """
        Args:
            min_delay_ms: Minimum simulated reasoning delay (models LLM inference floor).
            max_delay_ms: Maximum simulated reasoning delay.
            seed: Random seed for reproducibility. None = non-deterministic.
        """
        self.rng = random.Random(seed)
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms

    def _thinking_delay(self) -> int:
        """Simulates LLM inference latency with log-normal distribution."""
        # Log-normal gives a realistic tail: most actions fast, some very slow
        base = self.rng.gauss(
            (self.min_delay_ms + self.max_delay_ms) / 2,
            (self.max_delay_ms - self.min_delay_ms) / 4
        )
        return max(self.min_delay_ms, min(self.max_delay_ms, int(base)))

    def plan_next_action(self, current_page_state: Dict[str, Any]) -> Dict[str, Any]:
        task  = current_page_state.get("task", "shopping")
        step  = current_page_state.get("step", 0)
        steps = TASK_PLANS.get(task, SHOPPING_STEPS)
        idx   = min(step, len(steps) - 1)

        action = dict(steps[idx])  # copy to avoid mutating the template
        action["delay_ms"] = self._thinking_delay()
        action["source"]   = self.source_label
        return action


# ── LLMAgentAdapter ─────────────────────────────────────────────────────────

class LLMAgentAdapter(AgentProvider):
    """
    Calls a real LLM API to decide next actions from page state.

    This is a MINIMAL proof-of-concept. It is not a production agent
    framework. It has no:
      - Real browser integration (no Playwright/Selenium bindings)
      - DOM parsing
      - Error recovery strategies
      - Session continuity across page loads

    Configure via environment variable: AGENT_API_KEY

    If no API key is available, falls back to LocalDemoAgent silently
    and logs a warning.
    """

    source_label = "llm_agent_real"
    FALLBACK_SOURCE_LABEL = "simulated_agent_demo_fallback"

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("AGENT_API_KEY")
        self.model   = model
        self._fallback = LocalDemoAgent()

        if not self.api_key:
            logger.warning(
                "LLMAgentAdapter: No AGENT_API_KEY set. "
                "Falling back to LocalDemoAgent (source='simulated_agent_demo_fallback'). "
                "Sessions generated in fallback mode must NOT be presented as real LLM agent data."
            )

    def _build_prompt(self, page_state: Dict[str, Any]) -> str:
        return (
            f"You are a browser agent completing a task.\n"
            f"Task: {page_state.get('task', 'shopping')}\n"
            f"Step: {page_state.get('step', 0)}\n"
            f"Available actions: {json.dumps(TASK_PLANS.get(page_state.get('task', 'shopping'), []), indent=2)}\n"
            f"\nRespond with a JSON object: {{\"action\": str, \"target\": str, "
            f"\"text\": str|null, \"notes\": str}}"
        )

    def plan_next_action(self, current_page_state: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            action = self._fallback.plan_next_action(current_page_state)
            action["source"] = self.FALLBACK_SOURCE_LABEL
            return action

        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=self.api_key)
            client = genai.GenerativeModel(self.model)

            prompt   = self._build_prompt(current_page_state)
            t0       = time.time()
            response = client.generate_content(prompt)
            elapsed  = int((time.time() - t0) * 1000)

            raw_text = response.text.strip()
            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = "\n".join(raw_text.split("\n")[1:-1])

            parsed = json.loads(raw_text)
            parsed["delay_ms"] = elapsed  # actual LLM latency
            parsed["source"]   = self.source_label
            return parsed

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "LLMAgentAdapter: LLM call failed (%s). Falling back to LocalDemoAgent.", exc
            )
            action = self._fallback.plan_next_action(current_page_state)
            action["source"] = self.FALLBACK_SOURCE_LABEL
            return action


# ── Backwards compatibility shim ────────────────────────────────────────────

class AIAgentAdapter(LocalDemoAgent):
    """
    Backwards-compatible alias for LocalDemoAgent.
    New code should use LocalDemoAgent or LLMAgentAdapter directly.
    """

    def __init__(self, api_key: str = None, provider: str = "mock"):
        super().__init__()
        if api_key or (provider != "mock" and os.getenv("AGENT_API_KEY")):
            logger.info(
                "AIAgentAdapter: Use LLMAgentAdapter directly for real LLM calls."
            )
