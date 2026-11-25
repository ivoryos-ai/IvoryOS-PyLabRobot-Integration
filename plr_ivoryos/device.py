"""PyLabRobot devices that are not liquid handlers, as IvoryOS instruments: scales, pumps,
centrifuges, heater-shakers, thermocyclers, fans and plate readers.

Each is one instrument whose steps are PyLabRobot's own methods (bridge.add_steps), run on the one
background loop PyLabRobot's connections live on, after setting the device up the first time. Two
kinds of PyLabRobot class sit underneath:

* A PyLabRobot 1.0 class of the device's own (`pylabrobot.mettler_toledo.MTSICSDriver`,
  `pylabrobot.agilent.biotek.synergy.SynergyH1`, ...): its methods are the steps. PyLabRobot 1.0.0b1
  simulates none of them, so `simulated=True` runs this package's simulator for that kind of device
  (simulators.py) behind the same steps.
* PyLabRobot's legacy front end with a backend (`pylabrobot.legacy.scales.Scale`,
  `pylabrobot.legacy.thermocycling.Thermocycler`, ...), for devices PyLabRobot 1.0 has not yet given
  a class of their own (legacy.py). `simulated=True` is PyLabRobot's own legacy simulator for it.

A plate reader reads a plate where it sits on a liquid handler's worktable (`Reader`): its `plate`
and `wells` arguments are written as for any robot step (`assay_plate`, `assay_plate[A1:H1]`) and
resolved against that robot's labware, so one deck can pipette into a plate and read it. Without a
liquid handler beside it, the reader holds a plate of its own, named `plate`.
"""

import asyncio
import inspect
from typing import Any, Dict, List, Optional

from pylabrobot.resources import Coordinate, Resource

from plr_ivoryos import bridge, worktable
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.robot import WorktableRobot, live_robots, worktable_path


async def _maybe(result):
    return await result if inspect.isawaitable(result) else result


# A device's methods that are not steps: connecting (`setup` and `stop` are the device's own steps,
# below), the raw protocol, and the resource tree's own.
NOT_STEPS = ("setup", "stop", "send_command", "send", "read_resp", "describe_error_code", "reserve_transfer",
             "get_default_child_location", "get_all_instances", "serialize", "deserialize", "load_state", "save_state")


def device_steps(cls: type, source: type, exclude=(), markers: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, str]:
    """Put `source`'s methods on `cls` as steps (bridge.add_steps), leaving out NOT_STEPS and
    `exclude`. Returns what was left out because a required argument cannot be offered, and why."""
    return bridge.add_steps(cls, source, source.__name__, exclude=NOT_STEPS + tuple(exclude), markers=markers)


class Device:
    """A PyLabRobot device as one IvoryOS instrument. A subclass makes `self._plr` (the PyLabRobot
    object, or a simulator with the same methods) and puts its PyLabRobot class's methods on itself
    as steps (bridge.add_steps)."""

    def __init__(self, simulated: bool = False, step_delay_s: float = 0.0):
        self._simulated = bool(simulated)
        self._delay = float(step_delay_s) if self._simulated else 0.0
        self._ready = False
        self._setting_up: Optional[asyncio.Lock] = None
        self._plr: Any = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__}{' (simulated)' if self._simulated else ''}>"

    def _target(self):
        return self._plr

    async def _connect(self) -> None:
        setup = getattr(self._target(), "setup", None)
        if setup is not None:
            await _maybe(setup())

    async def _disconnect(self) -> None:
        stop = getattr(self._target(), "stop", None)
        if stop is not None:
            await _maybe(stop())

    async def _setup(self) -> None:
        if self._ready:
            return
        if self._setting_up is None:
            self._setting_up = asyncio.Lock()
        async with self._setting_up:
            if not self._ready:
                await self._connect()
                self._ready = True

    def setup(self) -> None:
        """Connect and set the device up. Any other step does this itself the first time."""
        run_async(self._setup())

    def stop(self) -> None:
        """Disconnect. The next step sets the device up again."""
        if self._ready:
            run_async(self._disconnect())
            self._ready = False

    def _run_step(self, name: str, given: Dict[str, Any], extra: Dict[str, Any], params: Dict[str, bridge.Param]):
        """Run PyLabRobot's `name` with `given` arguments read from text, on the background loop,
        after setting the device up; returns its result as data."""
        async def go():
            await self._setup()
            method = getattr(self._target(), name)
            kwargs = bridge.convert_arguments(given, params, self)
            positional = [kwargs.pop(p.name) for p in params.values()
                          if p.kind is inspect.Parameter.POSITIONAL_ONLY and p.name in kwargs]
            result = await _maybe(method(*positional, **kwargs, **extra))
            if self._delay:
                await asyncio.sleep(self._delay)
            return bridge.jsonable(result)
        return run_async(go())

    # A step argument naming labware is read by the instrument (bridge.convert_arguments); a device
    # with none never asks. `Reader` reads them against a worktable.
    def _bare_name(self, value) -> Optional[str]:
        raise ValueError("this instrument has no labware")

    def _named(self, name: str):
        raise ValueError("this instrument has no labware")

    def _items(self, value, categories=()) -> List[tuple]:
        raise ValueError("this instrument has no labware")


# The plate a reader holds when no liquid handler shares a worktable with it.
OWN_PLATE = "plate"


class _OwnPlate:
    """A reader's own plate, for a reader with no liquid handler beside it: one labware, named
    `plate`, read with the same `plate[A1:H1]` text as a robot's (WorktableRobot's reading)."""

    def __init__(self, definition: str):
        self.holder = Resource("reader", size_x=128.0, size_y=86.0, size_z=10.0)
        self.holder.location = Coordinate.zero()
        self.plate = worktable.make(definition, OWN_PLATE)
        self.holder.assign_child_resource(self.plate, location=Coordinate.zero())

    def _labware_map(self, with_trash: bool = False) -> Dict[str, Any]:
        return {OWN_PLATE: self.plate}

    def _bare_name(self, value) -> Optional[str]:
        return WorktableRobot._bare_name(self, value)

    def _labware(self, name: str):
        return WorktableRobot._labware(self, name)

    def _named(self, name: str):
        return self._labware(name)

    def _items(self, value, categories=()) -> List[tuple]:
        return WorktableRobot._items(self, value, categories)

    def _contents_of(self, labware: str, well: str) -> Dict[str, float]:
        return {}

    def layout(self) -> dict:
        return {"labware": {OWN_PLATE: {**WorktableRobot._describe(None, self.plate, {}, {}), "editable": False}}}


class Reader(Device):
    """A device that reads plates (a plate reader): its `plate` and `wells` arguments name labware
    on a liquid handler's worktable.

    worktable    the worktable file of the liquid handler whose plates it reads, as that robot was
                 given it; optional: the first liquid handler in the deck. Without one, the reader
                 holds a plate of its own, named `plate`.
    plate_type   that plate's PyLabRobot definition (any plate in PyLabRobot's catalogue)
    signal_liquids  simulated only: the liquids that absorb, fluoresce or glow, comma separated;
                 a well reads its blank plus a signal for every microlitre of them it holds
    """

    def __init__(self, simulated: bool = False, step_delay_s: float = 0.0, worktable: Optional[str] = None,
                 plate_type: str = worktable._PLATE, signal_liquids: str = "dye"):
        super().__init__(simulated, step_delay_s)
        self._worktable_file = worktable
        self._plate_type = plate_type
        self._signal_liquids = [s.strip() for s in str(signal_liquids or "").split(",") if s.strip()]
        self._own: Optional[_OwnPlate] = None

    def _robot(self) -> Optional[WorktableRobot]:
        """The liquid handler whose worktable this reader shares, found when it is needed (the
        robot may come after the reader in a deck file)."""
        robots = live_robots()
        if self._worktable_file:
            path = worktable_path(self._worktable_file)
            return next((robot for robot in robots if robot._path == path), None)
        return robots[0] if robots else None

    def _source(self):
        robot = self._robot()
        if robot is not None:
            return robot
        if self._own is None:
            self._own = _OwnPlate(self._plate_type)
        return self._own

    def _bare_name(self, value) -> Optional[str]:
        return self._source()._bare_name(value)

    def _named(self, name: str):
        return self._source()._named(name)

    def _items(self, value, categories=()) -> List[tuple]:
        return self._source()._items(value, categories)

    def _contents(self, labware: str, well: str) -> Dict[str, float]:
        """What a well holds, by liquid (the robot's liquid tracking), for simulated readings."""
        try:
            return self._source()._contents_of(labware, well)
        except Exception:
            return {}

    def __ivoryos_labware__(self) -> dict:
        """The plates it can read, without the deck, so its steps get plate choices and well pickers
        while the worktable is drawn once, for the robot."""
        source = self._source()
        labware = source._part_layout()["labware"] if isinstance(source, WorktableRobot) else source.layout()["labware"]
        return {"labware": {name: entry for name, entry in labware.items() if entry.get("category") in ("plate", "reservoir")}}
