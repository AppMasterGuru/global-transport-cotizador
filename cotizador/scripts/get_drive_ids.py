"""
GT Cotizador — Get SharePoint Drive ID and TARIFAS Folder ID.

Uses client credentials flow (CLIENT_ID + CLIENT_SECRET) to authenticate
against GT's Microsoft Entra ID, then queries Graph API to find:
  - SHAREPOINT_DRIVE_ID   (JP's personal OneDrive)
  - TARIFAS_FOLDER_ID     (Documents/GLOBAL TRANSPORT - COMERCIAL/TARIFAS)

Requires admin consent to be granted for Files.Read.All and Sites.Read.All.

Run from cotizador/ directory:
    python scripts/get_drive_ids.py

Updates .env automatically with both IDs.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
_COTIZADOR_DIR = Path(__file__).parent.parent
_ENV_PATH      = _COTIZADOR_DIR / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH)
except ImportError:
    # Manual parse if dotenv not available
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import requests  # noqa: E402 — after path setup

# ── Config ────────────────────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("GRAPH_CLIENT_ID", "")
TENANT_ID     = os.getenv("GRAPH_TENANT_ID", "")
CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
GRAPH_BASE    = "https://graph.microsoft.com/v1.0"

# JP's OneDrive user path from the SharePoint URL:
#   /personal/jparrue_gt_com_pe → UPN = jparrue@gt.com.pe
JP_UPN        = "jparrue@gt.com.pe"
# In Graph API, the OneDrive root IS the "Documents" library —
# the SharePoint URL prefix /Documents/ maps to drive root, not a subfolder.
FOLDER_PATH   = "GLOBAL TRANSPORT - COMERCIAL/TARIFAS"


# ── Step 1: Get access token (client credentials) ─────────────────────────────

def get_app_token() -> str:
    """
    Client credentials grant — app-level auth (no user needed).
    Requires admin consent for Files.Read.All + Sites.Read.All.
    """
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
        "grant_type":    "client_credentials",
    }, timeout=15)

    if resp.status_code != 200:
        print(f"\n❌ Token error {resp.status_code}: {resp.text}")
        print("\nLikely cause: admin consent not yet granted.")
        print("Ask Vania's IT provider to grant consent at:")
        print(f"  https://login.microsoftonline.com/{TENANT_ID}/adminconsent")
        print(f"  ?client_id={CLIENT_ID}")
        sys.exit(1)

    token = resp.json().get("access_token", "")
    print("✅ Access token obtained (client credentials)")
    return token


# ── Step 2: Try candidate UPNs to find JP's drive ────────────────────────────

# The path segment 'jparrue_gt_com_pe' suggests UPN jparrue@gt.com.pe
# Also try onmicrosoft.com variant in case the custom domain isn't verified
CANDIDATE_UPNS = [
    "jparrue@gt.com.pe",
    "jparrue@globaltransportsac285.onmicrosoft.com",
]

def get_drive_id(token: str) -> tuple[str, str]:
    """
    Try each candidate UPN to find JP's personal OneDrive.
    Returns (drive_id, upn_that_worked).
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    for upn in CANDIDATE_UPNS:
        url  = f"{GRAPH_BASE}/users/{upn}/drive"
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 200:
            data     = resp.json()
            drive_id = data.get("id", "")
            drv_type = data.get("driveType", "?")
            owner    = data.get("owner", {}).get("user", {}).get("displayName", "?")
            print(f"✅ Drive found via UPN: {upn}")
            print(f"   Drive ID:   {drive_id}")
            print(f"   Drive type: {drv_type}")
            print(f"   Owner:      {owner}")
            return drive_id, upn

        print(f"   → {upn}: HTTP {resp.status_code} ({resp.json().get('error', {}).get('code', '?')})")

    # Fallback: try listing all drives (requires broader permissions)
    print("\n⚠️  Direct user lookup failed. Trying sites approach…")
    return _get_drive_via_site(token)


def _get_drive_via_site(token: str) -> tuple[str, str]:
    """
    Alternative: resolve via SharePoint site URL.
    Uses Sites.Read.All permission.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Resolve the personal OneDrive site
    site_url = "globaltransportsac285-my.sharepoint.com:/personal/jparrue_gt_com_pe:"
    url  = f"{GRAPH_BASE}/sites/{site_url}/drives"
    resp = requests.get(url, headers=headers, timeout=15)

    if resp.status_code == 200:
        drives = resp.json().get("value", [])
        if drives:
            drive_id = drives[0]["id"]
            print(f"✅ Drive found via site resolution")
            print(f"   Drive ID: {drive_id}")
            return drive_id, "site"
        print("❌ No drives found via site resolution.")
    else:
        print(f"❌ Site resolution failed: HTTP {resp.status_code}")
        print(f"   {resp.text[:400]}")

    sys.exit(1)


# ── Step 3: Get TARIFAS folder ID ─────────────────────────────────────────────

def get_tarifas_folder_id(token: str, drive_id: str) -> str:
    """
    Navigate to Documents/GLOBAL TRANSPORT - COMERCIAL/TARIFAS by path.
    Returns the folder item ID.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # URL-encode the path for the Graph API path query syntax
    encoded = requests.utils.quote(FOLDER_PATH, safe="/")
    url     = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}"
    resp    = requests.get(url, headers=headers, timeout=15)

    if resp.status_code == 200:
        data      = resp.json()
        folder_id = data.get("id", "")
        name      = data.get("name", "?")
        modified  = data.get("lastModifiedDateTime", "?")
        print(f"\n✅ TARIFAS folder found")
        print(f"   Folder ID:       {folder_id}")
        print(f"   Name:            {name}")
        print(f"   Last modified:   {modified}")
        return folder_id

    print(f"\n❌ TARIFAS folder not found: HTTP {resp.status_code}")
    print(f"   Tried path: {FOLDER_PATH}")
    err = resp.json().get("error", {})
    print(f"   Error: {err.get('code')} — {err.get('message')}")

    # Show what's at root so we can debug the path
    _debug_list_root(token, drive_id, headers)
    sys.exit(1)


def _debug_list_root(token: str, drive_id: str, headers: dict) -> None:
    """List root children to help debug path issues."""
    url  = f"{GRAPH_BASE}/drives/{drive_id}/root/children"
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code == 200:
        items = resp.json().get("value", [])
        print("\n   Root contents (to help debug path):")
        for item in items[:10]:
            print(f"     {'📁' if 'folder' in item else '📄'} {item['name']}")


# ── Step 4: List TARIFAS contents to verify ───────────────────────────────────

def list_tarifas_contents(token: str, drive_id: str, folder_id: str) -> None:
    """List files in TARIFAS to confirm rate cards are accessible."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url     = f"{GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/children"
    resp    = requests.get(url, headers=headers, timeout=15)

    if resp.status_code == 200:
        items = resp.json().get("value", [])
        print(f"\n📂 TARIFAS folder contents ({len(items)} items):")
        for item in items:
            size = item.get("size", 0)
            mod  = item.get("lastModifiedDateTime", "?")[:10]
            icon = "📁" if "folder" in item else "📄"
            print(f"   {icon} {item['name']:<50} {size:>10,} bytes  {mod}")
    else:
        print(f"\n⚠️  Could not list TARIFAS contents: HTTP {resp.status_code}")


# ── Step 5: Update .env ───────────────────────────────────────────────────────

def update_env(drive_id: str, folder_id: str) -> None:
    """Write SHAREPOINT_DRIVE_ID and TARIFAS_FOLDER_ID into .env."""
    env_text = _ENV_PATH.read_text(encoding="utf-8")

    def replace_var(text: str, key: str, value: str) -> str:
        pattern = rf"^({re.escape(key)}=).*$"
        replacement = rf"\g<1>{value}"
        new_text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
        if new_text == text:
            # Key not found — append it
            new_text = text.rstrip() + f"\n{key}={value}\n"
        return new_text

    env_text = replace_var(env_text, "SHAREPOINT_DRIVE_ID", drive_id)
    env_text = replace_var(env_text, "TARIFAS_FOLDER_ID",   folder_id)
    _ENV_PATH.write_text(env_text, encoding="utf-8")
    print(f"\n✅ .env updated")
    print(f"   SHAREPOINT_DRIVE_ID={drive_id}")
    print(f"   TARIFAS_FOLDER_ID={folder_id}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("GT Cotizador — Get SharePoint Drive + Folder IDs")
    print("=" * 60)

    if not (CLIENT_ID and TENANT_ID and CLIENT_SECRET):
        print("❌ Missing credentials in .env:")
        print(f"   GRAPH_CLIENT_ID={CLIENT_ID!r}")
        print(f"   GRAPH_TENANT_ID={TENANT_ID!r}")
        print(f"   GRAPH_CLIENT_SECRET={'***' if CLIENT_SECRET else '(empty)'}")
        sys.exit(1)

    print(f"\nClient ID:  {CLIENT_ID}")
    print(f"Tenant ID:  {TENANT_ID}")
    print(f"Target UPN: {JP_UPN}")
    print(f"Folder:     {FOLDER_PATH}")
    print()

    token     = get_app_token()
    drive_id, upn = get_drive_id(token)
    folder_id = get_tarifas_folder_id(token, drive_id)

    list_tarifas_contents(token, drive_id, folder_id)
    update_env(drive_id, folder_id)

    print("\n" + "=" * 60)
    print("DONE. Add these to .env (already written):")
    print(f"  SHAREPOINT_DRIVE_ID={drive_id}")
    print(f"  TARIFAS_FOLDER_ID={folder_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
