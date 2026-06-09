"""
Tests for auto-send of provider emails on quote creation.

Covers:
  - PROVIDER_EMAILS_SKIPPED logged when no SMTP credentials (no-creds path)
  - send_provider_email called for each provider address (creds present path)
  - PROVIDER_EMAILS_AUTO_SENT audit event logged with correct counts
  - Exception inside auto-send never blocks quote creation
  - Stress test: full POST /quote/new → PROVIDER_EMAILS_SKIPPED in audit log
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

# DB isolation must happen before any app import.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name

from core.db import get_connection, init_db  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _audit_events(ref: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if ref:
            rows = conn.execute(
                "SELECT event_type, detail_json FROM audit_log WHERE quote_reference = ?",
                (ref,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_type, detail_json FROM audit_log"
            ).fetchall()
    return [{"event_type": r[0], "detail": json.loads(r[1] or "{}")} for r in rows]


def _event_types(ref: str | None = None) -> list[str]:
    return [e["event_type"] for e in _audit_events(ref)]


# Minimal form data that satisfies create_quote()
_QUOTE_FORM = {
    "client_name":       "Test Importer GmbH",
    "client_email":      "test@importer.de",
    "incoterm":          "FOB",
    "mode":              "lcl",
    "origin":            "Lima, Perú",
    "destination":       "Hamburgo, Alemania",
    "cargo_description": "Uvas frescas",
    "weight":            "500",
    "weight_unit":       "kg",
    "volume_cbm":        "2.0",
    "flete_lcl":         "300",
    "consolidator":      "MSL",
    "margin_pct":        "20",
    "staff_code":        "GT-PC",
    "language":          "es",
}


# ── Unit tests for _auto_send_provider_emails ─────────────────────────────────

class TestAutoSendSkippedWhenNoCredentials:
    """When CREDENTIALS_ROTATED is False, log SKIPPED and call nothing."""

    def test_skipped_event_logged(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", False)

        ref = "26-06-TEST-001"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        assert "PROVIDER_EMAILS_SKIPPED" in _event_types(ref)

    def test_send_not_called(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", False)

        calls = []
        monkeypatch.setattr(routes, "send_provider_email",
                            lambda **kw: calls.append(kw) or (True, "ok"))

        routes._auto_send_provider_emails("REF-X", {"mode": "lcl"}, "GT-PC")
        assert calls == []

    def test_skipped_detail_contains_reason(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", False)

        ref = "26-06-TEST-002"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        events = _audit_events(ref)
        skipped = next(e for e in events if e["event_type"] == "PROVIDER_EMAILS_SKIPPED")
        assert "graph credentials not configured" in skipped["detail"]["reason"]


class TestAutoSendWhenCredentialsPresent:
    """When CREDENTIALS_ROTATED is True, send_provider_email is called per address."""

    def _patch(self, monkeypatch, to_emails: list[str]):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)

        calls = []

        def fake_send(**kw):
            calls.append(kw)
            return True, "ok"

        monkeypatch.setattr(routes, "send_provider_email", fake_send)
        monkeypatch.setattr(
            routes, "generate_provider_emails",
            lambda q: [{"provider": "MSL", "subject": "S", "body": "B",
                        "to_emails": to_emails}],
        )
        return calls, routes

    def test_send_called_for_each_address(self, monkeypatch):
        calls, routes = self._patch(monkeypatch, ["a@msl.com", "b@msl.com"])
        routes._auto_send_provider_emails("REF-1", {"mode": "lcl"}, "GT-PC")
        assert len(calls) == 2

    def test_send_called_with_correct_provider(self, monkeypatch):
        calls, routes = self._patch(monkeypatch, ["a@msl.com"])
        routes._auto_send_provider_emails("REF-2", {"mode": "lcl"}, "GT-PC")
        assert calls[0]["provider"] == "MSL"

    def test_provider_with_no_addresses_skipped(self, monkeypatch):
        calls, routes = self._patch(monkeypatch, [])
        routes._auto_send_provider_emails("REF-3", {"mode": "lcl"}, "GT-PC")
        assert calls == []


class TestAutoSendAuditEvent:
    """PROVIDER_EMAILS_AUTO_SENT is logged with correct counts."""

    def test_auto_sent_event_logged(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)
        monkeypatch.setattr(routes, "send_provider_email",
                            lambda **kw: (True, "ok"))
        monkeypatch.setattr(
            routes, "generate_provider_emails",
            lambda q: [{"provider": "MSL", "subject": "S", "body": "B",
                        "to_emails": ["x@msl.com"]}],
        )

        ref = "26-06-TEST-003"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        assert "PROVIDER_EMAILS_AUTO_SENT" in _event_types(ref)

    def test_sent_count_correct(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)
        monkeypatch.setattr(routes, "send_provider_email",
                            lambda **kw: (True, "ok"))
        monkeypatch.setattr(
            routes, "generate_provider_emails",
            lambda q: [
                {"provider": "MSL",   "subject": "S", "body": "B",
                 "to_emails": ["a@msl.com", "b@msl.com"]},
                {"provider": "CRAFT", "subject": "S", "body": "B",
                 "to_emails": ["c@craft.com"]},
            ],
        )

        ref = "26-06-TEST-004"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        events = _audit_events(ref)
        ev = next(e for e in events if e["event_type"] == "PROVIDER_EMAILS_AUTO_SENT")
        assert ev["detail"]["sent"] == 3
        assert ev["detail"]["skipped"] == 0

    def test_skipped_count_correct(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)
        monkeypatch.setattr(routes, "send_provider_email",
                            lambda **kw: (True, "ok"))
        monkeypatch.setattr(
            routes, "generate_provider_emails",
            lambda q: [
                {"provider": "MSL",      "subject": "S", "body": "B",
                 "to_emails": ["a@msl.com"]},
                {"provider": "VANGUARD", "subject": "S", "body": "B",
                 "to_emails": []},
            ],
        )

        ref = "26-06-TEST-005"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        events = _audit_events(ref)
        ev = next(e for e in events if e["event_type"] == "PROVIDER_EMAILS_AUTO_SENT")
        assert ev["detail"]["sent"] == 1
        assert ev["detail"]["skipped"] == 1

    def test_failed_count_correct(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)
        monkeypatch.setattr(routes, "send_provider_email",
                            lambda **kw: (False, "smtp error"))
        monkeypatch.setattr(
            routes, "generate_provider_emails",
            lambda q: [{"provider": "MSL", "subject": "S", "body": "B",
                        "to_emails": ["a@msl.com"]}],
        )

        ref = "26-06-TEST-006"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        events = _audit_events(ref)
        ev = next(e for e in events if e["event_type"] == "PROVIDER_EMAILS_AUTO_SENT")
        assert ev["detail"]["failed"] == 1
        assert ev["detail"]["sent"] == 0


class TestAutoSendNeverBlocksQuoteCreation:
    """An exception inside _auto_send_provider_emails must not propagate."""

    def test_exception_does_not_raise(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)

        def explode(q):
            raise RuntimeError("boom")

        monkeypatch.setattr(routes, "generate_provider_emails", explode)

        # Must not raise
        routes._auto_send_provider_emails("REF-ERR", {"mode": "lcl"}, "GT-PC")

    def test_auto_failed_event_logged_on_exception(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)

        def explode(q):
            raise ValueError("connection refused")

        monkeypatch.setattr(routes, "generate_provider_emails", explode)

        ref = "26-06-TEST-007"
        routes._auto_send_provider_emails(ref, {"mode": "lcl"}, "GT-PC")

        assert "PROVIDER_EMAILS_AUTO_FAILED" in _event_types(ref)


# ── Stress test: full POST /quote/new flow ────────────────────────────────────

class TestStressFullQuoteCreation:
    """
    Create a real quote via POST /quote/new and confirm the auto-send audit
    event is written. Tests that require SKIPPED explicitly patch credentials
    out — .env may contain real Graph creds in CI/local environments.
    """

    def test_quote_created_successfully(self, client):
        resp = client.post("/quote/new", data=_QUOTE_FORM,
                           follow_redirects=False)
        assert resp.status_code == 302

    def test_provider_emails_skipped_logged(self, client, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", False)
        client.post("/quote/new", data=_QUOTE_FORM, follow_redirects=False)
        assert "PROVIDER_EMAILS_SKIPPED" in _event_types()

    def test_quote_created_event_present(self, client):
        client.post("/quote/new", data=_QUOTE_FORM, follow_redirects=False)
        assert "QUOTE_CREATED" in _event_types()

    def test_skipped_reason_is_credentials(self, client, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", False)
        client.post("/quote/new", data=_QUOTE_FORM, follow_redirects=False)
        events = _audit_events()
        ev = next(e for e in events if e["event_type"] == "PROVIDER_EMAILS_SKIPPED")
        assert "graph credentials not configured" in ev["detail"]["reason"]

    def test_skipped_detail_includes_mode(self, client, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", False)
        client.post("/quote/new", data=_QUOTE_FORM, follow_redirects=False)
        events = _audit_events()
        ev = next(e for e in events if e["event_type"] == "PROVIDER_EMAILS_SKIPPED")
        assert ev["detail"]["mode"] == "lcl"

    def test_stress_with_credentials_sends_emails(self, client, monkeypatch):
        """With credentials patched in, auto-send fires and PROVIDER_EMAILS_AUTO_SENT logged."""
        import api.routes as routes
        monkeypatch.setattr(routes, "CREDENTIALS_ROTATED", True)

        sent = []
        monkeypatch.setattr(routes, "send_provider_email",
                            lambda **kw: sent.append(kw) or (True, "ok"))

        client.post("/quote/new", data=_QUOTE_FORM, follow_redirects=False)

        assert "PROVIDER_EMAILS_AUTO_SENT" in _event_types()
        ev = next(e for e in _audit_events()
                  if e["event_type"] == "PROVIDER_EMAILS_AUTO_SENT")
        assert "sent" in ev["detail"]
        assert "skipped" in ev["detail"]
