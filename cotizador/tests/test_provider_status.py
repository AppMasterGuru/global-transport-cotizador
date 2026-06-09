"""Tests for core/provider_status.py — status logic and chase email."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from core.provider_status import (
    OVERDUE_HOURS,
    build_chase_email,
    compute_provider_statuses,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
T_22H = NOW - timedelta(hours=22)   # contacted recently  → ORANGE
T_25H = NOW - timedelta(hours=25)   # contacted long ago  → RED
T_24H = NOW - timedelta(hours=OVERDUE_HOURS)  # exactly at threshold → RED


def _sent_entry(provider: str, ts: datetime) -> dict:
    return {
        "event_type":  "PROVIDER_EMAIL_SENT",
        "ts":          ts.isoformat(),
        "detail_json": json.dumps({"provider": provider, "to": "x@x.com"}),
    }


def _reply(provider: str, flete: float = 500.0) -> dict:
    return {
        "provider_name": provider,
        "flete_usd":     flete,
        "parse_status":  "parsed",
    }


# ── GREEN ─────────────────────────────────────────────────────────────────────

class TestGreenStatus:
    def test_green_when_reply_exists(self):
        audit = [_sent_entry("MSL", T_25H)]
        rows = compute_provider_statuses(["MSL"], audit, [_reply("MSL")], now=NOW)
        assert rows[0]["status"] == "green"

    def test_green_overrides_age(self):
        # Even contacted 100h ago — having a reply makes it green, not red
        audit = [_sent_entry("MSL", NOW - timedelta(hours=100))]
        rows = compute_provider_statuses(["MSL"], audit, [_reply("MSL")], now=NOW)
        assert rows[0]["status"] == "green"

    def test_green_row_contains_reply_rate(self):
        r = _reply("MSL", flete=480.0)
        rows = compute_provider_statuses(["MSL"], [_sent_entry("MSL", T_22H)], [r], now=NOW)
        assert rows[0]["reply"]["flete_usd"] == 480.0

    def test_green_contacted_at_populated(self):
        rows = compute_provider_statuses(["MSL"], [_sent_entry("MSL", T_22H)], [_reply("MSL")], now=NOW)
        assert rows[0]["contacted_at"] == T_22H


# ── ORANGE ────────────────────────────────────────────────────────────────────

class TestOrangeStatus:
    def test_orange_within_window(self):
        rows = compute_provider_statuses(["CRAFT"], [_sent_entry("CRAFT", T_22H)], [], now=NOW)
        assert rows[0]["status"] == "orange"

    def test_orange_1h_ago(self):
        rows = compute_provider_statuses(["CRAFT"], [_sent_entry("CRAFT", NOW - timedelta(hours=1))], [], now=NOW)
        assert rows[0]["status"] == "orange"

    def test_orange_just_under_threshold(self):
        rows = compute_provider_statuses(
            ["CRAFT"], [_sent_entry("CRAFT", NOW - timedelta(hours=OVERDUE_HOURS - 1))], [], now=NOW
        )
        assert rows[0]["status"] == "orange"

    def test_orange_reply_is_none(self):
        rows = compute_provider_statuses(["CRAFT"], [_sent_entry("CRAFT", T_22H)], [], now=NOW)
        assert rows[0]["reply"] is None


# ── RED ───────────────────────────────────────────────────────────────────────

class TestRedStatus:
    def test_red_overdue(self):
        rows = compute_provider_statuses(["SACO"], [_sent_entry("SACO", T_25H)], [], now=NOW)
        assert rows[0]["status"] == "red"

    def test_red_exactly_at_threshold(self):
        # Contacted exactly OVERDUE_HOURS ago → red (boundary belongs to red)
        rows = compute_provider_statuses(["SACO"], [_sent_entry("SACO", T_24H)], [], now=NOW)
        assert rows[0]["status"] == "red"

    def test_red_very_old(self):
        rows = compute_provider_statuses(
            ["SACO"], [_sent_entry("SACO", NOW - timedelta(days=5))], [], now=NOW
        )
        assert rows[0]["status"] == "red"

    def test_red_contacted_at_populated(self):
        rows = compute_provider_statuses(["SACO"], [_sent_entry("SACO", T_25H)], [], now=NOW)
        assert rows[0]["contacted_at"] == T_25H


# ── GREY ─────────────────────────────────────────────────────────────────────

class TestGreyStatus:
    def test_grey_not_contacted(self):
        rows = compute_provider_statuses(["VANGUARD"], [], [], now=NOW)
        assert rows[0]["status"] == "grey"

    def test_grey_contacted_at_is_none(self):
        rows = compute_provider_statuses(["VANGUARD"], [], [], now=NOW)
        assert rows[0]["contacted_at"] is None

    def test_grey_reply_is_none(self):
        rows = compute_provider_statuses(["VANGUARD"], [], [], now=NOW)
        assert rows[0]["reply"] is None

    def test_grey_ignores_other_providers_events(self):
        # Sent event for MSL must not make VANGUARD orange
        rows = compute_provider_statuses(
            ["VANGUARD"], [_sent_entry("MSL", T_22H)], [], now=NOW
        )
        assert rows[0]["status"] == "grey"


# ── MIXED STRESS TEST ─────────────────────────────────────────────────────────

class TestMixedProviderStates:
    """All four statuses in one quote — confirms color logic across a full LCL set."""

    def setup_method(self):
        providers = ["MSL", "CRAFT", "SACO", "VANGUARD", "ECU WORLDWIDE"]
        audit = [
            _sent_entry("MSL",   T_25H),   # has reply → GREEN
            _sent_entry("CRAFT", T_22H),   # no reply, < 24h → ORANGE
            _sent_entry("SACO",  T_25H),   # no reply, >= 24h → RED
            # VANGUARD and ECU WORLDWIDE never contacted → GREY
        ]
        replies = [_reply("MSL", flete=490.0)]
        rows = compute_provider_statuses(providers, audit, replies, now=NOW)
        self.by_name = {r["provider"]: r for r in rows}
        self.rows = rows

    def test_five_rows_returned(self):
        assert len(self.rows) == 5

    def test_order_matches_input(self):
        assert [r["provider"] for r in self.rows] == [
            "MSL", "CRAFT", "SACO", "VANGUARD", "ECU WORLDWIDE"
        ]

    def test_msl_green(self):
        assert self.by_name["MSL"]["status"] == "green"

    def test_craft_orange(self):
        assert self.by_name["CRAFT"]["status"] == "orange"

    def test_saco_red(self):
        assert self.by_name["SACO"]["status"] == "red"

    def test_vanguard_grey(self):
        assert self.by_name["VANGUARD"]["status"] == "grey"

    def test_ecu_worldwide_grey(self):
        assert self.by_name["ECU WORLDWIDE"]["status"] == "grey"

    def test_msl_reply_rate(self):
        assert self.by_name["MSL"]["reply"]["flete_usd"] == 490.0

    def test_grey_providers_have_no_contacted_at(self):
        for name in ("VANGUARD", "ECU WORLDWIDE"):
            assert self.by_name[name]["contacted_at"] is None

    def test_only_msl_has_reply(self):
        for name in ("CRAFT", "SACO", "VANGUARD", "ECU WORLDWIDE"):
            assert self.by_name[name]["reply"] is None


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_providers_returns_empty(self):
        assert compute_provider_statuses([], [], [], now=NOW) == []

    def test_non_email_sent_events_ignored(self):
        audit = [
            {"event_type": "QUOTE_CREATED",  "ts": T_22H.isoformat(),
             "detail_json": json.dumps({"provider": "MSL"})},
            {"event_type": "MARGIN_OVERRIDE", "ts": T_22H.isoformat(),
             "detail_json": json.dumps({"provider": "MSL"})},
        ]
        rows = compute_provider_statuses(["MSL"], audit, [], now=NOW)
        assert rows[0]["status"] == "grey"

    def test_multiple_sent_events_uses_earliest(self):
        early = NOW - timedelta(hours=26)
        late  = NOW - timedelta(hours=10)
        audit = [_sent_entry("MSL", late), _sent_entry("MSL", early)]
        rows = compute_provider_statuses(["MSL"], audit, [], now=NOW)
        assert rows[0]["contacted_at"] == early
        assert rows[0]["status"] == "red"   # 26h > threshold

    def test_multiple_replies_uses_first(self):
        replies = [_reply("MSL", 400.0), _reply("MSL", 350.0)]
        rows = compute_provider_statuses(["MSL"], [], replies, now=NOW)
        assert rows[0]["reply"]["flete_usd"] == 400.0

    def test_detail_json_as_dict_object(self):
        # detail stored already parsed (dict) should still work
        audit = [{
            "event_type":  "PROVIDER_EMAIL_SENT",
            "ts":          T_22H.isoformat(),
            "detail_json": {"provider": "MSL", "to": "x@x.com"},
        }]
        rows = compute_provider_statuses(["MSL"], audit, [], now=NOW)
        assert rows[0]["status"] == "orange"

    def test_missing_ts_skipped(self):
        audit = [{"event_type": "PROVIDER_EMAIL_SENT", "ts": None,
                  "detail_json": json.dumps({"provider": "MSL"})}]
        rows = compute_provider_statuses(["MSL"], audit, [], now=NOW)
        assert rows[0]["status"] == "grey"

    def test_malformed_detail_json_skipped(self):
        audit = [{"event_type": "PROVIDER_EMAIL_SENT", "ts": T_22H.isoformat(),
                  "detail_json": "not-valid-json{{"}]
        rows = compute_provider_statuses(["MSL"], audit, [], now=NOW)
        assert rows[0]["status"] == "grey"

    def test_naive_ts_treated_as_utc(self):
        naive_ts = datetime(2026, 6, 9, 10, 0, 0)   # 2h before NOW, no tzinfo
        audit = [{"event_type": "PROVIDER_EMAIL_SENT", "ts": naive_ts.isoformat(),
                  "detail_json": json.dumps({"provider": "MSL"})}]
        rows = compute_provider_statuses(["MSL"], audit, [], now=NOW)
        assert rows[0]["status"] == "orange"

    def test_provider_in_replies_but_never_sent_is_green(self):
        # Reply arrived even though we have no PROVIDER_EMAIL_SENT audit entry
        rows = compute_provider_statuses(["MSL"], [], [_reply("MSL")], now=NOW)
        assert rows[0]["status"] == "green"


# ── Chase email ───────────────────────────────────────────────────────────────

class TestBuildChaseEmail:
    def setup_method(self):
        self.quote = {
            "reference_code": "26-06-001",
            "origin":         "Lima",
            "destination":    "Hamburgo",
        }
        self.result = build_chase_email("CRAFT", self.quote)

    def test_provider_key_present(self):
        assert self.result["provider"] == "CRAFT"

    def test_subject_contains_reference(self):
        assert "26-06-001" in self.result["subject"]

    def test_subject_contains_recordatorio(self):
        assert "Recordatorio" in self.result["subject"]

    def test_body_contains_provider_name(self):
        assert "CRAFT" in self.result["body"]

    def test_body_contains_reference(self):
        assert "26-06-001" in self.result["body"]

    def test_missing_quote_fields_dont_crash(self):
        result = build_chase_email("MSL", {})
        assert "subject" in result
        assert "body" in result
