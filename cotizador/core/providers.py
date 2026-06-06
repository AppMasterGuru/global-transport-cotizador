"""
Provider contact directory — DB-backed.

Seeded from DATA COLOADERS.xlsx on JP's OneDrive (confirmed 2026-05-15).
Companies: MSL CORPORATE, CRAFT, SACO, VANGUARD, ECU WORLDWIDE.

service_type values:
  lcl_impo  — LCL import pricing/sales
  lcl_expo  — LCL export pricing/sales
  air_impo  — Air import pricing/sales
  air_expo  — Air export pricing/sales
  general   — General sales (impo + expo, or unspecified)
"""

from __future__ import annotations

import re
from core.db import get_connection


# ── Normalise company name for matching ────────────────────────────────────────

_STOPWORDS = {"corporate", "del", "peru", "s.a.", "s.a.c.", "worldwide", "s.p.a."}

def _normalise(name: str) -> str:
    """Lower-case, strip trailing noise words so 'MSL CORPORATE' matches 'MSL'."""
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    return " ".join(w for w in words if w not in _STOPWORDS).strip()


# ── Service type inference from role text ─────────────────────────────────────

def _infer_service_type(role: str) -> str:
    if not role:
        return "general"
    r = role.upper()
    if "AIR" in r and "EXPORT" in r:
        return "air_expo"
    if "AIR" in r and ("IMPORT" in r or "IMPO" in r):
        return "air_impo"
    if "LCL" in r and "EXPORT" in r:
        return "lcl_expo"
    if "LCL" in r and ("IMPORT" in r or "IMPO" in r or "SALES SUPERVISOR" in r):
        return "lcl_impo"
    return "general"


# ── Seed ──────────────────────────────────────────────────────────────────────

def seed_providers(contacts: list[dict]) -> int:
    """
    Bulk-insert provider contacts.
    Each dict: {company, contact_name, role, email, phone}.
    Skips duplicates (same company + contact_name + email).
    Returns count inserted.
    """
    inserted = 0
    with get_connection() as conn:
        for c in contacts:
            company      = (c.get("company") or "").strip()
            contact_name = (c.get("contact_name") or "").strip()
            role         = (c.get("role") or "").strip()
            email        = (c.get("email") or "").strip()
            phone        = str(c.get("phone") or "").strip()
            if not company:
                continue
            service_type = _infer_service_type(role)

            # Skip exact duplicate (same company + contact + email)
            exists = conn.execute(
                "SELECT 1 FROM providers WHERE company=? AND contact_name=? AND email=?",
                (company, contact_name, email),
            ).fetchone()
            if exists:
                continue

            conn.execute(
                """INSERT INTO providers
                   (company, contact_name, role, email, phone, service_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (company, contact_name, role, email, phone, service_type),
            )
            inserted += 1
        conn.commit()
    return inserted


# ── Query ─────────────────────────────────────────────────────────────────────

def get_providers(
    company: str | None = None,
    service_type: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    """
    Return provider contacts. Optionally filter by company (fuzzy) and/or service_type.
    """
    clauses = []
    params: list = []
    if active_only:
        clauses.append("active = 1")
    if service_type:
        clauses.append("service_type = ?")
        params.append(service_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM providers {where} ORDER BY company, id", params
        ).fetchall()

    results = [dict(r) for r in rows]

    if company:
        needle = _normalise(company)
        results = [
            r for r in results
            if needle in _normalise(r["company"]) or _normalise(r["company"]) in needle
        ]
    return results


def get_provider_emails(company: str) -> list[str]:
    """
    Return all non-empty email addresses on file for a company (normalised match).
    Multiple addresses in one email field (semicolon-separated) are split individually.
    """
    contacts = get_providers(company=company)
    emails: list[str] = []
    for c in contacts:
        raw = c.get("email") or ""
        for addr in re.split(r"[;,]", raw):
            addr = addr.strip()
            if addr and "@" in addr:
                emails.append(addr)
    return list(dict.fromkeys(emails))  # deduplicate, preserve order


def get_company_names() -> list[str]:
    """Return sorted list of distinct company names in the providers table."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT company FROM providers WHERE active=1 ORDER BY company"
        ).fetchall()
    return [r[0] for r in rows]
