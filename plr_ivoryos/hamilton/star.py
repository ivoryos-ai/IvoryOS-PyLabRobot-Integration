"""A Hamilton STAR, STARlet or STARplus in IvoryOS, through PyLabRobot 1.0.

    from plr_ivoryos.hamilton import STAR
    star = STAR(simulated=True)                                   # a STARlet, PyLabRobot's simulator
    star = STAR(simulated=True, deck_type="STARDeck")             # a full-size STAR
    star = STAR(worktable="star.json")                            # the real one on USB (plr-ivoryos[usb])

In PyLabRobot 1.0 a STAR is one object, and each thing fitted to it is an object of its own:
`star.pipettes` (the independent channels), `star.head96` or `star.head384`, `star.iswap`,
`star.core_grippers` and `star.autoload`. IvoryOS shows them the same way: the STAR is an instrument
with its driver's own steps (firmware queries, ...), and each fitted thing is an instrument too,
named after it: in a deck that calls the robot `star`, `star_pipettes`, `star_head96`, ... each
with its PyLabRobot class's own steps, names and arguments
(`star_pipettes.aspirate(containers="plate[A1:H1]", volumes=[50])`).

Which frame it is (STARlet, STAR, STARplus) is the worktable file's `deck_type`, and what is fitted
is its `equipment`, because IvoryOS reads a deck's instruments once, when it starts, and PyLabRobot
only learns what is fitted once it connects. Simulated, what is fitted is what PyLabRobot's
recording of that frame has (8 channels, a 96-head, an iSWAP, CoRe grippers, an autoload; say
`"head384": true` for the 384-head recording). A real STAR is asked once, when the file does not
say, and the answer is written to the file; each time it is set up, what it reports is checked
against the file.

`simulated=True` is PyLabRobot's own STAR simulator (`STARSimulationDriver`): every command is
checked and answered as the firmware would, with PyLabRobot's tip and volume tracking.
"""

from typing import Any, Dict, List, Optional

from pylabrobot.hamilton.star.device import (RECORDING_STAR, RECORDING_STAR_HEAD384, RECORDING_STARLET,
                                             RECORDING_STARLET_HEAD384, RECORDING_STARPLUS, STAR as plr_STAR,
                                             STARlet as plr_STARlet, STARPlus as plr_STARPlus)
from pylabrobot.hamilton.star.driver.features.autoload import Autoload
from pylabrobot.hamilton.star.driver.features.core_grippers import CoreGrippers
from pylabrobot.hamilton.star.driver.features.head96 import Head96
from pylabrobot.hamilton.star.driver.features.head384 import Head384
from pylabrobot.hamilton.star.driver.features.iswap import iSWAP
from pylabrobot.hamilton.star.driver.features.pipettes import Pipettes
from pylabrobot.hamilton.star.driver.master import STARDriver
from pylabrobot.hamilton.star.driver.simulator import STARSimulationDriver

from plr_ivoryos import bridge, worktable
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.robot import WorktableRobot, part_class
from plr_ivoryos.wells import Labware, Site

# deck_type -> (PyLabRobot's frame, its recording, its recording with a 384-head)
FRAMES = {
    "STARLetDeck": (plr_STARlet, RECORDING_STARLET, RECORDING_STARLET_HEAD384),
    "STARDeck": (plr_STAR, RECORDING_STAR, RECORDING_STAR_HEAD384),
    "STARPlusDeck": (plr_STARPlus, RECORDING_STARPLUS, None),
}

# What can be fitted to a STAR, by PyLabRobot's attribute for it.
PARTS = ("pipettes", "head96", "head384", "iswap", "core_grippers", "autoload")


def check_equipment(equipment: Dict[str, Any]) -> Dict[str, Any]:
    """`equipment` as the worktable file keeps it ({"pipettes": true, "head96": true, ...}), or
    ValueError saying what is wrong with it."""
    if not isinstance(equipment, dict):
        raise ValueError('equipment is {"pipettes": true, "head96": true, "iswap": true, ...}')
    unknown = sorted(set(equipment) - set(PARTS))
    if unknown:
        raise ValueError(f"'{unknown[0]}' is not something fitted to a STAR: {', '.join(PARTS)}.")
    out = {part: bool(equipment.get(part, False)) for part in PARTS}
    if out["head96"] and out["head384"]:
        raise ValueError("A STAR has a 96-head or a 384-head, not both.")
    return out


def _fitted(device) -> Dict[str, Any]:
    return {part: getattr(device, part, None) is not None for part in PARTS}


class STAR(WorktableRobot):
    """A Hamilton STAR, STARlet or STARplus (the worktable file's deck_type). Steps take labware
    names and wells; each fitted thing (channels, 96- or 384-head, iSWAP, CoRe grippers, autoload) is
    an instrument of its own (`__ivoryos_instruments__`).

    simulated      PyLabRobot's STAR simulator, with the fitted things its recording of the frame has
    worktable      the worktable file (worktable.py); optional, worktable.json in the deck's data
                   folder. A new one starts ready-made (simulated) or empty, and is written on the
                   first change.
    deck_type      STARLetDeck, STARDeck or STARPlusDeck, for a new worktable file (default STARlet)
    equipment      what is fitted, when the file does not say ({"head384": true} chooses the 384-head
                   recording when simulated)
    device_address / serial_number   which STAR on USB, when there is more than one
    step_delay_s   a pause after each step, simulated only, so a run can be watched
    tracking       PyLabRobot's tip and volume tracking
    layouts_folder where layouts saved by name are kept; optional, worktable.layouts beside the
                   worktable file (see Flex)
    """

    KINDS = ["STARLetDeck", "STARDeck", "STARPlusDeck"]

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, deck_type: Optional[str] = None,
                 equipment: Optional[Dict[str, Any]] = None, device_address: Optional[int] = None,
                 serial_number: Optional[str] = None, step_delay_s: float = 0.0, tracking: bool = True,
                 layouts_folder: Optional[str] = None):
        super().__init__(worktable, deck_type, simulated, step_delay_s, tracking, layouts_folder)
        self._device_address, self._serial_number = device_address, serial_number
        found = None if self._new_file else self._config.get("equipment")
        wanted = check_equipment(found or equipment or {}) if (found or equipment) else None
        if simulated:
            # What the recording has; the file (or `equipment`) only chooses the 384-head one.
            self._head384 = bool(wanted and wanted["head384"])
            self._config["equipment"] = self._ask(self._make_plr(self._fresh_deck()))
        elif wanted:
            self._config["equipment"] = wanted
        else:
            self._config["equipment"] = self._ask(self._make_plr(self._fresh_deck()), real=True)
            self._new_file = True
        self._plr = self._make_plr(self.deck)
        self._parts = {part: PART_CLASSES[part](self, part) for part in PARTS if self.equipment.get(part)}
        if self._new_file and not self._simulated:
            self._save()
        self._after_init()

    @property
    def equipment(self) -> Dict[str, Any]:
        return dict(self._config.get("equipment") or {})

    def _fresh_deck(self):
        return worktable.make_deck(self._config.get("deck_type") or self.KINDS[0])

    def _make_plr(self, deck):
        frame, recording, recording384 = FRAMES[self._config.get("deck_type") or self.KINDS[0]]
        if self._simulated:
            if getattr(self, "_head384", False) and recording384 is None:
                raise ValueError("PyLabRobot has no recording of this frame with a 384-head to simulate.")
            driver = STARSimulationDriver(deck=deck, declared_configuration_json=recording384 if self._head384
                                          else recording)
        else:
            driver = STARDriver(device_address=self._device_address, serial_number=self._serial_number, deck=deck)
        return frame(deck=deck, driver=driver)

    def _ask(self, device, real: bool = False) -> Dict[str, Any]:
        """What this STAR has fitted: set up once (a real one without initializing it), read, put down."""
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
            raise ValueError(f"The worktable file ({self._path}) does not say what is fitted to the STAR, and the "
                             f"STAR could not be asked ({type(e).__name__}: {e}). Turn it on, or write equipment in "
                             'the file: {"pipettes": true, "head96": true, "iswap": true, "core_grippers": true, '
                             '"autoload": false}.') from None

    # --- the session --------------------------------------------------------------------------------

    async def _connect(self) -> None:
        await self._plr.setup()
        fitted, problems = _fitted(self._plr), []
        for part, wanted in self.equipment.items():
            if wanted and not fitted[part]:
                problems.append(f"there is no {part} (the file says there is)")
        if problems:
            await self._plr.stop()
            raise RuntimeError("The STAR does not have what the worktable file says it has: " + "; ".join(problems) +
                               f". Change equipment in {self._path} and restart the deck.")

    async def _disconnect(self) -> None:
        await self._plr.stop()

    def _plr_target(self):
        return self._plr.driver

    def _attach_deck(self, deck) -> None:
        self._plr = self._make_plr(deck)  # PyLabRobot 1.0 makes the deck a child of the device

    def _checked(self, config: dict) -> dict:
        """A layout from a file says what is fitted too: refuse what this robot cannot have, not
        when the deck next starts."""
        config["equipment"] = check_equipment(config.get("equipment") or self.equipment)
        return config

    def setup(self) -> None:
        """Connect and initialize the STAR, and find what is fitted, checking it against the
        worktable file. Any other step does this itself the first time. (PyLabRobot: STAR.setup)"""
        run_async(self._setup())

    def stop(self) -> None:
        """Put the STAR down. The next step sets it up again. (PyLabRobot: STAR.stop)"""
        if self._ready:
            run_async(self._disconnect())
            self._ready = False

    def _deck_extras(self) -> dict:
        return {"equipment": {part: True for part, on in self.equipment.items() if on}}


# --- the parts ----------------------------------------------------------------------------------------

_MOVABLE = Labware("plate", "reservoir", "tip_rack", "tube_rack")
_HERE = __name__

PART_CLASSES = {
    "pipettes": part_class("STARPipettes", Pipettes, "The STAR's independent channels (PyLabRobot: Pipettes).", _HERE),
    "head96": part_class("STARHead96", Head96, "The STAR's 96-head (PyLabRobot: Head96).", _HERE),
    "head384": part_class("STARHead384", Head384, "The STAR's 384-head (PyLabRobot: Head384).", _HERE),
    "iswap": part_class("STARiSWAP", iSWAP, "The STAR's iSWAP plate handler (PyLabRobot: iSWAP).", _HERE),
    "core_grippers": part_class("STARCoreGrippers", CoreGrippers,
                                "The CoRe grippers the channels carry (PyLabRobot: CoreGrippers).", _HERE,
                                markers={"pick_up_resource": {"resource": _MOVABLE},
                                         "drop_resource": {"to": Site()}}),
    "autoload": part_class("STARAutoload", Autoload, "The STAR's autoload (PyLabRobot: Autoload).", _HERE),
}
STARPipettes, STARHead96, STARHead384, STARiSWAP, STARCoreGrippers, STARAutoload = PART_CLASSES.values()

# What is left out of each, and why.
SKIPPED: Dict[str, Dict[str, str]] = {cls.__name__: cls._SKIPPED for cls in PART_CLASSES.values()}
# The robot's own: its driver's (firmware queries, ...). Setup and stop are above.
SKIPPED["STAR"] = bridge.add_steps(STAR, STARDriver, "STARDriver", exclude=(
    "setup", "stop", "discover", "initialize",
    # the driver's own helpers, not operations
    "format_setup_summary", "get_id_from_fw_response", "get_or_assign_tip_type_index", "features_below_safe_z"))
