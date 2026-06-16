"""
Regression tests for from-address routing (2026-06-16 verification finding 4).

Two independent problems:
  (a) config/signatures.py's GT-LOG entry had Daniela's name/title but
      Cielo's phone + email (wca.sales@gt.com.pe instead of
      lognet.sales@gt.com.pe) — looked like the GT-WCA block was
      copy-pasted and only name/title were edited.
  (b) core/email_sender.py's resolve_from_address() had no "gt-log" key
      (only a dead "gt-loc" alias matching no real staff code), and any
      unrecognized actor silently fell back to Abel's pricing@gt.com.pe —
      so a typo'd or unknown sender identity would silently send AS Abel.

resolve_from_address() must key off the real staff codes and must never
silently impersonate Abel for an unrecognized actor.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("DB_PATH", _tmp_db.name)

from core.email_sender import resolve_from_address, send_quote_email  # noqa: E402
from core.db import init_db, get_audit_trail  # noqa: E402
from config.signatures import get_signature  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    yield


class TestResolveFromAddressByStaffCode:
    @pytest.mark.parametrize(
        "staff_code,expected",
        [
            ("GT-PC", "pricing@gt.com.pe"),
            ("GT-WCA", "wca.sales@gt.com.pe"),
            ("GT-LOG", "lognet.sales@gt.com.pe"),
            ("RENATO", "ralvarez@gt.com.pe"),
            ("JP", "jparrue@gt.com.pe"),
        ],
    )
    def test_resolves_correct_address(self, staff_code, expected):
        assert resolve_from_address(staff_code) == expected

    def test_resolves_case_insensitively(self):
        assert resolve_from_address("gt-log") == "lognet.sales@gt.com.pe"


class TestResolveFromAddressRefusesToImpersonateAbel:
    def test_unknown_actor_raises_instead_of_defaulting_to_abel(self):
        with pytest.raises(ValueError):
            resolve_from_address("not-a-real-person")

    def test_blank_actor_raises_instead_of_defaulting_to_abel(self):
        with pytest.raises(ValueError):
            resolve_from_address("")


class TestSendQuoteEmailUsesStaffCodeNotFreeText:
    """The Send form's actor field is free text (whoever clicks send types
    their own name). The FROM address must be driven by the quote's real
    staff_code, not by whatever the human typed."""

    def test_from_staff_code_overrides_free_text_actor(self):
        ok, _ = send_quote_email(
            ref_code="26-06-ADDR-001",
            quote_id=1,
            customer_email="cliente@example.com",
            customer_name="Cliente SA",
            actor="JP",  # whoever clicked "send" — not Daniela
            from_staff_code="GT-LOG",  # the quote's actual owner
        )
        assert ok is True
        trail = get_audit_trail("26-06-ADDR-001")
        sent_event = next(e for e in trail if e["event_type"] == "QUOTE_SENT")
        assert sent_event["detail_json"]
        assert "lognet.sales@gt.com.pe" in sent_event["detail_json"]


class TestSignaturesFile:
    def test_gt_log_email_is_lognet_not_wca(self):
        assert get_signature("GT-LOG")["email"] == "lognet.sales@gt.com.pe"
