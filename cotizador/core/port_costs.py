"""
FCL port costs by terminal (APM vs DPW).

Source: Abel Parte 2 (2026-06-19), cross-checked against the official
tariffs (Tarifario v1411 Clean HR 05052026, TARIFARIO GENERAL — 15 nov 2025)
in Client Data/Part 2_Abel/.

DPW charges a USD port fee (+IGV) PLUS a separate PEN "deposito temporal"
service fee (+IGV) that depends on operation (export S/450, import S/600).
APM charges a single flat USD fee per container (+IGV); deposito temporal
is already folded into that figure for the bracket Abel quoted (export
<=7 dias DT, import standard DT plan).

All USD/PEN figures below are pre-IGV net. IGV is applied once, by the
costing/PDF layer, matching the rest of the cotizador's cost model.
"""

from __future__ import annotations

_CONTAINER_TYPES = ("20STD", "40STD", "40HC")
_OPERATIONS = ("exportacion", "importacion")

DPW_PORT_COSTS: dict[str, dict[str, dict]] = {
    "exportacion": {
        "20STD": {"usd_port": 118.21, "pen_deposito": 450.0},
        "40STD": {"usd_port": 228.53, "pen_deposito": 450.0},
        "40HC":  {"usd_port": 228.53, "usd_hc_surcharge": 28.20, "pen_deposito": 450.0},
    },
    "importacion": {
        "20STD": {"usd_port": 118.21, "pen_deposito": 600.0},
        "40STD": {"usd_port": 228.53, "pen_deposito": 600.0},
        "40HC":  {"usd_port": 228.53, "usd_hc_surcharge": 28.20, "pen_deposito": 600.0},
    },
}

APM_PORT_COSTS: dict[str, dict[str, float]] = {
    "exportacion": {
        "20STD": 243.10,
        "40STD": 375.70,
        "40HC":  375.70,
    },
    "importacion": {
        "20STD": 334.75,
        # TODO(abel-Q2): Abel's note wrote 498.95 for APM import 40' but the
        # official APM tariff (clause 1.4.1.2) says 489.95. Using 489.95 per
        # Barney's cross-check against the official tariff PDF (2026-06-19).
        "40STD": 489.95,
        "40HC":  489.95,
    },
}


def get_dpw_port_cost(operation: str, container_type: str) -> dict:
    """
    DPW port cost breakdown — USD port charge + PEN deposito temporal,
    both pre-IGV. operation: 'exportacion'|'importacion'.
    container_type: '20STD'|'40STD'|'40HC'.
    """
    if operation not in DPW_PORT_COSTS:
        raise ValueError(f"Unknown operation: {operation!r} (expected {_OPERATIONS})")
    if container_type not in DPW_PORT_COSTS[operation]:
        raise ValueError(f"Unknown container_type: {container_type!r} (expected {_CONTAINER_TYPES})")
    entry = DPW_PORT_COSTS[operation][container_type]
    usd_total = entry["usd_port"] + entry.get("usd_hc_surcharge", 0.0)
    return {
        "terminal": "DPW",
        "operation": operation,
        "container_type": container_type,
        "usd_port_usd": round(usd_total, 2),
        "pen_deposito_temporal": entry["pen_deposito"],
    }


def get_apm_port_cost(operation: str, container_type: str) -> dict:
    """APM port cost — single flat USD fee, pre-IGV (deposito temporal included)."""
    if operation not in APM_PORT_COSTS:
        raise ValueError(f"Unknown operation: {operation!r} (expected {_OPERATIONS})")
    if container_type not in APM_PORT_COSTS[operation]:
        raise ValueError(f"Unknown container_type: {container_type!r} (expected {_CONTAINER_TYPES})")
    usd_total = APM_PORT_COSTS[operation][container_type]
    return {
        "terminal": "APM",
        "operation": operation,
        "container_type": container_type,
        "usd_port_usd": round(usd_total, 2),
    }


def get_port_cost(terminal: str, operation: str, container_type: str) -> dict:
    """Dispatch to get_dpw_port_cost() or get_apm_port_cost() by terminal name."""
    terminal_u = terminal.strip().upper()
    if terminal_u == "DPW":
        return get_dpw_port_cost(operation, container_type)
    if terminal_u == "APM":
        return get_apm_port_cost(operation, container_type)
    raise ValueError(f"Unknown terminal: {terminal!r} (expected APM or DPW)")
