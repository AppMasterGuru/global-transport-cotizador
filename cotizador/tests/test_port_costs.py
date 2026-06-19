"""
Tests for FCL port costs by terminal (APM vs DPW) — Abel Parte 2 (2026-06-19),
cross-checked against the official tariffs (Tarifario v1411, TARIFARIO
GENERAL 2025-11-15) in Client Data/Part 2_Abel/.

DPW: USD port charge (+IGV) + PEN "deposito temporal" service fee (+IGV).
APM: flat USD per container (+IGV), deposito temporal already included.
"""

from __future__ import annotations

import pytest

from core.port_costs import get_apm_port_cost, get_dpw_port_cost, get_port_cost


class TestDpwExport:
    def test_20std(self):
        c = get_dpw_port_cost("exportacion", "20STD")
        assert c["usd_port_usd"] == pytest.approx(118.21, rel=0.001)
        assert c["pen_deposito_temporal"] == pytest.approx(450.0, rel=0.001)

    def test_40std(self):
        c = get_dpw_port_cost("exportacion", "40STD")
        assert c["usd_port_usd"] == pytest.approx(228.53, rel=0.001)
        assert c["pen_deposito_temporal"] == pytest.approx(450.0, rel=0.001)

    def test_40hc_includes_surcharge(self):
        # 228.53 + 28.20 = 256.73
        c = get_dpw_port_cost("exportacion", "40HC")
        assert c["usd_port_usd"] == pytest.approx(256.73, rel=0.001)
        assert c["pen_deposito_temporal"] == pytest.approx(450.0, rel=0.001)


class TestDpwImport:
    def test_20std(self):
        c = get_dpw_port_cost("importacion", "20STD")
        assert c["usd_port_usd"] == pytest.approx(118.21, rel=0.001)
        assert c["pen_deposito_temporal"] == pytest.approx(600.0, rel=0.001)

    def test_40std(self):
        c = get_dpw_port_cost("importacion", "40STD")
        assert c["usd_port_usd"] == pytest.approx(228.53, rel=0.001)
        assert c["pen_deposito_temporal"] == pytest.approx(600.0, rel=0.001)

    def test_40hc_includes_surcharge(self):
        c = get_dpw_port_cost("importacion", "40HC")
        assert c["usd_port_usd"] == pytest.approx(256.73, rel=0.001)
        assert c["pen_deposito_temporal"] == pytest.approx(600.0, rel=0.001)


class TestApmExport:
    def test_20std(self):
        c = get_apm_port_cost("exportacion", "20STD")
        assert c["usd_port_usd"] == pytest.approx(243.10, rel=0.001)

    def test_40std(self):
        c = get_apm_port_cost("exportacion", "40STD")
        assert c["usd_port_usd"] == pytest.approx(375.70, rel=0.001)

    def test_40hc_same_as_40std(self):
        c = get_apm_port_cost("exportacion", "40HC")
        assert c["usd_port_usd"] == pytest.approx(375.70, rel=0.001)


class TestApmImport:
    def test_20std(self):
        c = get_apm_port_cost("importacion", "20STD")
        assert c["usd_port_usd"] == pytest.approx(334.75, rel=0.001)

    def test_40std_uses_official_tariff_489_95_not_abels_498_95(self):
        # Abel's note wrote 498.95; the official APM tariff (1.4.1.2) says
        # 489.95 — Barney cross-checked and confirmed 489.95 (TODO abel-Q2).
        c = get_apm_port_cost("importacion", "40STD")
        assert c["usd_port_usd"] == pytest.approx(489.95, rel=0.001)

    def test_40hc_same_as_40std(self):
        c = get_apm_port_cost("importacion", "40HC")
        assert c["usd_port_usd"] == pytest.approx(489.95, rel=0.001)


class TestGetPortCostDispatch:
    def test_dpw_dispatch(self):
        c = get_port_cost("DPW", "exportacion", "20STD")
        assert c["terminal"] == "DPW"
        assert c["usd_port_usd"] == pytest.approx(118.21, rel=0.001)

    def test_apm_dispatch(self):
        c = get_port_cost("APM", "importacion", "20STD")
        assert c["terminal"] == "APM"
        assert c["usd_port_usd"] == pytest.approx(334.75, rel=0.001)

    def test_dispatch_case_insensitive(self):
        c = get_port_cost("apm", "exportacion", "20STD")
        assert c["terminal"] == "APM"

    def test_unknown_terminal_raises(self):
        with pytest.raises(ValueError):
            get_port_cost("UNKNOWN", "exportacion", "20STD")

    def test_unknown_container_type_raises(self):
        with pytest.raises(ValueError):
            get_dpw_port_cost("exportacion", "20FOOT")

    def test_unknown_operation_raises(self):
        with pytest.raises(ValueError):
            get_apm_port_cost("transbordo", "20STD")
