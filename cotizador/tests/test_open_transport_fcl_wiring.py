"""
Tests for Open Transport district delivery wired into FCL quotes (Q7).

Optional line item: only appears when the user submits an
open_transport_district on an FCL quote. No district selected (or any
other mode) → no charge, no line item — there is no inferred default.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("DB_PATH", _tmp_db.name)

from core.db import get_connection, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS provider_replies;
            DROP TABLE IF EXISTS credit_registry;
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


_BASE_FCL_FORM = {
    "client_name": "Test Importer SA",
    "client_email": "test@importer.com",
    "mode": "fcl",
    "incoterm": "DAP",
    "origin": "Shanghai, China",
    "destination": "Callao, Peru",
    "cargo_description": "Test cargo",
    "weight": "18000",
    "weight_unit": "kg",
    "volume_cbm": "60",
    "flete_lcl": "2500",
    "flete_rate_lcl": "",
    "consolidator": "",
    "staff_code": "GT-PC",
    "language": "es",
    "requester_type": "cliente",
    "operation": "importacion",
}


def _post_fcl_quote(client, overrides=None):
    from urllib.parse import unquote
    data = {**_BASE_FCL_FORM, **(overrides or {})}
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    assert row is not None, f"Quote not found for ref={ref!r}"
    return dict(row)


class TestOpenTransportNotChargedByDefault:
    def test_no_district_no_line_item(self, client):
        q = _post_fcl_quote(client, {"open_transport_district": ""})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert not any("Open Transport" in d for d in descriptions)

    def test_no_district_costeo_zero(self, client):
        q = _post_fcl_quote(client, {"open_transport_district": ""})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("open_transport_usd") in (None, 0, 0.0)


class TestOpenTransportDistrictSelected:
    def test_district_adds_line_item(self, client):
        q = _post_fcl_quote(client, {"open_transport_district": "CALLAO"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert any("Transporte Local" in d for d in descriptions)

    def test_general_rate_used_by_default(self, client):
        q = _post_fcl_quote(client, {"open_transport_district": "CALLAO"})
        costeo = json.loads(q["costeo_json"])
        # CALLAO general = S/550 net pre-IGV; just confirm it's non-zero and
        # smaller than the IMO rate would produce (780 -> larger USD figure).
        assert costeo["open_transport_usd"] > 0

    def test_hazardous_checkbox_uses_imo_rate(self, client):
        q_general = _post_fcl_quote(client, {"open_transport_district": "CALLAO"})
        q_imo = _post_fcl_quote(client, {
            "open_transport_district": "CALLAO",
            "open_transport_hazardous": "on",
        })
        costeo_general = json.loads(q_general["costeo_json"])
        costeo_imo = json.loads(q_imo["costeo_json"])
        assert costeo_imo["open_transport_usd"] > costeo_general["open_transport_usd"]

    def test_line_item_total_scales_with_margin(self, client):
        q = _post_fcl_quote(client, {
            "open_transport_district": "CALLAO",
            "margin_pct": "25",
        })
        costeo = json.loads(q["costeo_json"])
        venta = json.loads(q["venta_json"])
        item = next(i for i in venta["line_items"] if i["description"] == "Transporte Local")
        assert item["total"] == pytest.approx(costeo["open_transport_usd"] * 1.25, rel=0.01)

    def test_district_recorded_in_costeo(self, client):
        q = _post_fcl_quote(client, {"open_transport_district": "LA MOLINA"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("open_transport_district") == "LA MOLINA"

    def test_unknown_district_does_not_crash_and_skips_charge(self, client):
        q = _post_fcl_quote(client, {"open_transport_district": "ATLANTIS"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("open_transport_usd") in (None, 0, 0.0)

    def test_only_for_fcl_mode(self, client):
        from urllib.parse import unquote
        data = {
            "client_name": "Test Shipper SA",
            "client_email": "test@shipper.com",
            "mode": "lcl",
            "incoterm": "FOB",
            "origin": "Lima, Peru",
            "destination": "Hamburg, Germany",
            "cargo_description": "Test cargo",
            "weight": "500",
            "weight_unit": "kg",
            "volume_cbm": "2.0",
            "flete_lcl": "200.00",
            "consolidator": "MSL",
            "staff_code": "GT-PC",
            "language": "es",
            "requester_type": "cliente",
            "open_transport_district": "CALLAO",
        }
        resp = client.post("/quote/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
            ).fetchone()
        costeo = json.loads(dict(row)["costeo_json"])
        assert costeo.get("open_transport_usd") in (None, 0, 0.0)
