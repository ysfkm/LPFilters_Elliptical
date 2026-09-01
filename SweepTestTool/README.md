# Lowpass Filter Frequency Response Tester

Drives a Rigol DG1062Z function generator and reads a Rigol DS1104Z Plus
oscilloscope over LAN to automatically sweep a sine wave through a filter
and plot its measured Bode plot (gain and phase vs. frequency).

Built for testing the elliptic LC lowpass filter boards from this project
(see `../HANDOVER.md`) — each board is designed for a **50Ω source and 50Ω
load** (`Vin -(Rser=50)- ... RL=50@Vout` per the LTSpice netlist), so a real
50Ω terminator is required at the filter's output when testing, or the
measured response will show significant passband peaking that isn't real
(see the "Generator load setting" note below).

## Working from this shared folder (multiple users)

This folder is shared via Google Drive, but each person still needs to do
their own **local** setup — Drive syncs the files, not a Python install:
- Steps 1-2 below (install Python, `pip install -r requirements.txt`) need
  to be done once on each person's own machine.
- If a file looks stale or empty right after someone else saves changes,
  Google Drive may still be syncing — wait a moment and re-open it.
- Every sweep run creates its own folder under `Sweep_Results/`, and since
  everyone shares this same folder, everyone's runs will accumulate together
  there (synced to everyone) — this is intentional, not a bug.

## Wiring assumed by this tool

- Generator CH1 output -> filter input **and** scope **CH2** (input/reference)
- Filter output -> scope **CH1**
- Gain (dB) is computed as `20*log10(Vpp_CH1 / Vpp_CH2)`
- Phase is CH1 relative to CH2
- CH2 is used as the scope's trigger source (it stays constant amplitude
  across the whole sweep, unlike CH1 which shrinks above the filter's cutoff)

If your wiring is reversed, swap the channel numbers in `sweep.py`
(`RigolDS1104ZPlus.measure_vpp`/`measure_phase` calls inside `SweepRunner.run`).

## 1. Install Python

If you don't already have Python installed:

1. Download Python 3.11+ from https://www.python.org/downloads/
2. During install, check **"Add python.exe to PATH"**.
3. Verify from a terminal: `python --version`

**If you already have another Python install** (e.g. from MSYS2, Anaconda,
or a Microsoft Store install), `python --version` may keep showing the old
one even after installing a new version, because Windows searches your
System PATH before your User PATH. If that happens, use the **`py`**
launcher command instead of `python` for everything below (`py --version`,
`py -m pip install ...`, `py main.py`) — it isn't shadowed the same way.

## 2. Install dependencies

From this folder, run:

```
pip install -r requirements.txt
```

This uses `pyvisa-py` (a pure-Python VISA backend) plus `python-vxi11`, so
you do **not** need to install NI-VISA or any other vendor driver — both
instruments are controlled over plain LAN/VXI-11.

## 3. Find each instrument's IP address

On **both** the DG1062Z and the DS1104Z Plus:

1. Press the **Utility** button on the front panel.
2. Go to **IO Setting** (or **System** -> **IO**, depending on firmware).
3. Select **LAN**, and make sure it's enabled (DHCP is fine if your network
   has a router handing out addresses).
4. The screen will show the current **IP Address** — write down both.

Make sure both instruments and the PC running this tool are on the same
network/subnet (plugged into the same switch/router is simplest).

## 4. Run the tool

```
python main.py
```
(or `py main.py` — see the PATH note in step 1 if `python` isn't resolving
to the install you expect)

1. Enter both IP addresses and click **Test Connection** — you should see
   each instrument's `*IDN?` response. If this fails, double check the IP,
   that the instrument's LAN is enabled, and that nothing (e.g. a firewall)
   is blocking the connection.
2. Adjust sweep parameters if needed (defaults: 10 Hz - 1 MHz, 10 points/decade,
   1 Vpp, cutoff hint 100 kHz for denser sampling near the knee).
3. Click **Start Sweep**. Each run automatically creates its own folder under
   `Sweep_Results/sweep_<timestamp>/`, containing a CSV that's written point
   by point as the sweep runs (so you don't lose data if you stop early) and
   a PNG of the final plot, saved automatically once the sweep completes.
   The "CSV & PNG output" field shows the current run's folder.
4. **Stop** ends the sweep safely (turns the generator output off). The CSV
   up to that point is kept, but no PNG is auto-saved for a stopped/partial run.
5. **Save Plot PNG** manually exports the currently displayed plot to any
   location you choose — independent of the automatic per-run save above,
   e.g. useful for re-saving after zooming/panning the plot.

## Notes / things to double-check if something looks wrong

- **Probe ratio fields** (CH1/CH2 probe ratio) must match your physical
  probes/cables. If you're connecting with plain BNC cables (no probe),
  leave these at `1`. If you're using 10x scope probes, set to `10` — this
  is a scope-side setting the SCPI commands configure to match; the scope's
  Vpp measurement is only correct if this matches what you physically have.
- **Generator load setting / 50Ω termination**: this tool sets the
  generator's output impedance setting to **50Ω** (`output_load="50"` in
  `sweep.py`), matching these filter boards' 50Ω design. This setting only
  changes how the generator *calculates* its output amplitude — it does
  **not** create any real termination. You must add a **physical 50Ω
  terminator** (e.g. a BNC feedthrough terminator) at the filter's output,
  in-line before the scope's CH1 probe, so the filter actually sees the 50Ω
  load it was designed for. The scope's inputs are always fixed at 1MΩ (this
  model has no switchable 50Ω input mode), so this physical terminator is
  the only way to get a proper 50Ω load — without it, expect a large,
  non-physical peaking artifact in the measured passband near cutoff.
  If you ever test a different, non-50Ω-terminated circuit, change
  `output_load` back to `"INF"` in `sweep.py` to match.
- **SCPI command mismatches**: the commands used here were checked against
  the official Rigol DS1000Z Programming Guide and real open-source drivers
  for these instrument families, but firmware revisions occasionally differ.
  If you get a VISA error on a specific command, check that exact command
  in your instrument's Programming Guide PDF (searchable online) — it will
  usually be a very small naming difference (e.g. a different keyword form).
- Very low frequencies (near 10 Hz) take longer per point since the scope
  needs a slow timebase and more real time to acquire and average full
  waveforms — the sweep is expected to take longer at the low end.
