"""SCPI wrapper classes for the Rigol DG1062Z function generator and the
Rigol DS1104Z Plus oscilloscope, communicating over LAN (VXI-11) via PyVISA.

Command syntax below was cross-checked against the Rigol DS1000Z Programming
Guide and two real-world open-source drivers (jakeson21/pyDG1000Z,
pklaus/ds1054z) rather than from memory alone, since a wrong SCPI keyword
fails silently or throws an unhelpful VISA error.
"""

import math

import pyvisa


class InstrumentError(RuntimeError):
    pass


def _resource_string(ip_address):
    return f"TCPIP0::{ip_address}::INSTR"


# Rigol scopes return a sentinel value around 9.9E37 when a measurement item
# can't be computed (e.g. not enough valid edges in the current acquisition).
# Anything this large isn't a real Vpp/phase reading, so treat it as missing.
_INVALID_MEASUREMENT_THRESHOLD = 1e30


def _parse_measurement(raw_value):
    value = float(raw_value)
    if math.isnan(value) or abs(value) > _INVALID_MEASUREMENT_THRESHOLD:
        return float("nan")
    return value


class RigolDG1062Z:
    """Drives one sine output channel of the DG1062Z function generator."""

    def __init__(self, resource_manager, ip_address, channel=1, timeout_ms=5000):
        self.channel = channel
        self.inst = resource_manager.open_resource(_resource_string(ip_address))
        self.inst.timeout = timeout_ms
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"

    def identify(self):
        return self.inst.query("*IDN?").strip()

    def setup_sine(self, frequency_hz, amplitude_vpp, load="INF"):
        """Configure channel as a sine source and enable its output.

        load: "INF" for high-impedance load, or a number of ohms (e.g. 50).
        """
        self.inst.write(f":OUTPut{self.channel}:IMPedance {load}")
        self.inst.write(
            f":SOURce{self.channel}:APPLy:SINusoid {frequency_hz},{amplitude_vpp},0"
        )
        self.inst.write(f":OUTPut{self.channel} ON")

    def set_frequency(self, frequency_hz):
        self.inst.write(f":SOURce{self.channel}:FREQuency {frequency_hz}")

    def output_off(self):
        self.inst.write(f":OUTPut{self.channel} OFF")

    def close(self):
        try:
            self.output_off()
        except Exception:
            pass
        self.inst.close()


class RigolDS1104ZPlus:
    """Reads Vpp and phase measurements from two channels of the DS1104Z Plus."""

    def __init__(self, resource_manager, ip_address, timeout_ms=10000):
        self.inst = resource_manager.open_resource(_resource_string(ip_address))
        self.inst.timeout = timeout_ms
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"

    def identify(self):
        return self.inst.query("*IDN?").strip()

    def clear_measurements(self):
        """Clears all enabled measurement item slots on the scope. Used at
        the start of a run to reset any stale measurement state left over
        from a previous run (settings persist on the instrument itself,
        independent of any particular VISA connection's lifetime).
        """
        self.inst.write(":MEASure:CLEar ALL")

    def setup_channels(self, probe_ratio_ch1=1, probe_ratio_ch2=1, input_scale_ch2=None):
        self.inst.write(":CHANnel1:DISPlay ON")
        self.inst.write(":CHANnel2:DISPlay ON")
        self.inst.write(f":CHANnel1:PROBe {probe_ratio_ch1}")
        self.inst.write(f":CHANnel2:PROBe {probe_ratio_ch2}")
        self.inst.write(":CHANnel1:OFFSet 0")
        self.inst.write(":CHANnel2:OFFSet 0")
        if input_scale_ch2 is not None:
            self.inst.write(f":CHANnel2:SCALe {input_scale_ch2}")

    def setup_trigger(self, source="CHANnel2", level=0.0):
        self.inst.write(":TRIGger:MODE EDGE")
        self.inst.write(f":TRIGger:EDGE:SOURce {source}")
        self.inst.write(":TRIGger:EDGE:SLOPe POSitive")
        self.inst.write(f":TRIGger:EDGE:LEVel {level}")

    def setup_averaging(self, count=8):
        self.inst.write(":ACQuire:TYPE AVERages")
        self.inst.write(f":ACQuire:AVERages {count}")

    def set_timebase(self, seconds_per_div):
        self.inst.write(f":TIMebase:MAIN:SCALe {seconds_per_div}")

    def set_channel_scale(self, channel, volts_per_div):
        self.inst.write(f":CHANnel{channel}:SCALe {volts_per_div}")

    def measure_vpp(self, channel):
        """Returns Vpp in volts, or NaN if the scope reports an invalid measurement."""
        self.inst.write(f":MEASure:ITEM VPP,CHANnel{channel}")
        return _parse_measurement(self.inst.query(f":MEASure:ITEM? VPP,CHANnel{channel}"))

    def measure_phase(self, source_a=1, source_b=2):
        """Rising-edge phase of source_a relative to source_b, in degrees,
        or NaN if the scope reports an invalid measurement.
        """
        self.inst.write(f":MEASure:ITEM RPHase,CHANnel{source_a},CHANnel{source_b}")
        return _parse_measurement(
            self.inst.query(f":MEASure:ITEM? RPHase,CHANnel{source_a},CHANnel{source_b}")
        )

    def close(self):
        self.inst.close()
