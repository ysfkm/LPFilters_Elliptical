# LPFilters Elliptical

## Summary
- Set of 10 discrete PCBs, each a 5th-order passive Elliptic Low Pass Filter (LC ladder), covering cutoff frequencies from 1kHz to 1MHz.
- Each board ships with front/back panels and an aluminum enclosure; designed via markimicrowave (LC synthesis), LTSpice (deviation simulation), and KiCad (PCB + panel layout), with Claude assisting on JLCPCB basic-parts substitution and KiCad design duplication.

## Specs
- **Input:** IN (raw signal)
- **Output:** OUT (filtered signal)
- **Description:** Includes 10 separate boards of 5th order Elliptic Low Pass Filters that use passive elements, mainly LC ladders
- **Cutoffs:** 1kHz, 2kHz, 5kHz, 10kHz, 20kHz, 50kHz, 100kHz, 200kHz, 500kHz, 1MHz
- Includes front/back panels with labels and aluminum encasings
- **PCB:** 77mm x 21.5mm / 4 Layer
- **Aluminum box:** K1-2525-H7-L80 (25mm x 25mm x 80mm)
- **Panel size:** 25mm x 25mm

## Design Process / Notes
- Used markimicrowave to come up with LC values and circuit topology
- Used Claude to browse JLCPCB for available basic parts replacing the extended parts
- Used LTSpice for simulation to monitor deviations due to imperfect components & the swap of extended parts into basic parts
- Assembled circuit & PCB in KiCad (utilized Claude to duplicate designs and update footprint/symbols)
- Made front/back panel in KiCad as a PCB
