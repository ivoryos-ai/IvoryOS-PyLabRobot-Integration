"""
plr_ivoryos.liquid_handler
==========================
A PyLabRobot liquid handler as an IvoryOS instrument.

PyLabRobot already has what an IvoryOS deck should not rebuild: worktables for Hamilton,
Opentrons and Tecan robots, hundreds of plate, tip-rack and carrier definitions with their real
geometry, tip and volume tracking, and a simulator. What it does not have is a call a form can
fill in: `lh.aspirate(plate["A1:H1"], vols=[50] * 8)` takes live Python objects. This class is
that layer and nothing more. Its steps take names and well selections:

    lh.transfer(source="reservoir", source_wells="A1", dest="assay_plate", dest_wells="A1:H3",
                vols=100, tip_rack="tips_300")

The worktable is a file (worktable.py), so which robot it is and what sits where is
configuration, never code or a command-line flag:

    from plr_ivoryos import LiquidHandler
    lh = LiquidHandler(simulated=True, deck_json="worktable.json")       # PyLabRobot's simulator
    lh = LiquidHandler(backend=OpentronsOT2Backend(host="10.0.0.5"), deck_json="worktable.json")

`deck=` (a PyLabRobot deck built in code) still works; such a worktable cannot be edited from
IvoryOS, since there is no file to write it to.

In IvoryOS NextGen, the arguments are marked (wells.py): a labware argument lists what is on the
worktable, a wells argument is picked on that plate, and a batch step is given every row of its
group in one call, so one row per sample and one call per column of eight are the same workflow.
The worktable is reported through `__ivoryos_labware__`, which the Labware view draws and the
safety guard checks wells against. The original IvoryOS shows these as text fields.

Steps are synchronous and run on one background event loop (async_bridge.py), as they always have
in this package: a robot connection opened in setup() has to stay on the loop that opened it.
setup() itself waits for the first step, so a deck starts with the robot switched off.

Only the simulator has been exercised by this package's tests.
"""

import asyncio
import os
import threading
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pylabrobot.liquid_handling import LiquidHandler as _PLRLiquidHandler
from pylabrobot.resources import (Carrier, Container, ItemizedResource, Plate, ResourceHolder, TipRack, Trash,
                                  set_tip_tracking, set_volume_tracking)

from plr_ivoryos import worktable
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.wells import ALL, Labware, PerWell, Site, WellSelection, Wells, expand_wells

LIQUID_CONTAINERS = ("plate", "reservoir", "tube_rack")
# A liquid nobody named: the volume is tracked, what it is is not.
UNKNOWN = "liquid"
# Channels of a multichannel head sit 9 mm apart.
CHANNEL_PITCH_MM = 9.0

Volumes = Union[float, List[float]]


def _category(resource) -> str:
    if isinstance(resource, TipRack):
        return "tip_rack"
    if isinstance(resource, Plate):
        model = str(getattr(resource, "model", "") or "").lower()
        return "reservoir" if "trough" in model or "reservoir" in model else "plate"
    if isinstance(resource, Container):
        return "reservoir"
    return str(getattr(resource, "category", None) or "rack")


def _grid(resource) -> List[List[str]]:
    """Position names as rows of columns. PyLabRobot lists items column by column."""
    if not isinstance(resource, ItemizedResource):
        return [["A1"]]
    rows, columns = resource.num_items_y, resource.num_items_x
    names = [resource.get_child_identifier(item) for item in resource.get_all_items()]
    if len(names) != rows * columns:
        return [names]
    return [[names[c * rows + r] for c in range(columns)] for r in range(rows)]


def _box(resource) -> Dict[str, float]:
    at = resource.get_absolute_location()
    return {"x": round(at.x, 2), "y": round(at.y, 2),
            "w": round(resource.get_absolute_size_x(), 2), "h": round(resource.get_absolute_size_y(), 2)}


def _simulator(channels: int):
    from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
    return LiquidHandlerChatterboxBackend(num_channels=int(channels))


class LiquidHandler:
    """A liquid handler driven through PyLabRobot. Steps take labware names and wells.

    backend       any PyLabRobot liquid-handler backend (STARBackend, OpentronsOT2Backend, ...)
    deck_json     the worktable file (worktable.py). With `simulated=True` it may not exist yet:
                  the robot's starter worktable is used and the file is written on the first edit.
    deck          a PyLabRobot deck built in code, instead of deck_json
    simulated     use PyLabRobot's simulator (LiquidHandlerChatterboxBackend) when no backend is given
    channels      the simulator's channels
    tracking      PyLabRobot's tip and volume tracking. On, an aspirate from a well nobody filled is
                  refused; fill wells with `liquids` in the worktable file or a load_liquid step.
    step_delay_s  a pause after each move, on the simulator only, so a run can be watched
    """

    def __init__(self, backend=None, deck=None, deck_json: Optional[str] = None, simulated: bool = False,
                 channels: int = 8, tracking: bool = True, step_delay_s: float = 0.0, **kwargs):
        if tracking:
            set_tip_tracking(True)
            set_volume_tracking(True)
        if backend is None and simulated:
            backend = _simulator(channels)
        if backend is None:
            raise ValueError("Give a PyLabRobot backend, or simulated=True to use PyLabRobot's simulator.")
        if deck is not None and deck_json:
            raise ValueError("Give deck (built in code) or deck_json (a worktable file), not both.")
        self._path = os.path.abspath(deck_json) if deck_json else None
        # The worktable as data, kept so it can be edited and saved. None for a deck built in code.
        self._config: Optional[dict] = None
        if deck is None:
            if self._path and os.path.exists(self._path):
                self._config = worktable.load(self._path)
            elif simulated:
                self._config = worktable.starter(worktable.DEFAULT_DECK)
            elif self._path:
                raise FileNotFoundError(f"Worktable file not found: {self._path}")
            else:
                raise ValueError("Give deck_json (a worktable file), deck, or simulated=True.")
            deck = worktable.build_deck(self._config)
        self._channels_default = int(channels)
        self._kwargs = kwargs
        self._lh = _PLRLiquidHandler(backend=backend, deck=deck, **kwargs)
        self._simulated = type(backend).__name__.lower().endswith("chatterboxbackend")
        self._delay = float(step_delay_s) if self._simulated else 0.0
        self._ready = False
        self._setting_up: Optional[asyncio.Lock] = None
        # What each well holds, by liquid: PyLabRobot tracks a well's volume, not what it is.
        # Changed on the background loop, read by IvoryOS from its own threads, hence the lock.
        self._lock = threading.RLock()
        self._contents: Dict[tuple, Dict[str, float]] = {}
        self._in_tips: Dict[int, Dict[str, float]] = {}
        self._listeners: list = []
        self._layout: Optional[dict] = None
        self._load_liquids()

    def _load_liquids(self) -> None:
        for entry in (self._config or {}).get("liquids") or []:
            if entry["labware"] not in self._labware_map():
                print(f"Liquid '{entry['liquid']}' not loaded: {entry['labware']} is not on the worktable")
                continue
            self._load(entry["labware"], entry.get("wells", ALL), entry["liquid"], entry["volume_ul"])

    async def _setup(self) -> None:
        if self._ready:
            return
        if self._setting_up is None:
            self._setting_up = asyncio.Lock()
        async with self._setting_up:
            if not self._ready:
                if not getattr(self._lh, "setup_finished", False):
                    await self._lh.setup()
                self._ready = True

    def _channel_count(self) -> int:
        try:
            return int(self._lh.backend.num_channels)
        except Exception:  # a real backend may only know once set up
            return self._channels_default

    # --- the worktable, as IvoryOS reads it ---------------------------------------------------------

    def _labware_map(self) -> Dict[str, Any]:
        """Everything a step can address: racks and plates, and troughs on their own."""
        found: Dict[str, Any] = {}

        def walk(resource):
            for child in resource.children:
                if isinstance(child, Trash):
                    continue  # a Container to PyLabRobot, not somewhere to pipette
                if isinstance(child, (ItemizedResource, Container)):
                    found[child.name] = child
                else:
                    walk(child)

        walk(self._lh.deck)
        return found

    def _site_map(self) -> Dict[str, Any]:
        """Places a labware can sit, by the label a person uses: "5" on an OT-2, the carrier
        position's own name ("plate_carrier-0") on a Hamilton."""
        deck, out = self._lh.deck, {}

        def walk(resource):
            for child in resource.children:
                if isinstance(child, ResourceHolder):
                    prefix = f"{deck.name}_slot_"
                    out[child.name[len(prefix):] if child.name.startswith(prefix) else child.name] = child
                elif isinstance(child, Carrier) or not isinstance(child, (ItemizedResource, Container, Trash)):
                    walk(child)

        walk(deck)
        return out

    def __ivoryos_labware__(self) -> dict:
        """The worktable from above, in millimetres from the front left: each labware with its
        position names (`grid`, rows of columns) and each well's outline (`spots`), the places
        labware can sit, and fixed things (carriers, the trash)."""
        with self._lock:
            if self._layout is not None:
                return self._layout
            deck = self._lh.deck
            sites = self._site_map()
            site_of = {id(holder): label for label, holder in sites.items()}
            labware = {}
            for name, resource in self._labware_map().items():
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
                labware[name] = {
                    "label": name, "category": _category(resource), "model": getattr(resource, "model", None),
                    "grid": _grid(resource), "site": site_of.get(id(resource.parent)),
                    "max_volume_ul": getattr(first, "max_volume", None), **box, "spots": spots,
                }
            fixtures = []

            def walk(resource):
                for child in resource.children:
                    if isinstance(child, (Carrier, Trash)):
                        fixtures.append({"name": child.name, **_box(child),
                                         "category": "trash" if isinstance(child, Trash) else "carrier"})
                    if isinstance(child, (Carrier, ResourceHolder)):
                        walk(child)

            walk(deck)
            kind = (self._config or {}).get("deck_type") or type(deck).__name__
            self._layout = {
                "deck": {"name": deck.name, "kind": kind, "label": worktable.DECKS.get(kind, kind),
                         "width": deck.get_absolute_size_x(), "depth": deck.get_absolute_size_y(),
                         "simulated": self._simulated},
                "labware": labware,
                "sites": [{"name": holder.name, "label": label, **_box(holder),
                           "holds": holder.children[0].name if holder.children else None}
                          for label, holder in sites.items()],
                "fixtures": fixtures,
            }
            return self._layout

    def __ivoryos_labware_state__(self) -> dict:
        """What each well holds (volume, and by liquid) and which tips are left."""
        with self._lock:
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
                            liquids = self._contents.get((name, key)) or {UNKNOWN: volume}
                            spots[key] = {"volume_ul": round(volume, 3),
                                          "liquids": {k: round(v, 3) for k, v in liquids.items() if v > 1e-9}}
                out[name] = spots
            head = getattr(self._lh, "head", {}) or {}
            return {"labware": out, "channels": [bool(head[i].has_tip) for i in sorted(head)]}

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
            except Exception as e:  # a view must never fail a transfer
                print(f"Labware listener failed: {e}")

    async def _emit(self, action: str, labware: Optional[str] = None, wells: Optional[List[str]] = None) -> None:
        self._notify(action, labware, wells)
        if self._delay:
            await asyncio.sleep(self._delay)

    # --- changing the worktable (IvoryOS's Labware view) ------------------------------------------

    def __ivoryos_labware_catalog__(self) -> dict:
        """What can be put on this worktable, and which robots it can be switched to. Both empty
        when there is no worktable file to save a change to; robots only on the simulator, since a
        real robot is the robot it is."""
        editable = self._config is not None and self._path is not None
        return {
            "labware": worktable.catalog() if editable else [],
            "decks": worktable.describe_decks() if editable and self._simulated else [],
            "deck": (self._config or {}).get("deck_type"),
        }

    def __ivoryos_labware_edit__(self, action: str, **change) -> None:
        """Place or remove a labware, or (simulator) start over on another robot's worktable.
        This says what a person put on the worktable, exactly as the file does; nothing moves.
        Saved to the worktable file. Raises ValueError for what cannot be done."""
        if self._config is None or self._path is None:
            raise ValueError("This worktable has no file to save to: give the LiquidHandler deck_json to edit it here.")
        if any(getattr(channel, "has_tip", False) for channel in (getattr(self._lh, "head", {}) or {}).values()):
            raise ValueError("Tips are on the head: drop them before changing the worktable.")
        with self._lock:
            if action == "place":
                self._edit_place(str(change.get("site", "")), str(change.get("definition", "")),
                                 str(change.get("name", "")).strip())
            elif action == "remove":
                self._edit_remove(str(change.get("name", "")))
            elif action == "deck":
                self._edit_deck(str(change.get("deck", "")))
            else:
                raise ValueError(f"'{action}' is not something that can be done to a worktable.")
            self._layout = None
            worktable.save(self._path, self._config)
        self._notify("layout", change.get("name"))

    def _edit_place(self, site: str, definition: str, name: str) -> None:
        import re
        sites = self._site_map()
        if site not in sites:
            raise ValueError(f"'{site}' is not a place on this worktable.")
        holder = sites[site]
        if holder.children:
            raise ValueError(f"{site} already holds {holder.children[0].name}.")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError("A labware's name starts with a letter and has only letters, digits and _.")
        if self._lh.deck.has_resource(name):
            raise ValueError(f"Something on this worktable is already called '{name}'.")
        holder.assign_child_resource(worktable.make(definition, name))
        carrier = holder.parent if isinstance(holder.parent, Carrier) else None
        resources = self._config.setdefault("resources", [])
        if carrier is None:
            resources.append({"name": name, "type": definition, "slot": int(site)})
            return
        entry = next((e for e in resources if e.get("name") == carrier.name), None)
        if entry is None:
            raise ValueError(f"{carrier.name} is not in the worktable file, so nothing can be saved on it.")
        entry.setdefault("children", []).append(
            {"name": name, "type": definition, "site": carrier.children.index(holder)})

    def _edit_remove(self, name: str) -> None:
        self._resource(name).unassign()
        worktable.remove(self._config, name)
        self._config["liquids"] = [e for e in self._config.get("liquids") or [] if e.get("labware") != name]
        for key in [k for k in self._contents if k[0] == name]:
            del self._contents[key]

    def _edit_deck(self, kind: str) -> None:
        if not self._simulated:
            raise ValueError("A real robot's worktable is the robot's own; only the simulator can be switched.")
        if kind not in worktable.DECKS:
            raise ValueError(f"'{kind}' is not a robot this can simulate ({', '.join(worktable.DECKS)}).")
        self._config = worktable.starter(kind)
        self._lh = _PLRLiquidHandler(backend=_simulator(self._channel_count()),
                                     deck=worktable.build_deck(self._config), **self._kwargs)
        self._ready = False
        self._setting_up = None
        self._contents.clear()
        self._in_tips.clear()
        self._load_liquids()

    # --- resolving names ------------------------------------------------------------------------------

    def _resource(self, labware: str, kind: str = "labware"):
        found = self._labware_map()
        if labware not in found:
            raise ValueError(f"'{labware}' is not a {kind} on this worktable (it has: {', '.join(found) or 'nothing'})")
        return found[labware]

    def _targets(self, labware: str, wells: WellSelection) -> List[tuple]:
        """(labware, well, container) for each selected well, in visiting order."""
        resource = self._resource(labware)
        if isinstance(resource, TipRack):
            raise ValueError(f"'{labware}' is a tip rack, not something that holds liquid")
        try:
            names = expand_wells(wells, _grid(resource))
        except ValueError as e:
            raise ValueError(f"{e} on {labware}") from None
        if not names:
            raise ValueError(f"No wells were given for {labware}")
        if not isinstance(resource, ItemizedResource):
            return [(labware, "A1", resource) for _ in names]
        return [(labware, name, resource.get_item(name)) for name in names]

    @staticmethod
    def _per_well(value, count: int, what: str) -> List[float]:
        """One value for every well, or one per well. Text such as "100, 50" is accepted too,
        since that is how a form and the original IvoryOS send a list."""
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

    # --- tips -----------------------------------------------------------------------------------------

    def _mounted(self) -> List[int]:
        head = getattr(self._lh, "head", {}) or {}
        return [i for i in sorted(head) if head[i].has_tip]

    def _channels_for(self, count: int) -> List[int]:
        mounted = self._mounted()
        if count > len(mounted):
            raise ValueError(f"{count} wells need {count} tips on the head, and it has {len(mounted)}")
        return mounted[:count]

    async def _pick_up(self, tip_rack: str, count: int, tips: WellSelection = "next") -> List[str]:
        rack = self._resource(tip_rack, "tip rack")
        if not isinstance(rack, TipRack):
            raise ValueError(f"'{tip_rack}' is not a tip rack")
        if isinstance(tips, str) and tips.strip().lower() == "next":
            spots = [s for s in rack.get_all_items() if s.has_tip()][:count]
            if len(spots) < count:
                raise ValueError(f"{tip_rack} has {len(spots)} tips left and {count} are needed")
        else:
            spots = [rack.get_item(n) for n in expand_wells(tips, _grid(rack))]
        names = [rack.get_child_identifier(s) for s in spots]
        await self._lh.pick_up_tips(spots, use_channels=list(range(len(spots))))
        await self._emit("pick_up_tips", tip_rack, names)
        return names

    async def _drop(self, how: str = "discard") -> None:
        if not self._mounted():
            return
        await (self._lh.return_tips() if how == "return" else self._lh.discard_tips())
        with self._lock:
            self._in_tips.clear()
        await self._emit("drop_tips")

    # --- liquid ---------------------------------------------------------------------------------------

    def _load(self, labware: str, wells: WellSelection, liquid: str, volume_ul) -> List[str]:
        targets = self._targets(labware, wells)
        volumes = self._per_well(volume_ul, len(targets), "volume")
        with self._lock:
            for (name, well, container), volume in zip(targets, volumes):
                container.tracker.set_volume(container.tracker.get_used_volume() + volume)
                held = self._contents.setdefault((name, well), {})
                held[str(liquid)] = held.get(str(liquid), 0.0) + volume
        return [well for _, well, _ in targets]

    def _take(self, key: tuple, volume: float) -> Dict[str, float]:
        """What `volume` drawn from a well consists of, removed from the well's record."""
        held = self._contents.get(key) or {}
        total = sum(held.values())
        if total <= 1e-9:
            return {UNKNOWN: volume}
        share = min(1.0, volume / total)
        taken = {liquid: amount * share for liquid, amount in held.items()}
        for liquid, amount in taken.items():
            held[liquid] -= amount
        return taken

    @staticmethod
    def _fits(container) -> int:
        """How many channels reach into one container at once: one for a well, several for a trough."""
        return max(1, int(container.get_absolute_size_y() // CHANNEL_PITCH_MM) - 1)

    async def _liquid(self, action: str, targets: List[tuple], volumes: List[float], channels: List[int],
                      flow_rates: Optional[List[float]] = None, blow_out_air_volume: Optional[float] = None,
                      mix: Optional[tuple] = None) -> None:
        """One aspirate or dispense across `channels`. Channels sharing a container go in as many at
        a time as fit side by side in it; the rest go together."""
        operation = self._lh.aspirate if action == "aspirate" else self._lh.dispense
        groups: Dict[int, List[int]] = {}
        for i, (_, _, container) in enumerate(targets):
            groups.setdefault(id(container), []).append(i)
        batches = [[members[0] for members in groups.values() if len(members) == 1]]
        for members in groups.values():
            if len(members) > 1:
                fit = self._fits(targets[members[0]][2])
                batches += [members[i:i + fit] for i in range(0, len(members), fit)]
        for batch in batches:
            if not batch:
                continue
            extra: Dict[str, Any] = {}
            if flow_rates is not None:
                extra["flow_rates"] = [flow_rates[i] for i in batch]
            if blow_out_air_volume is not None:
                extra["blow_out_air_volume"] = [float(blow_out_air_volume)] * len(batch)
            if mix is not None:
                from pylabrobot.liquid_handling.standard import Mix
                extra["mix"] = [Mix(volume=mix[0], repetitions=mix[1], flow_rate=mix[2])] * len(batch)
            await operation([targets[i][2] for i in batch], vols=[volumes[i] for i in batch],
                            use_channels=[channels[i] for i in batch], **extra)
            with self._lock:
                for i in batch:
                    name, well, _ = targets[i]
                    tip = self._in_tips.setdefault(channels[i], {})
                    if action == "aspirate":
                        for liquid, amount in self._take((name, well), volumes[i]).items():
                            tip[liquid] = tip.get(liquid, 0.0) + amount
                        continue
                    held = self._contents.setdefault((name, well), {})
                    total = sum(tip.values())
                    if total <= 1e-9:
                        held[UNKNOWN] = held.get(UNKNOWN, 0.0) + volumes[i]
                        continue
                    share = min(1.0, volumes[i] / total)
                    for liquid in list(tip):
                        moved = tip[liquid] * share
                        tip[liquid] -= moved
                        held[liquid] = held.get(liquid, 0.0) + moved
        by_labware: Dict[str, List[str]] = {}
        for name, well, _ in targets:
            by_labware.setdefault(name, []).append(well)
        for name, wells in by_labware.items():
            await self._emit(action, name, wells)

    @staticmethod
    def _mix(volume, repetitions, flow_rate) -> Optional[tuple]:
        if volume is None or not repetitions:
            return None
        return (float(volume), int(repetitions), float(flow_rate) if flow_rate is not None else 100.0)

    # --- steps ------------------------------------------------------------------------------------------

    def transfer(self,
                 source: Annotated[str, Labware(*LIQUID_CONTAINERS)],
                 source_wells: Annotated[WellSelection, Wells("source")],
                 dest: Annotated[str, Labware(*LIQUID_CONTAINERS)],
                 dest_wells: Annotated[WellSelection, Wells("dest")],
                 vols: Annotated[Volumes, PerWell("dest_wells")],
                 tip_rack: Annotated[str, Labware("tip_rack")],
                 new_tip: Literal["always", "once", "never"] = "always",
                 aspiration_flow_rate: Optional[float] = None,
                 dispense_flow_rate: Optional[float] = None,
                 blow_out_air_volume: Optional[float] = None,
                 mix_after_volume: Optional[float] = None,
                 mix_after_repetitions: Optional[int] = None) -> Dict[str, float]:
        """Move liquid from source wells to destination wells (µL), as many at a time as the head has channels.

        One source well feeds every destination (a reservoir into a plate), or wells pair up one to
        one, or many pool into one. `vols` is one number for all of them or one per destination;
        a well given 0 is skipped. Tips come from the next unused ones in `tip_rack`: fresh for
        every group of wells ("always"), one set for the whole step ("once"), or the ones already
        on the head ("never"). Flow rates are µL/s. Returns the volume delivered to each
        destination well.
        """
        return run_async(self._transfer(source, source_wells, dest, dest_wells, vols, tip_rack, new_tip,
                                        aspiration_flow_rate, dispense_flow_rate, blow_out_air_volume,
                                        self._mix(mix_after_volume, mix_after_repetitions, dispense_flow_rate)))

    async def _transfer(self, source, source_wells, dest, dest_wells, vols, tip_rack, new_tip,
                        aspiration_flow_rate, dispense_flow_rate, blow_out_air_volume, mix_after):
        await self._setup()
        sources, dests = self._targets(source, source_wells), self._targets(dest, dest_wells)
        count = max(len(sources), len(dests))
        if len(sources) not in (1, count) or len(dests) not in (1, count):
            raise ValueError(f"{len(sources)} source wells and {len(dests)} destination wells do not pair up: "
                             "use one to many, many to one, or the same number of each")
        sources, dests = sources * (count // len(sources)), dests * (count // len(dests))
        volumes = self._per_well(vols, count, "vols")
        pairs = [(s, d, v) for s, d, v in zip(sources, dests, volumes) if v > 0]
        delivered: Dict[str, float] = {}
        if new_tip == "never" and not self._mounted():
            raise ValueError("new_tip is 'never' but no tips are on the head: pick some up first")
        width = self._channel_count()
        for start in range(0, len(pairs), width):
            group = pairs[start:start + width]
            if new_tip == "always" or (new_tip == "once" and not self._mounted()):
                await self._pick_up(tip_rack, len(group) if new_tip == "always" else min(width, len(pairs)))
            channels = self._channels_for(len(group))
            amounts = [v for _, _, v in group]
            await self._liquid("aspirate", [s for s, _, _ in group], amounts, channels,
                               flow_rates=None if aspiration_flow_rate is None else [aspiration_flow_rate] * len(group))
            await self._liquid("dispense", [d for _, d, _ in group], amounts, channels,
                               flow_rates=None if dispense_flow_rate is None else [dispense_flow_rate] * len(group),
                               blow_out_air_volume=blow_out_air_volume, mix=mix_after)
            for (_, (_, well, _), volume) in group:
                delivered[well] = round(delivered.get(well, 0.0) + volume, 3)
            if new_tip == "always":
                await self._drop()
        if new_tip == "once":
            await self._drop()
        return delivered

    def aspirate(self,
                 plate: Annotated[str, Labware(*LIQUID_CONTAINERS)],
                 wells: Annotated[WellSelection, Wells("plate")],
                 vols: Annotated[Volumes, PerWell("wells")] = 100.0,
                 flow_rates: Annotated[Optional[Volumes], PerWell("wells")] = None,
                 blow_out_air_volume: Optional[float] = None,
                 mix_volume: Optional[float] = None,
                 mix_repetitions: Optional[int] = None,
                 mix_flow_rate: Optional[float] = None) -> None:
        """Draw liquid up (µL) with the tips on the head, one channel per well (or, from one trough
        well, one channel per volume given). Mixes first if asked."""
        run_async(self._one_way("aspirate", plate, wells, vols, flow_rates, blow_out_air_volume,
                                self._mix(mix_volume, mix_repetitions, mix_flow_rate)))

    def dispense(self,
                 plate: Annotated[str, Labware(*LIQUID_CONTAINERS)],
                 wells: Annotated[WellSelection, Wells("plate")],
                 vols: Annotated[Volumes, PerWell("wells")] = 100.0,
                 flow_rates: Annotated[Optional[Volumes], PerWell("wells")] = None,
                 blow_out_air_volume: Optional[float] = None,
                 mix_volume: Optional[float] = None,
                 mix_repetitions: Optional[int] = None,
                 mix_flow_rate: Optional[float] = None) -> None:
        """Dispense (µL) from the tips on the head, one channel per well. Mixes after if asked."""
        run_async(self._one_way("dispense", plate, wells, vols, flow_rates, blow_out_air_volume,
                                self._mix(mix_volume, mix_repetitions, mix_flow_rate)))

    async def _one_way(self, action, plate, wells, vols, flow_rates, blow_out_air_volume, mix):
        await self._setup()
        targets = self._targets(plate, wells)
        listed = self._per_well(vols, 0, "vols") if isinstance(vols, (list, tuple)) or (
            isinstance(vols, str) and "," in vols) else None
        if len(targets) == 1 and listed and len(listed) > 1:
            # One well and a volume per channel: several tips in one trough well.
            targets = targets * len(listed)
        count = len(targets)
        await self._liquid(action, targets, self._per_well(vols, count, "vols"), self._channels_for(count),
                           flow_rates=None if flow_rates is None else self._per_well(flow_rates, count, "flow_rates"),
                           blow_out_air_volume=blow_out_air_volume, mix=mix)

    def mix(self,
            plate: Annotated[str, Labware(*LIQUID_CONTAINERS)],
            wells: Annotated[WellSelection, Wells("plate")],
            vols: float = 50.0,
            repetitions: int = 3) -> None:
        """Draw up and dispense in the same wells, `repetitions` times, with the tips on the head."""
        async def go():
            await self._setup()
            targets = self._targets(plate, wells)
            channels = self._channels_for(len(targets))
            amounts = [float(vols)] * len(targets)
            for _ in range(max(1, int(repetitions))):
                await self._liquid("aspirate", targets, amounts, channels)
                await self._liquid("dispense", targets, amounts, channels)
        run_async(go())

    def pick_up_tips(self,
                     tip_rack: Annotated[str, Labware("tip_rack")],
                     tip_spots: Annotated[WellSelection, Wells("tip_rack")] = "next",
                     count: int = 0) -> List[str]:
        """Put tips on the head: the positions given, or with "next" the next unused ones (`count`
        of them, or one per channel). Returns the positions taken."""
        async def go():
            await self._setup()
            return await self._pick_up(tip_rack, int(count) or self._channel_count(), tip_spots)
        return run_async(go())

    def drop_tips(self,
                  tip_rack: Annotated[str, Labware("tip_rack")],
                  tip_spots: Annotated[WellSelection, Wells("tip_rack")]) -> None:
        """Put the tips on the head into these positions of a tip rack, one per channel."""
        async def go():
            await self._setup()
            rack = self._resource(tip_rack, "tip rack")
            names = expand_wells(tip_spots, _grid(rack))
            channels = self._channels_for(len(names))
            await self._lh.drop_tips([rack.get_item(n) for n in names], use_channels=channels)
            with self._lock:
                for channel in channels:
                    self._in_tips.pop(channel, None)
            await self._emit("drop_tips", tip_rack, names)
        run_async(go())

    def return_tips(self) -> None:
        """Put the tips on the head back where they came from."""
        run_async(self._setup_then(self._drop("return")))

    def discard_tips(self) -> None:
        """Drop the tips on the head into the trash."""
        run_async(self._setup_then(self._drop("discard")))

    async def _setup_then(self, coro):
        await self._setup()
        return await coro

    def move_plate(self,
                   plate: Annotated[str, Labware("plate", "reservoir")],
                   to: Annotated[str, Site()]) -> None:
        """Carry a plate to another place on the worktable (needs a gripper on a real robot)."""
        async def go():
            await self._setup()
            sites = self._site_map()
            if str(to) not in sites:
                raise ValueError(f"'{to}' is not a place on this worktable (it has: {', '.join(sites)})")
            if sites[str(to)].children:
                raise ValueError(f"{to} already holds {sites[str(to)].children[0].name}")
            await self._lh.move_plate(self._resource(plate), sites[str(to)])
            with self._lock:
                self._layout = None
            await self._emit("move", plate)
        run_async(go())

    def load_liquid(self,
                    plate: Annotated[str, Labware(*LIQUID_CONTAINERS)],
                    wells: Annotated[WellSelection, Wells("plate")],
                    liquid: str,
                    vols: Annotated[Volumes, PerWell("wells")]) -> None:
        """Record what a person put on the worktable: this liquid, this much (µL), in these wells.
        Nothing moves."""
        loaded = self._load(plate, wells, liquid, vols)
        self._notify("load", plate, loaded)

    def read_volumes(self,
                     plate: Annotated[str, Labware(*LIQUID_CONTAINERS)],
                     wells: Annotated[WellSelection, Wells("plate")] = ALL) -> Dict[str, float]:
        """The volume tracked in each well (µL): what was loaded, plus and minus every transfer."""
        return {well: round(container.tracker.get_used_volume(), 3)
                for _, well, container in self._targets(plate, wells)}

    def tips_left(self, tip_rack: Annotated[str, Labware("tip_rack")]) -> int:
        """How many unused tips the rack still has."""
        rack = self._resource(tip_rack, "tip rack")
        return sum(1 for spot in rack.get_all_items() if spot.has_tip())

    def summary(self) -> str:
        """PyLabRobot's text summary of the worktable."""
        return self._lh.deck.summary()

    def start_visualizer(self, host: str = "127.0.0.1", ws_port: int = 2121, fs_port: int = 1337,
                         open_browser: bool = True) -> str:
        """Start PyLabRobot's own browser visualizer for this worktable. (IvoryOS NextGen draws the
        worktable in its Labware view instead.)"""
        from pylabrobot.visualizer import Visualizer
        visualizer = Visualizer(self._lh.deck, host=host, ws_port=ws_port, fs_port=fs_port, open_browser=open_browser)
        run_async(visualizer.setup())
        self._visualizer = visualizer
        return f"http://{visualizer.host}:{visualizer.fs_port}"

    # --- for instruments that share this worktable (a plate reader reading in place) --------------

    def _contents_of(self, labware: str, well: str) -> Dict[str, float]:
        with self._lock:
            return dict(self._contents.get((labware, well)) or {})
