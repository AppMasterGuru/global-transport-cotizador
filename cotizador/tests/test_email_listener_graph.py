"""
Tests for the Graph API wiring in fetch_pending_emails() / _graph_fetch_emails().

Covers:
  - Stub fallback when credentials absent
  - Successful fetch returns correct dict structure
  - HTML body stripped to plain text
  - mark-as-read PATCH called once per message
  - TOKEN_FAILED falls back to stubs gracefully
  - FETCH_ERROR (HTTP 500) falls back to stubs gracefully
  - LISTENER_SINCE filter appended to $filter when set

All tests mock requests.get / requests.patch — no real network calls.
DB isolated via temp file.
"""

from __future__ import annotations

import os
import tempfile
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest

# ── DB isolation ──────────────────────────────────────────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name

from core.db import init_db, get_connection  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS credit_registry;
            DROP TABLE IF EXISTS provider_replies;
        """)
    init_db()
    yield


# ── Graph message factory ─────────────────────────────────────────────────────

def _make_graph_msg(
    msg_id: str = "AAMkABCD",
    subject: str = "RE: 26-06-001 tarifa LCL",
    from_addr: str = "ventas@mslcorporate.com",
    body_content: str = "Flete USD 480. Tránsito 28 días.",
    content_type: str = "text",
    received_at: str = "2026-06-09T10:45:00Z",
) -> dict:
    return {
        "id": msg_id,
        "subject": subject,
        "from": {"emailAddress": {"address": from_addr, "name": "Luis Paredes"}},
        "body": {"contentType": content_type, "content": body_content},
        "receivedDateTime": received_at,
    }


def _mock_get(messages: list[dict], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"value": messages}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — Stub fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestStubFallback:

    def test_stub_returned_when_not_configured(self):
        with patch("core.email_listener._LISTENER_CONFIGURED", False):
            from core.email_listener import fetch_pending_emails, _SAMPLE_EMAILS
            assert fetch_pending_emails() is _SAMPLE_EMAILS

    def test_stub_has_3_emails(self):
        with patch("core.email_listener._LISTENER_CONFIGURED", False):
            from core.email_listener import fetch_pending_emails
            assert len(fetch_pending_emails()) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — Successful Graph fetch
# ═══════════════════════════════════════════════════════════════════════════════

class TestGraphFetch:

    def _fetch(self, messages: list[dict]):
        from core.email_listener import _graph_fetch_emails
        mock_resp = _mock_get(messages)
        with patch("core.drive.get_graph_token", return_value="fake-token"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            mock_req.patch.return_value = MagicMock()
            results = _graph_fetch_emails()
        return results, mock_req

    def test_returns_list(self):
        results, _ = self._fetch([_make_graph_msg()])
        assert isinstance(results, list)

    def test_correct_count(self):
        msgs = [_make_graph_msg(msg_id=f"msg-{i}") for i in range(3)]
        results, _ = self._fetch(msgs)
        assert len(results) == 3

    def test_has_all_required_keys(self):
        results, _ = self._fetch([_make_graph_msg()])
        for key in ("id", "from", "subject", "received_at", "body"):
            assert key in results[0], f"Missing key: {key!r}"

    def test_from_address_extracted(self):
        results, _ = self._fetch([_make_graph_msg(from_addr="tarifas@craft.com.pe")])
        assert results[0]["from"] == "tarifas@craft.com.pe"

    def test_subject_extracted(self):
        results, _ = self._fetch([_make_graph_msg(subject="RE: 26-06-001 tarifa")])
        assert results[0]["subject"] == "RE: 26-06-001 tarifa"

    def test_received_at_extracted(self):
        results, _ = self._fetch([_make_graph_msg(received_at="2026-06-09T10:45:00Z")])
        assert results[0]["received_at"] == "2026-06-09T10:45:00Z"

    def test_text_body_passed_through(self):
        results, _ = self._fetch([_make_graph_msg(body_content="Flete USD 480.", content_type="text")])
        assert "480" in results[0]["body"]

    def test_empty_inbox_returns_empty_list(self):
        results, _ = self._fetch([])
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — HTML stripping
# ═══════════════════════════════════════════════════════════════════════════════

class TestHtmlStripping:

    def test_tags_removed(self):
        from core.email_listener import _strip_html
        result = _strip_html("<p>Flete <b>USD 480</b>.</p>")
        assert "<" not in result
        assert "480" in result

    def test_script_block_removed(self):
        from core.email_listener import _strip_html
        result = _strip_html("<script>alert('xss')</script><p>Rate: 500</p>")
        assert "alert" not in result
        assert "500" in result

    def test_style_block_removed(self):
        from core.email_listener import _strip_html
        result = _strip_html("<style>body{color:red}</style><p>Flete 480</p>")
        assert "color" not in result
        assert "480" in result

    def test_entities_decoded(self):
        from core.email_listener import _strip_html
        result = _strip_html("<p>Rate: USD&nbsp;480 &amp; surcharge</p>")
        assert "&amp;" not in result
        assert "surcharge" in result

    def test_html_content_type_stripped_by_graph_fetch(self):
        from core.email_listener import _graph_fetch_emails
        html = "<html><body><p>Flete <strong>USD 480</strong>.</p></body></html>"
        msg = _make_graph_msg(body_content=html, content_type="HTML")
        mock_resp = _mock_get([msg])
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            mock_req.patch.return_value = MagicMock()
            results = _graph_fetch_emails()
        assert "<" not in results[0]["body"]
        assert "480" in results[0]["body"]


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — mark-as-read
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkAsRead:

    def test_patch_called_once_per_message(self):
        from core.email_listener import _graph_fetch_emails
        msgs = [_make_graph_msg(msg_id="msg-001"), _make_graph_msg(msg_id="msg-002")]
        mock_resp = _mock_get(msgs)
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            mock_req.patch.return_value = MagicMock()
            _graph_fetch_emails()
        assert mock_req.patch.call_count == 2

    def test_patch_payload_is_is_read_true(self):
        from core.email_listener import _graph_fetch_emails
        mock_resp = _mock_get([_make_graph_msg(msg_id="msg-001")])
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            mock_req.patch.return_value = MagicMock()
            _graph_fetch_emails()
        _, kwargs = mock_req.patch.call_args
        assert kwargs["json"] == {"isRead": True}

    def test_patch_failure_does_not_drop_message(self):
        from core.email_listener import _graph_fetch_emails
        mock_resp = _mock_get([_make_graph_msg(msg_id="msg-001")])
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            mock_req.patch.side_effect = Exception("network error")
            results = _graph_fetch_emails()
        assert len(results) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — Error handling / fallbacks
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorFallbacks:

    def test_empty_token_falls_back_to_stubs(self):
        from core.email_listener import _graph_fetch_emails, _SAMPLE_EMAILS
        with patch("core.drive.get_graph_token", return_value=""):
            result = _graph_fetch_emails()
        assert result is _SAMPLE_EMAILS

    def test_graph_500_falls_back_to_stubs(self):
        from core.email_listener import _graph_fetch_emails, _SAMPLE_EMAILS
        mock_resp = _mock_get([], status_code=500)
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            result = _graph_fetch_emails()
        assert result is _SAMPLE_EMAILS

    def test_network_exception_falls_back_to_stubs(self):
        from core.email_listener import _graph_fetch_emails, _SAMPLE_EMAILS
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.side_effect = Exception("timeout")
            result = _graph_fetch_emails()
        assert result is _SAMPLE_EMAILS


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — LISTENER_SINCE filter
# ═══════════════════════════════════════════════════════════════════════════════

class TestListenerSince:

    def test_since_filter_included_when_set(self):
        from core.email_listener import _graph_fetch_emails
        mock_resp = _mock_get([])
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._LISTENER_SINCE", "2026-05-21"), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            _graph_fetch_emails()
        _, kwargs = mock_req.get.call_args
        odata = kwargs["params"]["$filter"]
        assert "receivedDateTime ge 2026-05-21T00:00:00Z" in odata
        assert "isRead eq false" in odata

    def test_no_since_uses_only_is_read_filter(self):
        from core.email_listener import _graph_fetch_emails
        mock_resp = _mock_get([])
        with patch("core.drive.get_graph_token", return_value="tok"), \
             patch("core.email_listener._LISTENER_SINCE", ""), \
             patch("core.email_listener._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            _graph_fetch_emails()
        _, kwargs = mock_req.get.call_args
        odata = kwargs["params"]["$filter"]
        assert odata == "isRead eq false"
