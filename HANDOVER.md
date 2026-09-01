# LPFilters Elliptical — Handover Notes

_Last updated: 2026-06-10_

## What this project is

A family of **10 elliptic LC low-pass filter boards**, one per cutoff frequency:
**1kHz, 2kHz, 5kHz, 10kHz, 20kHz, 50kHz, 100kHz, 200kHz, 500kHz, 1MHz**.

Same circuit topology on every board (elliptic LC ladder), different component values per cutoff.
Each board has **7 references**: `L1, L2, C1, C2, C3, C4, C5`. All parts are sourced from **JLCPCB / LCSC**.

Topology (per board, from the LTSpice netlist):
```
Vin -(Rser=50)- n1 ; C1 shunt@n1 ; [L1 ‖ C2] series n1->n2 ; C3 shunt@n2 ;
                     [L2 ‖ C4] series n2->Vout ; C5 shunt@Vout ; RL=50@Vout
```
The `[L ‖ C]` parallel branches in series with the signal are the elliptic **notch** sections.

## What we did (chronological)

1. **Consolidated the parts spreadsheet** (`Parts & Simulation Spreadsheet.xlsx`, sheets per frequency + "Backup Parts") into one workbook with a matrix view (refs in rows, boards in columns).
2. **Added live JLCPCB data** for every part: **library type (Basic / Extended / Preferred)** and **assembly stock**, pulled from the JLCPCB API. Also added LCSC retail detail (MPN, brand, type, package).
3. **Built an "Alternative BOM"** that maximizes Basic-part usage to cut JLCPCB feeder fees.
   - User priorities (in final order): **stock-first** (large in-stock qty), **prefer Basic**, value tolerance **±40%**, voltage **≥15V**, any dielectric.
   - Capacitors standardized to **one footprint per reference** (all landed on **0603**) to maximize Basic coverage; footprint changes allowed & flagged.
   - Inductors kept per-board footprint — they span 8.2µH..10mH so no single footprint works, and JLCPCB has **essentially no Basic power inductors** in these sizes, so all L1/L2 stay Extended.
   - Result: **50/50 capacitor slots → well-stocked Basic** (vs 2 Basic originally); 20 inductor slots remain Extended.
4. **Ran LTSpice simulations** (headless) for all 10 boards, 3 configs each — Ideal (design values), Actual (current JLCPCB parts incl. inductor DCR), Proposed (Basic-swap BOM) — and compared frequency response.

## Final deliverables (in project root)

- **`LPF Consolidated Parts & Stock.xlsx`** — 5 sheets:
  1. **BOM (Original vs Proposed)** — per reference, an Original block stacked above a Proposed block (Value / Footprint / Part # / JLC Lib / JLC Stock), boards in columns. Peach = value changed, orange = footprint changed; JLC Lib colour-coded (Basic=green, Preferred=blue, Extended=yellow).
  2. **Sim results** — LTSpice cutoff/notch comparison table + 10 embedded response plots; flags filters detuned ≥15%.
  3. **Parts catalog** — full per-part lookup (MPN, brand, type, JLC+LCSC stock, where-used).
  4. **Backup inductors** — inductor substitution list with live type & stock.
  5. **Summary** — index/notes.
- **`Simulation Figures/`** — 40 PNGs: per board, `<b>_0_response.png` + `<b>_1_Ideal/_2_Actual/_3_Proposed_schematic.png`.
- **`LPF Frequency Response (Ideal vs Actual vs Proposed).png`** — 10-panel overview.
- **`Parts & Simulation Spreadsheet.xlsx` / `.gsheet`** — the ORIGINAL source (untouched).

## Key technical findings

- **Awkward E6 cap values** (270nF, 180nF, 150nF, 1.5µF, 5.6µF, 680nF, 68nF, …) have **no Basic part at any footprint** — nearest Basic is one E-series step away. Forcing all-Basic therefore shifts **37 of 50 caps >5%**, and **17 caps ≥20%** (e.g. 330nF→220nF, 1.5µF→1µF). User accepted this trade ("force Basic anyway").
- **Sim verdict** — the all-Basic ±40% BOM:
  - Holds the **−3 dB cutoff** well on most boards (7/10 within ±7%).
  - But **detunes the elliptic notch** on **1kHz (+26%), 5kHz (+20%), 20kHz (−31%)** — flagged "re-check" in the Sim results sheet.
  - **Counterintuitive note (raised by user):** 20kHz has the *best* LP cutoff fidelity (0% fc error) despite the largest cap value changes — because cutoff is dominated by the unchanged inductors + shunt caps — yet it's the *worst* notch (−31%). 1kHz has the worst passband loss (−8.5 dB) due to its large inductor **DCR (14.2 Ω / 10 Ω)**, which is inherent to the inductors, NOT the cap swap.
- **JLCPCB assembly stock ≠ LCSC retail stock.** e.g. C14663 reads 0 on LCSC retail but 21.6M in the JLCPCB assembly library. Always use the JLC stock column for assembly decisions.
- **C2045615** (16µH, 500kHz L2): delisted on LCSC retail but still in JLCPCB library (~281 pcs).

## Decision: STATUS = "good enough"

User chose **not** to re-tune the detuned notches. The all-Basic BOM stands as-is.
**Open option if resumed:** re-tune the notch on **1kHz / 5kHz / 20kHz** by paralleling two Basic caps to recover the exact series-notch capacitance, then re-simulate. (Caps C2 and C4 are the series-notch elements — those drive the null.)

## How to re-run / rebuild (all tooling lives in `_build/`)

Tooling, caches, and LTSpice run artifacts are in **`_build/`** (kept out of the main dir). Pipeline order:

1. `_jlc_fetch.py` — fetch JLCPCB lib-type + stock for used parts → `_jlc_cache.json`
2. `_fetch.py` (in history) / `_lcsc_cache.json` — LCSC retail detail
3. `_gather_candidates.py` — for each board×ref, gather all Basic/Pref/Ext candidates across footprints (±40%, with E12 neighbour queries) → `_candidates.json`
4. `_plan_altbom.py` — stock-first/Basic-preferred selection + per-cap-ref footprint optimization → `_altbom.json`
5. `_sim.py` — generate combined LTSpice netlist (3 circuits), run headless, parse `.raw` → `_sim_results.json`, `_sim_curves.json`
6. `_export_figs.py` — per-board response plots + schematic PNGs → `Simulation Figures/`
7. `_build_final.py` — assemble the final xlsx (reads caches from `_build/`, writes xlsx to project root)

**Environment:**
- Python 3.13 with `openpyxl`, `pandas`, `matplotlib` (all installed).
- **LTSpice**: `C:\Users\USER\AppData\Local\Programs\ADI\LTspice\LTspice.exe`. Headless: `LTspice.exe -b -ascii <file>` ; netlist: `-netlist <asc>`. Raw output is ASCII complex (`idx<TAB>re,im`).
- **JLCPCB API** (no key needed, but Python urllib gets 403 — must call via `curl` with headers `Origin: https://jlcpcb.com`, `Referer: https://jlcpcb.com/parts`):
  `POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList`
  body `{"currentPage":1,"pageSize":N,"keyword":"<C-code or value>"}`. Fields: `componentLibraryType` (base/expand), `preferredComponentFlag`, `stockCount`, `componentSpecificationEn` (footprint), `erpComponentName` (value), `firstSortName` (type).
- **LCSC detail** (works via urllib): `https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=<Ccode>`.

**Gotchas:**
- Save xlsx fails with PermissionError if the file is open in Excel — `_build_final.py` falls back to `(v2).xlsx`.
- Deleting sheets that contain images via openpyxl can transiently look corrupt due to Google-Drive sync lock; re-read after a moment.
- Shared drive is Google Drive (`g:\Shared drives\...`) — watch for sync locks.
