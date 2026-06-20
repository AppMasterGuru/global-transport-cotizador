"""
Tests for Open Transport SAC district-by-district delivery rates (Q7).

Source: "TARIFAS OPEN TRANSPORT 2025.pdf" (Client Data/Tarifarios/ and
Part 2_Abel/ — identical files, confirmed via diff before building this
module, per the project's audit-before-build rule). Rates are flat PEN
per delivery, by destination district, GENERAL vs IMO (hazardous cargo).
"""

from __future__ import annotations

import pytest

from core.open_transport_costs import (
    get_open_transport_rate_pen,
    get_open_transport_zone,
    list_open_transport_districts,
    open_transport_delivery_usd,
)


class TestGetOpenTransportZone:
    def test_known_district_zona1(self):
        zone = get_open_transport_zone("CALLAO")
        assert zone["zona"] == "ZONA 1"
        assert zone["general_pen"] == 550.0
        assert zone["imo_pen"] == 780.0

    def test_known_district_zona6(self):
        zone = get_open_transport_zone("HUARAL")
        assert zone["zona"] == "ZONA 6"
        assert zone["general_pen"] == 2000.0
        assert zone["imo_pen"] == 2800.0

    def test_case_and_whitespace_insensitive(self):
        zone = get_open_transport_zone("  callao  ")
        assert zone["general_pen"] == 550.0

    def test_unknown_district_raises(self):
        with pytest.raises(ValueError, match="Unknown Open Transport district"):
            get_open_transport_zone("ATLANTIS")


class TestGetOpenTransportRatePen:
    def test_general_rate(self):
        assert get_open_transport_rate_pen("LA MOLINA", hazardous=False) == 800.0

    def test_imo_rate(self):
        assert get_open_transport_rate_pen("LA MOLINA", hazardous=True) == 1120.0

    def test_default_is_general(self):
        assert get_open_transport_rate_pen("LA MOLINA") == 800.0


class TestListOpenTransportDistricts:
    def test_returns_all_59_districts(self):
        districts = list_open_transport_districts()
        assert len(districts) == 59

    def test_sorted_and_no_duplicates(self):
        districts = list_open_transport_districts()
        assert districts == sorted(districts)
        assert len(districts) == len(set(districts))

    def test_includes_known_districts(self):
        districts = list_open_transport_districts()
        assert "CALLAO" in districts
        assert "HUAROCHIRI" in districts


class TestOpenTransportDeliveryUsd:
    def test_converts_general_rate_to_usd(self):
        # CALLAO general = S/550, exchange_rate=3.72 (FALLBACK_EXCHANGE_RATE default)
        usd = open_transport_delivery_usd("CALLAO", hazardous=False, exchange_rate=3.72)
        assert usd == pytest.approx(147.85, rel=0.001)

    def test_converts_imo_rate_to_usd(self):
        usd = open_transport_delivery_usd("CALLAO", hazardous=True, exchange_rate=3.72)
        assert usd == pytest.approx(209.68, rel=0.001)

    def test_unknown_district_raises(self):
        with pytest.raises(ValueError):
            open_transport_delivery_usd("NARNIA", exchange_rate=3.72)
