"""
GT ISO 9001 Procedures — Google Drive Reader.

Reads procedure documents from GT's ISO 9001 Google Drive folder.
URL: https://drive.google.com/drive/folders/17uWrMaZXXF-mDuXOgZKmaSvX2Xx-sS_S

ACTIVATION: This module activates when GOOGLE_SERVICE_ACCOUNT_JSON is set in .env.
  GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/service_account.json
  (obtain from Google Cloud Console → IAM → Service Accounts → Keys)

STUB MODE: When GOOGLE_SERVICE_ACCOUNT_JSON is not set, returns the hardcoded
  procedure version from procedures.rules — no network call, no error.

NEXT STEP TO WIRE (when credentials are available):
  1. Create Google Cloud project
  2. Enable Google Drive API
  3. Create service account → download JSON key
  4. Share the GT ISO 9001 Drive folder with the service account email
  5. Add GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/key.json to .env
  6. Call read_procedures_folder() to fetch live document list
"""

from __future__ import annotations

import os
from pathlib import Path

# Folder URL saved in .env as ISO_GOOGLE_DRIVE_URL
ISO_DRIVE_FOLDER_URL: str = os.getenv(
    "ISO_GOOGLE_DRIVE_URL",
    "https://drive.google.com/drive/folders/17uWrMaZXXF-mDuXOgZKmaSvX2Xx-sS_S",
)

# Extract folder ID from URL
_FOLDER_ID = ISO_DRIVE_FOLDER_URL.rstrip("/").split("/")[-1]

# Google Drive API credentials path (from .env)
_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Whether we're in stub mode
DRIVE_AVAILABLE: bool = bool(_SERVICE_ACCOUNT_JSON and Path(_SERVICE_ACCOUNT_JSON).exists())


def get_procedure_folder_id() -> str:
    """Return the ISO 9001 Google Drive folder ID."""
    return _FOLDER_ID


def read_procedures_folder() -> list[dict]:
    """
    List all files in the ISO 9001 procedures Google Drive folder.

    Returns:
        List of dicts: [{id, name, mimeType, modifiedTime, webViewLink}, ...]

    STUB MODE: Returns an empty list when credentials are not configured.
    Logs a warning but does NOT raise — the cotizador continues to work
    without Drive integration using the hardcoded procedure rules.
    """
    if not DRIVE_AVAILABLE:
        return []

    try:
        return _live_read_folder()
    except Exception as exc:
        # Drive failure is non-fatal — fall back gracefully
        import warnings
        warnings.warn(
            f"Google Drive procedure read failed: {exc}. "
            "Cotizador will use hardcoded procedure rules (GT-PROC-1.0).",
            stacklevel=2,
        )
        return []


def _live_read_folder() -> list[dict]:
    """
    Fetch file list from Google Drive API.
    Only called when GOOGLE_SERVICE_ACCOUNT_JSON is configured.
    """
    # Lazy imports — only needed when Drive is configured
    from google.oauth2 import service_account  # type: ignore[import]
    from googleapiclient.discovery import build  # type: ignore[import]

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = service_account.Credentials.from_service_account_file(
        _SERVICE_ACCOUNT_JSON, scopes=SCOPES
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    results = service.files().list(
        q=f"'{_FOLDER_ID}' in parents and trashed=false",
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
        pageSize=100,
    ).execute()

    return results.get("files", [])


def is_drive_configured() -> bool:
    """Return True when Google Drive API credentials are present and valid path."""
    return DRIVE_AVAILABLE
