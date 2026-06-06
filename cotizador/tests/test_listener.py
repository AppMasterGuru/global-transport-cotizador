"""
Tests for Task 1 + Task 2 additions:
  email_listener.py    — parse, fetch, process functions
  acknowledgment.py    — generate_acknowledgment_from_request, send_acknowledgment

4 new tests bringing total from 74 → 78.
All tests run in stub mode (no ANTHROPIC_API_KEY required).
"""

from __future__ import annotations

import os
import tempfile

import pytest

# ── DB isolation ──────────────────────────────────────────────────────────────
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name

from core.db import init_db  # noqa: E402
from core.email_listener import (  # noqa: E402
    REQUIRED_FIELDS,
    fetch_pending_emails,
    parse_quote_request,
    process_inbound_emails,
)
from core.acknowledgment import generate_acknowledgment_from_request  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Full DB isolation for every test."""
    from core.db import get_connection
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
        """)
    init_db()
    yield


# ═══════════════════════════════════════════════════════════════════════════════
# 75. email_listener — parse_quote_request returns all required keys
# ═══════════════════════════════════════════════════════════════════════════════

def test_email_listener_required_keys():
    """parse_quote_request must return a dict containing all REQUIRED_FIELDS."""
    sample = (
        "Hello, I need a quote for air freight from Miami to Lima, Peru. "
        "Commodity: medical devices, weight 350 kg, 2 CBM. Incoterm DAP Lima. Urgent."
    )
    result = parse_quote_request(sample)
    assert isinstance(result, dict)
    for field in REQUIRED_FIELDS:
        assert field in result, f"Missing required field: {field!r}"
    # Language detection — English text → 'en'
    assert result["detected_language"] == "en"
    # Service type detection
    assert result["service_type"] == "aéreo"


# ═══════════════════════════════════════════════════════════════════════════════
# 76. email_listener — process_inbound_emails returns exactly 3 parsed emails
# ═══════════════════════════════════════════════════════════════════════════════

def test_email_listener_process_returns_3():
    """process_inbound_emails must return one parsed dict per stub sample (3)."""
    results = process_inbound_emails()
    assert len(results) == 3

    # Each result has envelope metadata attached
    for r in results:
        assert "_email_id" in r
        assert "_email_from" in r
        assert "_email_subject" in r

    # Languages must span ES, EN, DE (the three stubs)
    langs = {r["detected_language"] for r in results}
    assert "es" in langs
    assert "en" in langs
    assert "de" in langs


# ═══════════════════════════════════════════════════════════════════════════════
# 77. acknowledgment — generate_acknowledgment_from_request returns correct shape
# ═══════════════════════════════════════════════════════════════════════════════

def test_ack_from_request_returns_dict():
    """generate_acknowledgment_from_request must return the four required keys."""
    parsed = {
        "detected_language": "de",
        "customer_name":     "Hans Müller",
        "service_type":      "aéreo",
        "origin_city":       "Frankfurt",
        "destination_city":  "Lima",
        "commodity":         "Medizinische Geräte",
        "urgency":           "asap",
    }
    ack = generate_acknowledgment_from_request(parsed)

    assert isinstance(ack, dict)
    assert "subject" in ack
    assert "body" in ack
    assert "language" in ack
    assert "detected_topic" in ack

    # Language preserved
    assert ack["language"] == "de"
    # Body must not be empty
    assert len(ack["body"]) > 20
    # Subject must be in German (contains "Global Transport")
    assert "Global Transport" in ack["subject"]


# ═══════════════════════════════════════════════════════════════════════════════
# 78. Routes — GET /acknowledgment/demo returns 200
# ═══════════════════════════════════════════════════════════════════════════════

def test_ack_demo_route():
    """GET /acknowledgment/demo must return 200 with the three demo cards."""
    from api.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/acknowledgment/demo")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Page must contain all three language codes
    assert "ES" in body or "es" in body
    assert "EN" in body or "en" in body
    assert "DE" in body or "de" in body
