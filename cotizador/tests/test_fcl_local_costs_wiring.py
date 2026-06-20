"""
Tests for FCL local costs wired into the live quote form (Session E).

Terminal (APM/DPW) + naviera + container type + container count selectors,
flowing into: port cost, FCL-specific customs agent commission/gastos/
precinto (supersedes the generic transport.get_customs_agent() path for
mode="fcl"), export Visto Bueno (naviera-attributed only, no guessing), and
import THC+ISPS+MBL+VB importación (naviera-attributed via the Gastos
workbook's own VB IMPORTACION sheet — see core/fcl_import_costs.py).

TODO(abel-F1F4): margin is applied to all FCL local cost line items by
default (same as Visto Bueno/Agente de Aduana/Transporte Local elsewhere in
the codebase) since Abel hasn't explicitly flagged any of these as flat
pass-throughs (unlike Handling Aereo/Almacén Aéreo). Confirm via Abel's
F1-F4 scenario run.
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


_BASE_FCL_EXPORT_FORM = {
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

_BASE_FCL_IMPORT_FORM = {
    **_BASE_FCL_EXPORT_FORM,
    "operation": "importacion",
    "fcl_naviera": "MAERSK / SEALAND",
    "incoterm": "DAP",
    "origin": "Shanghai, China",
    "destination": "Callao, Peru",
}


def _post_fcl_quote(client, overrides=None):
    from urllib.parse import unquote
    data = {**_BASE_FCL_EXPORT_FORM, **(overrides or {})}
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    assert row is not None, f"Quote not found for ref={ref!r}"
    return dict(row)


def _post_fcl_import_quote(client, overrides=None):
    from urllib.parse import unquote
    data = {**_BASE_FCL_IMPORT_FORM, **(overrides or {})}
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    assert row is not None, f"Quote not found for ref={ref!r}"
    return dict(row)


class TestFclPortCostByTerminal:
    def test_dpw_20std_export_port_cost(self, client):
        q = _post_fcl_quote(client, {"fcl_terminal": "DPW", "fcl_container_type": "20STD"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_port_usd"] == pytest.approx(118.21, rel=0.001)

    def test_apm_20std_export_port_cost(self, client):
        q = _post_fcl_quote(client, {"fcl_terminal": "APM", "fcl_container_type": "20STD"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_port_usd"] == pytest.approx(243.10, rel=0.001)

    def test_port_cost_scales_with_container_count(self, client):
        q = _post_fcl_quote(client, {
            "fcl_terminal": "DPW", "fcl_container_type": "20STD", "num_containers": "2",
        })
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_port_usd"] == pytest.approx(118.21 * 2, rel=0.001)

    def test_dpw_deposito_temporal_flat_not_multiplied_by_containers(self, client):
        q1 = _post_fcl_quote(client, {"num_containers": "1"})
        q2 = _post_fcl_quote(client, {"num_containers": "2"})
        costeo1 = json.loads(q1["costeo_json"])
        costeo2 = json.loads(q2["costeo_json"])
        assert costeo1["fcl_deposito_temporal_usd"] == pytest.approx(costeo2["fcl_deposito_temporal_usd"], rel=0.001)
        assert costeo1["fcl_deposito_temporal_usd"] > 0

    def test_apm_has_no_separate_deposito_temporal(self, client):
        q = _post_fcl_quote(client, {"fcl_terminal": "APM"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("fcl_deposito_temporal_usd") in (None, 0, 0.0)

    def test_port_line_item_in_venta(self, client):
        q = _post_fcl_quote(client)
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert any("Puerto" in d for d in descriptions)


class TestFclCustomsAgentSupersedesGeneric:
    def test_alefero_default_one_container(self, client):
        q = _post_fcl_quote(client, {"num_containers": "1"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_customs_commission_usd"] == pytest.approx(50.0, rel=0.001)
        assert costeo["fcl_customs_precinto_usd"] == pytest.approx(10.0, rel=0.001)
        # generic customs_agent_usd path must be suppressed for FCL
        assert costeo.get("customs_agent_usd") in (None, 0, 0.0)

    def test_alefero_two_containers_includes_surcharge(self, client):
        q = _post_fcl_quote(client, {"num_containers": "2"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_customs_commission_usd"] == pytest.approx(75.0, rel=0.001)

    def test_oea_basc_checkbox_switches_agent(self, client):
        q = _post_fcl_quote(client, {"requires_oea_basc": "on", "num_containers": "1"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_customs_commission_usd"] == pytest.approx(70.0, rel=0.001)
        assert costeo["fcl_customs_gastos_operativos_usd"] == pytest.approx(20.0, rel=0.001)
        assert costeo["fcl_customs_precinto_usd"] == pytest.approx(5.0, rel=0.001)

    def test_generic_agente_de_aduana_item_not_duplicated(self, client):
        q = _post_fcl_quote(client)
        venta = json.loads(q["venta_json"])
        aduana_items = [i for i in venta["line_items"] if "Agente de Aduana" in i["description"]]
        assert len(aduana_items) == 1


class TestFclExportVistoBueno:
    def test_attributed_naviera_charged(self, client):
        q = _post_fcl_quote(client, {"fcl_naviera": "MAERSK"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_visto_bueno_usd"] == pytest.approx(160.0, rel=0.001)

    def test_unattributed_naviera_not_charged_no_guess(self, client):
        q = _post_fcl_quote(client, {"fcl_naviera": "MSC"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("fcl_visto_bueno_usd") in (None, 0, 0.0)

    def test_visto_bueno_line_item_only_when_attributed(self, client):
        q_attributed = _post_fcl_quote(client, {"fcl_naviera": "CMA CGM"})
        q_unattributed = _post_fcl_quote(client, {"fcl_naviera": "MSC"})
        descs_attributed = [i["description"] for i in json.loads(q_attributed["venta_json"])["line_items"]]
        descs_unattributed = [i["description"] for i in json.loads(q_unattributed["venta_json"])["line_items"]]
        assert any("Visto Bueno" in d for d in descs_attributed)
        assert not any("Visto Bueno" in d for d in descs_unattributed)


class TestFclImportLocalCosts:
    def test_thc_isps_mbl_charged_for_attributed_naviera(self, client):
        q = _post_fcl_import_quote(client, {"fcl_naviera": "MAERSK / SEALAND", "fcl_container_type": "20STD"})
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_thc_usd"] == pytest.approx(110.0, rel=0.001)
        assert costeo["fcl_mbl_usd"] == pytest.approx(55.0, rel=0.001)
        assert costeo["fcl_vb_importacion_usd"] == pytest.approx(442.0, rel=0.001)

    def test_40std_uses_40_thc_rate(self, client):
        q = _post_fcl_import_quote(client, {"fcl_naviera": "CMA CGM / APL", "fcl_container_type": "40STD"})
        costeo = json.loads(q["costeo_json"])
        # CMA CGM/APL raw G.LOCALES thc_40=70, but overridden to 65 (IGV-exempt) per Q4.
        assert costeo["fcl_thc_usd"] == pytest.approx(65.0, rel=0.001)

    def test_thc_scales_with_container_count(self, client):
        q = _post_fcl_import_quote(client, {
            "fcl_naviera": "MAERSK / SEALAND", "fcl_container_type": "20STD", "num_containers": "2",
        })
        costeo = json.loads(q["costeo_json"])
        assert costeo["fcl_thc_usd"] == pytest.approx(220.0, rel=0.001)

    def test_mbl_flat_not_multiplied_by_containers(self, client):
        q1 = _post_fcl_import_quote(client, {"num_containers": "1"})
        q2 = _post_fcl_import_quote(client, {"num_containers": "2"})
        costeo1 = json.loads(q1["costeo_json"])
        costeo2 = json.loads(q2["costeo_json"])
        assert costeo1["fcl_mbl_usd"] == pytest.approx(costeo2["fcl_mbl_usd"], rel=0.001)

    def test_inactive_naviera_not_charged(self, client):
        q = _post_fcl_import_quote(client, {"fcl_naviera": "HAMBURG SUD / ALIANCA"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("fcl_thc_usd") in (None, 0, 0.0)

    def test_import_line_items_present(self, client):
        q = _post_fcl_import_quote(client, {"fcl_naviera": "MAERSK / SEALAND"})
        venta = json.loads(q["venta_json"])
        descriptions = [i["description"] for i in venta["line_items"]]
        assert any("THC" in d for d in descriptions)
        assert any("MBL" in d for d in descriptions)
        assert any("Visto Bueno" in d for d in descriptions)

    def test_export_only_fields_absent_on_import_quote(self, client):
        q = _post_fcl_import_quote(client, {"fcl_naviera": "MAERSK / SEALAND"})
        costeo = json.loads(q["costeo_json"])
        assert costeo.get("fcl_visto_bueno_usd") in (None, 0, 0.0)


class TestFclOnlyAppliesToFclMode:
    def test_lcl_mode_unaffected(self, client):
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
            "fcl_terminal": "DPW",
            "fcl_naviera": "MAERSK",
            "fcl_container_type": "20STD",
            "num_containers": "1",
        }
        resp = client.post("/quote/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
            ).fetchone()
        costeo = json.loads(dict(row)["costeo_json"])
        assert costeo.get("fcl_port_usd") in (None, 0, 0.0)
        # Generic customs agent path must still apply normally for LCL.
        assert costeo["customs_agent_usd"] > 0
