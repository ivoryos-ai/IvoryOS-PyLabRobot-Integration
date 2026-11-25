"""Byonoy plate readers through PyLabRobot 1.0: the Absorbance 96 Automate and the Luminescence 96
Automate (USB HID).

    from plr_ivoryos.byonoy import ByonoyAbsorbance96, ByonoyLuminescence96
    reader = ByonoyAbsorbance96()                   # needs plr-ivoryos[hid]
    reader = ByonoyAbsorbance96(simulated=True)     # reads the plates of the liquid handler beside it

The steps are PyLabRobot's own methods. `plate` and `wells` name labware on a liquid handler's
worktable (device.Reader).
"""

from typing import Optional

from pylabrobot.byonoy import ByonoyAbsorbance96 as PLRByonoyAbsorbance96
from pylabrobot.byonoy import ByonoyLuminescence96 as PLRByonoyLuminescence96
from pylabrobot.byonoy.absorbance_96 import byonoy_a96a_detection_unit
from pylabrobot.byonoy.luminescence_96 import byonoy_l96_reader_unit

from plr_ivoryos import worktable as _worktable
from plr_ivoryos.device import Reader, device_steps
from plr_ivoryos.simulators import SimulatedPlateReader


class ByonoyAbsorbance96(Reader):
    """A Byonoy Absorbance 96 Automate (A96A) detection unit over USB (PyLabRobot: ByonoyAbsorbance96).

    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, plate_type: str = _worktable._PLATE,
                 signal_liquids: str = "dye", step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s, worktable, plate_type, signal_liquids)
        self._plr = SimulatedPlateReader(PLRByonoyAbsorbance96, self) if self._simulated else \
            byonoy_a96a_detection_unit("byonoy_absorbance_96")


class ByonoyLuminescence96(Reader):
    """A Byonoy Luminescence 96 Automate (L96) reader unit over USB (PyLabRobot: ByonoyLuminescence96).

    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, plate_type: str = _worktable._PLATE,
                 signal_liquids: str = "dye", step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s, worktable, plate_type, signal_liquids)
        self._plr = SimulatedPlateReader(PLRByonoyLuminescence96, self) if self._simulated else \
            byonoy_l96_reader_unit("byonoy_luminescence_96")


SKIPPED = {
    "ByonoyAbsorbance96": device_steps(ByonoyAbsorbance96, PLRByonoyAbsorbance96),
    "ByonoyLuminescence96": device_steps(ByonoyLuminescence96, PLRByonoyLuminescence96),
}
