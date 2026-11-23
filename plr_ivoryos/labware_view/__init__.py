"""The Labware view: an IvoryOS NextGen plugin that draws every worktable on the deck, live.

    "plugins": ["plr_ivoryos.labware_view:plugin"]                  in a deck file
    ivoryos_edge.run(__name__, plugins=[plr_ivoryos.labware_view.plugin])

It draws whatever an instrument reports through `__ivoryos_labware__` (robot.py, for a Flex):
wells show what they hold, tip racks which tips are left, and the wells a step is working on light
up while it runs. With "Edit layout" it changes the worktable the way a person changes the real
one, saved to its worktable file: what is mounted on the robot, drag labware from PyLabRobot's
catalogue onto a place (or a carrier onto the tracks), drag what is there to move it, rename or
remove it, fill wells with a liquid, or import a layout someone already has. A layout is saved
under a name, switched to, gone back to as it was saved, and downloaded as a file. Nothing moves.

Only IvoryOS NextGen loads this module, and it provides `ivoryos_edge`; the rest of plr-ivoryos
does not import it. Served at /plugins/labware/ (page), /plugins/labware/api/{layout,state,
catalog,edit,export} and /plugins/labware/events.
"""

import json
import os
from typing import Optional
from urllib.parse import quote

from fastapi.responses import FileResponse, JSONResponse, Response
from ivoryos_edge.plugins import Plugin

plugin = Plugin("Labware", id="labware", page="page", placement="panel-right", icon="grid-3x3")

# Worktables changed since this process started: steps offer the change only after a restart, and a
# page opened (or reloaded) in between should still say so. Only for a worktable that does not say
# itself whether it still is what the deck started with (`deck.restart_needed`).
_restart_pending: set = set()


def _needs_restart(name: str, found: dict) -> bool:
    told = (found.get("deck") or {}).get("restart_needed")
    return told if isinstance(told, bool) else name in _restart_pending


def _call(instrument, method: str, *args):
    found = getattr(instrument, method, None)
    if not callable(found):
        return None
    try:
        return found(*args)
    except Exception as e:  # a view must never take the deck down
        print(f"Labware view: {type(instrument).__name__}.{method} failed: {e}")
        return None


def _worktables() -> dict:
    """Instruments that own a worktable. One that only shares another's (a plate reader that
    reads in place) reports labware without a `deck`, and is not drawn twice."""
    found = {}
    for name, instrument in plugin.instruments.items():
        layout = _call(instrument, "__ivoryos_labware__")
        if isinstance(layout, dict) and layout.get("deck"):
            found[name] = (instrument, layout)
    return found


def layout() -> dict:
    worktables = {name: found for name, (_, found) in _worktables().items()}
    return {"worktables": worktables,
            "restart_needed": sorted(name for name, found in worktables.items() if _needs_restart(name, found))}


def state() -> dict:
    return {"worktables": {name: _call(instrument, "__ivoryos_labware_state__") or {}
                           for name, (instrument, _) in _worktables().items()}}


@plugin.on_start
def _start(instruments):
    for name, instrument in instruments.items():
        def on_event(event, name=name, instrument=instrument):
            # A change to the worktable itself means the page reads the layout again.
            plugin.publish({"worktable": name, "event": event,
                            "state": _call(instrument, "__ivoryos_labware_state__") or {},
                            # "load" too: filling wells changes whether a saved layout still matches.
                            "relayout": event.get("action") in ("move", "layout", "load")})

        _call(instrument, "__ivoryos_labware_events__", on_event)


@plugin.router.get("/api/layout")
def get_layout():
    return layout()


@plugin.router.get("/api/state")
def get_state():
    return state()


@plugin.router.get("/api/pylabrobot")
def get_pylabrobot(worktable: str, part: str = "layout"):
    """The worktable in PyLabRobot's own format, as a download: the layout (for
    `Deck.load_from_json_file`) or the starting state (for `deck.load_state_from_file`)."""
    found = _worktables().get(worktable)
    path = (((found or (None, {}))[1].get("deck") or {}).get("pylabrobot_files") or {}).get(part)
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "There is no PyLabRobot file for this worktable."})
    return FileResponse(path, media_type="application/json", filename=os.path.basename(path))


@plugin.router.get("/api/export")
def get_export(worktable: str, layout: Optional[str] = None):
    """A layout as a file, as a download: the one in use, or a saved one by name. It is the file
    "Import a layout" takes."""
    found = _worktables().get(worktable)
    give = getattr(found[0], "__ivoryos_labware_export__", None) if found else None
    if not callable(give):
        return JSONResponse(status_code=404, content={"error": "This worktable cannot be downloaded."})
    try:
        result = give(layout or None)
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    filename = str(result.get("filename") or "worktable.json")
    return Response(json.dumps(result.get("layout") or {}, indent=2) + "\n", media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@plugin.router.get("/api/catalog")
def get_catalog():
    """Per worktable: what can be put on it and which robots it can become. Empty lists for one
    that cannot be changed here."""
    out = {}
    for name, (instrument, _) in _worktables().items():
        found = _call(instrument, "__ivoryos_labware_catalog__")
        out[name] = found if isinstance(found, dict) else {"labware": [], "decks": [], "deck": None, "importable": False}
    return {"worktables": out}


@plugin.router.post("/api/edit")
def edit(change: dict):
    """Change a worktable: {"worktable", "action", ...} as `__ivoryos_labware_edit__` takes it
    (robot.py). `restart` says whether steps only offer the change after the deck
    restarts: labware names are read into the deck's schema once, at startup."""
    found = _worktables().get(str(change.get("worktable")))
    apply = getattr(found[0], "__ivoryos_labware_edit__", None) if found else None
    if not callable(apply):
        return JSONResponse(status_code=400, content={"error": "This worktable cannot be changed from here."})
    try:
        result = apply(str(change.get("action")), **{k: v for k, v in change.items() if k not in ("worktable", "action")})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    result = result if isinstance(result, dict) else {}
    if result.get("restart", True):
        _restart_pending.add(str(change.get("worktable")))
    now = layout()
    return {"layout": now, "catalog": get_catalog()["worktables"], "state": state(),
            "restart_needed": str(change.get("worktable")) in now["restart_needed"], "name": result.get("name"),
            "kept": os.path.basename(result["kept"]) if result.get("kept") else None}
