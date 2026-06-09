"""
Tests for the provider-reply parsing pipeline.

Covers:
  - Provider reply detection by subject (reference code) and sender domain
  - Provider identification from sender email
  - Rate extraction from 4 fixture emails (MSL, Craft, LAN, garbled)
  - Quote update logic (costeo_json patched with lowest flete)
  - Audit trail events: PROVIDER_REPLY_RECEIVED, PROVIDER_RATE_PARSED,
    PARSE_FAILED, RATES_READY
  - State transition (RATES_READY logged when all expected providers replied)
  - DB helpers: store_provider_reply, get_provider_replies, update_quote_flete
  - process_inbound_emails routing (provider vs client)

All tests run in stub mode (no ANTHROPIC_API_KEY required).
DB is fully isolated per test via a temp file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ── DB isolation — must happen before any core import ─────────────────────────
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name

from core.db import (  # noqa: E402
    get_audit_trail,
    get_connection,
    get_provider_replies,
    init_db,
    store_provider_reply,
    update_quote_flete,
)
from core.provider_reply_parser import (  # noqa: E402
    check_rates_ready,
    extract_reference_from_subject,
    identify_provider,
    is_provider_reply,
    parse_provider_reply,
    process_provider_reply,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "provider_replies"


# ── DB fixture ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db():
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS provider_replies;
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS credit_registry;
            DROP TABLE IF EXISTS ref_counters;
        """)
    init_db()
    yield


# ── Helper: create a minimal quote row ───────────────────────────────────────

def _create_quote(ref: str, mode: str = "lcl", flete: float = 0.0) -> None:
    costeo = {
        "flete_internacional_usd": flete,
        "visto_bueno_usd": 0.0,
        "handling_aereo_usd": 0.0,
        "customs_agent_usd": 0.0,
        "transport_usd": 0.0,
        "total_usd": flete,
    }
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO quotes
               (reference_code, client_name, incoterm, mode, origin, destination,
                weight_kg, volume_cbm, costeo_json, venta_json, margin_pct,
                exchange_rate, status, staff_code, language)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref, "Test Client", "FOB", mode, "Lima", "Hamburgo",
                500.0, 2.0,
                json.dumps(costeo), json.dumps({"total_usd": flete * 1.2}),
                0.20, 3.75, "PENDING", "GT-PC", "es",
            ),
        )
        conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — Detection: is_provider_reply()
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsProviderReply:

    def test_reference_in_subject_detected(self):
        email = {"subject": "RE: 26-06-001 — tarifa LCL Hamburgo", "from": "nobody@unknown.com"}
        assert is_provider_reply(email) is True

    def test_re_prefix_with_reference(self):
        email = {"subject": "RV: 26-05-003 cotización", "from": "x@x.com"}
        assert is_provider_reply(email) is True

    def test_fwd_prefix_with_reference(self):
        email = {"subject": "FWD: 26-06-007 rates", "from": "x@x.com"}
        assert is_provider_reply(email) is True

    def test_known_provider_domain_no_ref(self):
        email = {"subject": "Hola, aquí la tarifa", "from": "ventas@mslcorporate.com"}
        assert is_provider_reply(email) is True

    def test_latam_domain_detected(self):
        email = {"subject": "Rate quote", "from": "rates@latamairlines.com"}
        assert is_provider_reply(email) is True

    def test_plain_client_email_not_detected(self):
        email = {"subject": "Solicitud de cotización — carga aérea", "from": "client@company.com"}
        assert is_provider_reply(email) is False

    def test_empty_email_not_detected(self):
        assert is_provider_reply({}) is False

    def test_partial_reference_not_matched(self):
        # '26-06' without the third group is NOT a valid reference code
        email = {"subject": "RE: 26-06 consulta", "from": "x@x.com"}
        assert is_provider_reply(email) is False


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — Reference extraction
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractReference:

    def test_simple_subject(self):
        assert extract_reference_from_subject("RE: 26-06-001 tarifa") == "26-06-001"

    def test_embedded_in_prose(self):
        assert extract_reference_from_subject("Cotización ref 26-05-003 adjunta") == "26-05-003"

    def test_no_reference_returns_none(self):
        assert extract_reference_from_subject("Hola, aquí los datos") is None

    def test_empty_subject_returns_none(self):
        assert extract_reference_from_subject("") is None

    def test_none_subject_returns_none(self):
        assert extract_reference_from_subject(None) is None  # type: ignore[arg-type]

    def test_first_reference_returned_when_multiple(self):
        result = extract_reference_from_subject("RE: 26-06-001 y también 26-06-002")
        assert result == "26-06-001"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — Provider identification
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdentifyProvider:

    def test_msl_domain(self):
        assert identify_provider("ventas@mslcorporate.com") == "MSL"

    def test_craft_domain(self):
        assert identify_provider("tarifas@craft.com.pe") == "CRAFT"

    def test_saco_domain(self):
        assert identify_provider("info@saco.com.pe") == "SACO"

    def test_latam_domain(self):
        assert identify_provider("rates@latamairlines.com") == "LAN Airlines"

    def test_lan_domain(self):
        assert identify_provider("cargo@lan.com") == "LAN Airlines"

    def test_american_airlines_domain(self):
        assert identify_provider("rates@aa.com") == "American Airlines"

    def test_united_domain(self):
        assert identify_provider("cargo@united.com") == "United Airlines"

    def test_unknown_sender_fallback(self):
        result = identify_provider("someone@totally-unknown.com")
        assert result == "Unknown Provider"

    def test_empty_sender_fallback(self):
        assert identify_provider("") == "Unknown Provider"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — Rate extraction from fixture emails (stub mode)
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseProviderReply:

    def _load(self, filename: str) -> str:
        return (_FIXTURES / filename).read_text(encoding="utf-8")

    def test_msl_reply_flete_extracted(self):
        body = self._load("reply_msl.txt")
        result = parse_provider_reply(body, "MSL")
        assert result["parse_status"] == "parsed"
        assert result["flete_usd"] == 480.0

    def test_msl_reply_vb_extracted(self):
        body = self._load("reply_msl.txt")
        result = parse_provider_reply(body, "MSL")
        assert result["visto_bueno_usd"] == 55.0

    def test_msl_reply_transit_extracted(self):
        body = self._load("reply_msl.txt")
        result = parse_provider_reply(body, "MSL")
        assert result["transit_days"] == 28

    def test_msl_reply_validity_extracted(self):
        body = self._load("reply_msl.txt")
        result = parse_provider_reply(body, "MSL")
        assert result["validity_days"] == 15

    def test_craft_reply_flete_extracted(self):
        body = self._load("reply_craft.txt")
        result = parse_provider_reply(body, "CRAFT")
        assert result["parse_status"] == "parsed"
        assert result["flete_usd"] == 510.0

    def test_craft_reply_transit_extracted(self):
        body = self._load("reply_craft.txt")
        result = parse_provider_reply(body, "CRAFT")
        assert result["transit_days"] == 30

    def test_lan_reply_parsed(self):
        body = self._load("reply_lan.txt")
        result = parse_provider_reply(body, "LAN Airlines")
        assert result["parse_status"] == "parsed"
        assert result["flete_usd"] is not None

    def test_lan_reply_vb_extracted(self):
        body = self._load("reply_lan.txt")
        result = parse_provider_reply(body, "LAN Airlines")
        assert result["visto_bueno_usd"] == 30.0

    def test_lan_reply_transit_extracted(self):
        body = self._load("reply_lan.txt")
        result = parse_provider_reply(body, "LAN Airlines")
        assert result["transit_days"] == 2

    def test_garbled_reply_parse_failed(self):
        body = self._load("reply_garbled.txt")
        result = parse_provider_reply(body, "SACO")
        assert result["parse_status"] == "parse_failed"
        assert result["needs_manual_review"] is True
        assert result["flete_usd"] is None

    def test_empty_body_parse_failed(self):
        result = parse_provider_reply("", "Unknown")
        assert result["parse_status"] == "parse_failed"
        assert result["needs_manual_review"] is True

    def test_result_has_all_required_keys(self):
        body = self._load("reply_msl.txt")
        result = parse_provider_reply(body)
        for key in ("flete_usd", "visto_bueno_usd", "transit_days", "validity_days",
                    "currency", "surcharges_json", "parse_status", "needs_manual_review"):
            assert key in result, f"Missing key: {key!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — DB helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestDbHelpers:

    def test_store_provider_reply_returns_id(self):
        row_id = store_provider_reply({
            "quote_reference": "26-06-001",
            "provider_name":   "MSL",
            "flete_usd":       480.0,
            "parse_status":    "parsed",
        })
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_get_provider_replies_returns_stored_row(self):
        store_provider_reply({
            "quote_reference": "26-06-001",
            "provider_name":   "MSL",
            "flete_usd":       480.0,
            "parse_status":    "parsed",
        })
        rows = get_provider_replies("26-06-001")
        assert len(rows) == 1
        assert rows[0]["provider_name"] == "MSL"
        assert rows[0]["flete_usd"] == 480.0

    def test_get_provider_replies_sorted_cheapest_first(self):
        for name, flete in [("CRAFT", 510.0), ("MSL", 480.0), ("SACO", 495.0)]:
            store_provider_reply({
                "quote_reference": "26-06-001",
                "provider_name":   name,
                "flete_usd":       flete,
                "parse_status":    "parsed",
            })
        rows = get_provider_replies("26-06-001")
        assert rows[0]["provider_name"] == "MSL"
        assert rows[1]["provider_name"] == "SACO"
        assert rows[2]["provider_name"] == "CRAFT"

    def test_get_provider_replies_empty_for_unknown_ref(self):
        assert get_provider_replies("99-99-999") == []

    def test_update_quote_flete_patches_costeo(self):
        _create_quote("26-06-001", flete=0.0)
        result = update_quote_flete("26-06-001", 480.0, 55.0)
        assert result is True
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code='26-06-001'"
            ).fetchone()
        costeo = json.loads(row["costeo_json"])
        assert costeo["flete_internacional_usd"] == 480.0
        assert costeo["visto_bueno_usd"] == 55.0

    def test_update_quote_flete_recalculates_total(self):
        _create_quote("26-06-001", flete=0.0)
        update_quote_flete("26-06-001", 300.0, None)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code='26-06-001'"
            ).fetchone()
        costeo = json.loads(row["costeo_json"])
        assert costeo["total_usd"] == 300.0

    def test_update_quote_flete_unknown_ref_returns_false(self):
        assert update_quote_flete("99-99-999", 100.0, None) is False


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — Full process_provider_reply() pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessProviderReply:

    def _load(self, filename: str) -> str:
        return (_FIXTURES / filename).read_text(encoding="utf-8")

    def _msl_email(self) -> dict:
        body = self._load("reply_msl.txt")
        return {
            "id":          "pr-001",
            "from":        "ventas@mslcorporate.com",
            "subject":     "RE: 26-06-001 — tarifa LCL Hamburgo",
            "received_at": "2026-06-09T10:45:00Z",
            "body":        body,
        }

    def test_returns_dict_with_email_type(self):
        _create_quote("26-06-001")
        result = process_provider_reply(self._msl_email())
        assert result["_email_type"] == "provider_reply"

    def test_returns_quote_reference(self):
        _create_quote("26-06-001")
        result = process_provider_reply(self._msl_email())
        assert result["quote_reference"] == "26-06-001"

    def test_returns_provider_name(self):
        _create_quote("26-06-001")
        result = process_provider_reply(self._msl_email())
        assert result["provider_name"] == "MSL"

    def test_returns_reply_db_id(self):
        _create_quote("26-06-001")
        result = process_provider_reply(self._msl_email())
        assert isinstance(result.get("_reply_db_id"), int)

    def test_reply_stored_in_db(self):
        _create_quote("26-06-001")
        process_provider_reply(self._msl_email())
        rows = get_provider_replies("26-06-001")
        assert len(rows) == 1
        assert rows[0]["provider_name"] == "MSL"
        assert rows[0]["flete_usd"] == 480.0

    def test_audit_provider_reply_received(self):
        _create_quote("26-06-001")
        process_provider_reply(self._msl_email())
        trail = get_audit_trail("26-06-001")
        event_types = [e["event_type"] for e in trail]
        assert "PROVIDER_REPLY_RECEIVED" in event_types

    def test_audit_provider_rate_parsed(self):
        _create_quote("26-06-001")
        process_provider_reply(self._msl_email())
        trail = get_audit_trail("26-06-001")
        event_types = [e["event_type"] for e in trail]
        assert "PROVIDER_RATE_PARSED" in event_types

    def test_quote_flete_updated_after_parse(self):
        _create_quote("26-06-001", flete=0.0)
        process_provider_reply(self._msl_email())
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code='26-06-001'"
            ).fetchone()
        costeo = json.loads(row["costeo_json"])
        assert costeo["flete_internacional_usd"] == 480.0

    def test_lower_flete_overwrites_higher(self):
        _create_quote("26-06-001", flete=600.0)
        process_provider_reply(self._msl_email())
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code='26-06-001'"
            ).fetchone()
        costeo = json.loads(row["costeo_json"])
        assert costeo["flete_internacional_usd"] == 480.0

    def test_higher_flete_does_not_overwrite_lower(self):
        _create_quote("26-06-001", flete=300.0)
        process_provider_reply(self._msl_email())  # MSL = 480 > 300, should not overwrite
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code='26-06-001'"
            ).fetchone()
        costeo = json.loads(row["costeo_json"])
        assert costeo["flete_internacional_usd"] == 300.0

    def test_garbled_reply_logged_parse_failed(self):
        _create_quote("26-06-001")
        garbled_email = {
            "id":      "pr-garbled",
            "from":    "info@saco.com.pe",
            "subject": "RE: 26-06-001 tarifa",
            "body":    self._load("reply_garbled.txt"),
        }
        result = process_provider_reply(garbled_email)
        assert result["parse_status"] == "parse_failed"
        assert result.get("_needs_manual_review") is True
        trail = get_audit_trail("26-06-001")
        event_types = [e["event_type"] for e in trail]
        assert "PARSE_FAILED" in event_types

    def test_no_reference_code_logs_parse_failed(self):
        no_ref_email = {
            "id":      "pr-noref",
            "from":    "ventas@mslcorporate.com",
            "subject": "Aquí va la cotización",
            "body":    "Flete USD 480. Tránsito 28 días.",
        }
        result = process_provider_reply(no_ref_email)
        assert result["parse_status"] == "parse_failed"
        assert result.get("_needs_manual_review") is True
        assert result["quote_reference"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 7 — check_rates_ready() and RATES_READY event
# ═══════════════════════════════════════════════════════════════════════════════

class TestRatesReady:

    def test_not_ready_with_no_replies(self):
        _create_quote("26-06-001", mode="fcl")
        assert check_rates_ready("26-06-001") is False

    def test_ready_when_fcl_one_reply(self):
        _create_quote("26-06-001", mode="fcl")
        store_provider_reply({
            "quote_reference": "26-06-001",
            "provider_name":   "Naviera",
            "flete_usd":       1800.0,
            "parse_status":    "parsed",
        })
        assert check_rates_ready("26-06-001") is True

    def test_not_ready_for_lcl_with_only_2_replies(self):
        _create_quote("26-06-001", mode="lcl")
        for name, flete in [("MSL", 480.0), ("CRAFT", 510.0)]:
            store_provider_reply({
                "quote_reference": "26-06-001",
                "provider_name":   name,
                "flete_usd":       flete,
                "parse_status":    "parsed",
            })
        assert check_rates_ready("26-06-001") is False

    def test_ready_for_lcl_with_5_replies(self):
        _create_quote("26-06-001", mode="lcl")
        for name, flete in [
            ("MSL", 480.0), ("CRAFT", 510.0), ("SACO", 495.0),
            ("VANGUARD", 520.0), ("ECU WORLDWIDE", 500.0),
        ]:
            store_provider_reply({
                "quote_reference": "26-06-001",
                "provider_name":   name,
                "flete_usd":       flete,
                "parse_status":    "parsed",
            })
        assert check_rates_ready("26-06-001") is True

    def test_parse_failed_replies_do_not_count_toward_ready(self):
        _create_quote("26-06-001", mode="fcl")
        store_provider_reply({
            "quote_reference": "26-06-001",
            "provider_name":   "Naviera",
            "flete_usd":       None,
            "parse_status":    "parse_failed",
        })
        assert check_rates_ready("26-06-001") is False

    def test_rates_ready_audit_event_fired(self):
        """process_provider_reply fires RATES_READY when all expected providers replied."""
        _create_quote("26-06-001", mode="fcl")
        naviera_email = {
            "id":      "pr-fcl-001",
            "from":    "rates@naviera.com",
            "subject": "RE: 26-06-001 FCL rate",
            "body":    "Flete USD 1800. Tránsito 25 días. Vigencia 15 días.",
        }
        result = process_provider_reply(naviera_email)
        assert result.get("_rates_ready") is True
        trail = get_audit_trail("26-06-001")
        event_types = [e["event_type"] for e in trail]
        assert "RATES_READY" in event_types

    def test_rates_ready_not_fired_prematurely_for_aereo(self):
        """RATES_READY must NOT fire after only 1 of 3 aereo providers replied."""
        _create_quote("26-06-002", mode="aereo")
        lan_email = {
            "id":      "pr-aereo-001",
            "from":    "rates@latamairlines.com",
            "subject": "RE: 26-06-002 tarifa aérea LIM-LAX",
            "body":    (_FIXTURES / "reply_lan.txt").read_text(encoding="utf-8"),
        }
        result = process_provider_reply(lan_email)
        assert result.get("_rates_ready") is not True
        trail = get_audit_trail("26-06-002")
        event_types = [e["event_type"] for e in trail]
        assert "RATES_READY" not in event_types


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 8 — process_inbound_emails() routing
# ═══════════════════════════════════════════════════════════════════════════════

class TestInboundEmailRouting:

    def test_provider_reply_routed_correctly(self):
        """An email with a reference code in subject is routed as provider_reply."""
        import unittest.mock as mock  # noqa: PLC0415
        from core.email_listener import process_inbound_emails  # noqa: PLC0415

        _create_quote("26-06-001")

        fake_emails = [
            {
                "id":          "pr-routing-001",
                "from":        "ventas@mslcorporate.com",
                "subject":     "RE: 26-06-001 — tarifa LCL",
                "body":        "Flete USD 480. Visto bueno USD 55. Tránsito 28 días. Vigencia 15 días.",
                "received_at": "2026-06-09T10:00:00Z",
            }
        ]

        with mock.patch(
            "core.email_listener.fetch_pending_emails", return_value=fake_emails
        ):
            results = process_inbound_emails(auto_ack=False)

        assert len(results) == 1
        assert results[0]["_email_type"] == "provider_reply"
        assert results[0]["provider_name"] == "MSL"

    def test_client_request_still_routed_correctly(self):
        """A plain client email (no reference, unknown sender) goes to client_request path."""
        import unittest.mock as mock  # noqa: PLC0415
        from core.email_listener import process_inbound_emails  # noqa: PLC0415

        fake_emails = [
            {
                "id":          "cl-routing-001",
                "from":        "client@peruexports.com",
                "subject":     "Solicitud de cotización LCL Lima Hamburg",
                "body":        "Necesitamos cotización para 8 CBM de quinua orgánica desde Lima a Hamburgo. FOB.",
                "received_at": "2026-06-09T09:00:00Z",
            }
        ]

        with mock.patch(
            "core.email_listener.fetch_pending_emails", return_value=fake_emails
        ):
            results = process_inbound_emails(auto_ack=False)

        assert len(results) == 1
        assert results[0]["_email_type"] == "client_request"

    def test_mixed_inbox_routed_separately(self):
        """Two emails: one provider reply, one client request — routed independently."""
        import unittest.mock as mock  # noqa: PLC0415
        from core.email_listener import process_inbound_emails  # noqa: PLC0415

        _create_quote("26-06-001")

        fake_emails = [
            {
                "id": "pr-mix-001", "from": "ventas@mslcorporate.com",
                "subject": "RE: 26-06-001 tarifa",
                "body":    "Flete USD 480. Tránsito 28 días.",
                "received_at": "2026-06-09T10:00:00Z",
            },
            {
                "id": "cl-mix-001", "from": "buyer@company.com",
                "subject": "Cotización urgente aire Frankfurt Lima",
                "body":    "Necesito tarifa urgente aéreo Frankfurt a Lima. 320 kg, 1.8 CBM. DAP Lima.",
                "received_at": "2026-06-09T11:00:00Z",
            },
        ]

        with mock.patch(
            "core.email_listener.fetch_pending_emails", return_value=fake_emails
        ):
            results = process_inbound_emails(auto_ack=False)

        assert len(results) == 2
        types = {r["_email_type"] for r in results}
        assert "provider_reply" in types
        assert "client_request" in types
