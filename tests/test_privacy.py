"""
Privacy Tests for Telemetry Ingestion Pipeline.

Verifies that:
1. Keyboard events stored in raw_telemetry contain ONLY timing metadata —
   no character sequences, no text content.
2. The keyboard_events schema only stores: t, interval, hold, is_paste.
3. No session payload field named 'key', 'char', 'character', 'text', 'value',
   or 'key_code' survives to the DB.
4. Paste events are recorded as is_paste=True, NOT with the pasted text.

These tests enforce the privacy contract documented in models.py:
"keyboard_events store ONLY timing metadata — never character content,
 never passwords."
"""

import json
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from packages.database.db import get_db
from packages.database.models import RawTelemetry

client = TestClient(app)


# ── Blocked field names — must never appear in stored keyboard events ────────
PROHIBITED_KEYBOARD_FIELDS = {
    "key", "char", "character", "text", "value",
    "key_code", "keycode", "code", "which", "charcode",
    "key_value", "content", "input", "data",
}


def _ingest_session_with_keyboard(keyboard_events: list) -> str:
    """Helpers: ingest a session with given keyboard events, return session_id."""
    import time, uuid
    session_id = f"privacy_test_{uuid.uuid4().hex[:12]}"
    payload = {
        "session_id":         session_id,
        "visitor_id":         f"privacy_vis_{session_id[:8]}",
        "task":               "shopping",
        "start_time":         float(int(time.time() * 1000)),
        "end_time":           float(int(time.time() * 1000) + 5000),
        "duration_ms":        5000.0,
        "ground_truth_label": "HUMAN",
        "is_synthetic":       True,
        "data_source":        "privacy_test",
        "browser_signals":    {"webdriver": False},
        "mouse_events":       [{"x": 100, "y": 100, "t": 500}, {"x": 200, "y": 200, "t": 1000}],
        "keyboard_events":    keyboard_events,
        "scroll_events":      [],
        "click_events":       [],
        "task_actions":       [{"action": "product_selected", "t": 3000, "details": {}}],
    }
    res = client.post("/api/v1/sessions", json=payload)
    assert res.status_code == 200, f"Ingest failed: {res.text}"
    return session_id


def _get_stored_keyboard_events(session_id: str) -> list:
    """Retrieves stored keyboard_events from raw_telemetry for a session."""
    db = next(get_db())
    record = db.query(RawTelemetry).filter(
        RawTelemetry.session_id == session_id
    ).first()
    if record is None:
        pytest.fail(f"No raw_telemetry found for session {session_id!r}")
    events = record.keyboard_events or []
    if isinstance(events, str):
        events = json.loads(events)
    return events


class TestKeyboardPrivacy:

    def test_timing_only_schema_enforced(self):
        """
        A keyboard_events payload containing only legal timing fields (t, interval,
        hold, is_paste) should be stored as-is with no modification.
        """
        keyboard_events = [
            {"t": 1200, "interval": 185, "hold": 72, "is_paste": False},
            {"t": 1385, "interval": 210, "hold": 65, "is_paste": False},
            {"t": 1595, "interval": 190, "hold": 80, "is_paste": False},
        ]
        session_id = _ingest_session_with_keyboard(keyboard_events)
        stored = _get_stored_keyboard_events(session_id)

        assert len(stored) > 0, "Keyboard events should be stored"

        for event in stored:
            allowed_fields = {"t", "interval", "hold", "is_paste"}
            actual_fields  = set(event.keys())
            illegal_fields = actual_fields - allowed_fields
            assert not illegal_fields, (
                f"Stored keyboard event contains prohibited fields: {illegal_fields}. "
                f"Event: {event}"
            )

    def test_no_character_content_stored(self):
        """
        If an incoming payload erroneously includes character content
        (simulating a misconfigured collector), those fields must not survive
        to the database.
        """
        keyboard_events_with_chars = [
            {"t": 1200, "interval": 185, "hold": 72, "is_paste": False,
             "key": "a", "char": "a", "value": "aero"},  # these MUST be stripped
            {"t": 1385, "interval": 210, "hold": 65, "is_paste": False,
             "key": "e", "character": "e"},
        ]
        session_id = _ingest_session_with_keyboard(keyboard_events_with_chars)
        stored = _get_stored_keyboard_events(session_id)

        for event in stored:
            for prohibited in PROHIBITED_KEYBOARD_FIELDS:
                assert prohibited not in event, (
                    f"Prohibited field '{prohibited}' found in stored keyboard event: {event}"
                )

    def test_paste_event_recorded_without_content(self):
        """
        A paste event (Ctrl+V) should be stored as is_paste=True with
        timing metadata only — the pasted text must never be stored.
        """
        keyboard_events_with_paste = [
            {"t": 2000, "interval": 150, "hold": 50, "is_paste": True,
             "text": "pasted secret content"},  # text field must be stripped
            {"t": 2500, "interval": 200, "hold": 60, "is_paste": False},
        ]
        session_id = _ingest_session_with_keyboard(keyboard_events_with_paste)
        stored = _get_stored_keyboard_events(session_id)

        paste_events = [e for e in stored if e.get("is_paste")]
        assert len(paste_events) > 0, "Paste events should be recorded"

        for paste in paste_events:
            assert "text" not in paste, (
                f"Paste event should not store text content: {paste}"
            )
            assert paste.get("is_paste") is True

    def test_full_telemetry_roundtrip_has_no_raw_characters(self):
        """
        Integration: POST a session, GET its detail endpoint, verify
        no field named in PROHIBITED_KEYBOARD_FIELDS appears at any
        nesting level of the telemetry response.
        """
        keyboard_events = [
            {"t": 1000, "interval": 200, "hold": 75, "is_paste": False},
            {"t": 1200, "interval": 195, "hold": 70, "is_paste": False},
        ]
        session_id = _ingest_session_with_keyboard(keyboard_events)

        detail_res = client.get(f"/api/v1/sessions/{session_id}")
        assert detail_res.status_code == 200
        body = detail_res.json()

        # Flatten all keys recursively in the telemetry section
        def collect_keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k.lower()
                    yield from collect_keys(v)
            elif isinstance(obj, list):
                for item in obj:
                    yield from collect_keys(item)

        telemetry_section = body.get("telemetry", {})
        all_keys = set(collect_keys(telemetry_section))
        found_prohibited = all_keys & PROHIBITED_KEYBOARD_FIELDS

        assert not found_prohibited, (
            f"API detail response contains prohibited telemetry fields: {found_prohibited}. "
            f"These fields must be stripped before storage."
        )
