"""An Opentrons Flex in IvoryOS, through PyLabRobot 1.0.

    from plr_ivoryos.opentrons import Flex
    flex = Flex(simulated=True)                              # worktable.json in the deck's data folder
    flex = Flex(host="10.0.0.5", worktable="flex.json")      # a real Flex over Ethernet
    flex = Flex(serial_port="/dev/cu.usbmodem1201")          # over its USB-B port (plr-ivoryos[serial])

In PyLabRobot 1.0 a Flex is one object, and each thing mounted on it is an object of its own:
`flex.left` and `flex.right` (a pipette on each mount), `flex.head96` (the 96-channel head, which
takes both), `flex.gripper`. IvoryOS shows them the same way. The Flex is an instrument with the
robot's own steps (home, lights, stop, ...), and each mounted thing is an instrument too, named
after it: in a deck that calls the Flex `flex`, `flex_left`, `flex_right`, `flex_head96` and
`flex_gripper`, each with its PyLabRobot class's own steps, names and arguments
(`flex_left.aspirate(target="reservoir[A1]", volume=50)` is `flex.left.aspirate(reservoir["A1"][0],
50)`). A 1-, 8- and 96-channel pipette each has the steps PyLabRobot gives it.

What is mounted is part of the worktable file (worktable.py, `equipment`), because IvoryOS reads a
deck's instruments once, when it starts, and PyLabRobot only learns what is mounted once it
connects. When the file says nothing, a simulated Flex starts with an 8-channel and a 1-channel
1000 µL pipette and a gripper, and a real one is asked what it has (and the answer written to the
file). Each time the robot is set up, what it reports is checked against the file.

`simulated=True` runs PyLabRobot's own Flex code against a simulated robot-server (simulator.py),
so tips, volumes and PyLabRobot's own checks are real; only the robot is not.
"""

import asyncio
from typing import Annotated, Any, Dict, List, Optional

from pylabrobot.opentrons import Flex as PLRFlex
from pylabrobot.opentrons.flex.flex_gripper import FlexGripper
from pylabrobot.opentrons.flex.flex_head import FlexHead1, FlexHead8, FlexHead96
from pylabrobot.resources import TipRack

from plr_ivoryos import bridge, worktable
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.opentrons.simulator import FLEX_PIPETTES, SimulatedFlexServer
from plr_ivoryos.robot import WorktableRobot
from plr_ivoryos.wells import Labware, Site

MOUNTS = ("left", "right")
HEAD_CLASSES = {1: FlexHead1, 8: FlexHead8, 96: FlexHead96}
MOVABLE_TRASH = ("A1", "B1", "C1", "D1", "A3", "B3", "C3", "D3")


def check_equipment(equipment: Dict[str, Any]) -> Dict[str, Any]:
    """`equipment` as the worktable file keeps it, or ValueError saying what is wrong with it:
    {"left": pipette, "right": pipette} or {"head96": pipette}, "gripper": bool, "trash": slot."""
    if not isinstance(equipment, dict):
        raise ValueError("equipment is {\"left\": ..., \"right\": ..., \"gripper\": true, \"trash\": \"A3\"}")
    out: Dict[str, Any] = {}
    unknown = sorted(set(equipment) - {"left", "right", "head96", "gripper", "trash"})
    if unknown:
        raise ValueError(f"'{unknown[0]}' is not something fitted to a Flex: left, right, head96, gripper, trash.")
    for part in ("left", "right", "head96"):
        name = equipment.get(part)
        if name in (None, "", "none"):
            continue
        if name not in FLEX_PIPETTES:
            raise ValueError(f"'{name}' is not a Flex pipette: {', '.join(FLEX_PIPETTES)}.")
        channels = FLEX_PIPETTES[name]["channels"]
        if (part == "head96") != (channels == 96):
            raise ValueError(f"{name} goes on {'the 96-channel position (head96)' if channels == 96 else 'left or right'}, "
                             f"not {part}.")
        out[part] = name
    if "head96" in out and ("left" in out or "right" in out):
        raise ValueError("A 96-channel head takes both mounts: it cannot go with another pipette.")
    if not any(part in out for part in ("left", "right", "head96")):
        raise ValueError("A Flex needs a pipette: say what is on the left or right mount, or head96.")
    out["gripper"] = bool(equipment.get("gripper", False))
    trash = equipment.get("trash")
    if trash not in (None, "", "none"):
        trash = str(trash).strip().upper()
        if trash not in MOVABLE_TRASH:
            raise ValueError(f"A trash bin goes in {', '.join(MOVABLE_TRASH)}, not {trash}.")
        out["trash"] = trash
    return out


class Flex(WorktableRobot):
    """An Opentrons Flex. Steps take labware names and wells; each mounted pipette, the 96-channel
    head and the gripper are instruments of their own (`__ivoryos_instruments__`).

    host / port    the robot on the network (port 31950)
    serial_port    or its USB-B port instead (needs plr-ivoryos[serial])
    simulated      run against a simulated robot (simulator.py)
    worktable      the worktable file (worktable.py). Optional: it defaults to worktable.json in the
                   deck's data folder. A file that does not exist yet starts the worktable (a
                   ready-made one, simulated; an empty one on a real robot) and is written on the
                   first change. A relative path is in the data folder too.
    equipment      what is mounted, when the worktable file does not say: {"left": "p1000_multi_flex",
                   "right": "p50_single_flex", "gripper": true, "trash": "A3"} (FLEX_PIPETTES).
                   The file says it from then on.
    step_delay_s   a pause after each step, simulated only, so a run can be watched
    command_timeout  seconds PyLabRobot waits for one robot command
    tracking       PyLabRobot's tip and volume tracking. On, an aspirate from a well nobody filled is
                   refused; fill wells with `liquids` in the worktable file or a load_liquid step.
    """

    KINDS = ["FlexDeck"]

    def __init__(self, host: Optional[str] = None, port: int = 31950, serial_port: Optional[str] = None,
                 simulated: bool = False, worktable: Optional[str] = None,
                 equipment: Optional[Dict[str, Any]] = None, step_delay_s: float = 0.0,
                 command_timeout: float = 30.0, tracking: bool = True):
        if not simulated and not host and not serial_port:
            raise ValueError("Give the Flex's host (or serial_port), or simulated=True.")
        super().__init__(worktable, "FlexDeck", simulated, step_delay_s, tracking)
        self._host, self._port, self._serial_port = host, int(port), serial_port
        self._command_timeout = float(command_timeout)
        # What is mounted: the file's, once there is one; else what was given; else (simulated)
        # the ready-made worktable's; else the robot is asked.
        found = None if self._new_file else self._config.get("equipment")
        if found:
            self._config["equipment"] = check_equipment(found)
        elif equipment:
            self._config["equipment"] = check_equipment(equipment)
        elif simulated:
            self._config["equipment"] = check_equipment(self._config.get("equipment") or worktable_starter_equipment())
        else:
            self._config["equipment"] = self._detect_equipment()
            self._new_file = True
        self.deck = self._build()
        self._plr = self._make_plr()
        self._parts = self._make_parts()
        if self._new_file and not self._simulated:
            self._save()  # a real robot's equipment, as given or as it reported it
        self._after_init()

    # --- what is mounted ----------------------------------------------------------------------------

    @property
    def equipment(self) -> Dict[str, Any]:
        return dict(self._config.get("equipment") or {})

    def _build(self):
        """The deck from the file, with the trash bin where the equipment says it is."""
        return worktable.build_deck(self._config)

    def _make_plr(self) -> PLRFlex:
        if self._simulated:
            equipment = self.equipment
            mounts = {part: equipment[part] for part in MOUNTS if part in equipment}
            if "head96" in equipment:
                mounts = {"left": equipment["head96"]}
            server = SimulatedFlexServer(mounts, gripper=equipment.get("gripper", False),
                                         trash=equipment.get("trash"))
            return PLRFlex(host="simulated-flex", deck=self.deck, io=server, command_timeout=self._command_timeout,
                           command_poll_interval=0)
        if self._serial_port:
            return PLRFlex(serial_port=self._serial_port, deck=self.deck, command_timeout=self._command_timeout)
        return PLRFlex(host=self._host, port=self._port, deck=self.deck, command_timeout=self._command_timeout)

    def _make_parts(self) -> Dict[str, Any]:
        equipment = self.equipment
        parts: Dict[str, Any] = {}
        for part in ("left", "right", "head96"):
            if part in equipment:
                channels = FLEX_PIPETTES[equipment[part]]["channels"]
                parts[part] = PIPETTE_CLASSES[channels](self, part, equipment[part])
        if equipment.get("gripper"):
            parts["gripper"] = FlexGripperPart(self)
        return parts

    def _detect_equipment(self) -> Dict[str, Any]:
        """What a real Flex has mounted, asked once (it is then written to the worktable file)."""
        if self._serial_port:
            plr = PLRFlex(serial_port=self._serial_port, command_timeout=self._command_timeout)
        else:
            plr = PLRFlex(host=self._host, port=self._port, command_timeout=self._command_timeout)

        async def ask():
            await plr.connect()
            try:
                found = await plr.get_instruments()
                try:
                    trash = plr.deck.get_slot(plr.deck.get_trash_area())
                except ValueError:
                    trash = None
            finally:
                await plr.disconnect()
            return found, trash

        try:
            instruments, trash = run_async(ask())
        except Exception as e:
            where = self._serial_port or f"{self._host}:{self._port}"
            raise ValueError(f"The worktable file ({self._path}) does not say what is mounted on the Flex, and the "
                             f"Flex at {where} could not be asked ({type(e).__name__}: {e}). Turn it on, or write "
                             "equipment in the file: {\"left\": \"p1000_single_flex\", \"gripper\": true, "
                             "\"trash\": \"A3\"}.") from None
        equipment: Dict[str, Any] = {"gripper": False}
        for instrument in instruments:
            if instrument.instrument_type == "gripper":
                equipment["gripper"] = True
            elif instrument.instrument_type == "pipette":
                equipment["head96" if instrument.channels == 96 else instrument.mount] = instrument.name
        if trash:
            equipment["trash"] = trash
        return check_equipment(equipment)

    def __ivoryos_instruments__(self) -> Dict[str, Any]:
        """The instruments this Flex is in IvoryOS besides itself: each mounted pipette (`left`,
        `right`, or `head96`) and the gripper, as its equipment says. IvoryOS names them after the
        Flex: flex_left, flex_right, flex_head96, flex_gripper."""
        return dict(self._parts)

    # --- the session --------------------------------------------------------------------------------

    async def _connect(self, skip_home: bool = False) -> None:
        await self._plr.setup(skip_home=skip_home)
        problems = self._mismatches()
        if problems:
            await self._plr.disconnect()
            raise RuntimeError("The Flex does not have what the worktable file says it has: " + "; ".join(problems) +
                               f". Change equipment in {self._path} (or in the Labware panel) and restart the deck.")

    def _mismatches(self) -> List[str]:
        equipment, plr, problems = self.equipment, self._plr, []
        for part in ("left", "right", "head96"):
            head = getattr(plr, part)
            want = equipment.get(part)
            if want:
                channels = FLEX_PIPETTES[want]["channels"]
                if head is None:
                    problems.append(f"nothing is on {part} (the file says {want})")
                elif not isinstance(head, HEAD_CLASSES[channels]):
                    problems.append(f"{part} has a {type(head).__name__.replace('FlexHead', '')}-channel pipette "
                                    f"(the file says {want})")
            elif head is not None and part != "head96":
                print(f"plr-ivoryos: the Flex has a pipette on {part} that the worktable file does not list; "
                      "it is not offered as an instrument.")
        if equipment.get("gripper") and plr.gripper is None:
            problems.append("there is no gripper (the file says there is)")
        return problems

    async def _disconnect(self) -> None:
        await self._plr.cancel_run()
        await self._plr.disconnect()

    def _plr_target(self):
        return self._plr

    def _attach_deck(self, deck) -> None:
        self._plr.attach_deck(deck)

    def _head(self, part: str):
        head = getattr(self._plr, part, None)
        if head is None:
            raise RuntimeError(f"The Flex has nothing on {part}.")
        return head

    def _tip_count(self, part: Optional[str]) -> int:
        if part not in ("left", "right", "head96"):
            return 0
        head = getattr(self._plr, part, None)
        if head is None:
            return 0
        return sum(1 for tip in head.get_mounted_tips() if tip is not None)

    def _any_tips(self) -> bool:
        return any(self._tip_count(part) for part in ("left", "right", "head96"))

    def _channels_state(self) -> List[bool]:
        for part in ("left", "head96", "right"):
            head = getattr(self._plr, part, None)
            if head is not None:
                return [tip is not None for tip in head.get_mounted_tips()]
        return []

    # --- robot-level steps of plr-ivoryos's own ---------------------------------------------------

    def setup(self, skip_home: bool = False) -> None:
        """Connect, start a session, home (unless skip_home) and find what is mounted, checking it
        against the worktable file. Any other step does this itself the first time. (PyLabRobot:
        Flex.setup)"""
        async def go():
            if self._ready:
                return
            await self._connect(skip_home=skip_home)
            self._ready = True
        run_async(go())

    def stop(self) -> None:
        """Discard any mounted tips, park the gantry and hand the robot back to its touchscreen.
        The next step sets it up again. (PyLabRobot: Flex.stop)"""
        if not self._ready:
            return
        self._execute(None, self._plr_target, "stop", {}, {}, {})
        self._ready = False

    # --- the Labware view -----------------------------------------------------------------------------

    def _deck_extras(self) -> dict:
        equipment = self.equipment
        return {"equipment": {**equipment, "labels": {part: FLEX_PIPETTES[name]["label"]
                                                      for part, name in equipment.items() if name in FLEX_PIPETTES}}}

    def _catalog_extras(self) -> dict:
        return {"equipment": {"pipettes": [{"name": name, "label": spec["label"], "channels": spec["channels"]}
                                           for name, spec in FLEX_PIPETTES.items()],
                              "trash": list(MOVABLE_TRASH), "current": self.equipment}}

    def _edit_equipment(self, change: dict) -> str:
        """What is mounted: left, right, head96 (a pipette name, or none), gripper (true or false),
        trash (a slot). Takes effect when the deck restarts, since each mounted thing is an
        instrument of its own."""
        merged = self.equipment
        for key in ("left", "right", "head96", "gripper", "trash"):
            if key in change:
                merged[key] = change[key]
        if any(change.get(k) not in (None, "", "none") for k in ("left", "right")):
            merged.pop("head96", None)
        if change.get("head96") not in (None, "", "none"):
            merged.pop("left", None)
            merged.pop("right", None)
        merged = {k: v for k, v in merged.items() if v not in (None, "", "none")}
        merged.setdefault("gripper", False)
        equipment = check_equipment(merged)
        old_trash = self.equipment.get("trash")
        if equipment.get("trash") != old_trash:
            occupant = self.deck.get_resource_at_slot(equipment["trash"]) if equipment.get("trash") else None
            if occupant is not None and occupant.name != worktable.TRASH:
                raise ValueError(f"{equipment['trash']} holds {occupant.name}: move it before putting the trash bin there.")
        self._config["equipment"] = equipment
        self.deck = self._build()
        if self._simulated:
            self._plr = self._make_plr()  # a simulated robot with what is mounted now
        else:
            self._plr.attach_deck(self.deck)
        self._ledger.clear()
        self._load_liquids()
        return "equipment"


def worktable_starter_equipment() -> Dict[str, Any]:
    return dict(worktable.STARTERS["FlexDeck"]["equipment"])


# --- the parts: a pipette on a mount, the 96-channel head, the gripper ------------------------------

class _Part:
    """Something mounted on a Flex, as an IvoryOS instrument. It reports the Flex's labware (not
    its deck, which the Flex itself reports) so its steps get labware choices and well pickers."""

    def __init__(self, robot: Flex, part: str):
        self._robot = robot
        self._part = part

    def __ivoryos_labware__(self) -> dict:
        return self._robot._part_layout()

    def _target(self):
        return self._robot._head(self._part)

    def _run_step(self, name: str, given: Dict[str, Any], extra: Dict[str, Any], params: Dict[str, bridge.Param]):
        return self._robot._execute(self._part, self._target, name, given, extra, params)


class _Pipette(_Part):
    def __init__(self, robot: Flex, part: str, pipette: str):
        super().__init__(robot, part)
        self.pipette = pipette

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._part}: {self.pipette}>"


class FlexPipette1(_Pipette):
    """A 1-channel pipette on a Flex mount (PyLabRobot: FlexHead1)."""


class FlexPipette8(_Pipette):
    """An 8-channel pipette on a Flex mount (PyLabRobot: FlexHead8)."""


class FlexPipette96(_Pipette):
    """The Flex's 96-channel head (PyLabRobot: FlexHead96)."""


class FlexGripperPart(_Part):
    """The Flex's gripper (PyLabRobot: FlexGripper)."""

    def __init__(self, robot: Flex):
        super().__init__(robot, "gripper")

    def _target(self):
        if self._robot._plr.gripper is None:
            raise RuntimeError("The Flex has no gripper.")
        return self._robot._plr.gripper


PIPETTE_CLASSES = {1: FlexPipette1, 8: FlexPipette8, 96: FlexPipette96}

# Labware a step moves (not the trash), and where to: the gripper's slots.
_MOVABLE = Labware("plate", "reservoir", "tip_rack", "tube_rack")

# PyLabRobot's methods, as steps. What is left out (and why) is in SKIPPED.
SKIPPED: Dict[str, Dict[str, str]] = {
    "FlexPipette1": bridge.add_steps(FlexPipette1, FlexHead1, "FlexHead1"),
    "FlexPipette8": bridge.add_steps(FlexPipette8, FlexHead8, "FlexHead8"),
    "FlexPipette96": bridge.add_steps(FlexPipette96, FlexHead96, "FlexHead96"),
    "FlexGripperPart": bridge.add_steps(FlexGripperPart, FlexGripper, "FlexGripper",
                                        markers={"move_labware": {"resource": _MOVABLE, "to_slot": Site()}}),
    # The robot's own: setup and stop are above; connecting, runs and the deck object are the
    # session's business, not a step's.
    "Flex": bridge.add_steps(Flex, PLRFlex, "Flex", exclude=(
        "setup", "stop", "connect", "disconnect", "create_run", "cancel_run", "initialize", "attach_deck",
        "get_runs"), markers={"labware_moved_off_deck": {"resource": _MOVABLE},
                               "reload_labware": {"resource": _MOVABLE}}),
}
