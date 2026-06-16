"""
Regression tests for POST /quote/<ref>/send (mark_sent).

Bug (2026-06-16 verification pass): mark_sent() called send_quote_email()
with origin=/destination=/staff_code= kwargs that don't exist on its
signature, so every send raised TypeError (500). Worse, the APPROVED ->
SENT transition happened BEFORE the send attempt, so a quote ended up
marked SENT in the DB even though the client never received anything.

These tests pin down two independent behaviors:
  1. A real send (stub mode) must not crash the route.
  2. The SENT transition must be atomic with a successful send: no
     transition (and a logged failure) when the send fails or raises.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("DB_PATH", _tmp_db.name)

from core.db import get_connection, init_db, transition_status, get_audit_trail  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS provider_replies;
        """)
    init_db()
    yield


@pytest.fixture
def app():
    from api.app import create_app
    a = create_app()
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


_VENTA = json.dumps({
    "line_items": [{"description": "Flete", "quantity": 1, "unit_price": 500.0, "total": 500.0}],
    "total_usd": 600.0,
    "margin_pct": 0.20,
    "validity_days": 15,
})
_COSTEO = json.dumps({
    "flete_internacional_usd": 300.0,
    "visto_bueno_usd": 80.0,
    "handling_aereo_usd": 0.0,
    "handling_aereo_detail": {},
    "customs_agent_usd": 70.0,
    "transport_usd": 50.0,
    "transport_soles": 187.5,
    "transport_detail": {},
    "total_usd": 500.0,
    "exchange_rate": 3.75,
    "consolidator": "MSL",
    "airline": None,
    "customs_agent": "Test Agent",
})


def _insert_approved_quote(ref: str, client_email: str = "client@example.com") -> int:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO quotes
              (reference_code, client_name, client_email, incoterm, mode, origin, destination,
               cargo_description, weight_kg, volume_cbm, dimensions_json,
               costeo_json, venta_json, margin_pct, exchange_rate, status, staff_code, language)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?,?)
            """,
            (
                ref, "Test Client", client_email, "FOB", "lcl",
                "Lima, Peru", "Hamburgo, Alemania", "Uvas", 500.0, 2.0,
                json.dumps({"l": 40, "w": 30, "h": 20, "qty": 1}),
                _COSTEO, _VENTA, 0.20, 3.75, "GT-PC", "es",
            ),
        )
        conn.commit()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    quote_id = row["id"]
    transition_status(quote_id, "APPROVED", "test")
    return quote_id


def _status_of(ref: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    return row["status"]


class TestMarkSentRealSend:
    """Exercises the real send_quote_email() call site — no mocking.
    Stub mode is active in tests (no Graph credentials in the test env),
    so this is a real call through real code, just without a real network hop.
    """

    def test_send_with_client_email_does_not_500(self, client):
        _insert_approved_quote("26-06-MS-001")
        resp = client.post(
            "/quote/26-06-MS-001/send", data={"actor": "JP"}, follow_redirects=False
        )
        assert resp.status_code != 500

    def test_successful_send_logs_quote_sent(self, client):
        _insert_approved_quote("26-06-MS-002")
        client.post("/quote/26-06-MS-002/send", data={"actor": "JP"}, follow_redirects=False)
        trail = get_audit_trail("26-06-MS-002")
        assert any(e["event_type"] == "QUOTE_SENT" for e in trail)

    def test_successful_send_moves_status_to_sent(self, client):
        _insert_approved_quote("26-06-MS-003")
        client.post("/quote/26-06-MS-003/send", data={"actor": "JP"}, follow_redirects=False)
        assert _status_of("26-06-MS-003") == "SENT"


class TestMarkSentAtomicity:
    """The APPROVED -> SENT transition must only happen on a successful send."""

    def test_status_unchanged_when_send_raises(self, client, monkeypatch):
        _insert_approved_quote("26-06-MS-010")
        import api.routes as routes

        def _boom(**kwargs):
            raise RuntimeError("simulated send failure")

        monkeypatch.setattr(routes, "send_quote_email", _boom)
        resp = client.post(
            "/quote/26-06-MS-010/send", data={"actor": "JP"}, follow_redirects=False
        )
        assert resp.status_code != 500
        assert _status_of("26-06-MS-010") == "APPROVED"

    def test_failure_is_audit_logged_when_send_raises(self, client, monkeypatch):
        _insert_approved_quote("26-06-MS-011")
        import api.routes as routes

        def _boom(**kwargs):
            raise RuntimeError("simulated send failure")

        monkeypatch.setattr(routes, "send_quote_email", _boom)
        client.post("/quote/26-06-MS-011/send", data={"actor": "JP"}, follow_redirects=False)
        trail = get_audit_trail("26-06-MS-011")
        assert any("FAILED" in e["event_type"] for e in trail)

    def test_status_unchanged_when_send_returns_failure(self, client, monkeypatch):
        _insert_approved_quote("26-06-MS-012")
        import api.routes as routes

        monkeypatch.setattr(routes, "send_quote_email", lambda **kwargs: (False, "simulated failure"))
        client.post("/quote/26-06-MS-012/send", data={"actor": "JP"}, follow_redirects=False)
        assert _status_of("26-06-MS-012") == "APPROVED"

    def test_no_client_email_still_marks_sent_manually(self, client):
        """No client_email -> no auto-send attempted -> human-confirmed SENT is unaffected."""
        _insert_approved_quote("26-06-MS-013", client_email="")
        resp = client.post(
            "/quote/26-06-MS-013/send", data={"actor": "JP"}, follow_redirects=False
        )
        assert resp.status_code != 500
        assert _status_of("26-06-MS-013") == "SENT"
