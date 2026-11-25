"""Mettler Toledo balances, through PyLabRobot 1.0's MT-SICS driver.

    from plr_ivoryos.mettler_toledo import MettlerToledoWXS205SDU
    scale = MettlerToledoWXS205SDU(port="/dev/ttyUSB0")     # needs plr-ivoryos[serial]
    scale = MettlerToledoWXS205SDU(simulated=True)

The steps are `pylabrobot.mettler_toledo.MTSICSDriver`'s methods (PyLabRobot calls the class
MettlerToledoWXS205SDU too): tare, zero, read_weight, read_stable_weight, request_capacity, ...
Any balance that speaks MT-SICS works the same way.
"""

from typing import Optional

from pylabrobot.mettler_toledo import MTSICSDriver

from plr_ivoryos.device import Device, device_steps
from plr_ivoryos.simulators import SimulatedScale


class MettlerToledoWXS205SDU(Device):
    """A Mettler Toledo balance over MT-SICS (PyLabRobot: MTSICSDriver).

    port         the serial port (COM3, /dev/ttyUSB0); optional: PyLabRobot finds the balance by
                 its USB ids
    simulated    a balance with nothing on it (simulators.SimulatedScale)
    step_delay_s a pause after each step, simulated only
    """

    def __init__(self, port: Optional[str] = None, simulated: bool = False, step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s)
        self._plr = SimulatedScale(MTSICSDriver) if self._simulated else MTSICSDriver(port=port)


SKIPPED = {"MettlerToledoWXS205SDU": device_steps(MettlerToledoWXS205SDU, MTSICSDriver)}
