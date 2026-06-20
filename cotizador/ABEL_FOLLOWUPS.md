---
# ABEL_FOLLOWUPS.md — Global Transport x TimeBack AI
**Purpose:** Running list of items that need Abel's confirmation, correction, 
or input before go-live. Add to this file at the end of every build session 
when something new surfaces.
**Last updated:** 2026-06-20

---

## Open — needs Abel response

### 1. LURIGANCHO (PRIALE) transport rate
**Source:** Open Transport PDF, Session D build (commit 696758f)
**Issue:** PDF extraction garbled the column order for this district. 
Used ATE VITARTE (same zone, S/880 general / S/1,240 IMO) as a proxy.
**Question:** Is S/880 general / S/1,240 IMO correct for LURIGANCHO (PRIALE), 
or do you have the right value?

### 2. SAASA almacén aéreo simulator link
**Source:** Abel Q11 reply, June 19
**Issue:** Abel provided the TALMA simulator link but not SAASA's. 
Currently a placeholder in the aéreo form.
**Question:** What is the SAASA almacén simulator URL?

### 3. Export Visto Bueno — 7 of 9 blocks unattributed (FCL export)
**Source:** EXPO_IMPO.xlsx EXPORTACION-CALLAO sheet, Session E build (commit 6e71960)
**Issue:** Of 9 VISTO BUENO blocks on the export sheet, only 2 carry an
identifiable naviera token in their desglose text (MAERSK via "MSK", CMA CGM
via "CMA") — same pattern as the import-side problem that was just resolved
(item #2, closed below), but no equivalent clean per-naviera export sheet
has surfaced. The Gastos de Importacion en Callao por Naviera.xlsx workbook
that resolved the import side is import-only by title and content — it has
no export equivalent. These 7 blocks show as Visto Bueno = 0 on FCL export
quotes for those carriers.
**Question:** Can you identify which naviera each of the 7 unattributed
export VB blocks belongs to? Alternatively, do you have (or can your team
provide) a per-naviera export cost reference sheet — similar to the "VB
IMPORTACION" sheet in the Gastos workbook — that lists export Visto Bueno
explicitly keyed by naviera name?

### 4. LCL Escenario 3 consolidator confirmation
**Source:** Abel Parte 2 doc, June 19
**Issue:** Abel flagged LCL Esc 3 Visto Bueno as wrong (should be USD 90). 
CRAFT import was reverted to 90 based on screenshot evidence (commit 40a5cad). 
But we never got explicit confirmation that Esc 3 used CRAFT specifically.
**Question:** Which consolidador was selected in LCL Escenario 3? 
Just confirming CRAFT import = 90 is the right fix.

---

## Pending Abel action — validation

### 5. FCL F1–F4 scenarios
**Status:** FCL form wiring (Session E) must complete first. 
Once live, Abel to run F1–F4 against the system exactly as he did for 
LCL and Aéreo in Parte 2, and report results.
**Trigger:** Barney to notify Abel once Session E is committed and deployed.

---

## Closed — resolved

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
F1–F4 scenario run (item #5 above) before treating them as final.
