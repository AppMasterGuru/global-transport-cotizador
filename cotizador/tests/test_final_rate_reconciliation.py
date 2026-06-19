"""
Regression tests for Abel-confirmed rate values (2026-06-13, updated 2026-06-18).

Covers:
  - Import VB (confirmed by Abel 2026-06-18): MSL=90, CRAFT=160, SACO=190, EQ=90
  - Export VB: MSL=160, CRAFT=160, SACO=190, EQ=180
  - VANGUARD still has no confirmed rate (None) and warns at startup
  - Startup warning lists ONLY VANGUARD as missing
  - CIF customs broker uses independent minimums: costo floor=$70, venta floor=$110
  - DDP incoterm: quote creates normally AND detail page shows the out-of-scope banner
"""

import json

import pytest

from core.transport import (
    _MISSING_EXPORT_VB,
    _MISSING_IMPORT_VB,
    get_consolidator,
    vb_rate_missing,
    visto_bueno_net_usd,
)


# ── Fixture reuse ─────────────────────────────────────────────────────────────

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


_BASE_FORM = {
    "client_name": "Reconciliation Test SA",
    "client_email": "test@recon.com",
    "mode": "lcl",
    "incoterm": "FOB",
    "origin": "Lima, Peru",
    "destination": "Hamburg, Germany",
    "cargo_description": "Reconciliation cargo",
    "weight": "300",
    "weight_unit": "kg",
    "volume_cbm": "1.0",
    "flete_lcl": "250.00",
    "consolidator": "MSL",
    "staff_code": "GT-PC",
    "language": "es",
    "requester_type": "cliente",
    "margin_pct": "20",
}


def _post_and_fetch(client, overrides=None):
    from urllib.parse import unquote
    from core.db import get_connection
    data = {**_BASE_FORM, **(overrides or {})}
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    assert row is not None
    return dict(row), ref


# ── FIX 1: Import VB confirmed per-consolidator (Abel 2026-06-18) ─────────────

class TestImportVbNinety:
    """MSL and EQ import VB remain USD 90 net (unchanged 2026-06-18)."""

    def test_msl_import_vb_is_90(self):
        c = get_consolidator("MSL")
        assert c["visto_bueno_import_usd"] == 90.0
        assert visto_bueno_net_usd(c, "importacion") == 90.0

    def test_eq_import_vb_is_90(self):
        c = get_consolidator("EQ")
        assert c["visto_bueno_import_usd"] == 90.0
        assert visto_bueno_net_usd(c, "importacion") == 90.0
        assert vb_rate_missing(c, "importacion") is False

    def test_eq_alias_ecu_import_vb_is_90(self):
        c = get_consolidator("ECU WORLDWIDE")
        assert c["visto_bueno_import_usd"] == 90.0


class TestImportVbUpdated20260618:
    """SACO import VB updated by Abel 2026-06-18 (was USD 90)."""

    def test_saco_import_vb_is_190(self):
        c = get_consolidator("SACO")
        assert c["visto_bueno_import_usd"] == 190.0
        assert visto_bueno_net_usd(c, "importacion") == 190.0
        assert vb_rate_missing(c, "importacion") is False


# ── FIX 1: Export VB confirmed values ────────────────────────────────────────

class TestExportVbConfirmed:
    """Export VB rates confirmed by Abel 2026-06-13."""

    def test_msl_export_vb_is_160_not_180(self):
        c = get_consolidator("MSL")
        assert c["visto_bueno_export_usd"] == 160.0
        assert c["visto_bueno_export_usd"] != 180.0  # stale sheet value

    def test_craft_export_vb_is_160(self):
        c = get_consolidator("CRAFT")
        assert c["visto_bueno_export_usd"] == 160.0


class TestCraftImportVbReverted20260619:
    """
    Abel Parte 2 Q13 (2026-06-19): the 2026-06-18 change (commit dcceb5f,
    90->160) was wrong for CRAFT import. Reverted back to 90. Export is
    unaffected by this — CRAFT export stays at 160.
    """

    def test_craft_import_vb_is_90(self):
        c = get_consolidator("CRAFT")
        assert c["visto_bueno_import_usd"] == 90.0
        assert visto_bueno_net_usd(c, "importacion") == 90.0
        assert vb_rate_missing(c, "importacion") is False

    def test_craft_export_vb_still_160(self):
        c = get_consolidator("CRAFT")
        assert c["visto_bueno_export_usd"] == 160.0

    def test_saco_export_vb_is_190(self):
        c = get_consolidator("SACO")
        assert c["visto_bueno_export_usd"] == 190.0

    def test_eq_export_vb_is_180_not_170(self):
        c = get_consolidator("EQ")
        assert c["visto_bueno_export_usd"] == 180.0
        assert c["visto_bueno_export_usd"] != 170.0  # old unverified value


# ── FIX 1: VANGUARD still missing — fail-safe intact ─────────────────────────

class TestVanguardMissingRateFailing:
    """VANGUARD has no confirmed rate; startup warning must list it only."""

    def test_vanguard_import_still_none(self):
        c = get_consolidator("VANGUARD")
        assert c["visto_bueno_import_usd"] is None
        assert vb_rate_missing(c, "importacion") is True
        assert visto_bueno_net_usd(c, "importacion") == 0.0

    def test_vanguard_export_still_none(self):
        c = get_consolidator("VANGUARD")
        assert c["visto_bueno_export_usd"] is None
        assert vb_rate_missing(c, "exportacion") is True

    def test_startup_warning_lists_only_vanguard(self):
        """After all Abel-confirmed rates are set, only VANGUARD should appear
        in the startup missing-rate warnings."""
        assert _MISSING_IMPORT_VB == ["VANGUARD"], (
            f"Expected only VANGUARD in missing import VB, got: {_MISSING_IMPORT_VB}"
        )
        assert _MISSING_EXPORT_VB == ["VANGUARD"], (
            f"Expected only VANGUARD in missing export VB, got: {_MISSING_EXPORT_VB}"
        )


# ── FIX 2: CIF minimums are independent ──────────────────────────────────────

class TestCifIndependentMinimums:
    """
    CIF calc must apply separate floors: costo=$70, venta=$110.
    JS computes the values client-side; Python stores them. These tests verify
    the stored values in costeo_json/venta_json are correct.
    """

    def _cif_extra(self, cif_usd, costo_computed, venta_computed,
                   min_costo=70, min_venta=110):
        return json.dumps([{
            "concept": "Agente de Aduana",
            "bucket": "local",
            "cif_calc": True,
            "cif_usd": cif_usd,
            "pct_costo": 0.30,
            "pct_venta": 0.35,
            "min_costo": min_costo,
            "min_venta": min_venta,
            "valor": costo_computed,
            "venta_neto": venta_computed,
            "factor": None,
            "total": costo_computed,
        }])

    def test_small_cif_costo_floored_at_70(self, client):
        # CIF $5,000: 0.30%=15 < 70 → floor applies
        extra = self._cif_extra(5000, costo_computed=70.0, venta_computed=110.0)
        row, _ = _post_and_fetch(client, {"extra_items_json": extra})
        costeo = json.loads(row["costeo_json"])
        item = next(e for e in (costeo.get("extra_items") or []) if e.get("cif_calc"))
        assert item["valor"] == pytest.approx(70.0)

    def test_small_cif_venta_floored_at_110(self, client):
        # CIF $5,000: 0.35%=17.5 < 110 → floor applies independently
        extra = self._cif_extra(5000, costo_computed=70.0, venta_computed=110.0)
        row, _ = _post_and_fetch(client, {"extra_items_json": extra})
        venta = json.loads(row["venta_json"])
        item = next(
            li for li in venta["line_items"] if li.get("description") == "Agente de Aduana"
        )
        assert item["total"] == pytest.approx(110.0)

    def test_cif_detail_stores_independent_minimums(self, client):
        extra = self._cif_extra(5000, costo_computed=70.0, venta_computed=110.0)
        row, _ = _post_and_fetch(client, {"extra_items_json": extra})
        costeo = json.loads(row["costeo_json"])
        item = next(e for e in (costeo.get("extra_items") or []) if e.get("cif_calc"))
        detail = item.get("cif_detail", {})
        assert detail["min_costo"] == 70.0
        assert detail["min_venta"] == 110.0

    def test_large_cif_percentage_exceeds_both_minimums(self, client):
        # CIF $200,000: 0.30%=600>70, 0.35%=700>110 — percentage wins
        extra = self._cif_extra(200000, costo_computed=600.0, venta_computed=700.0)
        row, _ = _post_and_fetch(client, {"extra_items_json": extra})
        costeo = json.loads(row["costeo_json"])
        item = next(e for e in (costeo.get("extra_items") or []) if e.get("cif_calc"))
        assert item["valor"] == pytest.approx(600.0)
        venta = json.loads(row["venta_json"])
        venta_item = next(
            li for li in venta["line_items"] if li.get("description") == "Agente de Aduana"
        )
        assert venta_item["total"] == pytest.approx(700.0)


# ── FIX 3: DDP banner visible on quote detail page ────────────────────────────

class TestDdpBanner:
    """DDP incoterm quotes must show the out-of-scope duties banner."""

    def test_ddp_quote_creates_successfully(self, client):
        row, _ = _post_and_fetch(client, {"incoterm": "DDP", "mode": "lcl"})
        assert row["incoterm"] == "DDP"
        assert row["status"] in ("PENDING", "APPROVED", "DRAFT")

    def test_ddp_quote_detail_shows_banner(self, client):
        _, ref = _post_and_fetch(client, {"incoterm": "DDP", "mode": "lcl"})
        resp = client.get(f"/quote/{ref}", follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "Cotización DDP" in body
        assert "NO está incluido automáticamente" in body

    def test_non_ddp_quote_has_no_ddp_banner(self, client):
        _, ref = _post_and_fetch(client, {"incoterm": "FOB", "mode": "lcl"})
        resp = client.get(f"/quote/{ref}", follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "NO está incluido automáticamente" not in body
