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

### 2. Five unattributed VB-import blocks (FCL import)
**Source:** EXPO_IMPO.xlsx IMPORTACIÓN sheet, Session B build (commit 776310e)
**Issue:** Of 7 VB-import blocks in the sheet, only 2 could be attributed to 
a naviera with confidence (MAERSK/SEALAND via "MSK" token = USD 150.50; 
CMA CGM/APL via "CMA" token = USD 194.75). The other 5 blocks have no clear 
naviera identifier in their desglose text and were left unattributed rather 
than guessed. These show as VB = 0 on FCL import quotes for those carriers.
**Question:** Can you identify which naviera each of the 5 unattributed blocks 
belongs to? Please send the naviera name alongside each VB amount.

### 3. SAASA almacén aéreo simulator link
**Source:** Abel Q11 reply, June 19
**Issue:** Abel provided the TALMA simulator link but not SAASA's. 
Currently a placeholder in the aéreo form.
**Question:** What is the SAASA almacén simulator URL?

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

*(Nothing closed yet — items move here once Abel confirms)*
