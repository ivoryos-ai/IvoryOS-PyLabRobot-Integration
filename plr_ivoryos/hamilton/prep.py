"""A Hamilton Prep in IvoryOS, through PyLabRobot 1.0.

    from plr_ivoryos.hamilton import Prep
    prep = Prep(simulated=True)                  # PyLabRobot's Prep simulator
    prep = Prep(host="192.168.1.50")             # a real Prep on the network

As with the STAR (star.py), the Prep is an instrument and each thing fitted to it is one too:
`prep_pipettes` (the two independent channels), `prep_head8` (the 8-channel head), `prep_core_grippers`,
`prep_heater_shaker` and `prep_lights`, each with its PyLabRobot class's own steps. The worktable
is the Prep's eight labware spots, named 0 to 7 (front left first, column by column, as PyLabRobot's
`deck[0]` to `deck[7]`).

`simulated=True` is PyLabRobot's own Prep simulator (`PrepSimulationDriver`), with what its recording
of a Prep has fitted (two channels, an 8-channel head, a heater shaker).
"""

from typing import Any, Dict, List, Optional

from pylabrobot.hamilton.prep.device import Prep as plr_Prep, PrepDevice
from pylabrobot.hamilton.prep.driver.features.core_grippers import CoreGrippers
from pylabrobot.hamilton.prep.driver.features.head8 import Head8
from pylabrobot.hamilton.prep.driver.features.heater_shaker import PrepHamiltonHeaterShaker
from pylabrobot.hamilton.prep.driver.features.lights import Lights
from pylabrobot.hamilton.prep.driver.features.pipettes import Pipettes

from plr_ivoryos import bridge
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.robot import WorktableRobot, part_class, toggle
from plr_ivoryos.wells import Labware, Site

PARTS = ("pipettes", "head8", "core_grippers", "heater_shaker", "lights")


def check_equipment(equipment: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(equipment, dict):
        raise ValueError('equipment is {"pipettes": true, "head8": true, "heater_shaker": true, ...}')
    unknown = sorted(set(equipment) - set(PARTS))
    if unknown:
        raise ValueError(f"'{unknown[0]}' is not something fitted to a Prep: {', '.join(PARTS)}.")
    return {part: bool(equipment.get(part, False)) for part in PARTS}


def _fitted(device) -> Dict[str, bool]:
    return {part: getattr(device, part, None) is not None for part in PARTS}


class Prep(WorktableRobot):
    """A Hamilton Prep. Steps take labware names and wells; the channels, the 8-channel head, the
    CoRe grippers, the heater shaker and the lights are instruments of their own.

    host / port    the Prep on the network (port 2000)
    simulated      PyLabRobot's Prep simulator
    worktable      the worktable file (worktable.py); optional, worktable.json in the deck's data folder
    equipment      what is fitted, for a real Prep when the file does not say (it is asked otherwise)
    step_delay_s   a pause after each step, simulated only
    tracking       PyLabRobot's tip and volume tracking
    layouts_folder where layouts saved by name are kept; optional, worktable.layouts beside the
                   worktable file (see Flex)
    """

    KINDS = ["PrepDeck"]

    def __init__(self, host: Optional[str] = None, port: int = 2000, simulated: bool = False,
                 worktable: Optional[str] = None, equipment: Optional[Dict[str, Any]] = None,
                 step_delay_s: float = 0.0, tracking: bool = True,
                 layouts_folder: Optional[str] = None):
        if not simulated and not host:
            raise ValueError("Give the Prep's host, or simulated=True.")
        if simulated and host:
            raise ValueError("simulated=True runs no robot, so a host beside it would be ignored.")
        super().__init__(worktable, "PrepDeck", simulated, step_delay_s, tracking, layouts_folder)
        self._host, self._port = host, int(port)
        found = None if self._new_file else self._config.get("equipment")
        if simulated:
            self._config["equipment"] = self._ask(self._make_plr(worktable_deck()))
        elif found or equipment:
            self._config["equipment"] = check_equipment(found or equipment)
        else:
            self._config["equipment"] = self._ask(self._make_plr(worktable_deck()), real=True)
            self._new_file = True
        self._plr = self._make_plr(self.deck)
        self._parts = {part: PART_CLASSES[part](self, part) for part in PARTS if self.equipment.get(part)}
        if self._new_file and not self._simulated:
            self._save()
        self._after_init()

    @property
    def equipment(self) -> Dict[str, Any]:
        return dict(self._config.get("equipment") or {})

    def _make_plr(self, deck) -> PrepDevice:
        if self._simulated:
            return plr_Prep(deck=deck, simulation=True)
        return plr_Prep(deck=deck, host=self._host, port=self._port)

    def _ask(self, device, real: bool = False) -> Dict[str, Any]:
        async def ask():
            await device.setup(skip_device_initialization=True)
            try:
                return _fitted(device)
            finally:
                await device.stop()
        try:
            return check_equipment(run_async(ask()))
        except Exception as e:
            if not real:
                raise
            raise ValueError(f"The worktable file ({self._path}) does not say what is fitted to the Prep, and the Prep "
                             f"at {self._host}:{self._port} could not be asked ({type(e).__name__}: {e}). Turn it on, "
                             'or write equipment in the file: {"pipettes": true, "head8": false, ...}.') from None

    async def _connect(self) -> None:
        await self._plr.setup()
        fitted = _fitted(self._plr)
        missing = [part for part, wanted in self.equipment.items() if wanted and not fitted[part]]
        if missing:
            await self._plr.stop()
            raise RuntimeError(f"The Prep does not have what the worktable file says it has: no {', '.join(missing)}. "
                               f"Change equipment in {self._path} and restart the deck.")

    async def _disconnect(self) -> None:
        await self._plr.stop()

    def _plr_target(self):
        return self._plr

    def _attach_deck(self, deck) -> None:
        self._plr = self._make_plr(deck)

    def _checked(self, config: dict) -> dict:
        """A layout from a file says what is fitted too: refuse what this robot cannot have, not
        when the deck next starts."""
        config["equipment"] = check_equipment(config.get("equipment") or self.equipment)
        return config

    def setup(self) -> None:
        """Connect and initialize the Prep, checking what is fitted against the worktable file. Any
        other step does this itself the first time. (PyLabRobot: Prep.setup)"""
        run_async(self._setup())

    def stop(self) -> None:
        """Put the Prep down. The next step sets it up again. (PyLabRobot: Prep.stop)"""
        if self._ready:
            run_async(self._disconnect())
            self._ready = False

    def _deck_extras(self) -> dict:
        return {"equipment": {part: True for part, on in self.equipment.items() if on}}

    def _equipment_fields(self) -> List[dict]:
        now = self.equipment
        return [toggle(part, label, now.get(part)) for part, label in (
            ("pipettes", "Channels"), ("head8", "8-channel head"), ("core_grippers", "CoRe grippers"),
            ("heater_shaker", "Heater shaker"), ("lights", "Lights"))]

    def _equipment_fixed(self) -> Optional[str]:
        if self._simulated:
            return "As PyLabRobot's recording of a Prep has it."
        return "As the Prep reported it: what is built into it is not changed here."


def worktable_deck():
    from plr_ivoryos import worktable
    return worktable.make_deck("PrepDeck")


_MOVABLE = Labware("plate", "reservoir", "tip_rack", "tube_rack")
_HERE = __name__

PART_CLASSES = {
    "pipettes": part_class("PrepPipettes", Pipettes, "The Prep's independent channels (PyLabRobot: Pipettes).", _HERE),
    "head8": part_class("PrepHead8", Head8, "The Prep's 8-channel head (PyLabRobot: Head8).", _HERE),
    "core_grippers": part_class("PrepCoreGrippers", CoreGrippers, "The Prep's CoRe grippers (PyLabRobot: CoreGrippers).",
                                _HERE, markers={"pick_up_resource": {"resource": _MOVABLE},
                                                "drop_resource": {"to": Site()}}),
    "heater_shaker": part_class("PrepHeaterShaker", PrepHamiltonHeaterShaker,
                                "The Prep's heater shaker (PyLabRobot: PrepHamiltonHeaterShaker).", _HERE),
    "lights": part_class("PrepLights", Lights, "The Prep's lights (PyLabRobot: Lights).", _HERE),
}
PrepPipettes, PrepHead8, PrepCoreGrippers, PrepHeaterShaker, PrepLights = PART_CLASSES.values()

SKIPPED: Dict[str, Dict[str, str]] = {cls.__name__: cls._SKIPPED for cls in PART_CLASSES.values()}
# The robot's own (signal_error, error_lighting, ...). Setup and stop are above.
SKIPPED["Prep"] = bridge.add_steps(Prep, PrepDevice, "PrepDevice", exclude=("setup", "stop"))
