---
# ABEL_FOLLOWUPS.md — Global Transport x TimeBack AI
**Purpose:** Running list of items that need Abel's confirmation, correction, 
or input before go-live. Add to this file at the end of every build session 
when something new surfaces.
**Last updated:** 2026-07-06

---

## Pending Abel action — validation

### 4. Session L — FCL agente layer: §5 STOP items (no clean doc source)
**Status:** Built 2026-06-30. Naviera/port-dependent agente amounts were
re-sourced from the same port_costs + naviera docs the cliente_local import
path uses (Terminal Fee, THC, ISPS, BL Master/MBL, VB importación). Two
concepts have NO clean doc source and were LEFT at their tariff-sheet value
and flagged — not re-sourced, not guessed:
- **EXW "Gate out" (USD 150):** the export gate is per-depot and multi-valued
  (`get_export_gate_outs` returns a dict; e.g. EVERGREEN has 3 depots at 2
  amounts) and is not wired into any cost var. Confirm the single Gate-out
  figure (or the depot-selection rule) for the agente EXW quote.
- **DAP "Gate in" (USD 205):** no import-gate doc source exists in the system.
  (DDP's COST-only Gate in USD 210/cntr is a separate new §2 value.) Confirm
  the import Gate-in figure / source.

**Also flag (structural, not a guess):**
- agente **EXW** has no export "Visto Bueno" concept, so it does not charge the
  naviera export VB the cliente_local export path charges. Confirm whether EXW
  should include it (and whether EXW's "Coordinación" USD 214 already is it).
- agente **DAP** itemizes GT-fixed Coordinación (190) / Agency (4.75) instead
  of the full VB-importación bundle (which DDP uses). Confirm DAP's import
  local-cost structure vs DDP's.

### 3. FCL F1–F4 scenarios
**Status:** FCL form wired in Session E (commit 6e71960). Abel ran F1–F4 and
reported CONFORME on F1/F2 (2026-06-23). F1/F2 rendering fixes applied in
Session I (2026-06-24): LCL transport suppressed, Section 4 coloader gated,
IGV flags corrected (VB/THC/ISPS/MBL → _FLAGS_INTL), port+depósito merged,
transport label cleaned. Per-incoterm layer + DDP completed in Session L
(2026-06-30, commit 211d2d5). 966 tests green.
**Awaiting Abel — F3 + F4 on the complete site.** Notification sent via TEXT
June 30 ~1:12pm Lima — no reply yet. F3/F4 is Abel's technical validation
(precursor to go-live), NOT the saldo trigger.
**Most-likely F3/F4 correction to expect (flag in advance):** agente
VB-importación was built at **$225** (190 coordinación + 35 admin, CMA/APL
basis) vs Abel's ONE screenshot showing **$340** (box 155 + SCAC 60 + doc 115
+ admin 10). The figure is **naviera-dependent**, so expect Abel to flag the
import local-cost amount/structure on a non-CMA/APL naviera. Re-source per
naviera when he confirms.

---

## Closed — resolved

### FCL FOB agente structure — Ocean Freight ONLY — RESOLVED 2026-07-06
**Source:** Abel F3/F4 feedback July 6 — "el incoterm determina la estructura
de costos" (each incoterm shows only the concepts its Excel tarifario tab lists).
**The concept mismatch:** Session J (commit e20d521) built the agente
`(EXPO, FOB)` registry with GT fixed fees **Handling $85 + Doc Fee $25**, and
commits 2b60bdc/98daf2e (July 2, F3) then added a Flete Internacional
(COLLECT) line on top. Reconciling against the source Excel this pass shows
that was a **misread of the tab**: the `FCL FOB EXPO` client-facing
**TARIFA NETA** block (right-hand table) lists **one** concept — Ocean Freight
(COLLECT, by container size, 0.00). Handling/Doc Fee live in a *separate lower
table* on the same tab headed **"Los siguientes costos deben ser cobrados al
exportador"** — origin charges billed directly to the exporter, NOT part of the
FOB net tariff. Under FOB the consignee/agent arranges main carriage collect,
so the only client-facing line is the collect ocean freight.
**Resolution:** `_REGISTRY[(EXPO, FOB)]` trimmed to Ocean Freight only. FOB
agente venta now emits exactly one line (Flete Internacional COLLECT, USD 0.00,
IGV-exempt). Handling and Doc Fee removed. The 2 FOB structure pins from 98daf2e
and the Session J FOB pins were updated to the corrected structure.
**Verified against Excel this pass (F3/F4 structure check):** EXW (10 concepts),
DAP (8 concepts) and DDP each match their tab's TARIFA NETA block exactly —
only FOB was wrong. This confirms the item #4 structural flags below: EXW
genuinely has **no export Visto Bueno** line, and DAP genuinely itemizes
**Coordinación $190 + Agency $4.75** (not the DDP VB bundle) — both match the
Excel, not a build guess. DDP's Box Fee/SCAC/Doc Fee/Seal/Gate-in remain folded
into the RESOLVED "Visto Bueno (Importación)" naviera bundle (Session L
no-double-count; Gate-in is COST-only) — a deliberate preserve, not itemized.
**Commit:** this pass (per-incoterm registry reconciliation).

### FCL per-incoterm New-Quote form gating — RESOLVED 2026-07-06
**Source:** Abel F3/F4 July 6 — the New-Quote form showed the SAME field set
for every incoterm (visibility was gated on MODE, not INCOTERM), so e.g. FOB
still offered Naviera / Terminal Portuario / THC / Transporte Local / OEA —
inputs its cost structure doesn't use.
**Resolution:** Form-field visibility is now driven by the concept registry.
`core/fcl_agente_incoterm.agente_field_visibility()` derives, per incoterm,
which optional inputs apply (naviera / terminal / thc / transporte / oea /
ddp_cif); the map is injected into `new_quote.html` and the form JS shows +
serializes each optional input ONLY when its concept is in the selected
incoterm's registry set. FOB now shows only the freight-sizing inputs (Flete,
Tipo/N° Contenedor, Margen); EXW/DAP/DDP show exactly their structure sets
(DDP keeps Valor Factura + Seguro). Hidden inputs are disabled (can't
stale-submit) and incoterm/operación/tipo-de-cliente switches re-run the full
visibility pass (no stale resurrection). **cliente_local is byte-for-byte
unchanged** (per-incoterm gating applies only to the agente_internacional FCL
path). The 98daf2e hardening (Cache-Control: no-store, pageshow resync,
autocomplete="off") is preserved and re-verified across incoterm switching.
Verified by jsdom drive of the served page: all 4 incoterms × both
client_types + incoterm churn + FOB→EXW→FOB non-resurrection (119/119 checks).
**Commit:** this pass.

### FCL client_type — single top-of-form selector — RESOLVED 2026-07-06 (pass 2)
**Source:** Abel F3/F4 July 6 — the FCL New-Quote form read as if the
agente/cliente selector rendered "twice, top and bottom," and the per-incoterm
concept gating should fire off the top one.
**Finding (the dedup, honestly):** the form has, and has only ever had (since
Session J, e20d521), ONE `client_type` control — verified on the *served* page
(`name="client_type"` count = 1) and across git history. There was no duplicate
`client_type` <select> to remove. The perceived "two" are two *different*
agente/cliente-flavored dropdowns: §1 "Solicitante" (`requester_type`:
Agente | Cliente — a generic all-modes field) at the top, and §3 "Tipo de
Cliente" (`client_type`: Cliente Local | Agente Internacional — the FCL pricing
fork) at the bottom.
**Resolution:** the single `client_type` selector was relocated from §3 Tarifas
y Costos to §1 Cliente y Modo (top), alongside modo/incoterm/idioma/origen/
destino, so the concept gating fires off a top-of-form control. No JS change was
needed — every binding (`fclClientTypeSel` change→`applyModeVisibility`,
`agenteFieldSet` read) is by id (`fcl-client-type-select`), so the DOM move left
the wiring intact. `routes.py` reads it with `f.get("client_type")` (single
value, no `getlist`) → one unambiguous serialization (jsdom: FormData
`getAll("client_type").length === 1`). It stays FCL-only (hidden AND disabled
for non-FCL modes). **cliente_local is byte-for-byte unchanged**; the 00adcf6/
98daf2e hardening (Cache-Control: no-store, pageshow resync, autocomplete="off",
disabled-when-hidden) is preserved. Verified: full suite 1039 green (1034 + 5
new template/serialization guards) and jsdom drive 132/132 (single-selector
position + all 4 incoterms × both operations × both client_types).
**Flag for Abel:** `requester_type` ("Solicitante", top) was left as-is — it is a
separate field, not the `client_type` fork. If his "twice" actually meant the
Solicitante vs. Tipo-de-Cliente overlap (both ask agente/cliente), confirm
whether Solicitante should be removed/merged — that would be a separate change.
**Commit:** this pass.

### FCL F3 render + form-gating fixes — LOGGED 2026-07-06 (July 2 commits)
**Backfill — the two commits below predate this log's prior "last updated":**
- **2b60bdc** — Gated the New-Quote form's §2 CBM/package block and §4 coloader
  section for modo=FCL (hidden AND disabled so hidden LCL inputs can't
  stale-submit into an FCL quote). Abel F3/F4 blocker: the form invited edits
  to numbers the server silently discarded.
- **98daf2e** — Abel F3 render fixes: strip the "(COLLECT)"/"(PREPAID)" payment
  suffix from every client-facing label (proforma ES/EN + quote_detail);
  restore the FOB proforma "Costos de Flete Internacional" section (by adding
  the collect flete concept — now corrected to Ocean-Freight-only, see above);
  and restored-state form resync (pageshow re-applies mode visibility,
  autocomplete="off") for browser session-restore / bfcache.

### FCL Agente DDP thread — RESOLVED 2026-06-30 (Session L)
**Source:** Abel email/text thread June 30 resolving how DDP (and the agente
import path) should be priced.
**Resolution (per Abel):**
- **Amounts come from the naviera / port docs, NOT the tariff sheet.** The DDP
  tariff sheet is STRUCTURE ONLY (which concepts appear) — never the price
  source. THC / ISPS / MBL / VB-importación / Terminal Fee all re-sourced from
  the existing import docs the cliente_local import path already uses.
- **Customs Broker rates:** Alefero max(0.35% × CIF, **$110**) + IGV; OEA
  max(0.20% × CIF, **$80**) + IGV (min floors). Selected via `requires_oea_basc`.
  CIF = Invoice + Insurance + Freight. Implemented in `core/fcl_customs_broker.py`.
- **IGV:** **VB (export + import) and MBL are afecto a IGV** on all paths
  (todo VB afecto IGV; MBL emitido en Perú). THC / ISPS stay exempt.
- **Operative Charge** ($20/BL) → **venta**. **Gate in** ($210/cntr) → **COST-only**.
**Action taken:** DDP wired through `core/fcl_agente_incoterm.py` registry; the
old "no DDP changes" freeze is LIFTED. 966 tests green. Commit 211d2d5.
**Note:** cliente_local neto base unchanged, but VB+MBL IGV reversal means
cliente_local grand totals now include IGV on those lines (totals changed) —
authorized by Abel.

### EVERGREEN import VB — RESOLVED 2026-06-23
**Source:** Cross-check mismatch flagged in Session G (2026-06-22)
**Resolution:** Abel confirmed EXPO_IMPO IMPORTACIÓN tab is authoritative:
DELIVERY ORDER $230 net + BL TRANSMISIÓN FEE $65 net = **$295 net total**
(total with 18% IGV = $348.10). Gastos workbook figures ($250/$62) were stale.
**Action taken:** `VB_IMPORTACION_DATA["EVERGREEN"]` in `core/fcl_import_costs.py`
updated to $230 DO + $65 BL. GASTOS ADMINISTRATIVOS PEN 25 removed (stale artifact).
Gate outs paired with import: TPP $176.50, IMUPESA $190.50, DP World Logistics $120.50 net.
3 new red-first tests added; 839 tests green. Session H, 2026-06-23.

### VANGUARD consolidator — RESOLVED 2026-06-23
**Source:** Railway deploy logs — "VB FALTANTE — sin tarifa confirmada: VANGUARD"
**Resolution:** Abel confirmed "ya no existe, no tiene que ser considerado."
**Action taken:** VANGUARD removed from:
- `core/transport.py` CONSOLIDATORS dict
- `core/provider_emails.py` LCL_PROVIDERS list (now 4 providers)
- `core/provider_reply_parser.py` _DOMAIN_MAP + _EXPECTED_PROVIDERS["lcl"] now 4
- `procedures/rules.py` APPROVED_LCL_CONSOLIDATORS frozenset
Startup warning "VB FALTANTE — sin tarifa confirmada: VANGUARD" no longer fires.
6 new red-first tests added; existing VANGUARD tests updated. 839 tests, 0 warnings.
Session H, 2026-06-23.

### SAASA almacén aéreo simulator link — RESOLVED 2026-06-22
**Source:** Abel Q11 reply, June 19; URL supplied by Barney June 22
**Resolution:** URL wired into `new_quote.html` almacén aéreo helper text
as a clickable link alongside the existing TALMA reference. SHOHIN "no
simulator — manual entry only" note also added. Session G, commit this session.

### Export VB all 7 navieras attributed — RESOLVED 2026-06-22
**Source:** EXPO_IMPO.xlsx EXPORTACION-CALLAO sheet; Abel confirmed full
mapping June 22 (reply to Q2 question)
**Background:** Previous build only attributed MAERSK ($160, retención case)
and CMA CGM ($219.35 net) via desglose text tokens. Abel confirmed the
remaining 5 navieras: MSC ($365 net, MEDLOG gate), ONE ($272 net,
CONTRANS/DPW gate), HAPAG LLOYD ($152 net, RANSA gate), COSCO ($100 net,
FARGOLINE gate), EVERGREEN ($227 net, TPP/IMUPESA/DPW LOGISTICS gate).
**Action taken:** Rebuilt `_EXPORT_VB_BY_NAVIERA` in `core/fcl_naviera_costs.py`
— naviera-keyed table replacing the old almacén-keyed `EXPORT_NAVIERA_DATA`.
Now stores NET pre-IGV VB amounts (PDF layer adds 18% at render), fixing
a double-IGV bug for navieras previously stored as IGV-inclusive totals.
IMUPESA conflict resolved (CMA CGM $150 vs EVERGREEN $133.50 were both
previously stored as one entry — now each naviera has its own gate_out).
Routes.py now calls `get_export_vb_net_usd(naviera)` — 5 new naviera VBs
now charged in live export quotes. Session G, 831 tests passing.
**Still open — TODO(abel-F1F4):** MAERSK retención (30%) treatment not yet
resolved — stored as $160 (retención-inclusive total) until F1-F4 validation.
**Still open:** EVERGREEN import VB mismatch (see new open item above).

### LURIGANCHO (PRIALE) transport rate — RESOLVED 2026-06-22
**Originally:** PDF extraction garbled the column order for this district.
Used ATE VITARTE (same zone) as a proxy: S/880 general / S/1,240 IMO.
**Abel's June 22 reply:** Confirmed — S/880 general / S/1,240 IMO is correct.
**Action taken:** Removed the "proxy/needs confirmation" comment from
`core/open_transport_costs.py` (commit this session). Values were already
correct in the code — no data change needed.

### LCL Escenario 3 consolidator — RESOLVED 2026-06-22
**Originally:** LCL Esc 3 Visto Bueno reverted to $90 based on screenshot
evidence, but explicit confirmation of the consolidator used was still pending.
**Abel's June 22 reply:** Confirmed — Esc 3 used CRAFT and import VB = $90
is correct. No code change needed (already correct since commit 40a5cad).

### Five unattributed VB-import blocks (FCL import) — RESOLVED 2026-06-20
**Originally:** Of 7 VB-import blocks in EXPO_IMPO.xlsx's IMPORTACIÓN sheet 
(Session B build, commit 776310e), only 2 could be attributed to a naviera 
with confidence. The other 5 had no clear naviera identifier in their 
desglose text and were left unattributed rather than guessed.
**Resolution:** Found that the Gastos de Importacion en Callao por Naviera.xlsx 
workbook — the same file already used for THC/ISPS (G. LOCALES) and MBL 
(EMISION MBL) — has its own "VB IMPORTACION" sheet that keys every Visto 
Bueno block explicitly by naviera name (all 14 navieras, no guessing 
required). This sheet supersedes the EXPO_IMPO-based parser for FCL import 
VB in live wiring — see `parse_vb_importacion_sheet()` / 
`build_vb_importacion_totals()` in `core/fcl_import_costs.py` 
(Session E, commit 6e71960).
**Still open — TODO(abel-F1F4):** these amounts come from Abel's own file 
but haven't been validated against a real quote yet. Confirm via Abel's 
F1–F4 scenario run (item #3 above) before treating them as final.
