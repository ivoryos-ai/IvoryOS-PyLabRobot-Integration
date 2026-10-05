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

IvoryOS's Labware view edits this file (place, remove, change robot) through the LiquidHandler.
"""

import copy
import importlib
import inspect
import json
import os
from typing import Any, Dict, List, Optional

import pylabrobot.resources as plr_resources
from pylabrobot.resources import Carrier, Coordinate

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


def make(definition: str, name: str):
    return resolve(definition)(name=name)


def _place(deck, entry: dict) -> None:
    resource = make(entry["type"], entry["name"])
    if isinstance(resource, Carrier):
        for child in entry.get("children") or []:
            resource.assign_resource_to_site(make(child["type"], child["name"]), spot=int(child["site"]))
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


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, config: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    body = {"format": FORMAT, **{k: v for k, v in config.items() if k != "format"}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
        f.write("\n")


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
        {"name": "tips_300", "type": "opentrons_96_tiprack_300ul", "slot": 1},
        {"name": "tips_300_b", "type": "opentrons_96_tiprack_300ul", "slot": 4},
        {"name": "reservoir", "type": _RESERVOIR, "slot": 2},
        {"name": "assay_plate", "type": _PLATE, "slot": 5},
        {"name": "sample_plate", "type": _PLATE, "slot": 6},
    ], "liquids": _LIQUIDS},
    "STARLetDeck": {"deck_type": "STARLetDeck", "resources": [
        {"name": "tip_carrier", "type": "TIP_CAR_480_A00", "rails": 3, "children": [
            {"name": "tips_300", "type": "hamilton_96_tiprack_300uL_filter", "site": 0},
            {"name": "tips_300_b", "type": "hamilton_96_tiprack_300uL_filter", "site": 1}]},
        {"name": "plate_carrier", "type": "PLT_CAR_L5AC_A00", "rails": 15, "children": [
            {"name": "reservoir", "type": _RESERVOIR, "site": 0},
            {"name": "assay_plate", "type": _PLATE, "site": 1},
            {"name": "sample_plate", "type": _PLATE, "site": 2}]},
    ], "liquids": _LIQUIDS},
}


def starter(deck_type: str) -> dict:
    """A worktable to start from: tips, a reservoir with buffer and dye, two plates, with the same
    names on every robot so one workflow runs on any of them. Empty for a deck with no starter."""
    if deck_type in STARTERS:
        return copy.deepcopy(STARTERS[deck_type])
    return {"deck_type": deck_type, "resources": [], "liquids": []}


# --- What can be put on a worktable --------------------------------------------------------------

_catalog: Optional[List[Dict[str, str]]] = None


def catalog() -> List[Dict[str, str]]:
    """Every plate, tip rack and reservoir PyLabRobot defines, by the name `type` takes. Read from
    each definition's return type, so nothing is constructed to find out; an old spelling kept
    as a deprecated alias is left out."""
    global _catalog
    if _catalog is None:
        kinds = {"Plate": "plate", "TipRack": "tip_rack", "TubeRack": "tube_rack", "Trough": "reservoir"}
        found = []
        for name in dir(plr_resources):
            factory = getattr(plr_resources, name)
            if name.startswith("_") or inspect.isclass(factory) or not callable(factory):
                continue
            try:
                signature = inspect.signature(factory)
                returns = signature.return_annotation
                kind = kinds.get(returns if isinstance(returns, str) else getattr(returns, "__name__", ""))
                if not kind or list(signature.parameters)[:1] != ["name"]:
                    continue
                if "deprecated" in inspect.getsource(factory).lower():
                    continue
            except (TypeError, ValueError, OSError):
                continue
            if kind == "plate" and ("trough" in name.lower() or "reservoir" in name.lower()):
                kind = "reservoir"
            found.append({"definition": name, "category": kind})
        _catalog = sorted(found, key=lambda entry: (entry["category"], entry["definition"].lower()))
    return _catalog


def describe_decks() -> List[Dict[str, Any]]:
    return [{"kind": kind, "label": label, "starter": kind in STARTERS} for kind, label in DECKS.items()]
