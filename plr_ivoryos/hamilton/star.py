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
only learns what is fitted once it connects. A STAR's channels and heads are built into it, so a
real STAR is asked once, when the file does not say, and the answer is written to the file; each
time it is set up, what it reports is checked against the file. Simulated, the STAR is PyLabRobot's
recording of that frame (8 channels, a 96-head, an iSWAP, CoRe grippers, an autoload), changed to
have what the file says: how many channels (CHANNELS), a 96-head, a 384-head or none, an iSWAP or
not, an autoload or not (`simulated_configuration`), so a dry run matches the STAR it stands in for.

`simulated=True` is PyLabRobot's own STAR simulator (`STARSimulationDriver`): every command is
checked and answered as the firmware would, with PyLabRobot's tip and volume tracking.
"""

import hashlib
import json
import os
import tempfile
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
from plr_ivoryos.robot import WorktableRobot, choice, part_class, toggle
from plr_ivoryos.wells import Labware, Site

# deck_type -> (PyLabRobot's frame, its recording, its recording with a 384-head)
FRAMES = {
    "STARLetDeck": (plr_STARlet, RECORDING_STARLET, RECORDING_STARLET_HEAD384),
    "STARDeck": (plr_STAR, RECORDING_STAR, RECORDING_STAR_HEAD384),
    "STARPlusDeck": (plr_STARPlus, RECORDING_STARPLUS, None),
}

# What can be fitted to a STAR, by PyLabRobot's attribute for it.
PARTS = ("pipettes", "head96", "head384", "iswap", "core_grippers", "autoload")

# How many channels a simulated STAR can have, by frame: what the frames are built with.
# PyLabRobot's simulator cannot model a single channel.
CHANNELS = {"STARLetDeck": (2, 4, 8), "STARDeck": (2, 4, 8, 12, 16), "STARPlusDeck": (2, 4, 8, 12, 16)}


def check_equipment(equipment: Dict[str, Any]) -> Dict[str, Any]:
    """`equipment` as the worktable file keeps it ({"channels": 8, "head96": true, ...}), or
    ValueError saying what is wrong with it. `channels` decides `pipettes` (and the CoRe
    grippers, which two channels carry) when it is given."""
    if not isinstance(equipment, dict):
        raise ValueError('equipment is {"channels": 8, "head96": true, "iswap": true, ...}')
    unknown = sorted(set(equipment) - set(PARTS) - {"channels"})
    if unknown:
        raise ValueError(f"'{unknown[0]}' is not something fitted to a STAR: channels, {', '.join(PARTS)}.")
    out = {part: _yes(equipment.get(part, False)) for part in PARTS}
    if equipment.get("channels") is not None:
        try:
            number = float(equipment["channels"])
        except (TypeError, ValueError):
            raise ValueError(f"channels is a number of channels, not '{equipment['channels']}'.") from None
        if number != int(number) or not 0 <= number <= 16:
            raise ValueError(f"A STAR has 0 to 16 channels, not {equipment['channels']}.")
        channels = int(number)
        out.update(channels=channels, pipettes=channels > 0, core_grippers=channels >= 2)
    if out["head96"] and out["head384"]:
        raise ValueError("A STAR has a 96-head or a 384-head, not both.")
    return out


def _yes(value: Any) -> bool:
    return value.strip().lower() in ("true", "yes", "on", "1") if isinstance(value, str) else bool(value)


def _fitted(device) -> Dict[str, Any]:
    fitted = {part: getattr(device, part, None) is not None for part in PARTS}
    fitted["channels"] = device.pipettes.num_channels if fitted["pipettes"] else 0
    return fitted


def _recording(kind: str, head384: bool = False) -> dict:
    frame, recording, recording384 = FRAMES[kind]
    if head384 and recording384 is None:
        raise ValueError(f"PyLabRobot has no recording of a {worktable.DECKS.get(kind, kind)} with a 384-head "
                         "to simulate.")
    with open(recording384 if head384 else recording) as f:
        return json.load(f)


def recorded_equipment(kind: str, head384: bool = False) -> Dict[str, Any]:
    """What PyLabRobot's recording of a frame has fitted."""
    device = _recording(kind, head384)["device"]
    arm = device.get("left_arm") or {}
    return check_equipment({"channels": device.get("num_pip_channels", 0), "head96": arm.get("head96_installed"),
                            "head384": arm.get("head384_installed"), "iswap": arm.get("iswap_installed"),
                            "autoload": device.get("autoload_installed")})


def simulated_configuration(kind: str, equipment: Dict[str, Any]) -> str:
    """PyLabRobot's recording of the frame, changed to have what `equipment` says is fitted: the
    path of a configuration for PyLabRobot's simulator (`declared_configuration_json`). The 384-head
    one is PyLabRobot's own recording; channels, a head, the iSWAP and the autoload are taken away
    or the channels counted again, the way PyLabRobot derived its other recordings from one."""
    recorded = _recording(kind, bool(equipment.get("head384")))
    device, arm = recorded["device"], recorded["device"]["left_arm"]
    held = recorded["arms"]["left"]
    channels = int(equipment.get("channels", device["num_pip_channels"]))
    if channels < 2:
        raise ValueError("PyLabRobot's STAR simulator needs at least two channels.")
    device["num_pip_channels"] = channels
    recorded_channels = held["pipettes"]["channels"]
    held["pipettes"]["channels"] = [dict(recorded_channels[i % len(recorded_channels)]) for i in range(channels)]
    if not equipment.get("head96") and not equipment.get("head384"):
        for head in ("head96", "head384"):
            held.pop(head, None)
            arm[f"{head}_installed"] = device[f"{head}_installed"] = False
    if not equipment.get("iswap"):
        held.pop("iswap", None)
        arm["iswap_installed"] = device["kb_iswap_installed"] = False
    elif "iswap" not in held:
        raise ValueError(f"PyLabRobot's recording of a {worktable.DECKS.get(kind, kind)} has no iSWAP to simulate.")
    if not equipment.get("autoload"):
        recorded.pop("autoload", None)
        device["autoload_installed"] = False
    elif not recorded.get("autoload"):
        raise ValueError(f"PyLabRobot's recording of a {worktable.DECKS.get(kind, kind)} has no autoload to simulate.")
    text = json.dumps(recorded, sort_keys=True)
    folder = os.path.join(tempfile.gettempdir(), "plr-ivoryos-star")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, hashlib.sha256(text.encode()).hexdigest()[:16] + ".json")
    if not os.path.exists(path):
        with open(path + ".part", "w") as f:
            f.write(text)
        os.replace(path + ".part", path)
    return path


class STAR(WorktableRobot):
    """A Hamilton STAR, STARlet or STARplus (the worktable file's deck_type). Steps take labware
    names and wells; each fitted thing (channels, 96- or 384-head, iSWAP, CoRe grippers, autoload) is
    an instrument of its own (`__ivoryos_instruments__`).

    simulated      PyLabRobot's STAR simulator, with what the file says is fitted (simulated_configuration)
    worktable      the worktable file (worktable.py); optional, worktable.json in the deck's data
                   folder. A new one starts ready-made (simulated) or empty, and is written on the
                   first change.
    deck_type      STARLetDeck, STARDeck or STARPlusDeck, for a new worktable file (default STARlet)
    equipment      what is fitted, when the file does not say: {"channels": 4, "head96": false}; what it
                   leaves out is what the frame's recording has ({"head384": true}: the 384-head one)
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
            # What the file (or `equipment`) says, the rest as the frame's recording has it; then
            # what the simulated STAR made from that reports.
            asked = found or equipment or {}
            self._config["equipment"] = self._simulated_equipment(asked, fit=True)
            self._config["equipment"] = self._ask(self._make_plr(self._fresh_deck()))
            left_out = sorted(part for part, on in check_equipment(asked).items()
                              if part in asked and on and not self._config["equipment"].get(part))
            if left_out or ("channels" in asked and int(asked["channels"]) != self.equipment["channels"]):
                print(f"plr-ivoryos: a simulated {self._label()} cannot have all that its equipment says "
                      f"({', '.join(left_out) or 'those channels'}); it has what PyLabRobot's recording of one has "
                      "instead.")
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

    def _kind(self) -> str:
        return self._config.get("deck_type") or self.KINDS[0]

    def _fresh_deck(self):
        return worktable.make_deck(self._kind())

    def _simulated_equipment(self, given: Dict[str, Any], fit: bool = False) -> Dict[str, Any]:
        """What a simulated STAR of this frame has: what `given` says, the rest as the frame's
        recording has it. `fit`: what this frame cannot have (16 channels on a STARlet, after
        switching frames) becomes what its recording has, instead of refused."""
        kind, given = self._kind(), dict(given or {})
        has384 = FRAMES[kind][2] is not None
        if given.get("head384") and not has384:
            if not fit:
                _recording(kind, True)  # says why
            given.update(head384=False, head96=True)
        recorded = recorded_equipment(kind, bool(given.get("head384")))
        if given.get("head384"):
            given["head96"] = False
        elif given.get("head96"):
            given["head384"] = False
        given.pop("pipettes", None)
        given.pop("core_grippers", None)  # the channels decide these
        wanted = {**recorded, **given}
        if wanted.get("channels") is None:
            wanted["channels"] = recorded["channels"]
        out = check_equipment(wanted)
        problems = []
        if out["channels"] not in CHANNELS[kind]:
            problems.append(("channels", f"a simulated {worktable.DECKS.get(kind, kind)} has "
                                         f"{', '.join(map(str, CHANNELS[kind]))} channels, not {out['channels']}"))
        for part in ("iswap", "autoload"):
            if out[part] and not recorded[part]:
                problems.append((part, f"PyLabRobot's recording of a {worktable.DECKS.get(kind, kind)} has no "
                                       f"{'iSWAP' if part == 'iswap' else 'autoload'} to simulate"))
        if problems and not fit:
            text = "; ".join(why for _, why in problems)
            raise ValueError(text[0].upper() + text[1:] + ".")
        if problems:
            return check_equipment({**out, **{part: recorded[part] for part, _ in problems}})
        return out

    def _make_plr(self, deck):
        frame = FRAMES[self._kind()][0]
        if self._simulated:
            driver = STARSimulationDriver(deck=deck, declared_configuration_json=simulated_configuration(
                self._kind(), self.equipment or recorded_equipment(self._kind())))
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
            if part == "channels":
                if wanted != fitted["channels"]:
                    problems.append(f"it has {fitted['channels']} channels (the file says {wanted})")
            elif wanted and not fitted[part]:
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
        if self._simulated:  # another frame, perhaps: what it cannot have becomes what its recording has
            self._config["equipment"] = self._simulated_equipment(self._config.get("equipment") or {}, fit=True)
        self._plr = self._make_plr(deck)  # PyLabRobot 1.0 makes the deck a child of the device

    def _checked(self, config: dict) -> dict:
        """A layout from a file says what is fitted too: refuse what this robot cannot have, not
        when the deck next starts."""
        config["equipment"] = check_equipment(config.get("equipment") or self.equipment)
        return config

    def _parts_read(self) -> Any:
        # The instruments a STAR is split into are made from what is fitted; how many channels
        # the channels instrument drives is read when it runs.
        return sorted((part, str(on)) for part, on in self.equipment.items() if part != "channels")

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
        return {"equipment": {part: True for part, on in self.equipment.items() if on and part != "channels"}}

    def _equipment_fields(self) -> List[dict]:
        kind, now = self._kind(), self.equipment
        channels = sorted(set(CHANNELS[kind]) | ({now["channels"]} if now.get("channels") else set()))
        heads = [("96", "96-head")] + ([("384", "384-head")] if FRAMES[kind][2] is not None or now.get("head384") else [])
        head = "384" if now.get("head384") else "96" if now.get("head96") else None
        fields = [choice("channels", "Channels", now.get("channels"), [(n, n) for n in channels]),
                  choice("head", "Head", head, heads, none="none"),
                  toggle("iswap", "iSWAP", now.get("iswap"))]
        if not self._simulated or recorded_equipment(kind)["autoload"]:
            fields.append(toggle("autoload", "Autoload", now.get("autoload")))
        return fields

    def _equipment_fixed(self) -> Optional[str]:
        if not self._simulated:
            return "As the STAR reported it: its channels and heads are built into it."
        return None

    def _edit_equipment(self, change: dict) -> str:
        """What a simulated STAR has: channels (a number CHANNELS offers), head (96, 384 or none),
        iswap and autoload (true or false). A real STAR's are built into it, and read from it."""
        if not self._simulated:
            raise ValueError(f"{self._equipment_fixed()} Change it in {self._path} only if the STAR itself changed.")
        now = self.equipment
        given = {part: now.get(part) for part in ("channels", "head96", "head384", "iswap", "autoload")}
        if "channels" in change:
            given["channels"] = change["channels"]
        if "head" in change:
            head = str(change["head"])
            if head not in ("96", "384", "none", ""):
                raise ValueError(f"A STAR's head is a 96-head, a 384-head or none, not '{head}'.")
            given.update(head96=head == "96", head384=head == "384")
        for part in ("iswap", "autoload"):
            if part in change:
                given[part] = _yes(change[part])
        self._config["equipment"] = self._simulated_equipment(given)
        self._plr = self._make_plr(self.deck)
        return "equipment"


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
