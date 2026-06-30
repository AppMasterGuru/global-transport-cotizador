"""
Tests for FCL rendering/structure fixes F1-F6 (Abel validated CONFORME 2026-06-23).

FIX 1 - FCL must not render LCL line items
FIX 2 - De-duplicate Visto Bueno on FCL
FIX 3 - Auto-program IGV-exempt + coloader concepts
FIX 4 - Combine port cost + port storage into ONE concept
FIX 5 - Move THC + ISPS into Flete Internacional, mark IGV-exempt
FIX 6 - Transport label: "Transporte Local" only, never transporter name

SCOPE BOUNDARY: No per-incoterm or international-agent logic. Display/flag fixes only.
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


# Base form data

_BASE_FCL_EXPORT = {
    "client_name": "Test Exporter SA",
    "client_email": "test@exporter.com",
    "mode": "fcl",
    "incoterm": "FOB",
    "origin": "Callao, Peru",
    "destination": "Hamburg, Germany",
    "cargo_description": "Test cargo",
    "weight": "18000",
    "weight_unit": "kg",
    "volume_cbm": "60",
    "flete_lcl": "2500",
    "staff_code": "GT-PC",
    "language": "es",
    "requester_type": "cliente",
    "operation": "exportacion",
    "fcl_terminal": "DPW",
    "fcl_naviera": "MAERSK",
    "fcl_container_type": "20STD",
    "num_containers": "1",
}

_BASE_FCL_IMPORT = {
    **_BASE_FCL_EXPORT,
    "operation": "importacion",
    "incoterm": "DAP",
    "origin": "Shanghai, China",
    "destination": "Callao, Peru",
    "fcl_naviera": "MAERSK / SEALAND",
}

_BASE_FCL_IMPORT_CMA = {
    **_BASE_FCL_IMPORT,
    "fcl_naviera": "CMA CGM / APL",
}


def _post(client, base, overrides=None):
    from urllib.parse import unquote
    data = {**base, **(overrides or {})}
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    assert row is not None
    return dict(row)


def _export(client, overrides=None):
    return _post(client, _BASE_FCL_EXPORT, overrides)


def _import_maersk(client, overrides=None):
    return _post(client, _BASE_FCL_IMPORT, overrides)


def _import_cma(client, overrides=None):
    return _post(client, _BASE_FCL_IMPORT_CMA, overrides)


# FIX 1 - FCL must not render LCL line items

class TestFix1NoLclItemsOnFcl:
    def test_lcl_band_transport_not_computed_for_fcl(self, client):
        # 18 000 kg / 60 CBM triggers substantial LCL band transport. Must be 0 for FCL.
        q = _export(client, {"weight": "18000", "volume_cbm": "60"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("transport_usd") in (None, 0, 0.0)

    def test_lcl_band_transport_no_line_item_in_fcl_venta(self, client):
        # No district submitted -> no Open Transport either; no "Transporte Local" at all.
        q = _export(client, {"weight": "18000", "volume_cbm": "60"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert "Transporte Local" not in descriptions

    def test_section4_coloader_items_suppressed_on_fcl_export(self, client):
        extra = json.dumps([{"concept": "Flete Origen", "bucket": "intl", "valor": 200.0}])
        q = _export(client, {"extra_items_json": extra})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert "Flete Origen" not in descriptions

    def test_section4_coloader_items_suppressed_on_fcl_import(self, client):
        extra = json.dumps([{"concept": "Handling Origen", "bucket": "local", "valor": 75.0}])
        q = _import_maersk(client, {"extra_items_json": extra})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert "Handling Origen" not in descriptions


# FIX 2 - De-duplicate Visto Bueno on FCL

class TestFix2ExactlyOneVbOnFcl:
    def test_fcl_export_exactly_one_vb(self, client):
        # Section 4 VB submitted alongside auto-computed naviera VB -> only one must appear.
        extra = json.dumps([{"concept": "Visto Bueno", "bucket": "local", "valor": 50.0}])
        q = _export(client, {"fcl_naviera": "MAERSK", "extra_items_json": extra})
        venta = json.loads(q["venta_json"])
        vb_items = [i for i in venta["line_items"] if "Visto Bueno" in i["description"]]
        assert len(vb_items) == 1

    def test_fcl_import_exactly_one_vb(self, client):
        extra = json.dumps([{"concept": "Visto Bueno", "bucket": "local", "valor": 50.0}])
        q = _import_maersk(client, {"extra_items_json": extra})
        venta = json.loads(q["venta_json"])
        vb_items = [i for i in venta["line_items"] if "Visto Bueno" in i["description"]]
        assert len(vb_items) == 1

    def test_fcl_export_vb_is_naviera_value(self, client):
        q = _export(client, {"fcl_naviera": "MAERSK"})
        costeo = json.loads(q["costeo_json"])
        venta = json.loads(q["venta_json"])
        vb_item = next(i for i in venta["line_items"] if "Visto Bueno" in i["description"])
        assert vb_item["total"] == pytest.approx(costeo["fcl_visto_bueno_usd"] * 1.20, rel=0.01)


# FIX 3 - Auto-program coloader concepts + IGV treatment
# Session L (§4) — DELIBERATE REVERSAL of the original fix #3, per Abel:
# Visto Bueno (export + importación) and Emisión MBL are LOCAL charges issued
# in Peru and therefore AFECTO a IGV. (THC/ISPS stay exempt — see FIX 5.)

class TestFix3VbMblAfectoIgv:
    def test_fcl_export_vb_afecto_igv(self, client):
        # Naviera VB export is issued locally in Peru: afecto al IGV (§4 reversal).
        q = _export(client, {"fcl_naviera": "MAERSK"})
        venta = json.loads(q["venta_json"])
        vb_item = next(i for i in venta["line_items"] if i.get("description") == "Visto Bueno")
        assert vb_item.get("is_local") is True
        assert vb_item.get("igv_applicable") is True

    def test_fcl_import_mbl_auto_populates_without_manual_input(self, client):
        # MBL must appear with zero Section 4 items.
        q = _import_maersk(client)
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert any("MBL" in d for d in descriptions)

    def test_fcl_import_mbl_afecto_igv(self, client):
        # Emisión MBL is a locally issued charge: afecto al IGV (§4 reversal).
        q = _import_maersk(client)
        venta = json.loads(q["venta_json"])
        mbl_item = next(i for i in venta["line_items"] if "MBL" in i["description"])
        assert mbl_item.get("is_local") is True
        assert mbl_item.get("igv_applicable") is True

    def test_fcl_import_vb_importacion_afecto_igv(self, client):
        # VB Importación is a locally issued charge: afecto al IGV (§4 reversal).
        q = _import_maersk(client)
        venta = json.loads(q["venta_json"])
        vb_imp = next(
            i for i in venta["line_items"]
            if "Visto Bueno (Importaci" in i["description"]
        )
        assert vb_imp.get("is_local") is True
        assert vb_imp.get("igv_applicable") is True

    def test_fcl_customs_commission_auto_populates(self, client):
        # Customs agent commission appears without manual input (regression guard).
        q = _export(client)
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert any("Agente de Aduana" in d for d in descriptions)


# FIX 4 - Combine port cost + port storage into ONE concept

class TestFix4CombinedPortLine:
    def test_one_combined_port_line_dpw_export(self, client):
        q = _export(client, {"fcl_terminal": "DPW"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert any("Gastos de Puerto y Dep" in d for d in descriptions)

    def test_no_separate_puerto_line(self, client):
        q = _export(client, {"fcl_terminal": "DPW"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert not any(d in ("Puerto (DPW)", "Puerto (APM)") for d in descriptions)

    def test_no_separate_deposito_temporal_line(self, client):
        q = _export(client, {"fcl_terminal": "DPW"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert not any("Dep" in d and "Temporal" in d for d in descriptions)

    def test_combined_port_total_equals_port_plus_deposito(self, client):
        q = _export(client, {"fcl_terminal": "DPW", "margin_pct": "20"})
        costeo = json.loads(q["costeo_json"])
        venta = json.loads(q["venta_json"])
        expected_net = (costeo.get("fcl_port_usd") or 0) + (costeo.get("fcl_deposito_temporal_usd") or 0)
        port_item = next(i for i in venta["line_items"] if "Puerto" in i["description"])
        assert port_item["total"] == pytest.approx(expected_net * 1.20, rel=0.01)

    def test_apm_combined_line_port_only(self, client):
        # APM has no deposito temporal: combined line = port cost only.
        q = _export(client, {"fcl_terminal": "APM", "margin_pct": "20"})
        costeo = json.loads(q["costeo_json"])
        venta = json.loads(q["venta_json"])
        port_item = next(i for i in venta["line_items"] if "Puerto" in i["description"])
        assert port_item["total"] == pytest.approx((costeo.get("fcl_port_usd") or 0) * 1.20, rel=0.01)


# FIX 5 - Move THC + ISPS into Flete Internacional, mark IGV-exempt

class TestFix5ThcIspsIntl:
    def test_thc_marked_igv_exempt(self, client):
        # THC is a naviera terminal handling charge: inafecto al IGV.
        q = _import_cma(client, {"fcl_container_type": "20STD"})
        venta = json.loads(q["venta_json"])
        thc_item = next(i for i in venta["line_items"] if "THC" in i["description"])
        assert thc_item.get("is_international") is True
        assert thc_item.get("igv_applicable") is False

    def test_isps_marked_igv_exempt(self, client):
        # ISPS is a naviera surcharge: inafecto al IGV.
        q = _import_cma(client, {"fcl_container_type": "20STD"})
        venta = json.loads(q["venta_json"])
        isps_item = next(i for i in venta["line_items"] if "ISPS" in i["description"])
        assert isps_item.get("is_international") is True
        assert isps_item.get("igv_applicable") is False

    def test_thc_value_unchanged_same_money_different_section(self, client):
        q = _import_cma(client, {"fcl_container_type": "20STD", "margin_pct": "20"})
        costeo = json.loads(q["costeo_json"])
        venta = json.loads(q["venta_json"])
        thc_item = next(i for i in venta["line_items"] if "THC" in i["description"])
        assert thc_item["total"] == pytest.approx(costeo["fcl_thc_usd"] * 1.20, rel=0.01)

    def test_isps_value_unchanged_same_money_different_section(self, client):
        q = _import_cma(client, {"fcl_container_type": "20STD", "margin_pct": "20"})
        costeo = json.loads(q["costeo_json"])
        venta = json.loads(q["venta_json"])
        isps_item = next(i for i in venta["line_items"] if "ISPS" in i["description"])
        assert isps_item["total"] == pytest.approx(costeo["fcl_isps_usd"] * 1.20, rel=0.01)

    def test_venta_total_equals_sum_of_line_items(self, client):
        # No money dropped or doubled when moving THC/ISPS to Flete Internacional.
        q = _import_cma(client)
        venta = json.loads(q["venta_json"])
        assert venta["total_usd"] == pytest.approx(
            sum(i["total"] for i in venta["line_items"]), rel=0.001
        )


# FIX 6 - Transport label: "Transporte Local" only, never transporter name

class TestFix6TransporterNameHidden:
    def test_open_transport_label_is_transporte_local(self, client):
        q = _import_maersk(client, {"open_transport_district": "CALLAO"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert "Transporte Local" in descriptions

    def test_transporter_name_never_in_any_description(self, client):
        # "Open Transport" (company name) must never appear on client-facing proforma.
        q = _import_maersk(client, {"open_transport_district": "CALLAO"})
        venta = json.loads(q["venta_json"])
        for item in venta["line_items"]:
            assert "Open Transport" not in item["description"]

    def test_transporter_name_absent_even_without_district(self, client):
        q = _import_maersk(client)
        venta = json.loads(q["venta_json"])
        for item in venta["line_items"]:
            assert "Open Transport" not in item["description"]
