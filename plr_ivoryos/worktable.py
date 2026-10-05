"""The worktable as a file: which robot, what sits where, and what was put in it.

This is the `deck_json` the LiquidHandler has always taken, so a layout written for 0.1 still
loads. One file says everything, so switching robots is choosing (or editing) a file, never a
command-line flag:

    {
      "deck_type": "OTDeck",
      "resources": [
        {"name": "tips_300", "type": "opentrons_96_tiprack_300ul", "slot": 1},
        {"name": "assay_plate", "type": "cor_96_wellplate_360uL_Fb", "slot": 5}
      ],
      "liquids": [{"labware": "reservoir", "wells": "A1", "liquid": "buffer", "volume_ul": 14000}]
    }

- `deck_type` is a PyLabRobot deck: OTDeck, STARLetDeck, STARDeck, EVO100Deck, EVO150Deck,
  EVO200Deck. Default STARLetDeck.
- Each resource is a PyLabRobot definition (`type`, any name in `pylabrobot.resources`) placed by
  `slot` (Opentrons), `rails` (Hamilton, Tecan) or `location` ({x, y, z} in mm, as in 0.1).
  A carrier lists what it holds in `children`, each with the `site` it sits on.
- `liquids` is what a person put on the worktable before the run.
- A `{"name": "trash", "type": "Trash", "site": 3}` child is a trash in a carrier position (a Tecan
  tip carrier's waste): PyLabRobot discards tips into the resource called "trash".
- `other_worktables` keeps, per robot, the worktable it had before the robot was switched, so
  switching back loses nothing.

This file is the one a person (or the Hub, or the Labware panel) writes: short, by name. Whenever
the LiquidHandler loads or saves it, it also writes PyLabRobot's own description of the same
worktable beside it (`export_pylabrobot`): `worktable.pylabrobot.json`, every resource with its
size and absolute position, which plain PyLabRobot loads with `Deck.load_from_json_file`, and
`worktable.pylabrobot-state.json`, full tip racks and the starting liquids, for
`deck.load_state_from_file`. Those copies are output; edit this one.

IvoryOS's Labware view edits this file (place, move, rename, remove, liquids, change robot)
through the LiquidHandler.
"""

import copy
import importlib
import inspect
import json
import os
from typing import Any, Dict, List, Optional

import pylabrobot.resources as plr_resources
from pylabrobot.resources import Carrier, Coordinate, ItemizedResource, Trash

from plr_ivoryos.wells import ALL, expand_wells

FORMAT = "plr-ivoryos-worktable/1"
DEFAULT_DECK = "STARLetDeck"

# Decks that can be built with no arguments, and what a person calls them. (VantageDeck needs a
# size, and is reached by passing a built `deck=` instead.)
DECKS = {
    "OTDeck": "Opentrons OT-2",
    "STARLetDeck": "Hamilton STARlet",
    "STARDeck": "Hamilton STAR",
    "EVO100Deck": "Tecan EVO 100",
    "EVO150Deck": "Tecan EVO 150",
    "EVO200Deck": "Tecan EVO 200",
}

_SEARCH = ["pylabrobot.resources", "pylabrobot.resources.hamilton", "pylabrobot.resources.corning",
           "pylabrobot.resources.opentrons", "pylabrobot.resources.thermo_fisher", "pylabrobot.resources.greiner"]


def resolve(name: str):
    """A PyLabRobot deck or labware definition by name."""
    for module_path in _SEARCH:
        try:
            found = getattr(importlib.import_module(module_path), str(name), None)
        except Exception:
            continue
        if found is not None:
            return found
    import difflib
    close = difflib.get_close_matches(str(name), dir(plr_resources), n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise ValueError(f"'{name}' is not a deck or labware definition in pylabrobot.resources.{hint}")


def make(definition: str, name: str, size=None):
    """A labware, carrier or trash by its PyLabRobot definition name. "Trash" is the one that is
    not a ready-made definition: it takes the size of where it goes."""
    if definition == "Trash":
        x, y, z = (list(size) + [0, 0, 0])[:3] if size else (100, 100, 0)
        return Trash(name=name, size_x=x, size_y=y, size_z=z)
    return resolve(definition)(name=name)


def _place(deck, entry: dict) -> None:
    resource = make(entry["type"], entry["name"], entry.get("size"))
    if isinstance(resource, Carrier):
        for child in entry.get("children") or []:
            site = int(child["site"])
            holder = resource.children[site]
            size = (holder.get_size_x(), holder.get_size_y(), 0)
            resource.assign_resource_to_site(make(child["type"], child["name"], size), spot=site)
    elif entry.get("children"):
        for child in entry["children"]:
            at = child.get("location") or {}
            resource.assign_child_resource(make(child["type"], child["name"]),
                                           location=Coordinate(at.get("x", 0), at.get("y", 0), at.get("z", 0)))
    if "slot" in entry:
        deck.assign_child_at_slot(resource, int(entry["slot"]))
    elif "rails" in entry:
        deck.assign_child_resource(resource, rails=int(entry["rails"]))
    else:
        at = entry.get("location") or {}
        deck.assign_child_resource(resource, location=Coordinate(at.get("x", 0), at.get("y", 0), at.get("z", 0)))


def build_deck(config: dict):
    """The PyLabRobot deck a worktable file describes."""
    deck = resolve(config.get("deck_type") or DEFAULT_DECK)()
    for entry in config.get("resources") or []:
        _place(deck, entry)
    return deck


# Millimetres between rails, and where rail 1 is (PyLabRobot: HamiltonSTARDeck.rails_to_location,
# TecanDeck._coordinate_for_rails before a carrier's own offset).
_RAIL_PITCH = {"HamiltonSTARDeck": 22.5, "TecanDeck": 25.0}


def rails_of(deck) -> List[Dict[str, float]]:
    """Where each rail of a rail-based worktable is, `[{"rail", "x"}]`; empty for a deck of slots."""
    count = getattr(deck, "num_rails", None)
    if not count:
        return []
    if hasattr(deck, "rails_to_location"):
        return [{"rail": n, "x": round(deck.rails_to_location(n).x, 2)} for n in range(1, count + 1)]
    pitch = _RAIL_PITCH.get(type(deck).__name__, 25.0)
    return [{"rail": n, "x": round(100 + (n - 1) * pitch, 2)} for n in range(1, count + 1)]


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, config: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    body = {"format": FORMAT, **{k: v for k, v in config.items() if k != "format"}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
        f.write("\n")


def find(config: dict, name: str):
    """(the entry called `name`, the list it is in, the carrier entry holding it or None)."""
    for entry in config.get("resources") or []:
        if entry.get("name") == name:
            return entry, config["resources"], None
        for child in entry.get("children") or []:
            if child.get("name") == name:
                return child, entry["children"], entry
    return None, None, None


def grid_of(resource) -> List[List[str]]:
    """Position names as rows of columns. PyLabRobot lists items column by column."""
    if not isinstance(resource, ItemizedResource):
        return [["A1"]]
    rows, columns = resource.num_items_y, resource.num_items_x
    names = [resource.get_child_identifier(item) for item in resource.get_all_items()]
    if len(names) != rows * columns:
        return [names]
    return [[names[c * rows + r] for c in range(columns)] for r in range(rows)]


def apply_liquids(deck, config: dict) -> None:
    """Set the volumes `liquids` gives, on a deck built from this file (what a run starts from)."""
    for entry in config.get("liquids") or []:
        if not deck.has_resource(entry["labware"]):
            continue
        resource = deck.get_resource(entry["labware"])
        wells = entry.get("wells", ALL)
        wells = ", ".join(wells) if isinstance(wells, (list, tuple)) else wells
        for well in expand_wells(wells, grid_of(resource)):
            item = resource.get_item(well) if isinstance(resource, ItemizedResource) else resource
            item.tracker.set_volume(float(entry["volume_ul"]))


def pylabrobot_paths(path: str) -> Dict[str, str]:
    """Where PyLabRobot's own copy of a worktable file goes, beside it: worktable.json ->
    worktable.pylabrobot.json (the layout) and worktable.pylabrobot-state.json (full tip racks and
    the starting liquids, which PyLabRobot keeps apart from the layout)."""
    stem = os.path.splitext(path)[0]
    return {"layout": stem + ".pylabrobot.json", "state": stem + ".pylabrobot-state.json"}


def export_pylabrobot(config: dict, path: str) -> Optional[str]:
    """Write this worktable as PyLabRobot itself reads it, as it is when a run starts:

        deck = Deck.load_from_json_file("worktable.pylabrobot.json")      # every labware, placed
        deck.load_state_from_file("worktable.pylabrobot-state.json")       # tips and volumes

    Built fresh from the file (not from a deck a run has used tips from), and checked by reading
    both back the way PyLabRobot would. Returns why not when it cannot (PyLabRobot 0.2.2 cannot read
    back its own Tecan wash station), and then leaves no files behind."""
    from pylabrobot.resources import Deck
    targets = pylabrobot_paths(path)
    scratch = {part: target + ".tmp" for part, target in targets.items()}
    try:
        deck = build_deck(config)
        apply_liquids(deck, config)
        deck.save(scratch["layout"])
        deck.save_state_to_file(scratch["state"])
        Deck.load_from_json_file(scratch["layout"]).load_state_from_file(scratch["state"])
    except Exception as e:
        for leftover in [*scratch.values(), *targets.values()]:
            if os.path.exists(leftover):
                os.remove(leftover)
        return f"PyLabRobot cannot read this worktable back ({type(e).__name__}: {e})"
    for part, target in targets.items():
        os.replace(scratch[part], target)
    return None


def remove(config: dict, name: str) -> bool:
    """Take the entry called `name` off the worktable, wherever it sits. True if it was there."""
    resources = config.get("resources") or []
    for i, entry in enumerate(resources):
        if entry.get("name") == name:
            del resources[i]
            return True
        children = entry.get("children") or []
        for j, child in enumerate(children):
            if child.get("name") == name:
                del children[j]
                return True
    return False


# --- Ready-made worktables -----------------------------------------------------------------------

_PLATE = "cor_96_wellplate_360uL_Fb"
_RESERVOIR = "nest_12_troughplate_15000uL_Vb"
_LIQUIDS = [{"labware": "reservoir", "wells": "A1", "liquid": "buffer", "volume_ul": 14000},
            {"labware": "reservoir", "wells": "A2", "liquid": "dye", "volume_ul": 9000}]

STARTERS: Dict[str, dict] = {
    "OTDeck": {"deck_type": "OTDeck", "resources": [
        {"name": "tips", "type": "opentrons_96_tiprack_300ul", "slot": 1},
        {"name": "tips_b", "type": "opentrons_96_tiprack_300ul", "slot": 4},
        {"name": "reservoir", "type": _RESERVOIR, "slot": 2},
        {"name": "assay_plate", "type": _PLATE, "slot": 5},
        {"name": "sample_plate", "type": _PLATE, "slot": 6},
    ], "liquids": _LIQUIDS},
    "STARLetDeck": {"deck_type": "STARLetDeck", "resources": [
        {"name": "tip_carrier", "type": "TIP_CAR_480_A00", "rails": 3, "children": [
            {"name": "tips", "type": "hamilton_96_tiprack_300uL_filter", "site": 0},
            {"name": "tips_b", "type": "hamilton_96_tiprack_300uL_filter", "site": 1}]},
        {"name": "plate_carrier", "type": "PLT_CAR_L5AC_A00", "rails": 15, "children": [
            {"name": "reservoir", "type": _RESERVOIR, "site": 0},
            {"name": "assay_plate", "type": _PLATE, "site": 1},
            {"name": "sample_plate", "type": _PLATE, "site": 2}]},
    ], "liquids": _LIQUIDS},
}


STARTERS["STARDeck"] = {**copy.deepcopy(STARTERS["STARLetDeck"]), "deck_type": "STARDeck"}

_TECAN = {"resources": [
    # A Tecan EVO has no trash of its own: the waste position of the tip carrier is it.
    {"name": "tip_carrier", "type": "DiTi_3Pos___Waste", "rails": 10, "children": [
        {"name": "tips", "type": "DiTi_200ul_LiHa", "site": 0},
        {"name": "tips_b", "type": "DiTi_200ul_LiHa", "site": 1},
        {"name": "trash", "type": "Trash", "site": 3}]},
    {"name": "plate_carrier", "type": "MP_3Pos", "rails": 17, "children": [
        {"name": "reservoir", "type": _RESERVOIR, "site": 0},
        {"name": "assay_plate", "type": _PLATE, "site": 1},
        {"name": "sample_plate", "type": _PLATE, "site": 2}]},
], "liquids": _LIQUIDS}
for _kind in ("EVO100Deck", "EVO150Deck", "EVO200Deck"):
    STARTERS[_kind] = {"deck_type": _kind, **copy.deepcopy(_TECAN)}


def starter(deck_type: str) -> dict:
    """A worktable to start from: two racks of the robot's own tips, a reservoir with buffer and
    dye, two plates, with the same names on every robot (`tips`, `reservoir`, `assay_plate`, ...)
    so one workflow runs on any of them. Empty for a deck with no starter."""
    if deck_type in STARTERS:
        return copy.deepcopy(STARTERS[deck_type])
    return {"deck_type": deck_type, "resources": [], "liquids": []}


# --- What can be put on a worktable --------------------------------------------------------------

_catalog: Optional[List[Dict[str, str]]] = None

_KINDS = {"Plate": "plate", "TecanPlate": "plate", "TipRack": "tip_rack", "TecanTipRack": "tip_rack",
          "TubeRack": "tube_rack", "Trough": "reservoir",
          "PlateCarrier": "carrier", "TipCarrier": "carrier", "TroughCarrier": "carrier", "TubeCarrier": "carrier",
          "MFXCarrier": "carrier", "TecanPlateCarrier": "carrier", "TecanTipCarrier": "carrier"}
# Which maker's tips and carriers fit which robot. Plates, reservoirs and tube racks fit any.
_MAKER = {"OTDeck": "opentrons", "STARLetDeck": "hamilton", "STARDeck": "hamilton",
          "EVO100Deck": "tecan", "EVO150Deck": "tecan", "EVO200Deck": "tecan"}


def _all_definitions() -> List[Dict[str, str]]:
    global _catalog
    if _catalog is None:
        found = []
        for name in dir(plr_resources):
            factory = getattr(plr_resources, name)
            if name.startswith("_") or inspect.isclass(factory) or not callable(factory):
                continue
            try:
                signature = inspect.signature(factory)
                returns = signature.return_annotation
                kind = _KINDS.get(returns if isinstance(returns, str) else getattr(returns, "__name__", ""))
                if not kind or list(signature.parameters)[:1] != ["name"]:
                    continue
                if "deprecated" in inspect.getsource(factory).lower():
                    continue  # an old spelling kept as an alias of the current one
            except (TypeError, ValueError, OSError):
                continue
            if kind == "plate" and ("trough" in name.lower() or "reservoir" in name.lower()):
                kind = "reservoir"
            module = getattr(factory, "__module__", "") or ""
            maker = next((m for m in ("opentrons", "hamilton", "tecan") if f".{m}" in module), "")
            found.append({"definition": name, "category": kind, "maker": maker})
        _catalog = sorted(found, key=lambda entry: (entry["category"], entry["definition"].lower()))
    return _catalog


def catalog(deck_type: Optional[str] = None) -> List[Dict[str, str]]:
    """What PyLabRobot defines that can go on this robot's worktable, by the name `type` takes:
    plates, reservoirs and tube racks from anyone, tip racks and carriers by the robot's maker
    (carriers only where there are rails to put them on). Read from each definition's return
    type, so nothing is constructed to find out; an old spelling kept as an alias is left out."""
    maker = _MAKER.get(deck_type or "", "")
    rails = maker in ("hamilton", "tecan")
    out = []
    for entry in _all_definitions():
        if entry["category"] == "carrier" and not (rails and entry["maker"] == maker):
            continue
        if entry["category"] == "tip_rack" and maker and entry["maker"] != maker:
            continue
        if entry["category"] == "plate" and entry["maker"] == "tecan" and maker != "tecan":
            continue
        out.append({"definition": entry["definition"], "category": entry["category"]})
    return out


def describe_decks() -> List[Dict[str, Any]]:
    return [{"kind": kind, "label": label, "starter": kind in STARTERS} for kind, label in DECKS.items()]
