"""A simulated Opentrons Flex or OT-2: the robot-server's HTTP API, answered in Python.

PyLabRobot 1.0's Flex (and its OT-2, which speaks the same API) talks to the robot only through one HTTP transport (`pylabrobot.io.HTTP`),
which its constructor takes as `io=`. This is that transport with no robot behind it. Everything
above it runs exactly as it does against hardware: PyLabRobot's Flex sets up, discovers the pipettes
and gripper this says are mounted, uploads labware definitions, and sends every command a real run
would, with its own tip and volume tracking and its own refusals (a single-tip step with eight tips
on, a flow rate the pipette has no default for). So a workflow that runs here has been checked
against PyLabRobot, though not against the robot's own motion planning.

What it answers: health, instruments, deck configuration (the trash bin), modules (none), runs, run
actions, labware definitions and commands. Commands succeed at once; `loadPipette` and `loadLabware`
hand out ids, the tip sensor reports what was picked up and dropped, and a position query answers a
fixed position. A pickup from spots holding no tip leaves the sensor reading absent, which is what
fails it on a robot. `log` keeps every command, for tests.
"""

import asyncio
import itertools
import re
from typing import Any, Callable, Dict, List, Optional

from pylabrobot.io.http import HTTP, HTTPError
from pylabrobot.resources.errors import NoTipError, ResourceNotFoundError

# The Flex pipettes, by the name the robot reports (`instrumentName`): the model it reports for the
# simulator, channels, and volume range (µL). The models are ones PyLabRobot has default flow rates for.
FLEX_PIPETTES: Dict[str, Dict[str, Any]] = {
    "p50_single_flex": {"model": "p50_single_v3.5", "channels": 1, "min_ul": 1.0, "max_ul": 50.0,
                        "label": "Flex 1-Channel 50 µL"},
    "p1000_single_flex": {"model": "p1000_single_v3.5", "channels": 1, "min_ul": 5.0, "max_ul": 1000.0,
                          "label": "Flex 1-Channel 1000 µL"},
    "p50_multi_flex": {"model": "p50_multi_v3.5", "channels": 8, "min_ul": 1.0, "max_ul": 50.0,
                       "label": "Flex 8-Channel 50 µL"},
    "p1000_multi_flex": {"model": "p1000_multi_v3.5", "channels": 8, "min_ul": 5.0, "max_ul": 1000.0,
                         "label": "Flex 8-Channel 1000 µL"},
    "p1000_96": {"model": "p1000_96_v3.5", "channels": 96, "min_ul": 5.0, "max_ul": 1000.0,
                 "label": "Flex 96-Channel 1000 µL"},
    "p200_96": {"model": "p200_96_v3.3", "channels": 96, "min_ul": 1.0, "max_ul": 200.0,
                "label": "Flex 96-Channel 200 µL"},
}

# The OT-2 pipettes PyLabRobot 1.0 drives, by the name the robot reports, with their channels and
# volume range: PyLabRobot's own table, so a pipette it adds is simulated too.
from pylabrobot.opentrons.ot2.pipette import _PIPETTE_SPECS as _OT2_SPECS  # noqa: E402

OT2_PIPETTES: Dict[str, Dict[str, Any]] = {
    name: {"model": f"{name.replace('_gen2', '')}_v2.1" if name.endswith("_gen2") else f"{name}_v1.5",
           "channels": spec.channels, "min_ul": float(spec.minimum_volume), "max_ul": float(spec.maximum_volume),
           "label": f"{'GEN2 ' if name.endswith('_gen2') else ''}{'8-Channel' if spec.channels == 8 else 'Single-Channel'} "
                    f"{spec.maximum_volume:g} µL"}
    for name, spec in _OT2_SPECS.items()}

API_VERSION = "8.4.0"  # recent enough for every command PyLabRobot sends (robot/* needs 8.2.0)


def _holds_a_tip(spot) -> bool:
    """Whether a spot held a tip before this pickup. PyLabRobot has already staged taking the tip
    when the command arrives, and `get_tip` is what still reads it, as PyLabRobot's own pickup does."""
    try:
        spot.tracker.get_tip()
    except NoTipError:
        return False
    return True


class SimulatedFlexServer(HTTP):
    """The robot-server of a Flex with these pipettes mounted.

        mounts   {"left": "p1000_multi_flex", "right": "p50_single_flex"}, or {"left": "p1000_96"}
                 for the 96-channel head (which takes both mounts)
        gripper  whether the gripper is fitted
        trash    the slot of the trash bin, or None
        delay_s  how long each command takes, so a run can be watched
        labware  finds labware on the worktable by name, so a pickup can tell a used spot from a full
                 one. Without it every pickup finds a tip.
    """

    PIPETTES = FLEX_PIPETTES
    ROBOT_MODEL = "OT-3 Standard"
    LABEL = "Opentrons Flex"
    HOME = {"x": 0.0, "y": 0.0, "z": 100.0}  # where a pipette is before it is moved

    def __init__(self, mounts: Dict[str, str], gripper: bool = True, trash: Optional[str] = "A3",
                 delay_s: float = 0.0, name: str = "simulated-flex",
                 labware: Optional[Callable[[str], Any]] = None):
        super().__init__(f"Simulated {self.LABEL}", f"http://{name}", timeout=30)
        unknown = [p for p in mounts.values() if p not in self.PIPETTES]
        if unknown:
            raise ValueError(f"'{unknown[0]}' is not a pipette for this robot: {', '.join(self.PIPETTES)}")
        self.mounts = dict(mounts)
        self.gripper = bool(gripper)
        self.trash = trash
        self.delay_s = float(delay_s)
        self.name = name
        self.labware = labware
        self._ids = itertools.count(1)
        self.runs: Dict[str, dict] = {}
        self.log: List[dict] = []

    # PyLabRobot's transport has a thread pool to set up; this answers in place.
    async def setup(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def _id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    def _instruments(self) -> List[dict]:
        out = []
        for mount, name in self.mounts.items():
            spec = self.PIPETTES[name]
            out.append({"mount": mount, "instrumentType": "pipette", "instrumentName": name,
                        "instrumentModel": spec["model"],
                        "data": {"channels": spec["channels"], "min_volume": spec["min_ul"],
                                 "max_volume": spec["max_ul"]}})
        if self.gripper:
            out.append({"mount": "extension", "instrumentType": "gripper", "instrumentName": "flexGripper",
                        "instrumentModel": "gripperV1.3"})
        return out

    async def request(self, method: str, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        method = method.upper()
        if method == "GET" and path == "/health":
            return {"name": self.name, "robot_model": self.ROBOT_MODEL, "api_version": API_VERSION,
                    "robot_serial": "SIMULATED"}
        if method == "GET" and path == "/instruments":
            return {"data": self._instruments()}
        if method == "GET" and path == "/deck_configuration":
            fixtures = [{"cutoutId": f"cutout{self.trash}", "cutoutFixtureId": "trashBinAdapter"}] if self.trash else []
            return {"data": {"cutoutFixtures": fixtures}}
        if method == "GET" and path == "/modules":
            return {"data": []}
        if method == "GET" and path == "/runs":
            return {"data": [{"id": run_id, "status": run["status"]} for run_id, run in self.runs.items()]}
        if method == "POST" and path == "/runs":
            run_id = self._id("run")
            self.runs[run_id] = {"status": "idle", "commands": {}, "tips": {}}
            return {"data": {"id": run_id, "status": "idle"}}
        match = re.fullmatch(r"/runs/([^/]+)(/.*)?", path)
        if match:
            return await self._run_request(method, path, match.group(1), match.group(2) or "", data)
        raise HTTPError(method, path, 404, "not part of the simulated robot-server")

    async def _run_request(self, method, path, run_id, rest, data):
        run = self.runs.get(run_id)
        if run is None:
            raise HTTPError(method, path, 404, f"no run {run_id}")
        if method == "GET" and rest == "":
            return {"data": {"id": run_id, "status": run["status"]}}
        if method == "POST" and rest in ("/actions", "/cancel", "/actions/cancel"):
            run["status"] = "stopped"
            return {"data": {}}
        if method == "DELETE" and rest == "":
            del self.runs[run_id]
            return {}
        if method == "POST" and rest == "/labware_definitions":
            definition = (data or {}).get("data") or {}
            uri = f"{definition.get('namespace', 'custom_beta')}/{definition['parameters']['loadName']}/" \
                  f"{definition.get('version', 1)}"
            return {"data": {"definitionUri": uri}}
        if method == "POST" and rest == "/commands":
            if run["status"] == "stopped":
                raise HTTPError(method, path, 409, "the run has stopped")
            body = (data or {}).get("data") or {}
            command_id = self._id("command")
            command_type, params = body.get("commandType"), body.get("params") or {}
            run["commands"][command_id] = self._execute(run, command_type, params)
            self.log.append({"commandType": command_type, "params": params})
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            return {"data": {"id": command_id}}
        command = re.fullmatch(r"/commands/([^/]+)", rest)
        if method == "GET" and command and command.group(1) in run["commands"]:
            status, result, error = run["commands"][command.group(1)]
            return {"data": {"id": command.group(1), "status": status, "result": result, "error": error}}
        raise HTTPError(method, path, 404, "not part of the simulated robot-server")

    def _execute(self, run: dict, command_type: str, params: dict):
        """(status, result, error) for one command."""
        tips = run["tips"]
        if command_type == "loadPipette":
            pipette_id = self._id("pipette")
            run.setdefault("pipettes", {})[pipette_id] = params.get("pipetteName")
            return "succeeded", {"pipetteId": pipette_id}, None
        if command_type == "loadLabware":
            labware_id = params.get("labwareId") or self._id("labware")
            run.setdefault("labware", {})[labware_id] = params.get("displayName")
            return "succeeded", {"labwareId": labware_id}, None
        if command_type == "pickUpTip":
            pipette = params.get("pipetteId")
            tips[pipette] = bool(tips.get(pipette)) or self._finds_a_tip(run, params)
        elif command_type in ("dropTip", "dropTipInPlace", "unsafe/dropTipInPlace"):
            tips[params.get("pipetteId")] = False
        elif command_type == "getTipPresence":
            present = tips.get(params.get("pipetteId"))
            status = "unknown" if present is None else ("present" if present else "absent")
            return "succeeded", {"status": status}, None
        elif command_type == "verifyTipPresence":
            wanted = params.get("expectedState") == "present"
            if bool(tips.get(params.get("pipetteId"))) != wanted:
                return "failed", None, {"errorType": "TipNotAttachedError" if wanted else "TipAttachedError",
                                        "detail": "The tip sensor did not read what was expected."}
        elif command_type == "savePosition":
            at = run.setdefault("positions", {}).get(params.get("pipetteId"), self.HOME)
            return "succeeded", {"position": dict(at)}, None
        elif command_type == "moveToCoordinates" and isinstance(params.get("coordinates"), dict):
            run.setdefault("positions", {})[params.get("pipetteId")] = {
                axis: float(params["coordinates"].get(axis, self.HOME[axis])) for axis in ("x", "y", "z")}
        elif command_type in ("liquidProbe", "tryLiquidProbe"):
            return "succeeded", {"z_position": 10.0}, None
        elif command_type and command_type.startswith("robot/move"):
            return "succeeded", {"position": dict(params.get("axis_map") or {})}, None
        return "succeeded", {}, None

    def _finds_a_tip(self, run: dict, params: dict) -> bool:
        """Whether the nozzles of a pickup come down on at least one tip: what a robot's sensor reads
        after it. PyLabRobot skips spots it knows are empty and sends an 8- or 96-channel pickup
        anyway, so this reading is what fails a pickup from a used column, as on hardware.

        Asked of PyLabRobot's own record of the rack, not kept here, so a rack swapped on the
        worktable is a full rack at once. Anything unknown finds a tip, and a partial column is read
        as its whole column, so this can pass a pickup the robot would fail, but never fails one the
        robot would pass."""
        name = run.get("labware", {}).get(params.get("labwareId"))
        well = params.get("wellName")
        if self.labware is None or not name or not well:
            return True
        try:
            rack = self.labware(name)
        except ResourceNotFoundError:
            return True
        pipette = run.get("pipettes", {}).get(params.get("pipetteId"))
        channels = self.PIPETTES.get(pipette, {}).get("channels")
        if channels == 1:
            spots = [rack.get_item(well)]
        elif channels == 8:
            spots = rack.column(int(well[1:]) - 1)
        elif channels == 96:
            spots = rack.get_all_items()
        else:
            return True
        return any(_holds_a_tip(spot) for spot in spots)


class SimulatedOT2Server(SimulatedFlexServer):
    """The robot-server of an OT-2 with these pipettes mounted ({"left": "p300_multi_gen2", "right":
    "p20_single_gen2"}): what the Flex's answers, plus the OT-2's own pipette query and homing. An
    OT-2 has no gripper, and its trash is fixed in slot 12."""

    PIPETTES = OT2_PIPETTES
    ROBOT_MODEL = "OT-2 Standard"
    LABEL = "Opentrons OT-2"
    HOME = {"x": 200.0, "y": 200.0, "z": 150.0}  # within both mounts' reach, as homing leaves it

    def __init__(self, mounts: Dict[str, str], delay_s: float = 0.0, name: str = "simulated-ot2",
                 labware: Optional[Callable[[str], Any]] = None):
        super().__init__(mounts, gripper=False, trash=None, delay_s=delay_s, name=name, labware=labware)

    async def request(self, method: str, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if method.upper() == "GET" and path == "/pipettes":
            return {mount: ({"name": name, "model": self.PIPETTES[name]["model"], "id": f"SIM-{mount}"}
                            if (name := self.mounts.get(mount)) else {}) for mount in ("left", "right")}
        if method.upper() == "POST" and path == "/robot/home":
            return {"message": "Homing robot."}
        return await super().request(method, path, data)
