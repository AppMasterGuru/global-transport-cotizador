"""
Reference code generation and parsing.

Format: YY-MM-SEQ CLIENT INCOTERM STAFFCODE
Example: 26-05-011 Universal Cargo FOB GT-PC

Abel's system:
  YEAR (2 digits) + MONTH (2 digits) + SEQUENTIAL (3 digits, padded)
  + CLIENT NAME + INCOTERM + COMMERCIAL CODE

The reference code goes on every email subject to every provider.
It pulls all related emails into the folder automatically — Outlook
groups by subject prefix.

Staff codes:
  GT-PC   → pricing / commercial (default)
  GT-WCA  → WCA channel
  GT-LOG  → Lognet channel
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


STAFF_CODES: dict[str, str] = {
    "pricing": "GT-PC",
    "wca": "GT-WCA",
    "lognet": "GT-LOG",
}

DEFAULT_STAFF_CODE = "GT-PC"


def _next_seq(conn: sqlite3.Connection, year_month: str) -> int:
    """
    Atomically increment the sequence counter for year_month.
    Uses INSERT OR REPLACE + row update inside a transaction.
    Thread-safe within SQLite's serialised write model.
    """
    conn.execute(
        """
        INSERT INTO ref_counters (year_month, last_seq)
        VALUES (?, 1)
        ON CONFLICT(year_month) DO UPDATE SET last_seq = last_seq + 1
        """,
        (year_month,),
    )
    row = conn.execute(
        "SELECT last_seq FROM ref_counters WHERE year_month = ?",
        (year_month,),
    ).fetchone()
    return int(row[0])


def generate_reference(
    conn: sqlite3.Connection,
    client_name: str,
    incoterm: str,
    staff_code: str = DEFAULT_STAFF_CODE,
    now: datetime | None = None,
) -> str:
    """
    Generate the next reference code and persist the counter in the same
    transaction so concurrent callers never collide.

    Returns e.g. '26-05-011 Universal Cargo FOB GT-PC'
    """
    now = now or datetime.now()
    yy = now.strftime("%y")
    mm = now.strftime("%m")
    year_month = f"{yy}{mm}"

    with conn:
        seq = _next_seq(conn, year_month)

    seq_str = str(seq).zfill(3)
    client_clean = client_name.strip()
    incoterm_clean = incoterm.upper().strip()

    return f"{yy}-{mm}-{seq_str} {client_clean} {incoterm_clean} {staff_code}"


def parse_reference(ref: str) -> dict:
    """
    Parse a reference code back into its components.
    Input: '26-05-011 Universal Cargo FOB GT-PC'
    """
    # Split on space — first token is the date+seq part
    tokens = ref.split(" ")
    code_part = tokens[0]           # '26-05-011'
    segs = code_part.split("-")

    result: dict = {
        "raw": ref,
        "year": f"20{segs[0]}" if len(segs) > 0 else None,
        "month": segs[1] if len(segs) > 1 else None,
        "seq": int(segs[2]) if len(segs) > 2 else None,
        "client_name": None,
        "incoterm": None,
        "staff_code": None,
    }

    # Remaining tokens: CLIENT... INCOTERM STAFFCODE
    # STAFFCODE always starts with 'GT-'
    if len(tokens) >= 2:
        # Staff code is the last token if it starts with GT-
        if tokens[-1].startswith("GT-"):
            result["staff_code"] = tokens[-1]
            remaining = tokens[1:-1]
        else:
            remaining = tokens[1:]

        # Incoterm is a known 3-letter code in the remaining tokens
        from core.incoterms import VALID_INCOTERMS
        for i, tok in enumerate(remaining):
            if tok.upper() in VALID_INCOTERMS:
                result["incoterm"] = tok.upper()
                result["client_name"] = " ".join(remaining[:i]).strip() or None
                break
        else:
            result["client_name"] = " ".join(remaining).strip() or None

    return result
