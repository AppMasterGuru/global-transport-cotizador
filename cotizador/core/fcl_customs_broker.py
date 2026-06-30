"""
FCL Agente Internacional customs broker (agenciamiento de aduana) — Session L.

On the agente_internacional path the broker fee is a CALCULATED line: a
percentage of the CIF value with a per-broker minimum floor. The amount is
net of IGV — IGV (18%) is applied once by the render layer, the same as
every other local concept in the cotizador.

  - Alefero: comisión = max(0.0035 × CIF, 110.00)
  - OEA:     comisión = max(0.0020 × CIF, 80.00)

The broker is the one already selectable in the system through the
requires_oea_basc flag (OEA when set, Alefero otherwise) — see
core.fcl_naviera_costs.fcl_customs_agent_costs for the FCL agent dispatch.

NOTE (Session L assumption, on the record for F3/F4): each broker uses its
own rate card above. The gastos operativos USD 20 and precinto USD 5 seen
on the OEA card are treated as the SAME lines already present in the quote
(Operative Charge / seal), NOT added again here — i.e. this fee is the
commission only, with no double-counting. This is the no-overcharge default;
F3/F4 will correct if those should instead be additive.
"""

from __future__ import annotations

# broker name -> (rate as fraction of CIF, minimum floor in USD, net of IGV)
BROKER_RATES: dict[str, tuple[float, float]] = {
    "ALEFERO": (0.0035, 110.0),
    "OEA":     (0.0020, 80.0),
}


def broker_name_from_flag(requires_oea_basc: bool) -> str:
    """Map the existing requires_oea_basc selector to a broker name."""
    return "OEA" if requires_oea_basc else "ALEFERO"


def agente_customs_broker_fee(broker: str, cif_usd: float) -> float:
    """
    Net (pre-IGV) broker commission for the agente path: a percentage of CIF
    floored at the broker's minimum. IGV is applied later by the render layer.

    Raises ValueError on an unknown broker name (no silent default).
    """
    key = broker.strip().upper()
    if key not in BROKER_RATES:
        raise ValueError(
            f"Unknown broker {broker!r} (expected one of {sorted(BROKER_RATES)})"
        )
    rate, floor = BROKER_RATES[key]
    return round(max(rate * cif_usd, floor), 2)
