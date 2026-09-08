"""
Layer 5: Contextual Task & Interaction Logic Validation.
Checks whether the sequence of actions conforms to logical task progression rules.
"""

from typing import List, Dict, Any, Tuple


class ContextValidator:
    """Validates interaction sequences against task workflows to catch synthetic or headless bots."""

    def validate(
        self,
        task: str,
        task_actions: List[Dict[str, Any]],
        click_events: List[Dict[str, Any]],
        features: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Returns (is_valid, list_of_violations).
        """
        violations = []

        # 1. Check if clicks landed on valid categories
        invalid_click_targets = 0
        for clk in click_events:
            cat = clk.get("target_category", "general")
            if cat == "impossible_boundary" or cat == "hidden_honeypot":
                violations.append("CLICK_DETECTED_ON_HIDDEN_HONEYPOT_ELEMENT")

        # 2. Task-specific workflow validation
        actions = [a.get("action") for a in task_actions if a.get("action")]

        if task == "shopping":
            # E-commerce checkout requires items added before checkout
            if "checkout_complete" in actions and "add_to_cart" not in actions:
                violations.append("TASK_ANOMALY_CHECKOUT_COMPLETED_WITHOUT_CART_ADDITION")
            if "add_to_cart" in actions and features.get("duration_ms", 0) < 400:
                violations.append("TASK_ANOMALY_INSTANT_PRODUCT_ADDITION")

        elif task == "travel":
            # Flight booking requires origin/dest selection before confirmation
            if "flight_booked" in actions and "flight_search" not in actions:
                violations.append("TASK_ANOMALY_CONFIRMATION_WITHOUT_SEARCH_STAGE")

        elif task == "forum":
            # Forum post requires typing interaction before submission
            if "reply_posted" in actions and features.get("key_event_count", 0) < 3 and features.get("key_paste_count", 0) == 0:
                violations.append("TASK_ANOMALY_FORUM_POST_SUBMITTED_WITHOUT_KEYBOARD_INPUT")

        is_valid = len(violations) == 0
        return is_valid, violations
