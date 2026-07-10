"""
Integration tests for the FCL Agente Internacional path through the live
quote route (Session L).

Asserts that the agente path re-sources naviera/port amounts from the same
docs the cliente_local import path uses (so they MATCH), and that DDP is wired
end to end (§2/§3/§4): THC/ISPS exempt, MBL + VB importación afecto IGV,
Operative Charge in venta, calculated Customs Broker present, and Gate in
COST-only (never in the client quote).
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
from core.fcl_customs_broker import agente_customs_broker_fee  # noqa: E402


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
def client():
    from api.app import create_app
    a = create_app()
    a.config["TESTING"] = True
    with a.test_client() as c:
        yield c


_BASE_EXPORT_EXW = {
    "client_name": "Agente Test SA",
    "client_email": "a@test.com",
    "mode": "fcl",
    "client_type": "agente_internacional",
    "incoterm": "EXW",
    "operation": "exportacion",
    "origin": "Callao, Peru",
    "destination": "Hamburg, Germany",
    "cargo_description": "cargo",
    "weight": "18000",
    "weight_unit": "kg",
    "volume_cbm": "60",
    "staff_code": "GT-PC",
    "language": "es",
    "requester_type": "agente",
    "fcl_terminal": "DPW",
    "fcl_naviera": "CMA CGM",
    "fcl_container_type": "20STD",
    "num_containers": "1",
}

_BASE_IMPORT_DAP = {
    **_BASE_EXPORT_EXW,
    "incoterm": "DAP",
    "operation": "importacion",
    "origin": "Shanghai, China",
    "destination": "Callao, Peru",
    "fcl_naviera": "CMA CGM / APL",
}

_BASE_IMPORT_DDP = {
    **_BASE_IMPORT_DAP,
    "incoterm": "DDP",
    "invoice_usd": "50000",
    "insurance_usd": "500",
    "flete_lcl": "2000",
}


def _post(client, data):
    from urllib.parse import unquote
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302, resp.data
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    assert row is not None
    return dict(row)


def _lines(row):
    return json.loads(row["venta_json"])["line_items"]


def _costeo(row):
    return json.loads(row["costeo_json"])


# ── EXW: Terminal Fee re-sourced from port_costs ──────────────────────────────

class TestExwResolved:
    def test_terminal_fee_present_and_matches_port_doc(self, client):
        row = _post(client, dict(_BASE_EXPORT_EXW))
        costeo = _costeo(row)
        lines = _lines(row)
        tf = next(i for i in lines if i["description"] == "Terminal Fee")
        expected = (costeo.get("fcl_port_usd") or 0) + (costeo.get("fcl_deposito_temporal_usd") or 0)
        assert tf["total"] == pytest.approx(expected, rel=0.001)
        assert tf["igv_applicable"] is True

    def test_gate_out_naviera_sourced_with_depot_recorded(self, client):
        # Abel 2026-07-10: Gate out now comes from the selected naviera. Base
        # fixture is CMA CGM → IMUPESA 150 net (coincidentally 150, but now
        # depot-attributed and audited — no longer a static placeholder).
        row = _post(client, dict(_BASE_EXPORT_EXW))
        gate = next(i for i in _lines(row) if i["description"] == "Gate out")
        assert gate["total"] == 150.0  # CMA CGM IMUPESA net
        assert gate["igv_applicable"] is True
        costeo = _costeo(row)
        assert costeo["fcl_gate_out_usd"] == 150.0
        assert costeo["fcl_gate_out_depot"] == "IMUPESA"

    def test_visto_bueno_exportacion_present_afecto_igv(self, client):
        # New naviera-sourced VB line — CMA CGM net 219.35, afecto a IGV.
        row = _post(client, dict(_BASE_EXPORT_EXW))
        vb = next(i for i in _lines(row) if i["description"] == "Visto Bueno (Exportación)")
        assert vb["total"] == pytest.approx(219.35, rel=0.001)
        assert vb["igv_applicable"] is True and vb["is_local"] is True

    def test_coordinacion_and_vb_both_present_no_double_count(self, client):
        # Step 0b: Coordinación 214 (GT fee) and VB (Exportación) are distinct —
        # both appear, exactly once each. The export VB bundle never contained
        # Coordinación (only the import VB does).
        lines = _lines(_post(client, dict(_BASE_EXPORT_EXW)))
        coord = [i for i in lines if "Coordinación" in i["description"]]
        vb = [i for i in lines if i["description"] == "Visto Bueno (Exportación)"]
        assert len(coord) == 1 and coord[0]["unit_price"] == 214.0
        assert len(vb) == 1

    def test_no_static_150_gate_out_when_naviera_gate_differs(self, client):
        # Prove Gate out is not the old static 150: COSCO → FARGOLINE 125.5.
        data = {**_BASE_EXPORT_EXW, "fcl_naviera": "COSCO"}
        row = _post(client, data)
        gate = next(i for i in _lines(row) if i["description"] == "Gate out")
        assert gate["total"] == pytest.approx(125.5, rel=0.001)
        assert gate["total"] != 150.0
        assert _costeo(row)["fcl_gate_out_depot"] == "FARGOLINE"

    def test_gate_out_scales_per_container(self, client):
        # MSC MEDLOG 152 net × 2 containers = 304.
        data = {**_BASE_EXPORT_EXW, "fcl_naviera": "MSC", "num_containers": "2"}
        row = _post(client, data)
        gate = next(i for i in _lines(row) if i["description"] == "Gate out")
        assert gate["quantity"] == 2
        assert gate["total"] == pytest.approx(304.0, rel=0.001)


# ── EXW per-naviera VB + Gate Out (Session G confirmed figures) ────────────────

_EXW_NAVIERA_EXPECTATIONS = [
    # naviera,        vb_net,   gate_depot,           gate_net
    ("MSC",           365.0,    "MEDLOG",             152.0),
    ("ONE",           272.0,    "CONTRANS",           150.0),
    ("MAERSK",        160.0,    "DEMARES",            179.0),
    ("HAPAG LLOYD",   152.0,    "RANSA",              150.0),
    ("CMA CGM",       219.35,   "IMUPESA",            150.0),
    ("COSCO",         100.0,    "FARGOLINE",          125.5),
    ("EVERGREEN",     227.0,    "DP WORLD LOGISTICS", 120.5),
]


class TestExwPerNaviera:
    @pytest.mark.parametrize("naviera,vb_net,depot,gate_net",
                             _EXW_NAVIERA_EXPECTATIONS)
    def test_vb_and_gate_out_match_naviera_docs(self, client, naviera, vb_net,
                                                depot, gate_net):
        row = _post(client, {**_BASE_EXPORT_EXW, "fcl_naviera": naviera})
        lines = _lines(row)
        vb = next(i for i in lines if i["description"] == "Visto Bueno (Exportación)")
        gate = next(i for i in lines if i["description"] == "Gate out")
        assert vb["total"] == pytest.approx(vb_net, rel=0.001), naviera
        assert gate["total"] == pytest.approx(gate_net, rel=0.001), naviera
        costeo = _costeo(row)
        assert costeo["fcl_gate_out_depot"] == depot, naviera
        assert costeo["fcl_gate_out_usd"] == pytest.approx(gate_net, rel=0.001)


# ── cliente_local export regression (byte-for-byte: gate-out never added) ──────

class TestClienteLocalExportUnchanged:
    def _cliente_local_exw(self):
        return {**_BASE_EXPORT_EXW, "client_type": "cliente_local"}

    def test_cliente_local_charges_vb_but_never_gate_out(self, client):
        # cliente_local export has always charged the naviera VB (once) and NEVER
        # a Gate Out — the new agente EXW gate-out wiring must not leak into it.
        row = _post(client, self._cliente_local_exw())
        lines = _lines(row)
        descs = {i["description"] for i in lines}
        assert "Visto Bueno" in descs         # cliente_local VB line (unchanged)
        assert "Gate out" not in descs        # never charged for cliente_local
        costeo = _costeo(row)
        assert costeo.get("fcl_gate_out_usd") is None
        assert costeo.get("fcl_gate_out_depot") is None

    def test_cliente_local_vb_value_unchanged(self, client):
        # CMA CGM export VB 219.35 × margin — the cliente_local figure is
        # untouched by the agente path change.
        row = _post(client, self._cliente_local_exw())
        vb = next(i for i in _lines(row) if i["description"] == "Visto Bueno")
        m = 1 + float(row["margin_pct"])
        assert vb["total"] == pytest.approx(round(219.35 * m, 2), rel=0.001)


# ── DAP: THC/ISPS/BL Master re-sourced, matching cliente_local ────────────────

class TestDapResolved:
    def test_thc_isps_match_naviera_doc(self, client):
        row = _post(client, dict(_BASE_IMPORT_DAP))
        lines = _lines(row)
        thc = next(i for i in lines if i["description"] == "THC")
        isps = next(i for i in lines if i["description"] == "ISPS")
        # CMA CGM / APL override: THC 65, ISPS 39, both exempt
        assert thc["total"] == 65.0
        assert thc["igv_applicable"] is False
        assert isps["total"] == 39.0
        assert isps["igv_applicable"] is False

    def test_bl_master_matches_mbl_doc(self, client):
        row = _post(client, dict(_BASE_IMPORT_DAP))
        bl = next(i for i in _lines(row) if i["description"] == "BL Master")
        assert bl["total"] == 55.0  # CMA CGM MBL
        assert bl["igv_applicable"] is True

    def test_terminal_fee_resolved(self, client):
        row = _post(client, dict(_BASE_IMPORT_DAP))
        costeo = _costeo(row)
        tf = next(i for i in _lines(row) if i["description"] == "Terminal Fee")
        expected = (costeo.get("fcl_port_usd") or 0) + (costeo.get("fcl_deposito_temporal_usd") or 0)
        assert tf["total"] == pytest.approx(expected, rel=0.001)


# ── DDP: full §2/§3/§4 scenario ───────────────────────────────────────────────

class TestDdpScenario:
    def test_thc_isps_exempt(self, client):
        row = _post(client, dict(_BASE_IMPORT_DDP))
        lines = _lines(row)
        thc = next(i for i in lines if i["description"] == "THC")
        isps = next(i for i in lines if i["description"] == "ISPS")
        assert thc["igv_applicable"] is False
        assert isps["igv_applicable"] is False

    def test_mbl_and_vb_afecto_igv(self, client):
        row = _post(client, dict(_BASE_IMPORT_DDP))
        lines = _lines(row)
        mbl = next(i for i in lines if i["description"] == "Emisión MBL")
        vb = next(i for i in lines if i["description"] == "Visto Bueno (Importación)")
        assert mbl["igv_applicable"] is True and mbl["is_local"] is True
        assert vb["igv_applicable"] is True and vb["is_local"] is True
        assert mbl["total"] == 55.0
        assert vb["total"] == 225.0  # CMA: 190 coord + 35 admin

    def test_operative_charge_in_venta(self, client):
        row = _post(client, dict(_BASE_IMPORT_DDP))
        op = next(i for i in _lines(row) if i["description"] == "Operative Charge")
        assert op["total"] == 20.0
        assert op["igv_applicable"] is True

    def test_customs_broker_calculated_from_cif(self, client):
        row = _post(client, dict(_BASE_IMPORT_DDP))
        cb = next(i for i in _lines(row) if i["description"] == "Customs Broker")
        # CIF = invoice 50000 + insurance 500 + freight 2000 = 52500
        # Alefero (default): max(0.0035 × 52500, 110) = 183.75
        expected = agente_customs_broker_fee("ALEFERO", 52500.0)
        assert cb["total"] == expected == 183.75
        assert cb["igv_applicable"] is True

    def test_broker_uses_oea_when_flag_set(self, client):
        data = dict(_BASE_IMPORT_DDP)
        data["requires_oea_basc"] = "on"
        row = _post(client, data)
        cb = next(i for i in _lines(row) if i["description"] == "Customs Broker")
        # OEA: max(0.0020 × 52500, 80) = 105.00
        assert cb["total"] == 105.0

    def test_gate_in_cost_only_not_in_venta(self, client):
        row = _post(client, dict(_BASE_IMPORT_DDP))
        lines = _lines(row)
        assert not any("Gate in" in i["description"] for i in lines)
        costeo = _costeo(row)
        assert costeo.get("fcl_gate_in_usd") == 210.0  # 210 × 1 container

    def test_gate_in_scales_with_containers(self, client):
        data = dict(_BASE_IMPORT_DDP)
        data["num_containers"] = "3"
        row = _post(client, data)
        costeo = _costeo(row)
        assert costeo.get("fcl_gate_in_usd") == 630.0  # 210 × 3

    def test_no_duplicate_coordinacion_no_double_count(self, client):
        # Coordinación is inside the VB importación bundle — must not also appear
        # as a separate line (no double-count).
        row = _post(client, dict(_BASE_IMPORT_DDP))
        coord = [i for i in _lines(row) if "Coordinación" in i["description"]]
        assert coord == []
