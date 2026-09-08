"""
Deterministic Traditional Automation Generator for WebSense.
Simulates headless browser automation (Playwright/Selenium pattern).
"""

import time
import requests
from typing import Dict, Any
from packages.generators.seed_data import generate_synthetic_session


def run_bot_session(endpoint: str = "http://127.0.0.1:8000/api/v1/sessions", task: str = "shopping", index: int = 1):
    """Generates and transmits a deterministic bot session."""
    payload = generate_synthetic_session(label="BOT", task=task, index=index)
    try:
        res = requests.post(endpoint, json=payload, timeout=5)
        return res.json()
    except Exception as e:
        print(f"Error submitting bot session: {e}")
        return None


if __name__ == "__main__":
    print("[WebSense] Running automated bot generator...")
    run_bot_session()

