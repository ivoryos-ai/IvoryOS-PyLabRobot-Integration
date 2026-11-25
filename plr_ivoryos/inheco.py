"""Inheco ThermoShake heater-shakers through PyLabRobot 1.0, on an Inheco TEC control box (USB HID).

    from plr_ivoryos.inheco import InhecoThermoShake
    shaker = InhecoThermoShake(index=1)            # needs plr-ivoryos[hid]
    shaker = InhecoThermoShake(simulated=True)

The steps are `pylabrobot.inheco.InhecoThermoShake`'s methods: shake, start_shaking, stop_shaking,
set_temperature, request_current_temperature, ...
"""

from typing import Literal, Optional

from pylabrobot.inheco import (InhecoTECControlBox, InhecoThermoShake as PLRInhecoThermoShake, inheco_thermoshake,
                               inheco_thermoshake_ac, inheco_thermoshake_rm)

from plr_ivoryos.device import Device, device_steps
from plr_ivoryos.simulators import SimulatedHeaterShaker

_MODELS = {"thermoshake": inheco_thermoshake, "thermoshake_ac": inheco_thermoshake_ac,
           "thermoshake_rm": inheco_thermoshake_rm}


class InhecoThermoShake(Device):
    """An Inheco ThermoShake (classic, AC or RM) on a TEC control box (PyLabRobot: InhecoThermoShake).

    index         which slot of the control box it is on (1 to 6)
    serial_number the control box's serial number; optional when there is one
    model         thermoshake, thermoshake_ac or thermoshake_rm
    simulated     reaches its temperature at once, shakes for the time asked
                  (simulators.SimulatedHeaterShaker)
    step_delay_s  a pause after each step, simulated only
    """

    def __init__(self, index: int = 1, serial_number: Optional[str] = None,
                 model: Literal["thermoshake", "thermoshake_ac", "thermoshake_rm"] = "thermoshake",
                 simulated: bool = False, step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s)
        if model not in _MODELS:
            raise ValueError(f"model is one of {', '.join(_MODELS)}, not '{model}'")
        self._box: Optional[InhecoTECControlBox] = None
        if self._simulated:
            self._plr = SimulatedHeaterShaker(PLRInhecoThermoShake)
        else:
            self._box = InhecoTECControlBox(serial_number=serial_number)
            self._plr = _MODELS[model](name="thermoshake", control_box=self._box, index=int(index))

    async def _connect(self) -> None:
        if self._box is not None:
            await self._box.setup()
        else:
            await super()._connect()

    async def _disconnect(self) -> None:
        if self._box is not None:
            await self._box.stop()
        else:
            await super()._disconnect()


SKIPPED = {"InhecoThermoShake": device_steps(InhecoThermoShake, PLRInhecoThermoShake)}
