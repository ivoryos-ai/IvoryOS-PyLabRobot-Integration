"""QInstruments BioShake shakers and heater-shakers, through PyLabRobot 1.0.

    from plr_ivoryos.qinstruments import BioShake
    shaker = BioShake(port="COM5", model="BioShakeQ1")     # needs plr-ivoryos[serial]
    shaker = BioShake(simulated=True)

The steps are `pylabrobot.qinstruments.BioShake`'s methods: shake, start_shaking, stop_shaking,
set_temperature, lock_plate, ... The model decides what the device can do, and PyLabRobot refuses
what a model does not have (no heating on a BioShake 3000); the simulator refuses the same.

PyLabRobot 1.0.0b1 can make four models (MODELS). It names eight more (BioShake 3000-T, 3000-T elm,
5000 elm, D30 elm, D30-T elm, Q2, Heatplate, ColdPlate) but has no resource definition for them
yet, so making one raises "missing resource definition"; they are offered here when it does.
"""

from typing import Literal, Optional

import pylabrobot.qinstruments as _q
from pylabrobot.qinstruments import BioShake as PLRBioShake

from plr_ivoryos.device import Device, device_steps
from plr_ivoryos.simulators import SimulatedHeaterShaker

# What each model PyLabRobot 1.0.0b1 can make does (its own factories' flags): shake, lock a plate
# (an ELM), control temperature.
MODELS = {
    "BioShakeQ1": {"shake": True, "lock": True, "temperature": True},
    "BioShake3000": {"shake": True, "lock": False, "temperature": False},
    "BioShake3000Elm": {"shake": True, "lock": True, "temperature": False},
    "BioShake3000ElmDWP": {"shake": True, "lock": True, "temperature": False},
}
Model = Literal["BioShakeQ1", "BioShake3000", "BioShake3000Elm", "BioShake3000ElmDWP"]


class _SimulatedBioShake(SimulatedHeaterShaker):
    """The heater-shaker simulator, refusing what the model cannot do as PyLabRobot's BioShake does."""

    def __init__(self, can: dict):
        super().__init__(PLRBioShake)
        self._can = can

    def _need(self, what: str, message: str) -> None:
        if not self._can[what]:
            raise RuntimeError(message)

    async def set_temperature(self, temperature: float, *args, **kwargs):
        self._need("temperature", "This BioShake device does not support temperature control.")
        await super().set_temperature(temperature)

    async def lock_plate(self, *args, **kwargs):
        self._need("lock", "This BioShake device does not have an ELM and cannot lock plates.")
        await super().lock_plate()

    async def unlock_plate(self, *args, **kwargs):
        self._need("lock", "This BioShake device does not have an ELM and cannot lock plates.")
        await super().unlock_plate()


class BioShake(Device):
    """A QInstruments BioShake over serial (PyLabRobot: qinstruments.BioShake).

    port         the serial port
    model        BioShakeQ1 (shakes, locks, heats and cools), BioShake3000 (shakes), BioShake3000Elm
                 or BioShake3000ElmDWP (shake and lock): the models PyLabRobot 1.0.0b1 can make
    simulated    reaches its temperature at once, shakes for the time asked, and refuses what the
                 model cannot do (simulators.SimulatedHeaterShaker)
    step_delay_s a pause after each step, simulated only
    """

    def __init__(self, port: Optional[str] = None, model: Model = "BioShakeQ1", simulated: bool = False,
                 step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s)
        if model not in MODELS:
            raise ValueError(f"PyLabRobot 1.0.0b1 can make a BioShake of model {', '.join(MODELS)}, not '{model}'"
                             " (it names more, but has no resource definition for them yet).")
        if self._simulated:
            self._plr = _SimulatedBioShake(MODELS[model])
        elif not port:
            raise ValueError("Give the BioShake's serial port, or simulated=True.")
        else:
            self._plr = getattr(_q, model)(name="bioshake", port=port)


SKIPPED = {"BioShake": device_steps(BioShake, PLRBioShake)}
