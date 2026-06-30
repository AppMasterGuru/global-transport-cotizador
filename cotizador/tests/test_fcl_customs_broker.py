"""
Tests for the FCL Agente Internacional customs broker (agenciamiento de
aduana) calculated concept — Session L (§3).

The broker fee is a percentage of CIF with a per-broker minimum floor, net
of IGV (IGV is applied once by the render layer, same as every other concept):

  - Alefero: comisión = max(0.0035 × CIF, 110.00)
  - OEA:     comisión = max(0.0020 × CIF, 80.00)

Driven by the broker already selectable in the system via requires_oea_basc.
"""

from __future__ import annotations

import pytest

from core.fcl_customs_broker import (
    BROKER_RATES,
    agente_customs_broker_fee,
    broker_name_from_flag,
)


class TestBrokerNameFromFlag:
    def test_oea_basc_flag_true_selects_oea(self):
        assert broker_name_from_flag(True) == "OEA"

    def test_oea_basc_flag_false_selects_alefero(self):
        assert broker_name_from_flag(False) == "ALEFERO"


class TestAleferoFee:
    def test_percentage_above_floor(self):
        # 0.0035 × 100,000 = 350.00 (well above the 110 floor)
        assert agente_customs_broker_fee("ALEFERO", 100_000.0) == 350.0

    def test_floor_applies_on_low_cif(self):
        # 0.0035 × 10,000 = 35.00 → floored to 110.00
        assert agente_customs_broker_fee("ALEFERO", 10_000.0) == 110.0

    def test_floor_applies_on_zero_cif(self):
        assert agente_customs_broker_fee("ALEFERO", 0.0) == 110.0

    def test_exact_floor_boundary(self):
        # CIF where 0.0035 × CIF == 110.00 exactly (CIF = 31,428.57...)
        cif = 110.0 / 0.0035
        assert agente_customs_broker_fee("ALEFERO", cif) == 110.0

    def test_case_insensitive(self):
        assert agente_customs_broker_fee("alefero", 100_000.0) == 350.0


class TestOeaFee:
    def test_percentage_above_floor(self):
        # 0.0020 × 100,000 = 200.00 (above the 80 floor)
        assert agente_customs_broker_fee("OEA", 100_000.0) == 200.0

    def test_floor_applies_on_low_cif(self):
        # 0.0020 × 10,000 = 20.00 → floored to 80.00
        assert agente_customs_broker_fee("OEA", 10_000.0) == 80.0

    def test_floor_applies_on_zero_cif(self):
        assert agente_customs_broker_fee("OEA", 0.0) == 80.0

    def test_case_insensitive(self):
        assert agente_customs_broker_fee("oea", 100_000.0) == 200.0


class TestUnknownBroker:
    def test_unknown_broker_raises(self):
        with pytest.raises(ValueError):
            agente_customs_broker_fee("UNKNOWN", 100_000.0)


class TestRateCards:
    def test_alefero_rate_card(self):
        assert BROKER_RATES["ALEFERO"] == (0.0035, 110.0)

    def test_oea_rate_card(self):
        assert BROKER_RATES["OEA"] == (0.0020, 80.0)
