"""Tkinter GUI for running the lowpass filter frequency-response sweep and
plotting a live Bode plot as data comes in.
"""

import math
import os
import queue
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import pyvisa

from sweep import SweepRunner


def _split_phase_at_wraps(freqs, phases):
    """Builds (x, y) arrays for plotting phase on a fixed +-180deg axis.

    When consecutive raw (already +-180-bounded) phase readings imply the
    true phase crossed the +-180 boundary, splits the line into a segment
    exiting exactly at the boundary it crosses and a separate segment
    re-entering from the opposite boundary (with a gap in between) - instead
    of drawing one misleading line straight across the plot. The crossing
    x-position is interpolated in log-frequency space to line up visually
    with the log-scale x-axis. NaN phase values pass through as gaps as
    before. Display-only - the raw wrapped values are what's saved to CSV.
    """
    if not freqs:
        return [], []

    out_x = [freqs[0]]
    out_y = [phases[0]]

    for i in range(1, len(freqs)):
        f0, y0 = freqs[i - 1], phases[i - 1]
        f1, y1 = freqs[i], phases[i]

        if math.isnan(y0) or math.isnan(y1):
            out_x.append(f1)
            out_y.append(y1)
            continue

        raw_delta = y1 - y0
        if raw_delta > 180:
            exit_boundary, enter_boundary, true_delta = -180.0, 180.0, raw_delta - 360
        elif raw_delta < -180:
            exit_boundary, enter_boundary, true_delta = 180.0, -180.0, raw_delta + 360
        else:
            out_x.append(f1)
            out_y.append(y1)
            continue

        if true_delta == 0:
            out_x.append(f1)
            out_y.append(y1)
            continue

        t = (exit_boundary - y0) / true_delta
        log_f_cross = math.log10(f0) + t * (math.log10(f1) - math.log10(f0))
        f_cross = 10 ** log_f_cross

        out_x.extend([f_cross, f_cross, f_cross, f1])
        out_y.extend([exit_boundary, float("nan"), enter_boundary, y1])

    return out_x, out_y


class FilterSweepApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lowpass Filter Frequency Response")
        self.geometry("1050x780")

        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.results = []
        self._current_csv_path = None
        self._current_png_path = None

        self._build_widgets()
        self._poll_queue()

    # -- UI construction -----------------------------------------------

    def _build_widgets(self):
        conn_frame = ttk.LabelFrame(self, text="Instrument connections (LAN)")
        conn_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(conn_frame, text="Generator IP (DG1062Z):").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.gen_ip_var = tk.StringVar(value="192.168.1.10")
        ttk.Entry(conn_frame, textvariable=self.gen_ip_var, width=16).grid(row=0, column=1, padx=4, pady=4)

        ttk.Label(conn_frame, text="Scope IP (DS1104Z Plus):").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self.scope_ip_var = tk.StringVar(value="192.168.1.11")
        ttk.Entry(conn_frame, textvariable=self.scope_ip_var, width=16).grid(row=0, column=3, padx=4, pady=4)

        ttk.Button(conn_frame, text="Test Connection", command=self._on_test_connection).grid(
            row=0, column=4, padx=8, pady=4
        )

        self.conn_status_var = tk.StringVar(value="Not tested")
        ttk.Label(conn_frame, textvariable=self.conn_status_var).grid(row=0, column=5, padx=4, pady=4, sticky="w")

        params_frame = ttk.LabelFrame(self, text="Sweep parameters")
        params_frame.pack(fill="x", padx=8, pady=4)

        def add_param(row, col, label, default, width=10):
            ttk.Label(params_frame, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=3)
            var = tk.StringVar(value=str(default))
            ttk.Entry(params_frame, textvariable=var, width=width).grid(row=row, column=col + 1, padx=4, pady=3)
            return var

        self.f_start_var = add_param(0, 0, "Start freq (Hz):", 10)
        self.f_stop_var = add_param(0, 2, "Stop freq (Hz):", 1_000_000)
        self.ppd_var = add_param(0, 4, "Points/decade:", 10)
        self.cutoff_var = add_param(1, 0, "Filter cutoff (Hz):", 100_000)
        self.amplitude_var = add_param(1, 2, "Amplitude (Vpp):", 1.0)
        self.avg_var = add_param(1, 4, "Scope averages:", 8)
        self.probe1_var = add_param(2, 0, "CH1 probe ratio:", 1)
        self.probe2_var = add_param(2, 2, "CH2 probe ratio:", 1)

        ttk.Label(params_frame, text="CSV & PNG output:").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.output_location_var = tk.StringVar(value="(will be created when a sweep starts)")
        ttk.Entry(
            params_frame, textvariable=self.output_location_var, width=52, state="readonly"
        ).grid(row=3, column=1, columnspan=4, padx=4, pady=3, sticky="w")

        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", padx=8, pady=4)

        self.start_button = ttk.Button(control_frame, text="Start Sweep", command=self._on_start)
        self.start_button.pack(side="left", padx=4)

        self.stop_button = ttk.Button(control_frame, text="Stop", command=self._on_stop, state="disabled")
        self.stop_button.pack(side="left", padx=4)

        ttk.Button(control_frame, text="Save Plot PNG", command=self._on_save_png).pack(side="left", padx=4)

        self.progress_var = tk.StringVar(value="Idle")
        ttk.Label(control_frame, textvariable=self.progress_var).pack(side="left", padx=12)

        self.progress_bar = ttk.Progressbar(control_frame, mode="determinate", length=300)
        self.progress_bar.pack(side="left", padx=8)

        plot_frame = ttk.Frame(self)
        plot_frame.pack(fill="both", expand=True, padx=8, pady=4)

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.mag_ax = self.figure.add_subplot(211)
        self.phase_ax = self.figure.add_subplot(212, sharex=self.mag_ax)
        self.figure.tight_layout(pad=3.0)
        self._reset_axes()

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.draw()

    def _reset_axes(self):
        self.mag_ax.clear()
        self.mag_ax.set_xscale("log")
        self.mag_ax.set_ylabel("Gain (dB)")
        self.mag_ax.set_title("Lowpass Filter Frequency Response")
        self.mag_ax.grid(True, which="both", linestyle=":")

        self.phase_ax.clear()
        self.phase_ax.set_xscale("log")
        self.phase_ax.set_xlabel("Frequency (Hz)")
        self.phase_ax.set_ylabel("Phase (deg)")
        self.phase_ax.set_ylim(-180, 180)
        self.phase_ax.grid(True, which="both", linestyle=":")

    # -- helpers ---------------------------------------------------------

    def _new_run_paths(self):
        """Creates Sweep_Results/sweep_<timestamp>/ and returns (csv_path, png_path)."""
        project_root = os.path.dirname(os.path.abspath(__file__))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_name = f"sweep_{stamp}"
        run_folder = os.path.join(project_root, "Sweep_Results", run_name)
        os.makedirs(run_folder, exist_ok=True)
        csv_path = os.path.join(run_folder, f"{run_name}.csv")
        png_path = os.path.join(run_folder, f"{run_name}.png")
        return csv_path, png_path

    # -- button handlers --------------------------------------------------

    def _on_test_connection(self):
        try:
            rm = pyvisa.ResourceManager("@py")

            gen_resource = rm.open_resource(f"TCPIP0::{self.gen_ip_var.get()}::INSTR")
            gen_resource.timeout = 3000
            gen_id = gen_resource.query("*IDN?").strip()
            gen_resource.close()

            scope_resource = rm.open_resource(f"TCPIP0::{self.scope_ip_var.get()}::INSTR")
            scope_resource.timeout = 3000
            scope_id = scope_resource.query("*IDN?").strip()
            scope_resource.close()

            rm.close()
            self.conn_status_var.set("Connected OK")
            messagebox.showinfo("Connection test", f"Generator:\n{gen_id}\n\nScope:\n{scope_id}")
        except Exception as exc:
            self.conn_status_var.set("Connection failed")
            messagebox.showerror("Connection test failed", str(exc))

    def _on_start(self):
        try:
            f_start = float(self.f_start_var.get())
            f_stop = float(self.f_stop_var.get())
            ppd = int(self.ppd_var.get())
            cutoff = float(self.cutoff_var.get())
            amplitude = float(self.amplitude_var.get())
            probe1 = float(self.probe1_var.get())
            probe2 = float(self.probe2_var.get())
            avg_count = int(self.avg_var.get())
        except ValueError:
            messagebox.showerror("Invalid parameter", "Check that all sweep parameters are valid numbers.")
            return

        if f_start <= 0 or f_stop <= f_start:
            messagebox.showerror("Invalid parameter", "Stop frequency must be greater than start frequency (> 0).")
            return

        csv_path, png_path = self._new_run_paths()
        self._current_csv_path = csv_path
        self._current_png_path = png_path
        self.output_location_var.set(os.path.dirname(csv_path))

        self.results = []
        self._reset_axes()
        self.canvas.draw()
        self.stop_event.clear()
        self.progress_bar["value"] = 0
        self.progress_var.set("Starting...")
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")

        def progress_callback(index, total, result):
            self.result_queue.put(("progress", index, total, result))

        def worker():
            try:
                rm = pyvisa.ResourceManager("@py")
                runner = SweepRunner(
                    gen_ip=self.gen_ip_var.get(),
                    scope_ip=self.scope_ip_var.get(),
                    resource_manager=rm,
                    f_start=f_start,
                    f_stop=f_stop,
                    points_per_decade=ppd,
                    cluster_freq=cutoff,
                    amplitude_vpp=amplitude,
                    probe_ratio_ch1=probe1,
                    probe_ratio_ch2=probe2,
                    averaging_count=avg_count,
                    progress_callback=progress_callback,
                    stop_event=self.stop_event,
                    csv_path=csv_path,
                )
                runner.run()
                rm.close()
                self.result_queue.put(("done", None, None, None))
            except Exception as exc:
                self.result_queue.put(("error", str(exc), None, None))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _on_stop(self):
        self.stop_event.set()
        self.progress_var.set("Stopping...")

    def _on_save_png(self):
        path = filedialog.asksaveasfilename(defaultextension=".png")
        if path:
            self.figure.savefig(path, dpi=150, bbox_inches="tight")
            messagebox.showinfo("Saved", f"Plot saved to {path}")

    # -- background-thread -> UI bridge -----------------------------------

    def _poll_queue(self):
        try:
            while True:
                kind, a, b, c = self.result_queue.get_nowait()
                if kind == "progress":
                    index, total, result = a, b, c
                    self.results.append(result)
                    self.progress_bar["maximum"] = total
                    self.progress_bar["value"] = index
                    self.progress_var.set(
                        f"{index}/{total}  {result.frequency_hz:.1f} Hz  gain={result.gain_db:.2f} dB  "
                        f"phase={result.phase_deg:.1f} deg"
                    )
                    self._update_plot()
                elif kind == "done":
                    if self.stop_event.is_set():
                        self.progress_var.set(f"Stopped ({len(self.results)} points, CSV saved, no PNG)")
                    else:
                        if self._current_png_path and self.results:
                            self.figure.savefig(self._current_png_path, dpi=150, bbox_inches="tight")
                        self.progress_var.set(f"Done ({len(self.results)} points) - CSV & PNG saved")
                    self.start_button.config(state="normal")
                    self.stop_button.config(state="disabled")
                elif kind == "error":
                    self.progress_var.set("Error")
                    self.start_button.config(state="normal")
                    self.stop_button.config(state="disabled")
                    messagebox.showerror("Sweep error", a)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _update_plot(self):
        if not self.results:
            return
        freqs = [r.frequency_hz for r in self.results]
        gains = [r.gain_db for r in self.results]
        phase_freqs, phase_values = _split_phase_at_wraps(
            freqs, [r.phase_deg for r in self.results]
        )

        self._reset_axes()
        self.mag_ax.plot(freqs, gains, marker="o", markersize=3)
        self.phase_ax.plot(phase_freqs, phase_values, marker="o", markersize=3, color="tab:orange")
        self.canvas.draw_idle()
