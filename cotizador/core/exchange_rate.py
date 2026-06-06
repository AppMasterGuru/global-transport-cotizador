"""
SBS (Superintendencia de Banca y Seguros) daily exchange rate.

Abel: "Internal conversion uses SBS exchange rate of the day."
Rate: USD → PEN (sell/venta rate).

Source: public SBS wrapper at apis.net.pe — widely used in Peru fintech.
Caches to disk so only one HTTP call per day.
Falls back to FALLBACK_EXCHANGE_RATE env var if API unreachable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

CACHE_DIR = Path(os.getenv("CACHE_DIR", "/tmp/gt_cotizador_cache"))
SBS_API_URL = os.getenv(
    "SBS_API_URL",
    "https://api.apis.net.pe/v1/tipo-cambio-sunat",
)
FALLBACK_RATE = float(os.getenv("FALLBACK_EXCHANGE_RATE", "3.72"))


def _cache_path(day: date) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"sbs_rate_{day.isoformat()}.json"


def _fetch_from_api() -> float:
    """One HTTP call to the SBS wrapper. Returns venta (sell) rate."""
    req = urllib.request.Request(
        SBS_API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "GT-Cotizador/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode())
    # Response: {"venta": "3.72", "compra": "3.70", "moneda": "Dólar", ...}
    return float(data["venta"])


def get_exchange_rate(today: date | None = None) -> float:
    """
    Return today's SBS USD→PEN sell rate.
    Reads from disk cache; fetches once per day; falls back gracefully.
    """
    today = today or date.today()
    cache_file = _cache_path(today)

    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        return float(cached["rate"])

    try:
        rate = _fetch_from_api()
        cache_file.write_text(
            json.dumps({"rate": rate, "date": today.isoformat(), "source": "sbs"}),
            encoding="utf-8",
        )
        return rate
    except (urllib.error.URLError, KeyError, ValueError, OSError):
        # Log fallback to separate file so it's auditable
        fallback_file = CACHE_DIR / "sbs_fallback_log.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": today.isoformat(),
            "rate": FALLBACK_RATE,
            "reason": "api_unreachable",
        }
        with fallback_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return FALLBACK_RATE


def soles_to_usd(soles: float, rate: float | None = None) -> float:
    """Convert PEN to USD using today's SBS rate (or the supplied rate)."""
    r = rate if rate is not None else get_exchange_rate()
    return soles / r


def usd_to_soles(usd: float, rate: float | None = None) -> float:
    r = rate if rate is not None else get_exchange_rate()
    return usd * r
