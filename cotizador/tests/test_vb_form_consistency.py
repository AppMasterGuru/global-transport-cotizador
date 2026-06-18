"""
Regression guard for the New Quote form / engine VB drift bug (found 2026-06-18).

Bug: templates/new_quote.html kept its own copy of consolidator VB rates
(VB_RATES, used only for a hint) PLUS a static numeric default for the
Section 4 "Visto Bueno" line item (valor: 90 / valor: 160), set once by
operation only — never by consolidator. Because the form always submits
a "Visto Bueno" local item, api/routes.py suppresses its own correct
engine computation (core.transport.CONSOLIDATORS) and uses the form's
static value instead. When CRAFT/SACO import VB diverged from the old
uniform 90 (Abel 2026-06-18), the quoted venta silently kept charging 90
while the recorded cost correctly showed 160/190.

These tests pin two invariants so this can't silently regress:
  1. The JS VB_RATES table must always match core.transport.CONSOLIDATORS.
  2. The Section 4 "Visto Bueno" default must be computed from that table,
     never a bare numeric literal.
"""

import re
from pathlib import Path

import pytest

from core.transport import CONSOLIDATORS

_TEMPLATE = Path(__file__).parent.parent / "templates" / "new_quote.html"


@pytest.fixture(scope="module")
def template_src() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def _js_vb_rates(src: str) -> dict:
    block_match = re.search(r"var VB_RATES\s*=\s*\{(.*?)\};", src, re.S)
    assert block_match, "VB_RATES table not found in new_quote.html"
    block = block_match.group(1)
    rates = {}
    for m in re.finditer(
        r"(\w+):\s*\{\s*exportacion:\s*(\d+(?:\.\d+)?)\s*,\s*importacion:\s*(\d+(?:\.\d+)?)\s*\}",
        block,
    ):
        cons, export_v, import_v = m.group(1), float(m.group(2)), float(m.group(3))
        rates[cons] = {"exportacion": export_v, "importacion": import_v}
    return rates


class TestJsVbRatesMatchEngine:
    """The hint table must never drift from core.transport.CONSOLIDATORS."""

    def test_all_engine_consolidators_present_in_js_table(self, template_src):
        js_rates = _js_vb_rates(template_src)
        for key in ("MSL", "CRAFT", "SACO", "EQ"):
            assert key in js_rates, f"{key} missing from JS VB_RATES table"

    @pytest.mark.parametrize("key", ["MSL", "CRAFT", "SACO", "EQ"])
    def test_js_rate_matches_engine_rate(self, template_src, key):
        js_rates = _js_vb_rates(template_src)
        engine = CONSOLIDATORS[key]
        assert js_rates[key]["exportacion"] == engine["visto_bueno_export_usd"], (
            f"{key} export: JS={js_rates[key]['exportacion']} "
            f"engine={engine['visto_bueno_export_usd']}"
        )
        assert js_rates[key]["importacion"] == engine["visto_bueno_import_usd"], (
            f"{key} import: JS={js_rates[key]['importacion']} "
            f"engine={engine['visto_bueno_import_usd']}"
        )


class TestVistoBuenoDefaultIsDynamic:
    """The Section 4 default must never hardcode a bare number again."""

    def test_no_bare_numeric_literal_for_visto_bueno_default(self, template_src):
        bare_literal = re.search(
            r"concept:\s*'Visto Bueno',\s*valor:\s*\d", template_src
        )
        assert bare_literal is None, (
            "Found a hardcoded numeric default for the Visto Bueno line item — "
            "this overrides the engine's per-consolidator VB and reintroduces "
            "the 2026-06-18 CRAFT/SACO undercharge bug. The default must be "
            "computed from VB_RATES[consolidator][operation]."
        )

    def test_consolidator_change_resyncs_defaults(self, template_src):
        cons_block = re.search(
            r"consSel\.addEventListener\('change',\s*function\s*\([^)]*\)\s*\{(.*?)\}\);",
            template_src,
            re.S,
        )
        assert cons_block, "consolidator-select change listener not found"
        assert "populateDefaults(" in cons_block.group(1), (
            "Changing the consolidator must re-run populateDefaults() so the "
            "Visto Bueno line item updates — otherwise it silently keeps the "
            "previous consolidator's default value."
        )
