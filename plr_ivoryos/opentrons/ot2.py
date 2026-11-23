"""An Opentrons OT-2 in IvoryOS, through PyLabRobot 1.0.

    from plr_ivoryos.opentrons import OT2
    ot2 = OT2(simulated=True)                      # PyLabRobot's OT-2 on a simulated robot-server
    ot2 = OT2(host="10.0.0.6")                     # a real OT-2 over the network

As with the Flex (flex.py), the OT-2 is an instrument with the robot's own steps (home, health, ...)
and each mounted pipette is an instrument too: in a deck that calls the robot `ot2`, `ot2_left` and
`ot2_right`, each with its PyLabRobot class's steps (`OT2SingleChannelPipette`: pick_up_tip,
aspirate, ...; `OT2_8ChannelPipette`: pick_up_tips, aspirate, ...). What is mounted is the worktable
file's `equipment` ({"left": "p300_multi_gen2", "right": "p20_single_gen2"}); a real OT-2 is asked
once when the file does not say. Labware goes in slots 1 to 11; the trash is the OT-2's own, in 12.

`simulated=True` runs PyLabRobot's OT-2 unchanged against a simulated robot-server (simulator.py),
since PyLabRobot 1.0.0b1 has no OT-2 simulator for its 1.0 class (only for the legacy backend).
"""

from typing import Any, Dict, List, Optional

from pylabrobot.opentrons.ot2 import OT2 as PLROT2, OT2_8ChannelPipette, OT2SingleChannelPipette

from plr_ivoryos import bridge
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.opentrons.simulator import OT2_PIPETTES, SimulatedOT2Server
from plr_ivoryos.robot import WorktableRobot, part_class

MOUNTS = ("left", "right")
PIPETTE_CLASSES = {1: OT2SingleChannelPipette, 8: OT2_8ChannelPipette}


def check_equipment(equipment: Dict[str, Any]) -> Dict[str, Any]:
    """`equipment` as the worktable file keeps it ({"left": pipette, "right": pipette}), or
    ValueError saying what is wrong with it."""
    if not isinstance(equipment, dict):
        raise ValueError('equipment is {"left": "p300_multi_gen2", "right": "p20_single_gen2"}')
    unknown = sorted(set(equipment) - set(MOUNTS))
    if unknown:
        raise ValueError(f"'{unknown[0]}' is not an OT-2 mount: left, right.")
    out = {}
    for mount in MOUNTS:
        name = equipment.get(mount)
        if name in (None, "", "none"):
            continue
        if name not in OT2_PIPETTES:
            raise ValueError(f"'{name}' is not an OT-2 pipette PyLabRobot drives: {', '.join(OT2_PIPETTES)}.")
        out[mount] = name
    if not out:
        raise ValueError("An OT-2 needs a pipette: say what is on the left or right mount.")
    return out


class OT2(WorktableRobot):
    """An Opentrons OT-2. Steps take labware names and wells; each mounted pipette is an
    instrument of its own (`__ivoryos_instruments__`).

    host / port    the robot on the network (port 31950)
    simulated      run against a simulated robot-server (simulator.py)
    worktable      the worktable file (worktable.py); optional, worktable.json in the deck's data folder
    equipment      what is mounted, when the file does not say: {"left": "p300_multi_gen2"}
    step_delay_s   a pause after each step, simulated only
    command_timeout  seconds PyLabRobot waits for one robot command
    tracking       PyLabRobot's tip and volume tracking
    layouts_folder where layouts saved by name are kept; optional, worktable.layouts beside the
                   worktable file (see Flex)
    """

    KINDS = ["OTDeck"]

    def __init__(self, host: Optional[str] = None, port: int = 31950, simulated: bool = False,
                 worktable: Optional[str] = None, equipment: Optional[Dict[str, Any]] = None,
                 step_delay_s: float = 0.0, command_timeout: float = 30.0, tracking: bool = True,
                 layouts_folder: Optional[str] = None):
        if not simulated and not host:
            raise ValueError("Give the OT-2's host, or simulated=True.")
        if simulated and host:
            raise ValueError("simulated=True runs no robot, so a host beside it would be ignored. Turn simulated off "
                             "to use that robot, or leave the host out to simulate.")
        super().__init__(worktable, "OTDeck", simulated, step_delay_s, tracking, layouts_folder)
        self._host, self._port, self._command_timeout = host, int(port), float(command_timeout)
        found = None if self._new_file else self._config.get("equipment")
        if found or equipment:
            self._config["equipment"] = check_equipment(found or equipment)
        elif simulated:
            self._config["equipment"] = check_equipment(self._config.get("equipment") or {"left": "p300_multi_gen2",
                                                                                           "right": "p300_single_gen2"})
        else:
            self._config["equipment"] = self._detect_equipment()
            self._new_file = True
        self._plr = self._make_plr()
        self._parts = {mount: PIPETTE_PARTS[OT2_PIPETTES[name]["channels"]](self, mount)
                       for mount, name in self.equipment.items()}
        if self._new_file and not self._simulated:
            self._save()
        self._after_init()

    @property
    def equipment(self) -> Dict[str, Any]:
        return dict(self._config.get("equipment") or {})

    def _make_plr(self) -> PLROT2:
        if self._simulated:
            server = SimulatedOT2Server(self.equipment, labware=lambda name: self.deck.get_resource(name))
            return PLROT2(host="simulated-ot2", deck=self.deck, io=server, command_timeout=self._command_timeout,
                          command_poll_interval=0)
        return PLROT2(host=self._host, port=self._port, deck=self.deck, command_timeout=self._command_timeout)

    def _detect_equipment(self) -> Dict[str, Any]:
        plr = PLROT2(host=self._host, port=self._port, command_timeout=self._command_timeout)

        async def ask():
            await plr.connect()
            try:
                return await plr.get_mounted_pipettes()
            finally:
                await plr.stop()
        try:
            mounted = run_async(ask())
        except Exception as e:
            raise ValueError(f"The worktable file ({self._path}) does not say what is mounted on the OT-2, and the "
                             f"OT-2 at {self._host}:{self._port} could not be asked ({type(e).__name__}: {e}). Turn it "
                             'on, or write equipment in the file: {"left": "p300_multi_gen2"}.') from None
        return check_equipment({pipette.mount: pipette.name for pipette in mounted})

    async def _connect(self, skip_home: bool = False) -> None:
        await self._plr.setup(skip_home=skip_home)
        problems: List[str] = []
        for mount in MOUNTS:
            want, head = self.equipment.get(mount), getattr(self._plr, f"{mount}_pipette")
            if want and head is None:
                problems.append(f"nothing is on {mount} (the file says {want})")
            elif want and not isinstance(head, PIPETTE_CLASSES[OT2_PIPETTES[want]["channels"]]):
                problems.append(f"{mount} has another kind of pipette (the file says {want})")
        if problems:
            await self._plr.stop()
            raise RuntimeError("The OT-2 does not have what the worktable file says it has: " + "; ".join(problems) +
                               f". Change equipment in {self._path} and restart the deck.")

    async def _disconnect(self) -> None:
        await self._plr.stop()

    def _plr_target(self):
        return self._plr

    def _part_target(self, part: str):
        head = getattr(self._plr, f"{part}_pipette", None)
        if head is None:
            raise RuntimeError(f"The OT-2 has no pipette on {part} (it is set up at the first step).")
        return head

    def _attach_deck(self, deck) -> None:
        self._plr = self._make_plr()

    def _checked(self, config: dict) -> dict:
        """A layout from a file says what is fitted too: refuse what this robot cannot have, not
        when the deck next starts."""
        config["equipment"] = check_equipment(config.get("equipment") or self.equipment)
        return config

    def setup(self, skip_home: bool = False) -> None:
        """Connect, start a run, find what is mounted (checking it against the worktable file) and
        home, unless skip_home. Any other step does this itself the first time. (PyLabRobot: OT2.setup)"""
        async def go():
            if not self._ready:
                await self._connect(skip_home=skip_home)
                self._ready = True
        run_async(go())

    def stop(self) -> None:
        """End the run and disconnect. The next step sets the OT-2 up again. (PyLabRobot: OT2.stop)"""
        if self._ready:
            run_async(self._disconnect())
            self._ready = False

    def _deck_extras(self) -> dict:
        equipment = self.equipment
        return {"equipment": {**equipment, "labels": {mount: OT2_PIPETTES[name]["label"]
                                                      for mount, name in equipment.items()}}}


_HERE = __name__
OT2Pipette1 = part_class("OT2Pipette1", OT2SingleChannelPipette,
                         "A single-channel pipette on an OT-2 mount (PyLabRobot: OT2SingleChannelPipette).", _HERE)
OT2Pipette8 = part_class("OT2Pipette8", OT2_8ChannelPipette,
                         "An 8-channel pipette on an OT-2 mount (PyLabRobot: OT2_8ChannelPipette).", _HERE)
PIPETTE_PARTS = {1: OT2Pipette1, 8: OT2Pipette8}

SKIPPED: Dict[str, Dict[str, str]] = {
    "OT2Pipette1": OT2Pipette1._SKIPPED,
    "OT2Pipette8": OT2Pipette8._SKIPPED,
    # The robot's own (home, health, ...). Setup and stop are above; connecting is the session's.
    "OT2": bridge.add_steps(OT2, PLROT2, "OT2", exclude=("setup", "stop", "connect")),
}
