"""A PyLabRobot robot that owns a worktable file, as IvoryOS sees it.

Everything here is the same for any robot with a deck: the worktable as a file (worktable.py),
reporting it to IvoryOS (`__ivoryos_labware__` and friends, which the Labware view draws and the
safety guard checks wells against), changing it from the Labware view, reading `plate[A1:H1]` text
as PyLabRobot objects, and running a step on PyLabRobot's background loop while keeping track of
what moved (liquids.py). A robot subclass (opentrons/flex.py) says how to connect and what is
mounted.

Each part of a robot that works on the worktable (a pipette mount, a gripper) is an IvoryOS
instrument of its own (`__ivoryos_instruments__`); it reports the same labware without the deck, so
it gets labware choices and well pickers while the worktable is drawn once.
"""

import asyncio
import inspect
import os
import re
from typing import Annotated, Any, Callable, Dict, List, Optional, Union

from pylabrobot.resources import (Carrier, Container, ItemizedResource, Plate, ResourceHolder, TipRack, Trash,
                                  set_tip_tracking, set_volume_tracking)

from plr_ivoryos import bridge, liquids, worktable
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.wells import (ALL, Labware, PerWell, WellSelection, Wells, compact_wells, expand_references,
                               expand_wells, parse_references)

Volumes = Union[float, List[float]]


def category_of(resource) -> str:
    if isinstance(resource, Trash):
        return "trash"
    if isinstance(resource, TipRack):
        return "tip_rack"
    if isinstance(resource, Plate):
        model = str(getattr(resource, "model", "") or "").lower()
        return "reservoir" if "trough" in model or "reservoir" in model else "plate"
    if isinstance(resource, Container):
        return "reservoir"
    return str(getattr(resource, "category", None) or "rack")


def _box(resource) -> Dict[str, float]:
    at = resource.get_absolute_location()
    return {"x": round(at.x, 2), "y": round(at.y, 2),
            "w": round(resource.get_absolute_size_x(), 2), "h": round(resource.get_absolute_size_y(), 2)}


# Default worktable files handed out in this process, so two robots do not share one.
_defaults_taken: set = set()


def worktable_path(path: Optional[str]) -> str:
    """Where the worktable file is. A relative path, and the default when none is given, is in the
    deck's data folder when IvoryOS runs it (IVORYOS_DATA_DIR, which the desktop app sets), else in
    the working directory. So a deck made in the desktop app needs no path typed in."""
    base = os.environ.get("IVORYOS_DATA_DIR") or os.environ.get("IVORYOS_EDGE_HOME") or os.getcwd()
    if path:
        return os.path.abspath(path if os.path.isabs(path) else os.path.join(base, path))
    n, name = 1, "worktable.json"
    while os.path.abspath(os.path.join(base, name)) in _defaults_taken:
        n += 1
        name = f"worktable_{n}.json"
    found = os.path.abspath(os.path.join(base, name))
    _defaults_taken.add(found)
    return found


def _a(word: str) -> str:
    return "an" if word[:1].upper() in "AEIOU" else "a"


class WorktableRobot:
    """The worktable side of a robot. Subclasses set KINDS and implement `_connect`."""

    # The worktables this robot can have (worktable.DECKS); the first is its default.
    KINDS: List[str] = []

    def __init__(self, worktable_file: Optional[str] = None, deck_type: Optional[str] = None,
                 simulated: bool = False, step_delay_s: float = 0.0, tracking: bool = True):
        if tracking:
            set_tip_tracking(True)
            set_volume_tracking(True)
        self._simulated = bool(simulated)
        self._path = worktable_path(worktable_file)
        kind = deck_type or self.KINDS[0]
        if deck_type and deck_type not in self.KINDS:
            raise ValueError(f"This robot takes {self._kinds_text()} worktable, not '{deck_type}'.")
        if os.path.exists(self._path):
            self._config = worktable.load(self._path)
            self._config.setdefault("deck_type", kind)
            self._check_kind(self._config["deck_type"])
            self._new_file = False
        else:
            self._config = worktable.starter(kind) if self._simulated else {"deck_type": kind, "resources": [], "liquids": []}
            self._new_file = True
        self._delay = float(step_delay_s) if self._simulated else 0.0
        self._ledger = liquids.Ledger()
        self._listeners: list = []
        self._layout: Optional[dict] = None
        self._part_layout_cache: Optional[dict] = None
        self._pylabrobot_error: Optional[str] = None
        self._ready = False
        self._setting_up: Optional[asyncio.Lock] = None
        self._kept: Optional[str] = None
        self.deck = worktable.build_deck(self._config)

    def _after_init(self) -> None:
        """What a subclass calls once it has its equipment: liquids, and the file and PyLabRobot's copy."""
        self._load_liquids()
        if self._new_file:
            print(f"plr-ivoryos: no worktable at {self._path} yet: starting "
                  f"{'a ready-made' if self._simulated else 'an empty'} {self._label()} one, "
                  "written there on the first change.")
        elif self._config is not None:
            self._export_pylabrobot()

    def _label(self) -> str:
        kind = self._config.get("deck_type") or self.KINDS[0]
        return worktable.DECKS.get(kind, kind)

    def _kinds_text(self) -> str:
        own = " or ".join(worktable.DECKS.get(k, k) for k in self.KINDS)
        return f"{_a(own)} {own}"

    def _check_kind(self, kind: str) -> None:
        if kind not in self.KINDS:
            other = worktable.DECKS.get(kind, kind)
            raise ValueError(f"This robot takes {self._kinds_text()} worktable, not {_a(other)} {other} one.")

    def _export_pylabrobot(self) -> None:
        self._pylabrobot_error = worktable.export_pylabrobot(self._config, self._path)

    def _save(self) -> None:
        worktable.save(self._path, self._config)
        self._new_file = False
        self._export_pylabrobot()

    def _load_liquids(self) -> None:
        for entry in self._config.get("liquids") or []:
            if entry["labware"] not in self._labware_map():
                print(f"plr-ivoryos: liquid '{entry['liquid']}' not loaded: {entry['labware']} is not on the worktable")
                continue
            wells = entry.get("wells", ALL)
            wells = ", ".join(wells) if isinstance(wells, (list, tuple)) else wells
            self._load(f"{entry['labware']}[{wells}]", entry["liquid"], entry["volume_ul"])

    # --- what a subclass provides ---------------------------------------------------------------

    async def _connect(self) -> None:
        raise NotImplementedError

    async def _disconnect(self) -> None:
        """Hand the robot back (a fresh session starts at the next step)."""

    def _tip_count(self, part: Optional[str]) -> int:
        """Tips on that part's head now (0 for a part with no head)."""
        return 0

    def _any_tips(self) -> bool:
        return False

    async def _setup(self) -> None:
        if self._ready:
            return
        if self._setting_up is None:
            self._setting_up = asyncio.Lock()
        async with self._setting_up:
            if not self._ready:
                await self._connect()
                self._ready = True

    # --- the worktable, as IvoryOS reads it -------------------------------------------------------

    def _labware_map(self, with_trash: bool = False) -> Dict[str, Any]:
        """Everything a step can address: racks and plates, troughs on their own, and (for steps
        that drop tips into it) the trash."""
        found: Dict[str, Any] = {}

        def walk(resource):
            for child in resource.children:
                if isinstance(child, Trash):
                    if with_trash:
                        found[child.name] = child
                    continue
                if isinstance(child, (ItemizedResource, Container)):
                    found[child.name] = child
                else:
                    walk(child)

        walk(self.deck)
        return found

    def _site_map(self) -> Dict[str, Any]:
        """Places a labware can sit, by the label a person uses: "C1" on a Flex, a carrier
        position's own name ("plate_carrier-0") on a Hamilton. A slot holding a trash is not one."""
        out = {}

        def walk(resource):
            for child in resource.children:
                if isinstance(child, ResourceHolder):
                    if any(isinstance(c, Trash) for c in child.children):
                        continue
                    on_deck = child.parent is self.deck
                    out[worktable.slot_label(child) if on_deck else child.name] = child
                elif isinstance(child, Carrier) or not isinstance(child, (ItemizedResource, Container, Trash)):
                    walk(child)

        walk(self.deck)
        return out

    def _place_of(self, resource) -> Optional[str]:
        holder = resource.parent
        if isinstance(holder, ResourceHolder):
            return worktable.slot_label(holder) if holder.parent is self.deck else holder.name
        return None

    def __ivoryos_labware__(self) -> dict:
        """The worktable from above, in millimetres from the front left: each labware with its
        position names (`grid`, rows of columns) and each well's outline (`spots`), the places
        labware can sit, fixed things (carriers, trash), and on a Hamilton the tracks."""
        with self._ledger.lock:
            if self._layout is not None:
                return self._layout
            sites = self._site_map()
            site_of = {id(holder): label for label, holder in sites.items()}
            listed = {}
            for entry in self._config.get("resources") or []:
                listed[entry.get("name")] = entry
                for child in entry.get("children") or []:
                    listed[child.get("name")] = child
            labware = {}
            for name, resource in self._labware_map().items():
                labware[name] = self._describe(resource, site_of, listed)
            fixtures = []

            def walk(resource):
                for child in resource.children:
                    if isinstance(child, (Carrier, Trash)):
                        entry = listed.get(child.name) or {}
                        fixtures.append({"name": child.name, **_box(child),
                                         "category": "trash" if isinstance(child, Trash) else "carrier",
                                         "definition": entry.get("type"), "rails": entry.get("rails"),
                                         "editable": child.name in listed})
                    if isinstance(child, (Carrier, ResourceHolder)):
                        walk(child)

            walk(self.deck)
            kind = self._config.get("deck_type") or type(self.deck).__name__
            self._layout = {
                "deck": {"name": self.deck.name, "kind": kind, "label": worktable.DECKS.get(kind, kind),
                         "width": self.deck.get_absolute_size_x(), "depth": self.deck.get_absolute_size_y(),
                         "simulated": self._simulated, "rails": worktable.rails_of(self.deck),
                         "pylabrobot_files": {part: f for part, f in worktable.pylabrobot_paths(self._path).items()
                                              if os.path.exists(f)},
                         "pylabrobot_error": self._pylabrobot_error,
                         **self._deck_extras()},
                "labware": labware,
                "sites": [{"name": holder.name, "label": label, **_box(holder),
                           "holds": holder.children[0].name if holder.children else None,
                           "carrier": holder.parent.name if isinstance(holder.parent, Carrier) else None}
                          for label, holder in sites.items()],
                "fixtures": fixtures,
            }
            return self._layout

    def _deck_extras(self) -> dict:
        """More about the robot for the Labware view (a subclass's equipment)."""
        return {}

    def _describe(self, resource, site_of: Dict[int, str], listed: Dict[str, dict]) -> dict:
        box = _box(resource)
        spots = {}
        items = resource.get_all_items() if isinstance(resource, ItemizedResource) else [resource]
        for item in items:
            spot = _box(item)
            round_ = getattr(getattr(item, "cross_section_type", None), "value", "") == "circle" \
                or not isinstance(item, Container)
            key = resource.get_child_identifier(item) if isinstance(resource, ItemizedResource) else "A1"
            spots[key] = [round(spot["x"] - box["x"], 2), round(spot["y"] - box["y"], 2),
                          spot["w"], spot["h"], bool(round_)]
        first = items[0] if items else None
        holder = resource.parent
        return {
            "label": resource.name, "category": category_of(resource), "model": getattr(resource, "model", None),
            "definition": (listed.get(resource.name) or {}).get("type"),
            "grid": worktable.grid_of(resource), "site": site_of.get(id(holder)),
            "carrier": holder.parent.name if isinstance(getattr(holder, "parent", None), Carrier) else None,
            "editable": resource.name in listed,
            "max_volume_ul": getattr(first, "max_volume", None), **box, "spots": spots,
        }

    def _part_layout(self) -> dict:
        """What a part (a mount, the gripper) reports: the labware, the trash too (a step drops tips
        into it by name), and the places, without the deck, so the worktable is drawn once."""
        with self._ledger.lock:
            if self._part_layout_cache is None:
                layout = self.__ivoryos_labware__()
                labware = dict(layout["labware"])
                for name, trash in self._labware_map(with_trash=True).items():
                    if isinstance(trash, Trash):
                        labware[name] = {**self._describe(trash, {}, {}), "editable": False}
                self._part_layout_cache = {"labware": labware, "sites": layout["sites"]}
            return self._part_layout_cache

    def _invalidate(self) -> None:
        with self._ledger.lock:
            self._layout = None
            self._part_layout_cache = None

    def __ivoryos_labware_state__(self) -> dict:
        """What each well holds (volume, and by liquid) and which tips are left."""
        with self._ledger.lock:
            out: Dict[str, Dict[str, dict]] = {}
            for name, resource in self._labware_map().items():
                spots: Dict[str, dict] = {}
                if isinstance(resource, TipRack):
                    for spot in resource.get_all_items():
                        spots[resource.get_child_identifier(spot)] = {"tip": spot.has_tip()}
                else:
                    items = resource.get_all_items() if isinstance(resource, ItemizedResource) else [resource]
                    for item in items:
                        volume = item.tracker.get_used_volume() if isinstance(item, Container) else 0
                        if volume > 0:
                            key = resource.get_child_identifier(item) if isinstance(resource, ItemizedResource) else "A1"
                            held = self._ledger.contents((name, key), volume)
                            spots[key] = {"volume_ul": round(volume, 3),
                                          "liquids": {k: round(v, 3) for k, v in held.items() if v > 1e-9}}
                out[name] = spots
            return {"labware": out, "channels": self._channels_state()}

    def _channels_state(self) -> List[bool]:
        return []

    def __ivoryos_labware_events__(self, callback) -> None:
        """Call `callback(event)` as things happen on the worktable: {"action": "aspirate" |
        "dispense" | "pick_up_tips" | "drop_tips" | "move" | "load" | "layout", "labware", "wells"}.
        Called from the background loop's thread."""
        self._listeners.append(callback)

    def _notify(self, action: str, labware: Optional[str] = None, wells: Optional[List[str]] = None) -> None:
        event = {"action": action, "labware": labware, "wells": wells or []}
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:  # a view must never fail a step
                print(f"plr-ivoryos: Labware listener failed: {e}")

    # --- reading `plate[A1:H1]` (bridge.py's resolver; private, so never offered as steps) --------------------------------------------

    def _bare_name(self, value) -> Optional[str]:
        refs = parse_references(value)
        return refs[0][0] if len(refs) == 1 and refs[0][1] is None else None

    def _labware(self, name: str):
        found = self._labware_map(with_trash=True)
        if name not in found:
            raise ValueError(f"'{name}' is not on this worktable (it has: {', '.join(found) or 'nothing'})")
        return found[name]

    def _items(self, value, categories=()) -> List[tuple]:
        """(labware, well, the PyLabRobot well, tip spot or container) for every well `value` names,
        in order. Raises ValueError naming what is not on the worktable."""
        found = self._labware_map(with_trash=True)
        pairs = expand_references(value, {name: worktable.grid_of(r) for name, r in found.items()},
                                  {name: category_of(r) for name, r in found.items()}, categories)
        out = []
        for labware, well in pairs:
            resource = found[labware]
            out.append((labware, well, resource.get_item(well) if isinstance(resource, ItemizedResource) else resource))
        return out

    # --- running a step ---------------------------------------------------------------------------

    def _execute(self, part: Optional[str], target: Callable[[], Any], name: str, given: Dict[str, Any],
                 extra: Dict[str, Any], params: Dict[str, bridge.Param]) -> Any:
        """Run PyLabRobot's `name` on `target()` (a head, the gripper, the robot) with `given`
        arguments read from text, on the background loop, after setting the robot up. Reports what
        it changed to the Labware view and returns its result as data."""
        async def go():
            await self._setup()
            obj = target()
            method = getattr(obj, name)
            kwargs = bridge.convert_arguments(given, params, self)
            positional = [kwargs.pop(p.name) for p in params.values()
                          if p.kind is inspect.Parameter.POSITIONAL_ONLY and p.name in kwargs]
            labware = self._labware_map()
            before = liquids.take(labware, self._place_of)
            tips_before = self._tip_count(part)
            channels = tips_before
            try:
                result = method(*positional, **kwargs, **extra)
                if inspect.isawaitable(result):
                    result = await result
            finally:
                await self._after_step(part, before, tips_before, channels)
            if name in ("stop", "cancel_run", "disconnect"):
                self._ready = False
            return bridge.jsonable(result)
        return run_async(go())

    async def _after_step(self, part, before, tips_before, channels) -> None:
        after = liquids.take(self._labware_map(), self._place_of)
        change = liquids.changes(before, after)
        tips_after = self._tip_count(part)
        self._ledger.apply(part, max(channels, tips_after, 1), change, tips_before, tips_after)
        if change.moved:
            self._invalidate()
        for labware, wells in change.by_labware([k for k, _ in change.lost]).items():
            self._notify("aspirate", labware, wells)
        for labware, wells in change.by_labware([k for k, _ in change.gained]).items():
            self._notify("dispense", labware, wells)
        for labware, wells in change.by_labware(change.tips_taken).items():
            self._notify("pick_up_tips", labware, wells)
        for labware, wells in change.by_labware(change.tips_returned).items():
            self._notify("drop_tips", labware, wells)
        if tips_before and not tips_after and not change.tips_returned:
            self._notify("drop_tips")
        for labware in change.moved:
            self._notify("move", labware)
        if self._delay:
            await asyncio.sleep(self._delay)

    def _run_step(self, name: str, given: Dict[str, Any], extra: Dict[str, Any], params: Dict[str, bridge.Param]):
        """A robot-level PyLabRobot step (bridge.add_steps on the robot class)."""
        return self._execute(None, self._plr_target, name, given, extra, params)

    def _plr_target(self):
        raise NotImplementedError

    # --- steps of plr-ivoryos's own (not PyLabRobot's) --------------------------------------------

    def _load(self, resources: WellSelection, liquid: str, vols) -> List[tuple]:
        targets = self._items(resources, bridge.LIQUID)
        volumes = _per_well(vols, len(targets), "vols")
        with self._ledger.lock:
            for (name, well, container), volume in zip(targets, volumes):
                container.tracker.set_volume(container.tracker.get_used_volume() + volume)
                self._ledger.add((name, well), str(liquid), volume)
        return targets

    def load_liquid(self,
                    resources: Annotated[WellSelection, Wells(*bridge.LIQUID)],
                    liquid: str,
                    vols: Annotated[Volumes, PerWell("resources")]) -> None:
        """Record what a person put on the worktable: this liquid, this much (µL), in these wells.
        Nothing moves. (Not a PyLabRobot step: there it is `well.tracker.set_volume`.)"""
        loaded = self._load(resources, liquid, vols)
        by: Dict[str, List[str]] = {}
        for labware, well, _ in loaded:
            by.setdefault(labware, []).append(well)
        for labware, wells in by.items():
            self._notify("load", labware, wells)

    def read_volumes(self, resources: Annotated[WellSelection, Wells(*bridge.LIQUID)]) -> Dict[str, float]:
        """The volume tracked in each well (µL), by `plate[well]`. (PyLabRobot:
        `well.tracker.get_used_volume()`.)"""
        return {f"{labware}[{well}]": round(container.tracker.get_used_volume(), 3)
                for labware, well, container in self._items(resources, bridge.LIQUID)}

    def tips_left(self, tip_rack: Annotated[str, Labware("tip_rack")]) -> int:
        """How many unused tips the rack still has."""
        rack = self._labware(tip_rack)
        if not isinstance(rack, TipRack):
            raise ValueError(f"'{tip_rack}' is not a tip rack")
        return sum(1 for spot in rack.get_all_items() if spot.has_tip())

    def summary(self) -> str:
        """PyLabRobot's text summary of the worktable."""
        return self.deck.summary()

    def _contents_of(self, labware: str, well: str) -> Dict[str, float]:
        """What a well holds, by liquid, for an instrument that shares this worktable."""
        resource = self._labware(labware)
        item = resource.get_item(well) if isinstance(resource, ItemizedResource) else resource
        return self._ledger.contents((labware, well), item.tracker.get_used_volume())

    # --- changing the worktable (IvoryOS's Labware view) ------------------------------------------

    def __ivoryos_labware_catalog__(self) -> dict:
        """What can be put on this worktable (with carriers where it has tracks), and which
        worktables it can be switched to."""
        kind = self._config.get("deck_type")
        return {
            "labware": worktable.catalog(kind),
            "decks": worktable.describe_decks(self.KINDS) if len(self.KINDS) > 1 else [],
            "deck": kind,
            "importable": True,
            **self._catalog_extras(),
        }

    def _catalog_extras(self) -> dict:
        return {}

    def __ivoryos_labware_edit__(self, action: str, **change) -> dict:
        """Change the worktable, the way a person changes the real one; nothing moves.

            place      definition, site (a slot or carrier position) or rails (a carrier), name optional
            move       name, site or rails
            rename     name, to
            remove     name (a carrier takes what is on it with it)
            liquid     labware, wells, liquid, volume_ul: what those wells hold (empty with no liquid)
            deck       deck: another of this robot's worktables; each keeps its own
            import     content: a layout someone already has (this package's file, or PyLabRobot's
                       own deck file), replacing this worktable; a worktable file it replaces is
                       kept beside it as worktable.before-import.json (`kept`)
            equipment  what is fitted to the robot (the subclass says what)

        Saved to the worktable file at once. Returns {"restart": True} when steps only offer the
        change after a restart (labware names, and the instruments a robot is split into, are read
        once at startup). Raises ValueError for what cannot be done."""
        structural = action != "liquid"
        if structural and self._any_tips():
            raise ValueError("Tips are on a head: drop them before changing the worktable.")
        if structural and self._ready:
            if not self._simulated:
                raise ValueError("The robot is connected: stop it (its stop step) or restart the deck, then change "
                                 "its worktable.")
            self._restart_session()  # a robot's session knows labware by where it was
        self._kept = None
        with self._ledger.lock:
            if action == "place":
                name = self._edit_place(str(change.get("definition", "")), change.get("site"), change.get("rails"),
                                        str(change.get("name") or "").strip())
            elif action == "move":
                name = self._edit_move(str(change.get("name", "")), change.get("site"), change.get("rails"))
            elif action == "rename":
                name = self._edit_rename(str(change.get("name", "")), str(change.get("to", "")).strip())
            elif action == "remove":
                name = self._edit_remove(str(change.get("name", "")))
            elif action == "liquid":
                name = self._edit_liquid(str(change.get("labware", "")), change.get("wells"),
                                         str(change.get("liquid") or "").strip(), change.get("volume_ul"))
            elif action == "deck":
                name = self._edit_deck(str(change.get("deck", "")))
            elif action == "import":
                name = self._edit_import(str(change.get("content") or ""), str(change.get("filename") or "the file"))
            elif action == "equipment":
                name = self._edit_equipment({k: v for k, v in change.items()})
            else:
                raise ValueError(f"'{action}' is not something that can be done to a worktable.")
            self._invalidate()
            self._save()
        self._notify("layout" if structural else "load", name)
        return {"name": name, "restart": structural, **({"kept": self._kept} if self._kept else {})}

    def _restart_session(self) -> None:
        """End the session, so the next step starts a fresh one."""
        run_async(self._disconnect())
        self._ready = False

    def _edit_equipment(self, change: dict) -> str:
        raise ValueError("This robot has no equipment to change here.")

    def _check_name(self, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError("A name starts with a letter and has only letters, digits and _.")
        if name == worktable.TRASH or self.deck.has_resource(name):
            raise ValueError(f"Something on this worktable is already called '{name}'.")

    def _free_name(self, definition: str) -> str:
        kind = next((e["category"] for e in worktable.catalog(self._config.get("deck_type")) + worktable.catalog()
                     if e["definition"] == definition), "labware")
        prefix = {"plate": "plate", "tip_rack": "tips", "reservoir": "reservoir", "tube_rack": "tubes",
                  "carrier": "carrier"}.get(kind, "labware")
        n = 1
        while self.deck.has_resource(f"{prefix}_{n}"):
            n += 1
        return f"{prefix}_{n}"

    def _holder(self, site) -> Any:
        sites = self._site_map()
        key = str(site).strip()
        if worktable.is_flex(self.deck):
            key = key.upper()
        if key not in sites:
            raise ValueError(f"'{site}' is not a place on this worktable.")
        holder = sites[key]
        if holder.children:
            raise ValueError(f"{key} already holds {holder.children[0].name}.")
        return holder

    def _rails(self, rails) -> int:
        count = getattr(self.deck, "num_tracks", None)
        if not count:
            raise ValueError("This worktable has slots, not tracks: put labware in a slot.")
        try:
            rails = int(rails)
        except (TypeError, ValueError):
            raise ValueError("rails is a track number") from None
        if not 1 <= rails <= count:
            raise ValueError(f"Tracks run from 1 to {count}.")
        return rails

    def _on_deck(self, resource, rails: int) -> None:
        try:
            self.deck.assign_child_resource(resource, track=rails)
        except ValueError as e:  # PyLabRobot: "Location ... is already occupied by resource 'x'"
            raise ValueError(f"It does not fit at track {rails}: {e}") from None

    def _entry_for(self, holder, entry: dict) -> None:
        """Write `entry` (name, type) into the file where `holder` is: a slot, or a carrier's site."""
        carrier = holder.parent if isinstance(holder.parent, Carrier) else None
        if carrier is None:
            label = worktable.slot_label(holder)
            slot = label if worktable.is_flex(self.deck) else int(label)
            self._config.setdefault("resources", []).append({**entry, "slot": slot})
            return
        parent, _, _ = worktable.find(self._config, carrier.name)
        if parent is None:
            raise ValueError(f"{carrier.name} is not in the worktable file, so nothing can be saved on it.")
        parent.setdefault("children", []).append({**entry, "site": carrier.children.index(holder)})

    def _edit_place(self, definition: str, site, rails, name: str) -> str:
        if not definition:
            raise ValueError("Say which labware to place.")
        name = name or self._free_name(definition)
        self._check_name(name)
        if rails not in (None, ""):
            rails = self._rails(rails)
            resource = worktable.make(definition, name)
            if not isinstance(resource, Carrier):
                raise ValueError(f"{definition} is not a carrier: put it in a carrier position.")
            self._on_deck(resource, rails)
            self._config.setdefault("resources", []).append({"name": name, "type": definition, "rails": rails})
            return name
        holder = self._holder(site)
        resource = worktable.make(definition, name)
        if isinstance(resource, Carrier):
            raise ValueError(f"{definition} is a carrier: it goes on the tracks, not in a position.")
        try:
            holder.assign_child_resource(resource)
        except ValueError as e:  # PyLabRobot: a holder that takes only one kind of labware
            raise ValueError(f"{definition} does not go there: {e}") from None
        try:
            self._entry_for(holder, {"name": name, "type": definition})
        except ValueError:
            resource.unassign()
            raise
        return name

    def _edit_move(self, name: str, site, rails) -> str:
        entry, siblings, _ = worktable.find(self._config, name)
        if entry is None:
            raise ValueError(f"'{name}' is not in the worktable file, so it cannot be moved from here.")
        resource = self.deck.get_resource(name)
        if rails not in (None, ""):
            rails = self._rails(rails)
            if not isinstance(resource, Carrier):
                raise ValueError(f"{name} is not a carrier: move it to a position.")
            before = resource.location
            resource.unassign()
            try:
                self._on_deck(resource, rails)
            except ValueError:
                self.deck.assign_child_resource(resource, location=before)
                raise
            entry.pop("location", None)
            entry["rails"] = rails
            return name
        holder = self._holder(site)
        if isinstance(resource, Carrier):
            raise ValueError(f"{name} is a carrier: move it along the tracks.")
        old_holder = resource.parent
        resource.unassign()
        try:
            holder.assign_child_resource(resource)
        except ValueError as e:
            old_holder.assign_child_resource(resource)
            raise ValueError(f"{name} does not go there: {e}") from None
        siblings.remove(entry)
        moved = {k: v for k, v in entry.items() if k not in ("slot", "site", "rails", "location")}
        try:
            self._entry_for(holder, moved)
        except ValueError:
            resource.unassign()
            old_holder.assign_child_resource(resource)
            siblings.append(entry)
            raise
        return name

    def _edit_rename(self, name: str, to: str) -> str:
        """PyLabRobot 1.0 fixes a resource's name when it is made, so a renamed labware is made
        again under its new name, holding what the old one held."""
        entry, _, _ = worktable.find(self._config, name)
        if entry is None:
            raise ValueError(f"'{name}' is not in the worktable file, so it cannot be renamed from here.")
        if to == name:
            return name
        self._check_name(to)
        old = self.deck.get_resource(name)
        if isinstance(old, Carrier):
            raise ValueError("A carrier keeps its name: what sits on it can be renamed.")
        new = worktable._resource_for({**entry, "name": to})
        olds = old.get_all_items() if isinstance(old, ItemizedResource) else [old]
        news = new.get_all_items() if isinstance(new, ItemizedResource) else [new]
        for a, b in zip(olds, news):
            if isinstance(old, TipRack):
                if not a.has_tip() and b.has_tip():
                    b.tracker.remove_tip()
            elif isinstance(a, Container):
                b.tracker.set_volume(a.tracker.get_used_volume())
        holder = old.parent
        old.unassign()
        holder.assign_child_resource(new)
        entry["name"] = to
        for liquid in self._config.get("liquids") or []:
            if liquid.get("labware") == name:
                liquid["labware"] = to
        self._ledger.rename(name, to)
        return to

    def _edit_remove(self, name: str) -> str:
        entry, _, _ = worktable.find(self._config, name)
        if entry is None:
            raise ValueError(f"'{name}' is not in the worktable file, so it cannot be removed from here.")
        gone = {name, *(child.get("name") for child in entry.get("children") or [])}
        self.deck.get_resource(name).unassign()
        worktable.remove(self._config, name)
        self._config["liquids"] = [e for e in self._config.get("liquids") or [] if e.get("labware") not in gone]
        for labware in gone:
            self._ledger.forget(labware)
        return name

    def _edit_liquid(self, labware: str, wells, liquid: str, volume_ul) -> str:
        """What these wells hold from now on, and at every start: `liquid` at `volume_ul` each,
        replacing what they held. No liquid (or 0) empties them."""
        targets = self._items(f"{labware}[{', '.join(wells) if isinstance(wells, (list, tuple)) else (wells or 'all')}]",
                             bridge.LIQUID)
        volume = 0.0 if not liquid else float(volume_ul or 0)
        if volume < 0:
            raise ValueError("A volume cannot be negative.")
        for _, well, container in targets:
            if volume > (container.max_volume or float("inf")) + 1e-9:
                raise ValueError(f"{labware}[{well}] holds at most {container.max_volume:g} µL.")
        chosen = {well for _, well, _ in targets}
        grid = worktable.grid_of(self._labware(labware))
        kept = []
        for entry in self._config.get("liquids") or []:
            if entry.get("labware") != labware:
                kept.append(entry)
                continue
            listed = entry.get("wells", ALL)
            listed = ", ".join(listed) if isinstance(listed, (list, tuple)) else listed
            remaining = [w for w in expand_wells(listed, grid) if w not in chosen]
            if remaining:
                kept.append({**entry, "wells": compact_wells(remaining, grid)})
        if volume > 0:
            kept.append({"labware": labware, "wells": compact_wells([w for _, w, _ in targets], grid),
                         "liquid": liquid, "volume_ul": volume})
        self._config["liquids"] = kept
        for name, well, container in targets:
            container.tracker.set_volume(volume)
            self._ledger.set((name, well), liquid, volume)
        return labware

    def _rebuild(self, config: dict) -> None:
        """Use `config` as the worktable from now on."""
        self._config = config
        self.deck = worktable.build_deck(config)
        self._attach_deck(self.deck)
        self._ledger.clear()
        self._load_liquids()

    def _attach_deck(self, deck) -> None:
        """Give the robot its new deck (a subclass's PyLabRobot object holds one)."""

    def _edit_deck(self, kind: str) -> str:
        self._check_kind(kind)
        current = self._config.get("deck_type") or self.KINDS[0]
        if kind == current:
            return kind
        others = dict(self._config.get("other_worktables") or {})
        others[current] = {k: v for k, v in self._config.items() if k not in ("format", "other_worktables")}
        config = others.pop(kind, None) or (worktable.starter(kind) if self._simulated
                                            else {"deck_type": kind, "resources": [], "liquids": []})
        if others:
            config["other_worktables"] = others
        self._rebuild(config)
        return kind

    def _edit_import(self, content: str, filename: str) -> str:
        if not content.strip():
            raise ValueError("The file is empty.")
        config = worktable.read_layout(content)
        kind = config.get("deck_type") or self.KINDS[0]
        self._check_kind(kind)
        config.setdefault("equipment", self._config.get("equipment"))
        if self._config.get("other_worktables"):
            config["other_worktables"] = self._config["other_worktables"]
        if os.path.exists(self._path):
            self._kept = os.path.splitext(self._path)[0] + ".before-import.json"
            worktable.save(self._kept, self._config)
        self._rebuild(config)
        return kind


def _per_well(value, count: int, what: str) -> List[float]:
    """One value for every well, or one per well. Text such as "100, 50" is accepted too, since that
    is how a form and the original IvoryOS send a list."""
    if isinstance(value, str):
        text = value.strip().strip("[]")
        value = [v for v in (part.strip() for part in text.split(",")) if v] if "," in text else text
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    if len(values) == 1 and count:
        values = values * count
    if count and len(values) != count:
        raise ValueError(f"{what} has {len(values)} values for {count} wells: give one, or one per well")
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number, or one number per well") from None
