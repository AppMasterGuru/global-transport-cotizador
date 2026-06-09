#!/usr/bin/env python3
"""
scripts/test_smtp.py — SMTP connection test for all five GT ejecutivo accounts.

Tests STARTTLS login to smtp.office365.com:587 for each account.
Does NOT send any email — only authenticates and disconnects.

Exit codes:
    0 — all accounts authenticated successfully
    1 — one or more accounts failed

Usage:
    cd cotizador/
    source .venv/bin/activate
    python scripts/test_smtp.py
"""

from __future__ import annotations

import os
import smtplib
import sys
from pathlib import Path

# ── Load .env from cotizador root ─────────────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

def _load_env(path: Path) -> None:
    if not path.exists():
        print(f"[WARN] .env not found at {path} — relying on shell environment")
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

_load_env(_ENV_PATH)

# ── Account table (env-key-suffix → display name) ────────────────────────────
_ACCOUNTS = [
    ("ABEL",   "Abel Díaz Peralta"),
    ("DANIELA","Daniella Leveau"),
    ("CIELO",  "Cielo Cuellar"),
    ("JP",     "Jean Paul Arrue"),
    ("RENATO", "Renato Alvarez"),
]

_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))


def _test_account(key: str, display: str) -> tuple[bool, str]:
    """
    Attempt STARTTLS SMTP login for one account.
    Returns (success: bool, message: str).
    Does not send any email.
    """
    user = os.getenv(f"SMTP_USER_{key}", "")
    password = os.getenv(f"SMTP_PASS_{key}", "")

    if not user or not password:
        return False, f"credentials missing (SMTP_USER_{key} / SMTP_PASS_{key} not set)"

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            # Explicit quit — do not send anything
            smtp.quit()
        return True, f"authenticated as {user}"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"authentication failed for {user}: {e.smtp_error!r}"
    except smtplib.SMTPException as e:
        return False, f"SMTP error for {user}: {e}"
    except OSError as e:
        return False, f"connection error ({_SMTP_HOST}:{_SMTP_PORT}): {e}"


def main() -> int:
    print(f"\nSMTP connection test — {_SMTP_HOST}:{_SMTP_PORT} STARTTLS")
    print("=" * 62)

    results: list[tuple[str, str, bool, str]] = []
    for key, display in _ACCOUNTS:
        ok, msg = _test_account(key, display)
        results.append((key, display, ok, msg))
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}  {display:<22}  {msg}")

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed

    print("=" * 62)
    print(f"  {passed}/{len(results)} accounts passed")

    if failed:
        print(f"\n  {failed} account(s) FAILED — do not deploy until resolved.\n")
        return 1

    print("\n  All accounts authenticated. Safe to wire into the app.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
