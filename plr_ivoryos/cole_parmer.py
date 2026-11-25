"""Cole-Parmer Masterflex peristaltic pumps, through PyLabRobot 1.0.

    from plr_ivoryos.cole_parmer import Masterflex
    pump = Masterflex(com_port="COM4")          # needs plr-ivoryos[serial]
    pump = Masterflex(simulated=True)

The steps are `pylabrobot.cole_parmer.Masterflex`'s methods: run_continuously, run_revolutions,
halt. PyLabRobot 1.0 has no volume calibration for it: a volume is revolutions you have measured.
"""

from typing import Optional

from pylabrobot.cole_parmer import Masterflex as PLRMasterflex

from plr_ivoryos.device import Device, device_steps
from plr_ivoryos.simulators import SimulatedPump


class Masterflex(Device):
    """A Masterflex peristaltic pump over serial (PyLabRobot: cole_parmer.Masterflex).

    com_port     the serial port (COM4, /dev/ttyUSB0)
    simulated    a pump that keeps its speed and revolutions (simulators.SimulatedPump)
    step_delay_s a pause after each step, simulated only
    """

    def __init__(self, com_port: Optional[str] = None, simulated: bool = False, step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s)
        if self._simulated:
            self._plr = SimulatedPump(PLRMasterflex)
        elif not com_port:
            raise ValueError("Give the pump's com_port, or simulated=True.")
        else:
            self._plr = PLRMasterflex(com_port=com_port)


SKIPPED = {"Masterflex": device_steps(Masterflex, PLRMasterflex)}
