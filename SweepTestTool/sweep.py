"""Frequency-sweep logic: builds the list of test frequencies and drives the
generator + scope through each point to measure gain and phase.
"""

import csv
import math
import threading
import time

from instruments import RigolDG1062Z, RigolDS1104ZPlus

HORIZONTAL_DIVISIONS = 12
MIN_CHANNEL_SCALE = 0.001
MAX_CHANNEL_SCALE = 10


def _log_spaced(lo, hi, n):
    if n <= 1:
        return [lo]
    log_lo = math.log10(lo)
    log_hi = math.log10(hi)
    step = (log_hi - log_lo) / (n - 1)
    return [10 ** (log_lo + i * step) for i in range(n)]


def generate_frequency_points(f_start, f_stop, points_per_decade,
                               cluster_freq=None, cluster_span_factor=3,
                               cluster_density_multiplier=3):
    """Log-spaced frequencies from f_start to f_stop, with extra points
    clustered around cluster_freq (e.g. the filter's cutoff) so the knee of
    the response curve is well resolved.
    """
    decades = math.log10(f_stop / f_start)
    n_points = max(int(round(decades * points_per_decade)) + 1, 2)
    points = set(_log_spaced(f_start, f_stop, n_points))

    if cluster_freq:
        lo = max(cluster_freq / cluster_span_factor, f_start)
        hi = min(cluster_freq * cluster_span_factor, f_stop)
        if hi > lo:
            cluster_decades = math.log10(hi / lo)
            n_extra = max(int(round(cluster_decades * points_per_decade * cluster_density_multiplier)), 2)
            points.update(_log_spaced(lo, hi, n_extra))

    return sorted(points)


def cycles_to_timebase(frequency_hz, cycles_shown=4):
    """Seconds/div needed to display `cycles_shown` periods across the screen."""
    period = 1.0 / frequency_hz
    return (cycles_shown * period) / HORIZONTAL_DIVISIONS


def choose_channel_scale(vpp, target_divisions=6, min_scale=MIN_CHANNEL_SCALE, max_scale=MAX_CHANNEL_SCALE):
    """Volts/div that puts a signal of amplitude `vpp` at `target_divisions` tall."""
    if vpp <= 0:
        return max_scale
    scale = vpp / target_divisions
    return min(max(scale, min_scale), max_scale)


class SweepResult:
    __slots__ = ("frequency_hz", "vpp_in", "vpp_out", "gain_db", "phase_deg")

    def __init__(self, frequency_hz, vpp_in, vpp_out, gain_db, phase_deg):
        self.frequency_hz = frequency_hz
        self.vpp_in = vpp_in
        self.vpp_out = vpp_out
        self.gain_db = gain_db
        self.phase_deg = phase_deg


class SweepRunner:
    """Owns the instrument connections for one sweep run and executes it.

    CH1 on the scope is wired to the filter OUTPUT, CH2 to the filter INPUT
    (shared node with the generator), so gain = Vpp(CH1) / Vpp(CH2) and CH2
    is used as the trigger source since its amplitude stays constant across
    the whole sweep.
    """

    def __init__(self, gen_ip, scope_ip, resource_manager,
                 f_start=10, f_stop=1_000_000, points_per_decade=10,
                 cluster_freq=100_000, amplitude_vpp=1.0,
                 probe_ratio_ch1=1, probe_ratio_ch2=1,
                 averaging_count=8, settle_margin_s=0.15,
                 initial_warmup_s=1.5, output_load="50",
                 progress_callback=None, stop_event=None,
                 csv_path=None):
        self.gen_ip = gen_ip
        self.scope_ip = scope_ip
        self.rm = resource_manager
        self.f_start = f_start
        self.f_stop = f_stop
        self.points_per_decade = points_per_decade
        self.cluster_freq = cluster_freq
        self.amplitude_vpp = amplitude_vpp
        self.probe_ratio_ch1 = probe_ratio_ch1
        self.probe_ratio_ch2 = probe_ratio_ch2
        self.averaging_count = averaging_count
        self.settle_margin_s = settle_margin_s
        self.initial_warmup_s = initial_warmup_s
        # Generator's assumed load impedance ("50" ohms, or "INF" for High-Z).
        # This must match the *actual* physical termination at the filter's
        # output (e.g. a real 50-ohm terminator resistor) - it only changes
        # how the generator computes its output amplitude, it doesn't by
        # itself add any real termination.
        self.output_load = output_load
        self.progress_callback = progress_callback or (lambda *a, **k: None)
        self.stop_event = stop_event or threading.Event()
        self.csv_path = csv_path

    def _settle_time(self, timebase):
        # Averaging needs several full-screen acquisitions to converge; this
        # is a rough heuristic, not an exact spec figure.
        acquisition_time = timebase * HORIZONTAL_DIVISIONS
        return max(self.settle_margin_s, acquisition_time * self.averaging_count * 0.5)

    def _configure_scope(self, scope, input_scale):
        # Instrument settings persist on the scope itself regardless of any
        # particular VISA connection's lifetime, so a stale measurement item
        # from a previous run isn't cleared just by opening a new session -
        # clear_measurements() resets that explicitly.
        scope.clear_measurements()
        scope.setup_channels(self.probe_ratio_ch1, self.probe_ratio_ch2,
                              input_scale_ch2=input_scale)
        scope.setup_trigger(source="CHANnel2", level=0.0)
        scope.setup_averaging(self.averaging_count)

    def run(self):
        gen = RigolDG1062Z(self.rm, self.gen_ip, channel=1)
        scope = RigolDS1104ZPlus(self.rm, self.scope_ip)

        results = []
        csv_file = None
        writer = None
        try:
            gen.identify()
            scope.identify()

            gen.setup_sine(self.f_start, self.amplitude_vpp, load=self.output_load)

            input_scale = choose_channel_scale(self.amplitude_vpp)
            self._configure_scope(scope, input_scale)

            # One-time warm-up: the generator output and the scope's average
            # acquisition mode were both just switched on/reconfigured for the
            # first time, and need longer to stabilize than the steady-state
            # per-point settle time below (this is what caused a bad first
            # reading before this fix was added).
            time.sleep(self.initial_warmup_s)

            if self.csv_path:
                csv_file = open(self.csv_path, "w", newline="")
                writer = csv.writer(csv_file)
                writer.writerow(["frequency_hz", "vpp_in", "vpp_out", "gain_db", "phase_deg"])

            frequencies = generate_frequency_points(
                self.f_start, self.f_stop, self.points_per_decade,
                cluster_freq=self.cluster_freq,
            )

            out_scale = input_scale  # first guess: unity gain at low frequency
            in_scale = input_scale  # CH2 isn't actually constant-amplitude
            # near a notch/transmission zero (the filter's input impedance
            # varies there), so it needs the same dynamic auto-ranging as
            # CH1 - a fixed scale can clip CH2's waveform off the display
            # exactly at those points, making VPP/phase unmeasurable there
            # (confirmed by watching the scope screen directly during a run).
            consecutive_invalid_vpp_out = 0
            consecutive_invalid_vpp_in = 0
            MAX_CONSECUTIVE_INVALID = 2

            for i, freq in enumerate(frequencies):
                if self.stop_event.is_set():
                    break

                gen.set_frequency(freq)
                timebase = cycles_to_timebase(freq)
                scope.set_timebase(timebase)
                scope.set_channel_scale(1, out_scale)
                scope.set_channel_scale(2, in_scale)

                settle = self._settle_time(timebase)
                time.sleep(settle)

                vpp_out = scope.measure_vpp(1)

                # Re-range CH1 if the previous scale is a poor fit and re-measure.
                if vpp_out > 0:
                    ideal_scale = choose_channel_scale(vpp_out)
                    if abs(ideal_scale - out_scale) / out_scale > 0.3:
                        out_scale = ideal_scale
                        scope.set_channel_scale(1, out_scale)
                        time.sleep(settle)
                        vpp_out = scope.measure_vpp(1)
                elif math.isnan(vpp_out) and out_scale > MIN_CHANNEL_SCALE:
                    # The signal may simply be too small to resolve at the
                    # current scale (common deep in the stopband) rather than
                    # genuinely absent - zoom CH1 in and retry once before
                    # giving up on this point.
                    out_scale = max(out_scale / 10, MIN_CHANNEL_SCALE)
                    scope.set_channel_scale(1, out_scale)
                    time.sleep(settle)
                    vpp_out = scope.measure_vpp(1)

                if math.isnan(vpp_out):
                    consecutive_invalid_vpp_out += 1
                else:
                    consecutive_invalid_vpp_out = 0

                if consecutive_invalid_vpp_out >= MAX_CONSECUTIVE_INVALID:
                    # Sustained failure across multiple points - not just one
                    # low-SNR blip the retry above already tried to fix - means
                    # something is stuck. This also covers the case where a
                    # single spurious-but-plausible (non-NaN) bad reading
                    # earlier drove out_scale to an extreme (e.g. the scope's
                    # finest scale) with the real signal now off-screen: the
                    # per-point retries above can only zoom CH1 IN, never back
                    # OUT, so once mis-ranged this way there's no recovery
                    # without resetting out_scale itself back to a sane guess.
                    scope.close()
                    scope = RigolDS1104ZPlus(self.rm, self.scope_ip)
                    self._configure_scope(scope, input_scale)
                    out_scale = input_scale
                    scope.set_timebase(timebase)
                    scope.set_channel_scale(1, out_scale)
                    time.sleep(self.initial_warmup_s)
                    vpp_out = scope.measure_vpp(1)
                    consecutive_invalid_vpp_out = 0

                vpp_in = scope.measure_vpp(2)

                # Re-range CH2 if the previous scale is a poor fit and re-measure.
                if vpp_in > 0:
                    ideal_scale = choose_channel_scale(vpp_in)
                    if abs(ideal_scale - in_scale) / in_scale > 0.3:
                        in_scale = ideal_scale
                        scope.set_channel_scale(2, in_scale)
                        time.sleep(settle)
                        vpp_in = scope.measure_vpp(2)
                elif math.isnan(vpp_in) and in_scale < MAX_CHANNEL_SCALE:
                    # Unlike CH1 (which tends to fail from being too SMALL
                    # deep in the stopband), CH2 tends to fail from being too
                    # BIG - its actual amplitude swells near a notch/
                    # transmission zero and clips off the display at the
                    # scale calibrated for its nominal constant amplitude -
                    # so the right recovery direction here is to widen the
                    # scale, not narrow it.
                    in_scale = min(in_scale * 10, MAX_CHANNEL_SCALE)
                    scope.set_channel_scale(2, in_scale)
                    time.sleep(settle)
                    vpp_in = scope.measure_vpp(2)

                if math.isnan(vpp_in):
                    consecutive_invalid_vpp_in += 1
                else:
                    consecutive_invalid_vpp_in = 0

                if consecutive_invalid_vpp_in >= MAX_CONSECUTIVE_INVALID:
                    # Same sustained-failure safety net as CH1: reconnect and
                    # reset CH2's scale back to the nominal guess in case a
                    # spurious reading ratcheted it to an extreme with no way
                    # back.
                    scope.close()
                    scope = RigolDS1104ZPlus(self.rm, self.scope_ip)
                    self._configure_scope(scope, input_scale)
                    in_scale = input_scale
                    scope.set_timebase(timebase)
                    scope.set_channel_scale(1, out_scale)
                    scope.set_channel_scale(2, in_scale)
                    time.sleep(self.initial_warmup_s)
                    vpp_in = scope.measure_vpp(2)
                    consecutive_invalid_vpp_in = 0

                if math.isnan(vpp_in):
                    # One more retry with extra settle time for any remaining
                    # transient case not explained by scale/clipping.
                    time.sleep(settle)
                    vpp_in = scope.measure_vpp(2)

                phase_deg = scope.measure_phase(1, 2)

                if math.isnan(phase_deg):
                    # Phase (edge-crossing based) can fail even when Vpp is
                    # fine, e.g. at low-SNR points near a deep notch. A retry
                    # after a little more settle time sometimes recovers it.
                    time.sleep(settle)
                    phase_deg = scope.measure_phase(1, 2)

                if math.isnan(vpp_in) or math.isnan(vpp_out):
                    gain_db = float("nan")
                elif vpp_in > 0 and vpp_out > 0:
                    gain_db = 20 * math.log10(vpp_out / vpp_in)
                else:
                    gain_db = float("-inf")

                result = SweepResult(freq, vpp_in, vpp_out, gain_db, phase_deg)
                results.append(result)

                if writer:
                    writer.writerow([freq, vpp_in, vpp_out, gain_db, phase_deg])
                    csv_file.flush()

                self.progress_callback(i + 1, len(frequencies), result)

        finally:
            try:
                gen.close()
            except Exception:
                pass
            try:
                scope.close()
            except Exception:
                pass
            if csv_file:
                csv_file.close()

        return results
