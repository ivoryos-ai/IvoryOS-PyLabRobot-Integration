"""PyLabRobot's own methods as IvoryOS steps: same names, same arguments, wells written as text.

PyLabRobot 1.0 drives each machine through a class of its own whose public methods are the
machine's operations (`flex.left.aspirate(target, volume, ...)`), so an IvoryOS step needs nothing
invented: it is that method. What a form cannot fill in is a live PyLabRobot object, so this module
reads each method's signature and makes one IvoryOS can call:

* An argument that takes wells, tip spots or a container (`Well`, `TipSpot`, `Sequence[Well]`,
  `Union[Plate, Well, Sequence[Well]]`, ...) takes text instead, as PyLabRobot writes it:
  `assay_plate[A1:H1]` (wells.py), marked `Wells(...)` so IvoryOS NextGen offers a plate picker.
  A bare name (`assay_plate`, `tips`) is the labware itself where the method takes one.
* An argument that takes a labware (`Plate`, `TipRack`, `Trash`, `Resource`) takes its name,
  marked `Labware(...)` so IvoryOS offers what is on the worktable.
* `Sequence[int]` and `Sequence[float]` become lists (a form's "0, 1, 2" too), dataclasses
  (`Coordinate`, `Mix`) stay as they are (IvoryOS draws them as nested forms), and plain values
  pass through.
* What a method returns is made into plain data: a dataclass or named tuple becomes a dict, a
  resource its name.

An argument of any other type is left out when it has a default (PyLabRobot's default applies),
and a method with a required one is not offered; `skipped` says which and why. Nothing is renamed:
a parameter keeps PyLabRobot's name, kind and default, so a step reads as the PyLabRobot call it is.

The steps are synchronous: each hands its call to the instrument (`_run_step`), which runs it on
the one background loop PyLabRobot's connections live on (async_bridge.py).
"""

import collections.abc
import dataclasses
import enum
import inspect
import json
import types
import typing
from typing import Annotated, Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from pylabrobot.resources import (Container, ItemizedResource, Plate, Resource, TipRack, TipSpot, Trash, Tube,
                                  TubeRack, Well)

from plr_ivoryos.wells import Labware, Site, WellSelection, Wells

NoneType = type(None)

# What each kind of PyLabRobot object is, as the worktable's categories (robot.py `category_of`).
LIQUID = ("plate", "reservoir", "tube_rack")
_CATEGORIES: List[Tuple[type, Tuple[str, ...]]] = [
    (TipSpot, ("tip_rack",)), (TipRack, ("tip_rack",)),
    (Tube, ("tube_rack",)), (TubeRack, ("tube_rack",)),
    (Well, ("plate", "reservoir")), (Plate, ("plate", "reservoir")),
    (Trash, ("trash",)),
    (Container, LIQUID),
    (ItemizedResource, ("plate", "reservoir", "tip_rack", "tube_rack")),
    (Resource, ()),  # anything on the worktable
]
# What is addressed as a position on a labware (`plate[A1]`) rather than by a labware's name.
_ITEMS = (Well, TipSpot, Tube)


def _categories(cls: type) -> Tuple[str, ...]:
    return next((cats for base, cats in _CATEGORIES if issubclass(cls, base)), ())


def _is_resource_class(t: Any) -> bool:
    return inspect.isclass(t) and issubclass(t, Resource)


def _arms(t: Any) -> List[Any]:
    origin = typing.get_origin(t)
    if origin is Union or (hasattr(types, "UnionType") and origin is getattr(types, "UnionType")):
        return list(typing.get_args(t))
    return [t]


def _sequence_of(t: Any) -> Optional[Any]:
    """X for Sequence[X], List[X], Tuple[X, ...]; None otherwise."""
    origin = typing.get_origin(t)
    if origin in (list, tuple, collections.abc.Sequence, collections.abc.MutableSequence):
        args = [a for a in typing.get_args(t) if a is not Ellipsis]
        return args[0] if len(args) == 1 else None
    return None


@dataclasses.dataclass
class ResourceArm:
    cls: type
    many: bool = False


class Unsupported(Exception):
    """A parameter type this module cannot offer as a form field."""


@dataclasses.dataclass
class Param:
    """One of a method's parameters: PyLabRobot's, and what IvoryOS is shown in its place."""
    name: str
    kind: inspect._ParameterKind
    default: Any
    annotation: Any          # what IvoryOS reads
    convert: Callable        # (value, resolver) -> what PyLabRobot is handed
    # A default this module gives where PyLabRobot has none (a trash argument: the robot's trash),
    # so it is passed when the step is called without one.
    filled: bool = False


def _plain(value, resolver):
    return value


def _number_list(cast):
    def convert(value, resolver):
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = [v for v in (part.strip() for part in value.strip().strip("[]").split(",")) if v]
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        try:
            return [cast(v) for v in values]
        except (TypeError, ValueError):
            raise ValueError(f"expected a list of {cast.__name__} values, e.g. 0, 1, 2") from None
    return convert


def _json_value(value, resolver):
    if isinstance(value, str) and value.strip()[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            raise ValueError(f"'{value}' is not valid JSON") from None
    return value


def _dataclass_value(cls):
    def convert(value, resolver):
        if value is None or isinstance(value, cls):
            return value
        if isinstance(value, str) and value.strip():
            value = _json_value(value, resolver)
        if isinstance(value, dict):
            names = {f.name for f in dataclasses.fields(cls)}
            return cls(**{k: v for k, v in value.items() if k in names and v not in (None, "")})
        if value in ("", {}):
            return None
        raise ValueError(f"expected {cls.__name__} fields, e.g. {{\"x\": 0, \"y\": 0, \"z\": 1}}")
    return convert


def _resource_value(arms: List[ResourceArm], what: str):
    """Text naming labware or wells -> the PyLabRobot object(s) the method takes."""
    def convert(value, resolver):
        if value is None or value == "" or value == []:
            return None
        bare = resolver._bare_name(value)
        if bare is not None:
            resource = resolver._labware(bare)
            for arm in arms:
                if not arm.many and isinstance(resource, arm.cls) and not isinstance(resource, _ITEMS):
                    return resource
        items = [item for _, _, item in resolver._items(value)]
        singles = [arm for arm in arms if not arm.many]
        manys = [arm for arm in arms if arm.many]
        if len(items) == 1:
            for arm in singles:
                if isinstance(items[0], arm.cls):
                    return items[0]
        for arm in manys:
            if items and all(isinstance(item, arm.cls) for item in items):
                return list(items)
        if len(items) > 1 and singles and not manys:
            raise ValueError(f"{what} takes one {singles[0].cls.__name__.lower()}; '{value}' names {len(items)}")
        kinds = " or ".join(("several " if a.many else "") + a.cls.__name__ for a in arms)
        raise ValueError(f"{what} takes {kinds}; '{value}' is not that")
    return convert


def translate_param(param: inspect.Parameter, hint: Any, marker: Any = None) -> Param:
    """What IvoryOS is shown for one PyLabRobot parameter, and how its value is turned back."""
    default = param.default
    optional = default is not inspect.Parameter.empty and default is None
    arms = [a for a in _arms(hint) if a is not NoneType]
    optional = optional or len(arms) < len(_arms(hint))
    resource_arms: List[ResourceArm] = []
    for arm in arms:
        inner = _sequence_of(arm)
        if _is_resource_class(arm):
            resource_arms.append(ResourceArm(arm))
        elif inner is not None and _is_resource_class(inner):
            resource_arms.append(ResourceArm(inner, many=True))
    if resource_arms:
        if len(resource_arms) != len(arms):
            raise Unsupported(f"{param.name} mixes labware with other kinds of value")
        cats: List[str] = []
        for arm in resource_arms:
            for cat in _categories(arm.cls):
                if cat not in cats:
                    cats.append(cat)
        if any(not _categories(a.cls) for a in resource_arms):
            cats = []
        takes_items = any(arm.many or issubclass(arm.cls, _ITEMS) or arm.cls is Container for arm in resource_arms)
        if marker is None:
            marker = Wells(*cats) if takes_items else Labware(*cats)
        base = WellSelection if isinstance(marker, Wells) else str
        if isinstance(marker, Site):
            base = str
        annotation = Annotated[Optional[base] if optional else base, marker]
        filled = False
        if all(issubclass(a.cls, Trash) for a in resource_arms) and default is inspect.Parameter.empty:
            default, filled = "trash", True  # the robot's trash bin, which is what a Flex's is called
        return Param(param.name, param.kind, default, annotation, _resource_value(resource_arms, param.name), filled)
    if len(arms) == 1:
        arm = arms[0]
        inner = _sequence_of(arm)
        if inner in (int, float):
            annotation = Optional[List[inner]] if optional else List[inner]
            return Param(param.name, param.kind, default, annotation, _number_list(inner))
        if dataclasses.is_dataclass(arm) and inspect.isclass(arm):
            return Param(param.name, param.kind, default, Optional[arm] if optional else arm, _dataclass_value(arm))
        origin = typing.get_origin(arm)
        if arm in (dict, list) or origin in (dict, list, collections.abc.Mapping):
            return Param(param.name, param.kind, default, hint, _json_value)
        if marker is not None and arm is str:
            return Param(param.name, param.kind, default, Annotated[hint, marker], _plain)
        if arm in (str, int, float, bool) or (inspect.isclass(arm) and issubclass(arm, enum.Enum)) \
                or origin is typing.Literal or arm is Any:
            return Param(param.name, param.kind, default, hint, _plain)
    raise Unsupported(f"{param.name}: {hint!r}")


def jsonable(value: Any) -> Any:
    """What a PyLabRobot method returned, as data IvoryOS can keep."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Resource):
        return value.name
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return {k: jsonable(v) for k, v in value._asdict().items()}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if hasattr(value, "maximal_volume"):  # a Tip
        return {"tip": type(value).__name__, "maximal_volume": getattr(value, "maximal_volume", None),
                "has_filter": getattr(value, "has_filter", None)}
    return str(value)


def _return_annotation(hint: Any) -> Any:
    """What a step returns, for IvoryOS: plain types as they are, the rest as data."""
    if hint in (inspect.Signature.empty, None, NoneType):
        return None
    arms = [a for a in _arms(hint) if a is not NoneType]
    plain = (bool, int, float, str)
    if all(a in plain for a in arms):
        return hint
    if len(arms) == 1:
        arm = arms[0]
        if dataclasses.is_dataclass(arm) and inspect.isclass(arm):
            if all(f.type in plain or f.type in ("float", "int", "str", "bool") for f in dataclasses.fields(arm)):
                return Optional[arm] if len(arms) < len(_arms(hint)) else arm
            return Dict[str, Any]
        if inspect.isclass(arm) and issubclass(arm, tuple) and hasattr(arm, "_fields"):
            return Dict[str, Any]
        inner = _sequence_of(arm)
        if inner is not None or typing.get_origin(arm) in (tuple, list):
            return List[Any]
        if typing.get_origin(arm) in (dict, collections.abc.Mapping):
            return Dict[str, Any]
    return Any


def _hints(fn: Callable) -> Dict[str, Any]:
    """The method's type hints, read from the function under PyLabRobot's decorators (which keep
    its signature, not the module its annotations are resolved in)."""
    inner = inspect.unwrap(fn)
    try:
        return typing.get_type_hints(inner)
    except Exception:
        return {name: p.annotation for name, p in inspect.signature(inner).parameters.items()}


def _summary(fn: Callable, owner: str) -> str:
    doc = inspect.getdoc(fn) or ""
    first = doc.split("\n\n", 1)[0].strip()
    return f"{first}\n\n(PyLabRobot: {owner}.{fn.__name__})" if first else f"PyLabRobot: {owner}.{fn.__name__}"


@dataclasses.dataclass
class Step:
    name: str
    params: List[Param]
    returns: Any
    doc: str
    accepts_kwargs: bool = False


def describe(fn: Callable, owner: str, markers: Optional[Dict[str, Any]] = None) -> Step:
    """A PyLabRobot method as a step. Raises Unsupported when a required argument cannot be offered."""
    signature = inspect.signature(fn)
    hints = _hints(fn)
    params: List[Param] = []
    accepts_kwargs = False
    for param in signature.parameters.values():
        if param.name == "self":
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_kwargs = True
            continue
        hint = hints.get(param.name, param.annotation)
        if hint is inspect.Parameter.empty:
            hint = Any
        try:
            params.append(translate_param(param, hint, (markers or {}).get(param.name)))
        except Unsupported:
            if param.default is inspect.Parameter.empty:
                raise
    return Step(fn.__name__, params, _return_annotation(hints.get("return", signature.return_annotation)),
                _summary(fn, owner), accepts_kwargs)


def make_method(step: Step) -> Callable:
    """The step as a method IvoryOS reads (its signature and annotations) and calls (`self._run_step`)."""
    by_name = {p.name: p for p in step.params}
    parameters = [inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    seen_default = False
    for p in step.params:
        kind = p.kind
        if kind is inspect.Parameter.POSITIONAL_ONLY:
            kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
        if kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and p.default is inspect.Parameter.empty and seen_default:
            kind = inspect.Parameter.KEYWORD_ONLY  # a required one after a defaulted one PyLabRobot never has; keep it valid
        seen_default = seen_default or p.default is not inspect.Parameter.empty
        parameters.append(inspect.Parameter(p.name, kind, default=p.default, annotation=p.annotation))
    if step.accepts_kwargs:
        parameters.append(inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD))
    signature = inspect.Signature(parameters, return_annotation=step.returns if step.returns is not None else None)

    def method(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        given = {k: v for k, v in bound.arguments.items() if k != "self"}
        extra = given.pop("kwargs", {}) if step.accepts_kwargs else {}
        for p in step.params:
            if p.filled and p.name not in given:
                given[p.name] = p.default
        return self._run_step(step.name, given, extra, by_name)

    method.__name__ = step.name
    method.__qualname__ = step.name
    method.__doc__ = step.doc
    method.__signature__ = signature
    method.__annotations__ = {p.name: p.annotation for p in step.params}
    method.__annotations__["return"] = step.returns if step.returns is not None else None
    return method


def convert_arguments(given: Dict[str, Any], params: Dict[str, Param], resolver) -> Dict[str, Any]:
    """The arguments a step was given, as PyLabRobot takes them. Raises ValueError naming the
    argument that cannot be read."""
    out = {}
    for name, value in given.items():
        param = params.get(name)
        if param is None:
            out[name] = value
            continue
        try:
            out[name] = param.convert(value, resolver)
        except ValueError as e:
            raise ValueError(f"{name}: {e}") from None
    return out


def add_steps(cls: type, source: type, owner: str, *, include: Optional[Iterable[str]] = None,
              exclude: Iterable[str] = (), markers: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, str]:
    """Put `source`'s public methods on `cls` as steps (`describe`, `make_method`). Returns the
    methods left out and why. A method `cls` defines itself is kept."""
    skipped: Dict[str, str] = {}
    names = list(include) if include is not None else sorted(dir(source))
    for name in names:
        if name.startswith("_") or name in exclude:
            continue
        member = inspect.getattr_static(source, name, None)
        if member is None or isinstance(member, property) or not callable(getattr(source, name)):
            continue
        if name in cls.__dict__:
            continue
        try:
            step = describe(getattr(source, name), owner, (markers or {}).get(name))
        except Unsupported as e:
            skipped[name] = str(e)
            continue
        setattr(cls, name, make_method(step))
    return skipped
