---
# ABEL_FOLLOWUPS.md — Global Transport x TimeBack AI
**Purpose:** Running list of items that need Abel's confirmation, correction, 
or input before go-live. Add to this file at the end of every build session 
when something new surfaces.
**Last updated:** 2026-06-22

---

## Open — needs Abel response

### 1. SAASA almacén aéreo simulator link
**Source:** Abel Q11 reply, June 19; partial reply June 22
**Issue:** Abel provided the TALMA simulator link but not SAASA's. Currently
a placeholder in the aéreo form: `SAASA: (enlace pendiente de Abel)`.
Abel's June 22 message referenced SAASA but the URL was not captured in the
session task message — cannot add it until Barney supplies the exact URL.
Also to add alongside the URL: SHOHIN has no online simulator (manual entry
only), unlike TALMA and SAASA.
**Blocked on:** Barney to paste the SAASA URL from Abel's email so it can
be wired into new_quote.html helper text.

### 2. Export Visto Bueno — 5 of 7 blocks unattributed (FCL export)
**Source:** EXPO_IMPO.xlsx EXPORTACION-CALLAO sheet, inspected 2026-06-22
**Background:** Abel confirmed on June 22 the export VB lives in
EXPO_IMPO.xlsx EXPORTACION-CALLAO (the same sheet Session E already parsed).
The sheet was re-inspected row by row on June 22. Findings:

The sheet has 7 distinct VB blocks. Of these:
- MAERSK (Block 3): confirmed via "BOX FEE - EXPO MSK" + "COVERAGE FEE - EXPO MSK"
  in desglose text. VB = $160 (with 30% RETENCIÓN, not IGV). Gate: DEMARES $179.
- CMA CGM (Block 5): confirmed via "CMA - COORDINACIÓN Y SUPERVISIÓN DE EMBARQUE"
  in desglose text. VB = $219.35. Gate: IMUPESA $150.
- Block 1 (VB=$365, Gate MEDLOG $152): no naviera token in desglose, but a NOTA
  in Abel's own sheet says "cuando se hacen embarques FOB con MSC, la naviera
  también cobra el VB" — attached to this block's section. Possible=MSC but not
  a structural header, so not treated as confirmed.
- Block 6 (VB=$100, Gate FARGOLINE $125.50): same pattern — NOTA says COSCO.
  Possible=COSCO but not structurally confirmed.
- Block 2 (VB~$272, Gates CONTRANS $150 + DPW $150): no naviera attribution.
- Block 4 (VB=$152, Gate RANSA $150): no naviera attribution.
- Block 7 (VB=$227, Gates TPP $120.50 / IMUPESA $133.50 / DPW LOGISTICS $120.50):
  no naviera attribution. (Note: IMUPESA $133.50 = 119.50+14; DP World Logistics
  $120.50 — these are Abel's spot-check reference values.)

This sheet is NOT clean like the VB IMPORTACION sheet (which had all 14
navieras explicitly headed). Stopped per "no guessing" rule — no build until
the attribution is resolved.

**Question for Abel:** 
(a) Blocks 1 and 6 — your own file notes say these are MSC and COSCO. Can you
    confirm so we can attribute them without guessing?
(b) Blocks 2, 4, and 7 — which navieras do these belong to? Or do you have a
    per-naviera export cost sheet (like the VB IMPORTACION sheet in the Gastos
    workbook) that would resolve this cleanly?

---

## Pending Abel action — validation

### 3. FCL F1–F4 scenarios
**Status:** FCL form wired in Session E (commit 6e71960). Abel to run F1–F4
against the live system exactly as he did for LCL and Aéreo in Parte 2, and
report results.
**Trigger:** Barney to notify Abel — Session E deployed to Railway.

---

## Closed — resolved

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
