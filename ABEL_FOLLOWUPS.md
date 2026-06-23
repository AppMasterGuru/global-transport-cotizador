---
# ABEL_FOLLOWUPS.md — Global Transport x TimeBack AI
**Purpose:** Running list of items that need Abel's confirmation, correction, 
or input before go-live. Add to this file at the end of every build session 
when something new surfaces.
**Last updated:** 2026-06-23

---

## Pending Abel action — validation

### 3. FCL F1–F4 scenarios
**Status:** FCL form wired in Session E (commit 6e71960). Abel to run F1–F4
against the live system exactly as he did for LCL and Aéreo in Parte 2, and
report results.
**Trigger:** Barney to notify Abel — Session E deployed to Railway.

---

## Closed — resolved

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
