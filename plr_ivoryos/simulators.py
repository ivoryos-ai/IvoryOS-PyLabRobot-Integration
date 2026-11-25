"""Simulated devices for the PyLabRobot 1.0 classes PyLabRobot 1.0.0b1 does not simulate.

A simulator stands behind the same steps as the real class (the steps are always made from the
real class's methods, device.py), so a workflow made in simulation is the one run on the device.
Each kind of device keeps the state its main operations change: a scale's tare, a heater-shaker's
target temperature and shaking, a centrifuge's door and spin, a pump's running. A step that waits
(a spin of 60 s, a shake for 30 s) takes that long here too.

A plate reader's readings come from what the liquid handler put in each well (liquids.py): a well
reads its blank plus a signal for every microlitre of the reader's signal liquids, with a little
noise, in the shape the real class returns (a plate-shaped `data` matrix, None where not read).

Anything else the real class can do (a firmware version, a serial number, a status register) is
answered with a stand-in value of the type it returns: 0, 0.0, False, "simulated", an empty list.
Nothing here knows a device's protocol: what passes in simulation has been checked against
PyLabRobot's signatures, not against the device.
"""

import asyncio
import collections.abc
import dataclasses
import datetime
import enum
import inspect
import random
import time
import types
import typing
from typing import Any, List, Optional

NoneType = type(None)


def _return_hint(cls: type, name: str) -> Any:
    member = getattr(cls, name, None)
    if member is None:
        return None
    fn = inspect.unwrap(member)
    try:
        return typing.get_type_hints(fn).get("return")
    except Exception:
        try:
            return inspect.signature(fn).return_annotation
        except (TypeError, ValueError):
            return None


def placeholder(hint: Any) -> Any:
    """A value of type `hint` that says nothing: what a simulator answers where it has no state."""
    if hint in (None, NoneType, inspect.Signature.empty, Any):
        return None
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is typing.Union or origin is getattr(types, "UnionType", None):
        return None if NoneType in args else placeholder(args[0])
    if origin is typing.Literal:
        return args[0] if args else None
    if origin in (list, collections.abc.Sequence, collections.abc.MutableSequence, set, frozenset):
        return []
    if origin is tuple:
        return () if not args or args[-1] is Ellipsis else tuple(placeholder(a) for a in args)
    if origin in (dict, collections.abc.Mapping):
        return {}
    if hint is bool:
        return False
    if hint is int:
        return 0
    if hint is float:
        return 0.0
    if hint is str:
        return "simulated"
    if hint is bytes:
        return b""
    if hint is datetime.datetime:
        return datetime.datetime.now()
    if inspect.isclass(hint) and issubclass(hint, enum.Enum):
        return next(iter(hint), None)
    if dataclasses.is_dataclass(hint) and inspect.isclass(hint):
        try:
            hints = typing.get_type_hints(hint)
        except Exception:
            hints = {}
        values = {f.name: placeholder(hints.get(f.name, f.type)) for f in dataclasses.fields(hint)
                  if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
        try:
            return hint(**values)
        except Exception:
            return None
    return None


class Simulator:
    """Answers every method of `real`, the PyLabRobot class it stands in for: what a subclass
    defines it simulates, anything else returns a stand-in of the type the real method returns."""

    def __init__(self, real: type):
        self._real = real
        self.calls: List[str] = []

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if not callable(getattr(self._real, name, None)):
            raise AttributeError(f"{self._real.__name__} has no method {name}")
        returns = _return_hint(self._real, name)

        async def stand_in(*args, **kwargs):
            self.calls.append(name)
            return placeholder(returns)

        stand_in.__name__ = name
        return stand_in

    async def setup(self, *args, **kwargs) -> None:
        self.calls.append("setup")

    async def stop(self, *args, **kwargs) -> None:
        self.calls.append("stop")


class SimulatedScale(Simulator):
    """A balance with nothing on it: reads 0 g less its tare, until something is weighed for real."""

    def __init__(self, real: type, load_g: float = 0.0):
        super().__init__(real)
        self._load = float(load_g)
        self._tare = 0.0
        self._zero = 0.0

    def _net(self) -> float:
        return round(self._load - self._zero - self._tare, 5)

    async def read_weight(self, *args, **kwargs) -> float:
        return self._net()

    read_stable_weight = read_dynamic_weight = read_weight_value_immediately = read_weight

    async def tare(self, *args, **kwargs) -> None:
        self._tare = self._load - self._zero

    tare_stable = tare_immediately = tare_timeout = tare

    async def zero(self, *args, **kwargs) -> None:
        self._zero, self._tare = self._load, 0.0

    zero_stable = zero_immediately = zero_timeout = zero

    async def clear_tare(self, *args, **kwargs):
        self._tare = 0.0
        return []

    async def request_tare_weight(self) -> float:
        return round(self._tare, 5)


class SimulatedPump(Simulator):
    """A peristaltic pump: running or not, at what speed, and how many revolutions it was asked for."""

    def __init__(self, real: type):
        super().__init__(real)
        self.speed = 0.0
        self.revolutions = 0.0

    async def run_continuously(self, speed: float, *args, **kwargs):
        self.speed = float(speed)

    async def run_revolutions(self, num_revolutions: float, *args, **kwargs):
        self.revolutions += float(num_revolutions)

    async def halt(self, *args, **kwargs):
        self.speed = 0.0

    async def stop(self, *args, **kwargs):
        self.speed = 0.0
        self.calls.append("stop")


class SimulatedCentrifuge(Simulator):
    """A centrifuge's door, bucket lock and spin. A spin takes its duration; it refuses to start
    with the door open, as the real one does."""

    def __init__(self, real: type):
        super().__init__(real)
        self.door_open = False
        self.door_locked = True
        self.bucket_locked = False
        self.position = 0
        self.spinning = False

    async def open_door(self, *args, **kwargs):
        self.door_locked = False
        self.door_open = True

    async def close_door(self, *args, **kwargs):
        self.door_open = False

    async def lock_door(self, *args, **kwargs):
        if self.door_open:
            raise RuntimeError("The door is open: close it before locking it.")
        self.door_locked = True

    async def unlock_door(self, *args, **kwargs):
        self.door_locked = False

    async def lock_bucket(self, *args, **kwargs):
        self.bucket_locked = True

    async def unlock_bucket(self, *args, **kwargs):
        self.bucket_locked = False

    async def go_to_bucket1(self, *args, **kwargs):
        self.position = 0

    async def go_to_bucket2(self, *args, **kwargs):
        self.position = 1

    async def go_to_position(self, position: int, *args, **kwargs):
        self.position = int(position)

    async def spin(self, g: float = 500, duration: float = 60, *args, **kwargs):
        if self.door_open:
            raise RuntimeError("The door is open: close it before spinning.")
        self.spinning = True
        try:
            await asyncio.sleep(float(duration))
        finally:
            self.spinning = False

    async def stop_spin(self, *args, **kwargs):
        self.spinning = False

    async def request_door_open(self) -> bool:
        return self.door_open

    async def request_door_locked(self) -> bool:
        return self.door_locked

    async def request_bucket_locked(self) -> bool:
        return self.bucket_locked

    async def request_bucket_unlocked(self) -> bool:
        return not self.bucket_locked

    async def request_spinning(self) -> bool:
        return self.spinning

    async def request_position(self) -> int:
        return self.position

    def g_to_rpm(self, g: float) -> int:
        return 0


class SimulatedHeaterShaker(Simulator):
    """A heater-shaker (or a plain shaker): reaches its target temperature at once, shakes for the
    duration asked, locks and unlocks its plate."""

    AMBIENT = 25.0

    def __init__(self, real: type):
        super().__init__(real)
        self.target: Optional[float] = None
        self.speed = 0.0
        self.locked = False

    async def set_temperature(self, temperature: float, *args, **kwargs):
        self.target = float(temperature)

    async def request_current_temperature(self, *args, **kwargs) -> float:
        return self.target if self.target is not None else self.AMBIENT

    async def stop_temperature_control(self, *args, **kwargs):
        self.target = None

    async def deactivate(self, *args, **kwargs):
        self.target = None
        self.speed = 0.0

    async def start_shaking(self, speed: float, *args, **kwargs):
        self.speed = float(speed)

    async def set_shaker_speed(self, speed: float, *args, **kwargs):
        self.speed = float(speed)

    async def stop_shaking(self, *args, **kwargs):
        self.speed = 0.0

    async def shake(self, speed: float, duration: float, *args, **kwargs):
        self.speed = float(speed)
        try:
            await asyncio.sleep(float(duration))
        finally:
            self.speed = 0.0

    async def lock_plate(self, *args, **kwargs):
        self.locked = True

    async def unlock_plate(self, *args, **kwargs):
        self.locked = False


def _row_col(identifier: str) -> tuple:
    """"B3" -> (1, 2); "AA1" -> (26, 0)."""
    letters = "".join(c for c in identifier if c.isalpha())
    row = 0
    for c in letters.upper():
        row = row * 26 + (ord(c) - ord("A") + 1)
    return row - 1, int("".join(c for c in identifier if c.isdigit())) - 1


# What a reading is made of, in simulation: an empty well, and each microlitre of a signal liquid.
BLANK = {"absorbance": 0.04, "fluorescence": 50.0, "luminescence": 10.0}
PER_UL = {"absorbance": 0.025, "fluorescence": 1000.0, "luminescence": 500.0}
NOISE = {"absorbance": 0.003, "fluorescence": 5.0, "luminescence": 2.0}


class SimulatedPlateReader(Simulator):
    """A plate reader whose readings follow what is in each well (device.Reader `_contents`)."""

    def __init__(self, real: type, reader):
        super().__init__(real)
        self._reader = reader
        self.door_open = False
        self.target: Optional[float] = None

    def _matrix(self, kind: str, plate, wells) -> List[List[Optional[float]]]:
        rows, cols = plate.num_items_y, plate.num_items_x
        data: List[List[Optional[float]]] = [[None] * cols for _ in range(rows)]
        for well in (wells or plate.get_all_items()):
            if well.parent is not plate:
                raise ValueError(f"{well.name} is not a well of {plate.name}")
            key = plate.get_child_identifier(well)  # "B3"
            row, col = _row_col(key)
            contents = self._reader._contents(plate.name, key)
            signal = sum(v for liquid, v in contents.items() if liquid in self._reader._signal_liquids)
            value = BLANK[kind] + PER_UL[kind] * signal + random.gauss(0.0, NOISE[kind])
            data[row][col] = round(max(value, 0.0), 4)
        return data

    def _result(self, method: str, data, **fields) -> Any:
        """What the real `method` returns: a list of its result dataclass (PyLabRobot 1.0), or the
        legacy backends' list of dicts."""
        hint = _return_hint(self._real, method)
        inner = (typing.get_args(hint) or [None])[0] if typing.get_origin(hint) in (list, collections.abc.Sequence) else None
        if dataclasses.is_dataclass(inner) and inspect.isclass(inner):
            try:
                types = typing.get_type_hints(inner)
            except Exception:
                types = {}
            values = {}
            for f in dataclasses.fields(inner):
                kind = types.get(f.name, f.type)
                if f.name == "data":
                    values[f.name] = data
                elif f.name in fields:
                    values[f.name] = fields[f.name]
                elif f.name == "temperature":
                    values[f.name] = self.target
                elif f.name == "timestamp":
                    values[f.name] = datetime.datetime.now() if kind is datetime.datetime else time.time()
                elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                    values[f.name] = placeholder(kind)
            return [inner(**values)]
        return [{"time": time.time(), "temperature": self.target, "data": data, **fields}]

    async def read_absorbance(self, plate, wells=None, wavelength: int = 0, *args, **kwargs):
        return self._result("read_absorbance", self._matrix("absorbance", plate, wells), wavelength=wavelength)

    async def read_fluorescence(self, plate, wells=None, excitation_wavelength: int = 0, emission_wavelength: int = 0,
                                *args, **kwargs):
        return self._result("read_fluorescence", self._matrix("fluorescence", plate, wells),
                            excitation_wavelength=excitation_wavelength, emission_wavelength=emission_wavelength)

    async def read_luminescence(self, plate, wells=None, *args, **kwargs):
        return self._result("read_luminescence", self._matrix("luminescence", plate, wells))

    async def open(self, *args, **kwargs):
        self.door_open = True

    async def close(self, *args, **kwargs):
        self.door_open = False

    async def set_temperature(self, temperature: float, *args, **kwargs):
        self.target = float(temperature)

    async def request_current_temperature(self, *args, **kwargs) -> float:
        return self.target if self.target is not None else SimulatedHeaterShaker.AMBIENT

    async def stop_heating_or_cooling(self, *args, **kwargs):
        self.target = None
