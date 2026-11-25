"""Molecular Devices SpectraMax plate readers through PyLabRobot 1.0: the M5 and the 384 Plus.

    from plr_ivoryos.molecular_devices import SpectraMaxM5, SpectraMax384Plus
    reader = SpectraMaxM5(port="/dev/ttyUSB0")      # needs plr-ivoryos[serial]
    reader = SpectraMax384Plus(simulated=True)

The steps are PyLabRobot's own methods. `plate` and `wells` name labware on a liquid handler's
worktable (device.Reader). The SpectraMax Gemini EM is driven only through PyLabRobot's legacy
backend (legacy.SpectraMaxGeminiEM).
"""

from typing import Optional

from pylabrobot.molecular_devices.spectramax.spectramax_384_plus import SpectraMax384Plus as PLRSpectraMax384Plus
from pylabrobot.molecular_devices.spectramax.spectramax_m5 import SpectraMaxM5 as PLRSpectraMaxM5

from plr_ivoryos import worktable as _worktable
from plr_ivoryos.device import Reader, device_steps
from plr_ivoryos.simulators import SimulatedPlateReader


class _SpectraMax(Reader):
    _PLR: type

    def __init__(self, port: Optional[str] = None, simulated: bool = False, worktable: Optional[str] = None,
                 plate_type: str = _worktable._PLATE, signal_liquids: str = "dye", step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s, worktable, plate_type, signal_liquids)
        if self._simulated:
            self._plr = SimulatedPlateReader(self._PLR, self)
        elif not port:
            raise ValueError("Give the reader's serial port, or simulated=True.")
        else:
            self._plr = self._PLR(name=type(self).__name__.lower(), port=port)


class SpectraMaxM5(_SpectraMax):
    """A SpectraMax M5 over serial: absorbance, fluorescence (also polarization and time-resolved)
    and luminescence (PyLabRobot: SpectraMaxM5).

    port         the serial port
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """
    _PLR = PLRSpectraMaxM5


class SpectraMax384Plus(_SpectraMax):
    """A SpectraMax 384 Plus absorbance reader over serial (PyLabRobot: SpectraMax384Plus).

    port         the serial port
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """
    _PLR = PLRSpectraMax384Plus


SKIPPED = {
    "SpectraMaxM5": device_steps(SpectraMaxM5, PLRSpectraMaxM5, exclude=("wait_for_idle",)),
    "SpectraMax384Plus": device_steps(SpectraMax384Plus, PLRSpectraMax384Plus, exclude=("wait_for_idle",)),
}
