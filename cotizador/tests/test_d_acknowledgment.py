"""
Tests for multilingual auto-acknowledgment system — Build 2.

File is named test_d_*.py so pytest loads it AFTER test_core.py (alphabetically
test_c > test_d is wrong — 'c' < 'd' so test_core.py loads before test_d_*).
This ensures core/db.py is imported with the right DB_PATH set by test_core.py,
and test_core.py's fresh_db fixture wipes the correct file.

Covers:
  - detect_and_acknowledge() for 5 languages: ES, EN, DE, ZH, FR
  - Auto-trigger wiring in process_inbound_emails()
  - Ack queue mechanism (pending_acks.jsonl)
  - Language detection from raw text

All tests are offline — no ANTHROPIC_API_KEY required (stub mode).
Running total contribution: +16 tests (bringing 124 → 140).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ── CACHE_DIR for ack queue (must be set before imports use it) ───────────────
_tmp_cache = tempfile.mkdtemp()
os.environ["CACHE_DIR"] = _tmp_cache

# ── Imports (core.db already imported by test_core.py with correct DB_PATH) ───
from core.db import init_db  # noqa: E402
from core.acknowledgment import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    detect_and_acknowledge,
    generate_acknowledgment,
)
from core.email_listener import process_inbound_emails  # noqa: E402
from core.parser import detect_language  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Full DB isolation — uses get_connection() so it wipes the correct file."""
    from core.db import get_connection
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS credit_registry;
        """)
    init_db()
    yield


# ── Raw email fixtures (one per language) ────────────────────────────────────

_EMAILS = {
    "es": (
        "Buenos días,\n\n"
        "Mi nombre es Carlos Pérez de Lima Exports SAC. Necesitamos cotización "
        "para envío LCL desde Lima hasta Madrid, España. Mercancía: prendas de "
        "vestir, 500 kg, 3 CBM, incoterm FOB.\n\n"
        "Muchas gracias,\nCarlos Pérez"
    ),
    "en": (
        "Hello,\n\n"
        "I'm Sarah Johnson from Miami Cargo LLC. We need a quote for air freight "
        "from Lima, Peru to Miami, USA. Commodity: fresh asparagus, 350 kg, 2 CBM, "
        "Incoterm DAP Miami. Urgent.\n\n"
        "Best regards,\nSarah Johnson\nsarah@miamicargo.com"
    ),
    "de": (
        "Sehr geehrte Damen und Herren,\n\n"
        "mein Name ist Hans Müller von Berlin Trade GmbH. Wir benötigen eine "
        "Offerte für Luftfracht von Frankfurt nach Lima. Sendung: Medizingeräte, "
        "320 kg, 1.8 CBM, Incoterm DAP Lima. Dringend.\n\n"
        "Mit freundlichen Grüßen,\nHans Müller"
    ),
    "zh": (
        "您好，\n\n"
        "我是王伟，来自北京贸易有限公司。我们需要从利马到上海的LCL集装箱运输报价。"
        "货物：有机藜麦，重量2000公斤，体积8CBM，贸易术语FOB。\n\n"
        "谢谢,\n王伟"
    ),
    "fr": (
        "Monsieur, Madame,\n\n"
        "Je suis Pierre Dupont de Paris Logistics SA. Nous avons besoin d'une "
        "cotation pour une expédition LCL de Lima vers Paris. Marchandise: "
        "quinoa bio, 800 kg, 4 CBM, incoterm FOB. "
        "Veuillez nous envoyer votre offre rapidement.\n\n"
        "Cordialement,\nPierre Dupont"
    ),
}


# ── Tests: detect_language ────────────────────────────────────────────────────


class TestLanguageDetection:
    def test_detect_spanish(self):
        lang = detect_language(_EMAILS["es"])
        assert lang == "es"

    def test_detect_english(self):
        lang = detect_language(_EMAILS["en"])
        assert lang == "en"

    def test_detect_german(self):
        lang = detect_language(_EMAILS["de"])
        assert lang == "de"

    def test_detect_chinese(self):
        lang = detect_language(_EMAILS["zh"])
        assert lang == "zh"

    def test_detect_french(self):
        lang = detect_language(_EMAILS["fr"])
        assert lang == "fr"


# ── Tests: detect_and_acknowledge — 5 languages ──────────────────────────────


class TestDetectAndAcknowledge:
    def _check_ack_structure(self, ack: dict) -> None:
        """Assert the required keys and types are present."""
        assert isinstance(ack, dict)
        assert "subject" in ack,        "Missing 'subject'"
        assert "body" in ack,           "Missing 'body'"
        assert "language" in ack,       "Missing 'language'"
        assert "detected_topic" in ack, "Missing 'detected_topic'"
        assert "response_hours" in ack, "Missing 'response_hours'"
        assert len(ack["body"]) > 20,   "Body too short"
        # Body must contain a reference to GT
        assert "Global Transport" in ack["body"]

    def test_spanish_ack(self):
        ack = detect_and_acknowledge(_EMAILS["es"])
        self._check_ack_structure(ack)
        assert ack["language"] == "es"

    def test_english_ack(self):
        ack = detect_and_acknowledge(_EMAILS["en"])
        self._check_ack_structure(ack)
        assert ack["language"] == "en"

    def test_german_ack(self):
        ack = detect_and_acknowledge(_EMAILS["de"])
        self._check_ack_structure(ack)
        assert ack["language"] == "de"
        assert "Eingangsbestätigung" in ack["subject"]

    def test_chinese_ack(self):
        ack = detect_and_acknowledge(_EMAILS["zh"])
        self._check_ack_structure(ack)
        assert ack["language"] == "zh"

    def test_french_ack(self):
        ack = detect_and_acknowledge(_EMAILS["fr"])
        self._check_ack_structure(ack)
        assert ack["language"] == "fr"

    def test_urgent_email_gets_2h_sla(self):
        ack = detect_and_acknowledge(_EMAILS["en"])  # contains "Urgent"
        assert ack["response_hours"] == 2

    def test_non_urgent_email_gets_4h_sla(self):
        ack = detect_and_acknowledge(_EMAILS["es"])  # no urgency markers
        assert ack["response_hours"] == 4

    def test_custom_staff_name_appears_in_body(self):
        ack = detect_and_acknowledge(
            _EMAILS["en"], staff_name="Abel Díaz Peralta"
        )
        assert "Abel Díaz Peralta" in ack["body"]

    def test_all_6_languages_in_supported_list(self):
        for lang in ("es", "en", "de", "zh", "fr", "pt"):
            assert lang in SUPPORTED_LANGUAGES


# ── Tests: process_inbound_emails + auto-ack wiring ──────────────────────────


class TestEmailListenerAutoAck:
    def test_process_emails_returns_ack_key(self):
        """Each parsed email must have _ack attached."""
        results = process_inbound_emails(auto_ack=True)
        assert len(results) == 3
        for r in results:
            assert "_ack" in r, "Missing _ack key on parsed email result"

    def test_ack_has_correct_language_per_email(self):
        """Ack language must match the email's detected language."""
        results = process_inbound_emails(auto_ack=True)
        for r in results:
            ack = r["_ack"]
            if ack:  # ack may be empty dict on error
                assert "language" in ack
                assert ack["language"] == r.get("detected_language")

    def test_process_without_auto_ack(self):
        """auto_ack=False must still return parsed results; ack is empty dict."""
        results = process_inbound_emails(auto_ack=False)
        assert len(results) == 3
        for r in results:
            assert r["_ack"] == {}

    def test_pending_acks_queued_to_file(self):
        """After processing, pending_acks.jsonl must exist with 3 entries."""
        # Clear any queue left by previous tests in this session
        queue_path = Path(os.environ.get("CACHE_DIR", _tmp_cache)) / "pending_acks.jsonl"
        if queue_path.exists():
            queue_path.unlink()

        process_inbound_emails(auto_ack=True)

        assert queue_path.exists(), f"pending_acks.jsonl not created at {queue_path}"
        lines = queue_path.read_text(encoding="utf-8").strip().split("\n")
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) >= 3

        # Each line must be valid JSON with required keys
        for line in non_empty:
            entry = json.loads(line)
            assert "ts" in entry
            assert "language" in entry
            assert "subject" in entry
            assert "body" in entry
