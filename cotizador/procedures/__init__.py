"""
GT ISO 9001 Procedures — public API.

Business rules codified from:
  - GT SIG ISO 9001 procedures (Google Drive, access confirmed 2026-05-15)
  - Abel Díaz Peralta operational demo (2026-05-07)
  - Jean Paul Arrue business review (2026-04-29)

BASC requirement: every quote must log PROCEDURE_VERSION to the audit trail.
See procedures.rules.PROCEDURE_VERSION.

Usage:
    from procedures import (
        PROCEDURE_VERSION,
        validate_margin,
        validate_mode,
        validate_incoterm,
        validate_cargo,
        requires_oea_basc_agent,
        get_response_sla_hours,
        run_all_checks,
        ProcedureViolation,
    )
"""

from procedures.rules import (
    PROCEDURE_VERSION,
    ProcedureViolation,
    get_response_sla_hours,
    requires_oea_basc_agent,
    run_all_checks,
    validate_cargo,
    validate_incoterm,
    validate_margin,
    validate_mode,
)

__all__ = [
    "PROCEDURE_VERSION",
    "ProcedureViolation",
    "validate_margin",
    "validate_mode",
    "validate_incoterm",
    "validate_cargo",
    "requires_oea_basc_agent",
    "get_response_sla_hours",
    "run_all_checks",
]
