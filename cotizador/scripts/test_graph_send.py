#!/usr/bin/env python3
"""
scripts/test_graph_send.py — Graph API end-to-end send test.

Tests:
  1. Token acquisition (client_credentials against Azure AD)
  2. Real email send from pricing@gt.com.pe to barney@timebackai.co
  3. Reports actor → from-address resolution for all 5 ejecutivos

Does NOT touch the main app or any database.

Usage:
    cd cotizador/
    source .venv/bin/activate
    python scripts/test_graph_send.py

Exit codes:
    0 — all checks passed, email sent successfully
    1 — token or send failed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

def _load_env(path: Path) -> None:
    if not path.exists():
        print(f"[WARN] .env not found at {path}")
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

_load_env(_ENV_PATH)

# ── Import after env load ─────────────────────────────────────────────────────
# Add cotizador/ to path so core/ imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub out audit() so we don't need a real DB
import types
_fake_db = types.ModuleType("core.db")
_fake_db.audit = lambda *a, **kw: None
sys.modules["core.db"] = _fake_db

from core.email_sender import (
    GRAPH_MODE,
    STUB_MODE,
    CREDENTIALS_ROTATED,
    _EJECUTIVOS,
    _DEFAULT_FROM,
    _get_access_token,
    _graph_send,
    resolve_from_address,
)

TEST_RECIPIENT = "barney@timebackai.co"


def print_header(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check_config() -> bool:
    print_header("1. Configuration check")
    from core.email_sender import _CLIENT_ID, _CLIENT_SECRET, _TENANT_ID
    ok = True
    for name, val in [
        ("GRAPH_CLIENT_ID",     _CLIENT_ID),
        ("GRAPH_TENANT_ID",     _TENANT_ID),
        ("GRAPH_CLIENT_SECRET", _CLIENT_SECRET),
    ]:
        status = "✓" if val else "✗ MISSING"
        print(f"  {status}  {name}")
        if not val:
            ok = False

    print(f"\n  GRAPH_MODE         : {GRAPH_MODE}")
    print(f"  STUB_MODE          : {STUB_MODE}")
    print(f"  CREDENTIALS_ROTATED: {CREDENTIALS_ROTATED}")
    return ok


def check_token() -> bool:
    print_header("2. Token acquisition")
    if STUB_MODE:
        print("  SKIP — Graph credentials not configured (STUB_MODE=True)")
        return False
    try:
        token = _get_access_token()
        print(f"  ✓  Token acquired ({len(token)} chars)")
        return True
    except Exception as exc:
        print(f"  ✗  Token failed: {exc}")
        return False


def check_address_resolution() -> None:
    print_header("3. Actor → from-address resolution")
    test_actors = [
        ("Abel",    "pricing@gt.com.pe"),
        ("Daniela", "lognet.sales@gt.com.pe"),
        ("Cielo",   "wca.sales@gt.com.pe"),
        ("JP",      "jparrue@gt.com.pe"),
        ("Renato",  "ralvarez@gt.com.pe"),
        ("Unknown", _DEFAULT_FROM),
    ]
    all_ok = True
    for actor, expected in test_actors:
        resolved = resolve_from_address(actor)
        match = resolved == expected
        status = "✓" if match else "✗"
        note = "" if match else f"  ← expected {expected!r}"
        print(f"  {status}  {actor:<12} → {resolved}{note}")
        if not match:
            all_ok = False
    return all_ok


def send_test_email() -> bool:
    print_header("4. Real send — pricing@gt.com.pe → barney@timebackai.co")
    if STUB_MODE:
        print("  SKIP — Graph credentials not configured (STUB_MODE=True)")
        return False

    from_address = resolve_from_address("Abel")
    subject      = "GT Cotizador — Graph API connection test"
    body         = (
        "This is an automated connection test from the GT Cotizador system.\n\n"
        "If you receive this message, the Microsoft Graph API Mail.Send "
        "permission is working correctly for:\n"
        f"  From : {from_address}\n"
        f"  To   : {TEST_RECIPIENT}\n\n"
        "No action required — this is not a real quote.\n\n"
        "— TimeBack AI · GT Pipeline #1"
    )

    try:
        _graph_send(from_address, TEST_RECIPIENT, subject, body)
        print(f"  ✓  Sent from {from_address}")
        print(f"  ✓  Check inbox: {TEST_RECIPIENT}")
        return True
    except Exception as exc:
        print(f"  ✗  Send failed: {exc}")
        return False


def main() -> int:
    print("\nGraph API send test — Global Transport Cotizador")
    print("=" * 60)

    cfg_ok    = check_config()
    token_ok  = check_token()
    check_address_resolution()
    send_ok   = send_test_email()

    print(f"\n{'=' * 60}")
    if STUB_MODE:
        print("  STUB MODE — Graph credentials not configured.")
        print("  Set GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, GRAPH_TENANT_ID in .env")
        return 1

    all_ok = cfg_ok and token_ok and send_ok
    if all_ok:
        print("  ✓  All checks passed. Graph API email is live.")
        if not CREDENTIALS_ROTATED:
            print()
            print("  ⚠  CREDENTIALS_ROTATED is not set.")
            print("     The Send button in the UI is disabled until you add:")
            print("     CREDENTIALS_ROTATED=true  to cotizador/.env")
            print("     Do this ONLY after rotating all 5 GT app passwords.")
    else:
        print("  ✗  One or more checks failed — see above.")

    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
