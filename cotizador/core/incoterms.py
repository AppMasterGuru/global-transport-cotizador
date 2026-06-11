"""
Incoterm classifier and cost-routing logic.

Abel's rule: "Cotizamos en base a lo que son los incoterms. Cada embarque
diferente tiene un incoterm diferente y dependiendo de este incoterm es en
donde se aumentan o se disminuyen los costos."

Each incoterm maps to a set of cost components that Global Transport includes
in the quote. This drives which line items appear in the costeo and venta.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class IncotermError(ValueError):
    pass


VALID_INCOTERMS = frozenset([
    "EXW", "FCA", "FOB", "CFR", "CIF",
    "CPT", "CIP", "DAP", "DDU", "DDP",
])


@dataclass(frozen=True)
class CostComponents:
    """Which cost components Global Transport charges for a given incoterm."""
    flete_internacional: bool = True    # International freight
    visto_bueno: bool = True            # Consolidator port-release fee (LCL)
    origen_charges: bool = True         # Origin port / handling
    agente_aduana: bool = True          # Customs agent
    transporte_local: bool = True       # Last-mile local delivery
    seguro: bool = False                # Marine insurance (CIF/CIP)
    derechos_importacion: bool = False  # Import duties (DDP only)


# Mapping built from Abel's demo and standard Incoterms 2020 logic.
# Global Transport is typically the freight forwarder on the exporter side (Lima).
INCOTERM_COMPONENTS: dict[str, CostComponents] = {
    # EXW: buyer picks up at seller's door — GT handles everything
    "EXW": CostComponents(
        flete_internacional=True, visto_bueno=True, origen_charges=True,
        agente_aduana=True, transporte_local=True,
    ),
    # FCA: seller delivers to named carrier — origin charges not GT's
    "FCA": CostComponents(
        flete_internacional=True, visto_bueno=True, origen_charges=False,
        agente_aduana=True, transporte_local=True,
    ),
    # FOB: seller delivers to port of loading — most common for LCL exports
    "FOB": CostComponents(
        flete_internacional=True, visto_bueno=True, origen_charges=False,
        agente_aduana=True, transporte_local=True,
    ),
    # CFR: seller pays freight to destination — no insurance, no local delivery
    "CFR": CostComponents(
        flete_internacional=False, visto_bueno=True, origen_charges=False,
        agente_aduana=True, transporte_local=True,
    ),
    # CIF: CFR + insurance
    "CIF": CostComponents(
        flete_internacional=False, visto_bueno=True, origen_charges=False,
        agente_aduana=True, transporte_local=True, seguro=True,
    ),
    # CPT: seller pays carriage to named destination
    "CPT": CostComponents(
        flete_internacional=False, visto_bueno=True, origen_charges=False,
        agente_aduana=True, transporte_local=True,
    ),
    # CIP: CPT + insurance
    "CIP": CostComponents(
        flete_internacional=False, visto_bueno=True, origen_charges=False,
        agente_aduana=True, transporte_local=True, seguro=True,
    ),
    # DAP: seller delivers to destination — buyer handles customs
    "DAP": CostComponents(
        flete_internacional=False, visto_bueno=False, origen_charges=False,
        agente_aduana=False, transporte_local=False,
    ),
    # DDU: seller delivers to destination, buyer handles customs/import duties
    "DDU": CostComponents(
        flete_internacional=False, visto_bueno=False, origen_charges=False,
        agente_aduana=False, transporte_local=False,
    ),
    # DDP: maximum seller responsibility — GT handles customs + import duties
    "DDP": CostComponents(
        flete_internacional=False, visto_bueno=False, origen_charges=False,
        agente_aduana=True, transporte_local=False, derechos_importacion=True,
    ),
}


def validate(incoterm: str) -> str:
    """Return the canonical uppercase incoterm or raise IncotermError."""
    key = incoterm.upper().strip()
    if key not in VALID_INCOTERMS:
        raise IncotermError(
            f"Unknown incoterm: {incoterm!r}. Valid: {sorted(VALID_INCOTERMS)}"
        )
    return key


def get_cost_components(incoterm: str) -> CostComponents:
    return INCOTERM_COMPONENTS[validate(incoterm)]


def classify_incoterm(incoterm: str) -> dict:
    """Return structured classification dict (suitable for JSON serialisation)."""
    key = validate(incoterm)
    c = INCOTERM_COMPONENTS[key]
    return {
        "incoterm": key,
        "components": {
            "flete_internacional": c.flete_internacional,
            "visto_bueno": c.visto_bueno,
            "origen_charges": c.origen_charges,
            "agente_aduana": c.agente_aduana,
            "transporte_local": c.transporte_local,
            "seguro": c.seguro,
            "derechos_importacion": c.derechos_importacion,
        },
    }


def active_components(incoterm: str) -> list[str]:
    """Return list of component names that are True for this incoterm."""
    c = get_cost_components(incoterm)
    return [name for name, active in vars(c).items() if active]
