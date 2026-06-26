"""
Tests for the FCL Agente Internacional per-incoterm concept layer.

Covers:
  - Registry completeness and structure (three incoterms wired, DDP absent)
  - build_agente_venta_items() for EXW, FOB, DAP
  - IGV/INTL flag assertions (F3 analogue for agente path)
  - No-LCL-transport assertion (F1 analogue)
  - Collect item renders but contributes 0 total (EXW ocean freight)
  - PER_CNTR_EXTRA skipped when num_containers == 1
  - BY_SIZE selects correct terminal amount per container type
  - DYNAMIC item omitted when open_transport_usd == 0
  - Regression: DDP returns None (falls back to cliente_local)
  - F1/F2/F3/F4/F5/F6 fix assertions on new incoterm outputs
"""

from __future__ import annotations

import pytest

from core.fcl_agente_incoterm import (
    BY_SIZE,
    DYNAMIC,
    PER_BL,
    PER_CNTR,
    PER_CNTR_EXTRA,
    FclConcept,
    build_agente_venta_items,
    get_incoterm_concepts,
    registered_incoterms,
)


# ── Registry structure ────────────────────────────────────────────────────────

class TestRegistry:
    def test_three_incoterms_registered(self):
        keys = registered_incoterms()
        assert ("EXPO", "EXW") in keys
        assert ("EXPO", "FOB") in keys
        assert ("IMPO", "DAP") in keys

    def test_ddp_absent(self):
        assert get_incoterm_concepts("IMPO", "DDP") is None

    def test_unknown_incoterm_returns_none(self):
        assert get_incoterm_concepts("EXPO", "CIF") is None
        assert get_incoterm_concepts("IMPO", "FOB") is None

    def test_lookup_case_insensitive(self):
        assert get_incoterm_concepts("expo", "exw") is not None
        assert get_incoterm_concepts("Impo", "Dap") is not None

    def test_concepts_are_fcl_concept_instances(self):
        for flujo, inc in registered_incoterms():
            concepts = get_incoterm_concepts(flujo, inc)
            assert all(isinstance(c, FclConcept) for c in concepts)

    def test_all_concepts_have_description(self):
        for flujo, inc in registered_incoterms():
            for c in get_incoterm_concepts(flujo, inc):
                assert c.description and isinstance(c.description, str)

    def test_by_size_concepts_have_all_three_sizes(self):
        for flujo, inc in registered_incoterms():
            for c in get_incoterm_concepts(flujo, inc):
                if c.unit == BY_SIZE:
                    assert "20STD" in c.amount_by_size
                    assert "40STD" in c.amount_by_size
                    assert "40HC"  in c.amount_by_size


# ── EXW concept list ──────────────────────────────────────────────────────────

class TestExwConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "EXW")

    def test_descriptions_in_order(self, concepts):
        descs = [c.description for c in concepts]
        assert descs[0] == "Flete Internacional (COLLECT)"
        assert "Customs Broker" in descs
        assert "Operative Charge" in descs
        assert "Seal" in descs
        assert "Coordinación y Supervisión del Embarque" in descs
        assert "Agency Fee" in descs
        assert "Gate out" in descs
        assert "Terminal Fee" in descs
        assert "Pick up" in descs

    def test_collect_item_is_intl_and_zero(self, concepts):
        collect = concepts[0]
        assert collect.is_collect is True
        assert collect.amount_usd == 0.0
        assert collect.is_international is True
        assert collect.igv_applicable is False

    def test_terminal_fee_amounts(self, concepts):
        tf = next(c for c in concepts if c.unit == BY_SIZE)
        assert tf.amount_by_size["20STD"] == 212.0
        assert tf.amount_by_size["40STD"] == 311.0
        assert tf.amount_by_size["40HC"]  == 338.0

    def test_per_cntr_extra_present(self, concepts):
        extra = [c for c in concepts if c.unit == PER_CNTR_EXTRA]
        assert len(extra) == 1
        assert extra[0].amount_usd == 25.0

    def test_dynamic_pickup_present(self, concepts):
        dyn = [c for c in concepts if c.unit == DYNAMIC]
        assert len(dyn) == 1
        assert dyn[0].description == "Pick up"


# ── FOB concept list ──────────────────────────────────────────────────────────

class TestFobConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "FOB")

    def test_exactly_two_concepts(self, concepts):
        assert len(concepts) == 2

    def test_handling_amount(self, concepts):
        handling = concepts[0]
        assert handling.description == "Handling"
        assert handling.amount_usd == 85.0
        assert handling.unit == PER_CNTR
        assert handling.igv_applicable is True

    def test_doc_fee_amount(self, concepts):
        doc = concepts[1]
        assert doc.description == "Doc Fee / Por BL"
        assert doc.amount_usd == 25.0
        assert doc.unit == PER_BL
        assert doc.igv_applicable is True

    def test_no_intl_items(self, concepts):
        assert not any(c.is_international for c in concepts)


# ── DAP concept list ──────────────────────────────────────────────────────────

class TestDapConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("IMPO", "DAP")

    def test_descriptions_in_order(self, concepts):
        descs = [c.description for c in concepts]
        assert descs[0] == "THC"
        assert descs[1] == "ISPS"
        assert "BL Master" in descs
        assert "Coordinación y Supervisión del Embarque" in descs
        assert "Agency Fee" in descs
        assert "Gate in" in descs
        assert "Terminal Fee" in descs
        assert "Delivery" in descs

    def test_thc_isps_are_intl_no_igv(self, concepts):
        thc  = concepts[0]
        isps = concepts[1]
        assert thc.is_international  is True
        assert thc.igv_applicable    is False
        assert isps.is_international is True
        assert isps.igv_applicable   is False

    def test_thc_amount(self, concepts):
        assert concepts[0].amount_usd == 60.0

    def test_isps_amount(self, concepts):
        assert concepts[1].amount_usd == 39.0

    def test_bl_master_is_local_igv(self, concepts):
        bl = next(c for c in concepts if c.description == "BL Master")
        assert bl.is_international is False
        assert bl.igv_applicable   is True
        assert bl.amount_usd == 55.0

    def test_terminal_fee_amounts(self, concepts):
        tf = next(c for c in concepts if c.unit == BY_SIZE)
        assert tf.amount_by_size["20STD"] == 245.0
        assert tf.amount_by_size["40STD"] == 345.0
        assert tf.amount_by_size["40HC"]  == 372.0

    def test_dynamic_delivery_present(self, concepts):
        dyn = [c for c in concepts if c.unit == DYNAMIC]
        assert len(dyn) == 1
        assert dyn[0].description == "Delivery"


# ── build_agente_venta_items — EXW ───────────────────────────────────────────

class TestBuildExwItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "EXW")

    def _items(self, concepts, num_containers=1, container_type="20STD",
               open_transport_usd=0.0):
        return build_agente_venta_items(
            concepts, num_containers, container_type, open_transport_usd
        )

    def test_collect_item_total_is_zero(self, concepts):
        items = self._items(concepts)
        collect = next(i for i in items if "COLLECT" in i["description"])
        assert collect["total"] == 0.0
        assert collect["is_international"] is True
        assert collect["igv_applicable"] is False

    def test_customs_broker_per_bl_flat(self, concepts):
        items = self._items(concepts, num_containers=3)
        cb = next(i for i in items if i["description"] == "Customs Broker")
        assert cb["total"] == 50.0  # flat per BL, not × 3

    def test_customs_broker_extra_skipped_at_one_container(self, concepts):
        items = self._items(concepts, num_containers=1)
        extra = [i for i in items if "Adicional" in i["description"]]
        assert extra == []

    def test_customs_broker_extra_charged_at_three_containers(self, concepts):
        items = self._items(concepts, num_containers=3)
        extra = next(i for i in items if "Adicional" in i["description"])
        assert extra["quantity"] == 2      # 3 - 1
        assert extra["total"] == 50.0     # 25 × 2

    def test_terminal_fee_20std(self, concepts):
        items = self._items(concepts, container_type="20STD")
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["unit_price"] == 212.0

    def test_terminal_fee_40hc(self, concepts):
        items = self._items(concepts, container_type="40HC")
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["unit_price"] == 338.0

    def test_terminal_fee_scales_with_containers(self, concepts):
        items = self._items(concepts, num_containers=2, container_type="40STD")
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["total"] == 311.0 * 2

    def test_dynamic_pickup_omitted_when_zero(self, concepts):
        items = self._items(concepts, open_transport_usd=0.0)
        pickup = [i for i in items if i["description"] == "Pick up"]
        assert pickup == []

    def test_dynamic_pickup_included_when_nonzero(self, concepts):
        items = self._items(concepts, open_transport_usd=250.0)
        pickup = next(i for i in items if i["description"] == "Pick up")
        assert pickup["total"] == 250.0
        assert pickup["igv_applicable"] is True
        assert pickup["is_local"] is True

    def test_all_local_items_flagged_correctly(self, concepts):
        items = self._items(concepts, open_transport_usd=100.0)
        for item in items:
            if "COLLECT" in item["description"]:
                assert item["is_international"] is True
                assert item["igv_applicable"] is False
            else:
                assert item["is_local"] is True
                assert item["igv_applicable"] is True

    def test_no_lcl_transport_items(self, concepts):
        items = self._items(concepts)
        for item in items:
            assert "LCL" not in item["description"].upper()

    def test_no_company_name_in_labels(self, concepts):
        items = self._items(concepts, open_transport_usd=100.0)
        for item in items:
            assert "Open Transport" not in item["description"]

    def test_exw_total_one_container_no_pickup_20std(self, concepts):
        items = self._items(concepts, num_containers=1, container_type="20STD")
        # Collect=0, Broker=50, Operative=20, Seal=10, Coor=214, Agency=5.35,
        # Gate=150, Terminal20=212  (no extra, no pickup)
        total = sum(i["total"] for i in items)
        assert round(total, 2) == round(0 + 50 + 20 + 10 + 214 + 5.35 + 150 + 212, 2)


# ── build_agente_venta_items — FOB ───────────────────────────────────────────

class TestBuildFobItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "FOB")

    def _items(self, concepts, num_containers=1, container_type="20STD",
               open_transport_usd=0.0):
        return build_agente_venta_items(
            concepts, num_containers, container_type, open_transport_usd
        )

    def test_exactly_two_items_one_container(self, concepts):
        items = self._items(concepts)
        assert len(items) == 2

    def test_handling_scales_with_containers(self, concepts):
        items = self._items(concepts, num_containers=2)
        handling = next(i for i in items if i["description"] == "Handling")
        assert handling["total"] == 170.0  # 85 × 2

    def test_doc_fee_flat_per_bl(self, concepts):
        items = self._items(concepts, num_containers=3)
        doc = next(i for i in items if "Doc Fee" in i["description"])
        assert doc["total"] == 25.0        # flat, not × 3

    def test_both_items_local_with_igv(self, concepts):
        items = self._items(concepts)
        for item in items:
            assert item["is_local"] is True
            assert item["igv_applicable"] is True

    def test_fob_total_one_container(self, concepts):
        items = self._items(concepts)
        total = sum(i["total"] for i in items)
        assert total == 110.0              # 85 + 25

    def test_no_intl_items_no_collect(self, concepts):
        items = self._items(concepts)
        assert not any(i["is_international"] for i in items)


# ── build_agente_venta_items — DAP ───────────────────────────────────────────

class TestBuildDapItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("IMPO", "DAP")

    def _items(self, concepts, num_containers=1, container_type="20STD",
               open_transport_usd=0.0):
        return build_agente_venta_items(
            concepts, num_containers, container_type, open_transport_usd
        )

    def test_thc_flagged_intl_no_igv(self, concepts):
        items = self._items(concepts)
        thc = next(i for i in items if i["description"] == "THC")
        assert thc["is_international"] is True
        assert thc["igv_applicable"] is False
        assert thc["total"] == 60.0

    def test_isps_flagged_intl_no_igv(self, concepts):
        items = self._items(concepts)
        isps = next(i for i in items if i["description"] == "ISPS")
        assert isps["is_international"] is True
        assert isps["igv_applicable"] is False
        assert isps["total"] == 39.0

    def test_bl_master_local_igv(self, concepts):
        items = self._items(concepts)
        bl = next(i for i in items if i["description"] == "BL Master")
        assert bl["is_local"] is True
        assert bl["igv_applicable"] is True
        assert bl["total"] == 55.0

    def test_terminal_fee_20std(self, concepts):
        items = self._items(concepts, container_type="20STD")
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["unit_price"] == 245.0

    def test_terminal_fee_40std(self, concepts):
        items = self._items(concepts, container_type="40STD")
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["unit_price"] == 345.0

    def test_terminal_fee_40hc(self, concepts):
        items = self._items(concepts, container_type="40HC")
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["unit_price"] == 372.0

    def test_dynamic_delivery_omitted_when_zero(self, concepts):
        items = self._items(concepts, open_transport_usd=0.0)
        delivery = [i for i in items if i["description"] == "Delivery"]
        assert delivery == []

    def test_dynamic_delivery_included_when_nonzero(self, concepts):
        items = self._items(concepts, open_transport_usd=338.0)
        delivery = next(i for i in items if i["description"] == "Delivery")
        assert delivery["total"] == 338.0
        assert delivery["igv_applicable"] is True

    def test_dap_total_one_container_20std_no_delivery(self, concepts):
        items = self._items(concepts, num_containers=1, container_type="20STD")
        total = sum(i["total"] for i in items)
        # THC=60 + ISPS=39 + BL=55 + Coord=190 + Agency=4.75 + Gate=205 + Terminal=245
        expected = 60 + 39 + 55 + 190 + 4.75 + 205 + 245
        assert round(total, 2) == round(expected, 2)

    def test_dap_two_containers_thc_doubles(self, concepts):
        items = self._items(concepts, num_containers=2, container_type="20STD")
        thc = next(i for i in items if i["description"] == "THC")
        assert thc["total"] == 120.0       # 60 × 2

    def test_no_lcl_items(self, concepts):
        items = self._items(concepts, open_transport_usd=200.0)
        for item in items:
            assert "LCL" not in item["description"].upper()

    def test_no_company_name_in_transport(self, concepts):
        items = self._items(concepts, open_transport_usd=200.0)
        for item in items:
            assert "Open Transport" not in item["description"]


# ── DDP fallback ──────────────────────────────────────────────────────────────

class TestDdpFallback:
    def test_ddp_not_in_registry(self):
        assert get_incoterm_concepts("IMPO", "DDP") is None

    def test_unknown_impo_returns_none(self):
        assert get_incoterm_concepts("IMPO", "EXW") is None

    def test_unknown_expo_returns_none(self):
        assert get_incoterm_concepts("EXPO", "DAP") is None


# ── Cliente local regression guard ───────────────────────────────────────────
# The registry returns None for any non-agente incoterm, guaranteeing that
# routes.py falls through to the existing cliente_local FCL behavior unchanged.

class TestClienteLocalFallthrough:
    def test_none_for_cif(self):
        assert get_incoterm_concepts("EXPO", "CIF") is None

    def test_none_for_fca(self):
        assert get_incoterm_concepts("EXPO", "FCA") is None

    def test_none_for_cfr(self):
        assert get_incoterm_concepts("EXPO", "CFR") is None

    def test_none_for_ddu(self):
        assert get_incoterm_concepts("IMPO", "DDU") is None

    def test_none_for_empty_string(self):
        assert get_incoterm_concepts("EXPO", "") is None


# ── F1–F6 cross-incoterm assertions ──────────────────────────────────────────

class TestF1ToF6OnAgentePath:
    """
    Verify the 6 Session-I rendering fixes still hold on every registered
    incoterm when routed through the agente_internacional concept builder.
    """

    @pytest.mark.parametrize("flujo,incoterm", registered_incoterms())
    def test_f1_no_lcl_transport_items(self, flujo, incoterm):
        concepts = get_incoterm_concepts(flujo, incoterm)
        items = build_agente_venta_items(
            concepts, 1, "20STD", open_transport_usd=200.0
        )
        for item in items:
            assert "LCL" not in item["description"].upper()

    @pytest.mark.parametrize("flujo,incoterm", registered_incoterms())
    def test_f2_no_duplicate_vb(self, flujo, incoterm):
        concepts = get_incoterm_concepts(flujo, incoterm)
        items = build_agente_venta_items(
            concepts, 1, "20STD", open_transport_usd=200.0
        )
        vb_items = [
            i for i in items if "visto bueno" in i["description"].lower()
        ]
        assert len(vb_items) <= 1, (
            f"Duplicate VB in ({flujo}, {incoterm}): "
            f"{[i['description'] for i in vb_items]}"
        )

    def test_f3_thc_isps_flagged_intl_in_dap(self):
        concepts = get_incoterm_concepts("IMPO", "DAP")
        items = build_agente_venta_items(concepts, 1, "20STD")
        for item in items:
            if item["description"] in ("THC", "ISPS"):
                assert item["igv_applicable"] is False
                assert item["is_international"] is True

    def test_f4_terminal_fee_single_item_no_split(self):
        for flujo, incoterm in registered_incoterms():
            concepts = get_incoterm_concepts(flujo, incoterm)
            items = build_agente_venta_items(concepts, 1, "20STD")
            tf_items = [i for i in items if i["description"] == "Terminal Fee"]
            assert len(tf_items) <= 1, (
                f"Multiple Terminal Fee items in ({flujo},{incoterm})"
            )

    def test_f5_no_thc_isps_with_igv_in_any_incoterm(self):
        for flujo, incoterm in registered_incoterms():
            concepts = get_incoterm_concepts(flujo, incoterm)
            items = build_agente_venta_items(concepts, 1, "20STD")
            for item in items:
                if item["description"] in ("THC", "ISPS"):
                    assert item["igv_applicable"] is False, (
                        f"({flujo},{incoterm}) {item['description']} must be IGV-exempt"
                    )

    @pytest.mark.parametrize("flujo,incoterm", registered_incoterms())
    def test_f6_no_transporter_company_name(self, flujo, incoterm):
        concepts = get_incoterm_concepts(flujo, incoterm)
        items = build_agente_venta_items(
            concepts, 1, "20STD", open_transport_usd=200.0
        )
        for item in items:
            assert "Open Transport" not in item["description"], (
                f"Transporter name in label: {item['description']!r}"
            )
