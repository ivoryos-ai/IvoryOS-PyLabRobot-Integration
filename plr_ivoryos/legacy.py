"""What PyLabRobot 1.0.0b1 drives only through `pylabrobot.legacy`: the Hamilton Nimbus, the
Hamilton Vantage and the Tecan Freedom EVO, and any other legacy liquid handler backend; and the
devices PyLabRobot 1.0 has not yet given a class of their own (further down): plate readers (BMG
CLARIOstar, Tecan Spark and Infinite 200 PRO, SpectraMax Gemini EM), thermocyclers (Inheco ODTC,
Opentrons, Thermo Fisher ProFlex and ATC), the Hamilton heater-shaker and HEPA fan, and PyLabRobot's
generic Scale, Pump, Centrifuge, HeaterShaker, Thermocycler, Fan and PlateReader with any legacy
backend.

    from plr_ivoryos.legacy import Nimbus, Vantage, EVO, LiquidHandler
    nimbus = Nimbus(simulated=True)                    # PyLabRobot's legacy simulator
    nimbus = Nimbus(host="192.168.100.100")            # a real Nimbus over TCP
    vantage = Vantage(simulated=True)
    evo = EVO(simulated=True, deck_type="EVO150Deck")
    lh = LiquidHandler(backend=SomeLegacyBackend(...), deck_type="NimbusDeck")   # any legacy backend

PyLabRobot 1.0 keeps its older `LiquidHandler` front end, with a backend per robot, as
`pylabrobot.legacy.liquid_handling`, for the robots it has not yet given a class of their own. It is
one object with every operation on it (pick_up_tips, aspirate, dispense, pick_up_tips96, move_plate,
...), so here it is one instrument with those steps, PyLabRobot's names and arguments, and the same
worktable file, Labware view and wells-as-text as every other robot in this package. When PyLabRobot
gives one of these robots a 1.0 class, it moves to a module of its own (as the STAR has).

`simulated=True` is PyLabRobot's `LiquidHandlerChatterboxBackend`: the legacy front end's own tip and
volume tracking and checks, with a backend that accepts every command. It knows nothing of the
robot's firmware: what passes here has been checked against PyLabRobot, not against the robot.
"""

from typing import Any, Dict, List, Optional

from pylabrobot.legacy.liquid_handling import LiquidHandler as PLRLiquidHandler
from pylabrobot.legacy.liquid_handling.backends import LiquidHandlerChatterboxBackend

from plr_ivoryos import bridge, worktable
from plr_ivoryos.async_bridge import run_async
from plr_ivoryos.robot import WorktableRobot
from plr_ivoryos.wells import Labware, Site


# What the liquid ledger (liquids.py) calls this robot's channels.
HEAD = "head"


class LiquidHandler(WorktableRobot):
    """PyLabRobot's legacy LiquidHandler with any legacy backend, as one IvoryOS instrument.

    backend        a pylabrobot.legacy backend (NimbusBackend, VantageBackend, EVOBackend, ...)
    simulated      PyLabRobot's LiquidHandlerChatterboxBackend instead of a backend
    channels       how many channels the simulated robot has (default 8)
    worktable      the worktable file (worktable.py); optional, worktable.json in the deck's data folder
    deck_type      which worktable a new file is (one of KINDS)
    step_delay_s   a pause after each step, simulated only
    tracking       PyLabRobot's tip and volume tracking
    layouts_folder where layouts saved by name are kept; optional, worktable.layouts beside the
                   worktable file (see Flex)
    """

    # Any worktable but the Flex's (PyLabRobot's legacy front end has no Flex backend); a STARlet by
    # default, as PyLabRobot's own examples simulate.
    KINDS = ["STARLetDeck"] + [kind for kind in worktable.DECKS if kind not in ("FlexDeck", "STARLetDeck")]

    def __init__(self, backend=None, simulated: bool = False, channels: int = 8, worktable: Optional[str] = None,
                 deck_type: Optional[str] = None, step_delay_s: float = 0.0, tracking: bool = True,
                 layouts_folder: Optional[str] = None):
        if backend is None and not simulated:
            raise ValueError("Give a pylabrobot.legacy backend, or simulated=True.")
        if backend is not None and simulated:
            raise ValueError("simulated=True runs no robot, so a backend beside it would be ignored.")
        super().__init__(worktable, deck_type, simulated, step_delay_s, tracking, layouts_folder)
        self._channels = int(channels)
        self._backend = backend
        self._plr = self._make_plr()
        self._after_init()

    def _make_plr(self) -> PLRLiquidHandler:
        backend = LiquidHandlerChatterboxBackend(num_channels=self._channels) if self._simulated else self._backend
        return PLRLiquidHandler(backend=backend, deck=self.deck)

    async def _connect(self) -> None:
        await self._plr.setup()

    async def _disconnect(self) -> None:
        await self._plr.stop()

    def _plr_target(self):
        return self._plr

    def _run_step(self, name: str, given: Dict[str, Any], extra: Dict[str, Any], params: Dict[str, bridge.Param]):
        # Every step works with the one set of channels, so liquids follow the tips across steps.
        return self._execute(HEAD, self._plr_target, name, given, extra, params)

    def _attach_deck(self, deck) -> None:
        self._plr = self._make_plr()

    def _tip_count(self, part: Optional[str]) -> int:
        return sum(self._channels_state()) + self._head96_tips()

    def _any_tips(self) -> bool:
        return self._tip_count(None) > 0

    def _head96_tips(self) -> int:
        head96 = getattr(self._plr, "head96", None) or {}
        return sum(1 for tracker in head96.values() if tracker.has_tip)

    def _channels_state(self) -> List[bool]:
        head = getattr(self._plr, "head", None) or {}
        return [head[channel].has_tip for channel in sorted(head)]

    def setup(self) -> None:
        """Connect and set up the robot. Any other step does this itself the first time.
        (PyLabRobot: LiquidHandler.setup)"""
        run_async(self._setup())

    def stop(self) -> None:
        """Put the robot down. The next step sets it up again. (PyLabRobot: LiquidHandler.stop)"""
        if self._ready:
            run_async(self._disconnect())
            self._ready = False


class Nimbus(LiquidHandler):
    """A Hamilton Nimbus (PyLabRobot: legacy NimbusBackend, over TCP)."""

    KINDS = ["NimbusDeck"]

    def __init__(self, host: Optional[str] = None, port: int = 2000, simulated: bool = False,
                 worktable: Optional[str] = None, channels: int = 8, step_delay_s: float = 0.0, tracking: bool = True,
                 layouts_folder: Optional[str] = None):
        backend = None
        if host and not simulated:
            from pylabrobot.legacy.liquid_handling.backends.hamilton.nimbus_backend import NimbusBackend
            backend = NimbusBackend(host=host, port=port)
        elif not simulated:
            raise ValueError("Give the Nimbus's host, or simulated=True.")
        elif host:
            raise ValueError("simulated=True runs no robot, so a host beside it would be ignored.")
        super().__init__(backend, simulated, channels, worktable, "NimbusDeck", step_delay_s, tracking, layouts_folder)


class Vantage(LiquidHandler):
    """A Hamilton Vantage, 1.3 m deck (PyLabRobot: legacy VantageBackend, over USB)."""

    KINDS = ["VantageDeck"]

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, device_address: Optional[int] = None,
                 serial_number: Optional[str] = None, channels: int = 8, step_delay_s: float = 0.0,
                 tracking: bool = True, layouts_folder: Optional[str] = None):
        backend = None
        if not simulated:
            from pylabrobot.legacy.liquid_handling.backends import VantageBackend
            backend = VantageBackend(device_address=device_address, serial_number=serial_number)
        super().__init__(backend, simulated, channels, worktable, "VantageDeck", step_delay_s, tracking, layouts_folder)


class EVO(LiquidHandler):
    """A Tecan Freedom EVO 100, 150 or 200 (PyLabRobot: legacy EVOBackend, over USB).

    PyLabRobot 1.0.0b1 cannot make a Tecan tip rack yet (its tip diameters are not measured), so
    disposable tips cannot be put on an EVO worktable until it can."""

    KINDS = ["EVO150Deck", "EVO100Deck", "EVO200Deck"]

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, deck_type: Optional[str] = None,
                 diti_count: int = 0, channels: int = 8, step_delay_s: float = 0.0, tracking: bool = True,
                 layouts_folder: Optional[str] = None):
        backend = None
        if not simulated:
            from pylabrobot.legacy.liquid_handling.backends import EVOBackend
            backend = EVOBackend(diti_count=diti_count)
        super().__init__(backend, simulated, channels, worktable, deck_type, step_delay_s, tracking, layouts_folder)


# Labware a step moves, and where to.
_MOVABLE = Labware("plate", "reservoir", "tip_rack", "tube_rack")
_MOVES = {"move_plate": {"plate": _MOVABLE, "to": Site()},
          "move_resource": {"resource": _MOVABLE, "to": Site()},
          "move_lid": {"to": Site()},
          "pick_up_resource": {"resource": _MOVABLE},
          "drop_resource": {"destination": Site()}}

# PyLabRobot's methods, as steps; what is left out, and why. Setup and stop are above; the session,
# the backend and the deck object are not a step's business.
SKIPPED: Dict[str, Dict[str, str]] = {
    "LiquidHandler": bridge.add_steps(LiquidHandler, PLRLiquidHandler, "LiquidHandler", exclude=(
        "setup", "stop", "serialize", "deserialize", "load", "save", "update_head_state", "update_head96_state",
        "clear_head_state", "clear_head96_state", "register_default_tip_rack", "set_deck",
        "use_channels", "use_tips"),  # context managers, for a `with` block in code
        markers=_MOVES),
}


# --- devices: PyLabRobot's legacy front ends, and the backends PyLabRobot 1.0 has no class for ---------
#
# Each generic class below is PyLabRobot's legacy front end (pylabrobot.legacy.scales.Scale, ...)
# with any legacy backend, or `simulated=True` for PyLabRobot's own legacy simulator (its
# "chatterbox" backend), and the front end's methods as steps: what PyLabRobot's legacy front end
# adds (a shake for a duration, waiting for a temperature, a PCR profile) runs as PyLabRobot wrote it,
# in simulation too. Each named device is one of them with its backend made from plain arguments.
#
# A plate reader is the exception: PyLabRobot's legacy PlateReader reads only a plate placed in it,
# as a child resource, which a plate on a liquid handler's worktable is not. Its backend, though,
# takes the plate and wells to read, as PyLabRobot 1.0's reader classes do, so a legacy reader's
# steps are its backend's methods, with `plate` and `wells` named on the worktable (device.Reader),
# and `simulated=True` is this package's simulated reader, whose readings follow the liquids.

from pylabrobot.legacy.centrifuge import Centrifuge as PLRCentrifuge
from pylabrobot.legacy.centrifuge.chatterbox import CentrifugeChatterboxBackend
from pylabrobot.legacy.heating_shaking import HeaterShaker as PLRHeaterShaker
from pylabrobot.legacy.heating_shaking import HeaterShakerChatterboxBackend
from pylabrobot.legacy.only_fans import Fan as PLRFan
from pylabrobot.legacy.only_fans.chatterbox import FanChatterboxBackend
from pylabrobot.legacy.plate_reading import (CLARIOstarBackend, ExperimentalSparkBackend,
                                             ExperimentalTecanInfinite200ProBackend,
                                             MolecularDevicesSpectraMaxGeminiEMBackend)
from pylabrobot.legacy.plate_reading.backend import PlateReaderBackend
from pylabrobot.legacy.pumps import Pump as PLRPump
from pylabrobot.legacy.pumps.chatterbox import PumpChatterboxBackend
from pylabrobot.legacy.scales import Scale as PLRScale
from pylabrobot.legacy.scales import ScaleChatterboxBackend
from pylabrobot.legacy.thermocycling import Thermocycler as PLRThermocycler
from pylabrobot.legacy.thermocycling import ThermocyclerChatterboxBackend
from pylabrobot.resources import Coordinate

from plr_ivoryos.device import Device, Reader, device_steps
from plr_ivoryos.simulators import SimulatedPlateReader


class _Machine(Device):
    """A PyLabRobot legacy front end with a backend, or with PyLabRobot's simulator for it."""

    def __init__(self, backend=None, simulated: bool = False, step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s)
        if backend is None and not simulated:
            raise ValueError("Give a pylabrobot.legacy backend, or simulated=True.")
        if backend is not None and simulated:
            raise ValueError("simulated=True runs no device, so a backend beside it would be ignored.")
        self._backend = self._simulator() if self._simulated else backend
        self._plr = self._front(self._backend)

    def _simulator(self):
        raise NotImplementedError

    def _front(self, backend):
        raise NotImplementedError


class Scale(_Machine):
    """PyLabRobot's legacy Scale with any legacy scale backend; simulated: ScaleChatterboxBackend."""

    def _simulator(self):
        return ScaleChatterboxBackend()

    def _front(self, backend):
        return PLRScale(name="scale", size_x=0, size_y=0, size_z=0, backend=backend)


class Pump(_Machine):
    """PyLabRobot's legacy Pump with any legacy pump backend; simulated: PumpChatterboxBackend. A
    volume (pump_volume) needs the pump's calibration, which PyLabRobot keeps on the front end."""

    def _simulator(self):
        return PumpChatterboxBackend()

    def _front(self, backend):
        return PLRPump(backend=backend)


class _CentrifugeChatterbox(CentrifugeChatterboxBackend):
    """PyLabRobot's centrifuge simulator, taking a spin as its front end asks for one: the front end
    passes no acceleration unless given, and the simulator requires one (PyLabRobot 1.0.0b1)."""

    async def spin(self, g: float, duration: float, acceleration: float = 0.8, **kwargs):
        await super().spin(g, duration, acceleration)


class Centrifuge(_Machine):
    """PyLabRobot's legacy Centrifuge with any legacy centrifuge backend; simulated:
    CentrifugeChatterboxBackend. (The Agilent VSpin has a PyLabRobot 1.0 class: agilent.VSpin.)"""

    def _simulator(self):
        return _CentrifugeChatterbox()

    def _front(self, backend):
        return PLRCentrifuge(backend=backend, name="centrifuge", size_x=0, size_y=0, size_z=0)


class Fan(_Machine):
    """PyLabRobot's legacy Fan with any legacy fan backend; simulated: FanChatterboxBackend."""

    def _simulator(self):
        return FanChatterboxBackend()

    def _front(self, backend):
        return PLRFan(backend=backend)


class HeaterShaker(_Machine):
    """PyLabRobot's legacy HeaterShaker with any legacy heater-shaker backend; simulated:
    HeaterShakerChatterboxBackend, which reaches its temperature at once."""

    def _simulator(self):
        return HeaterShakerChatterboxBackend()

    def _front(self, backend):
        return PLRHeaterShaker(name="heater_shaker", size_x=0, size_y=0, size_z=0, backend=backend,
                               child_location=Coordinate.zero())


class Thermocycler(_Machine):
    """PyLabRobot's legacy Thermocycler with any legacy thermocycler backend; simulated:
    ThermocyclerChatterboxBackend, which reaches its temperatures at once.

    zones        how many temperature zones the simulated block has (temperatures are lists, one
                 value per zone)
    """

    def __init__(self, backend=None, simulated: bool = False, zones: int = 1, step_delay_s: float = 0.0):
        self._zones = int(zones)
        super().__init__(backend, simulated, step_delay_s)

    def _simulator(self):
        return ThermocyclerChatterboxBackend(num_zones=self._zones)

    def _front(self, backend):
        return PLRThermocycler(name="thermocycler", size_x=0, size_y=0, size_z=0, backend=backend,
                               child_location=Coordinate.zero())


class HamiltonHepaFan(Fan):
    """A Hamilton HEPA fan over FTDI (PyLabRobot: legacy HamiltonHepaFanBackend).

    device_id    the FTDI serial number; optional when there is one fan
    """

    def __init__(self, device_id: Optional[str] = None, simulated: bool = False, step_delay_s: float = 0.0):
        backend = None
        if not simulated:
            from pylabrobot.legacy.only_fans import HamiltonHepaFanBackend
            backend = HamiltonHepaFanBackend(device_id=device_id)
        super().__init__(backend, simulated, step_delay_s)


class HamiltonHeaterShaker(HeaterShaker):
    """A Hamilton Heater Shaker on its USB control box (PyLabRobot: legacy HamiltonHeaterShakerBackend
    with HamiltonHeaterShakerBox).

    index          which heater-shaker on the box (0, 1, ...)
    device_address the box's USB address; optional when there is one box
    serial_number  the box's serial number; optional
    """

    def __init__(self, index: int = 0, device_address: Optional[int] = None, serial_number: Optional[str] = None,
                 simulated: bool = False, step_delay_s: float = 0.0):
        backend = None
        self._box = None
        if not simulated:
            from pylabrobot.legacy.heating_shaking import HamiltonHeaterShakerBackend, HamiltonHeaterShakerBox
            self._box = HamiltonHeaterShakerBox(device_address=device_address, serial_number=serial_number)
            backend = HamiltonHeaterShakerBackend(index=int(index), interface=self._box)
        super().__init__(backend, simulated, step_delay_s)

    async def _connect(self) -> None:
        if self._box is not None:
            await self._box.setup()
        await super()._connect()

    async def _disconnect(self) -> None:
        await super()._disconnect()
        if self._box is not None:
            await self._box.stop()


class InhecoODTC(Thermocycler):
    """An Inheco ODTC over the network, by SiLA (PyLabRobot: legacy ExperimentalODTCBackend, marked
    experimental by PyLabRobot).

    ip           the ODTC's address
    client_ip    this computer's address the ODTC answers to; optional
    """

    def __init__(self, ip: Optional[str] = None, client_ip: Optional[str] = None, simulated: bool = False,
                 step_delay_s: float = 0.0):
        backend = None
        if not simulated:
            if not ip:
                raise ValueError("Give the ODTC's ip, or simulated=True.")
            from pylabrobot.legacy.thermocycling.inheco import ExperimentalODTCBackend
            backend = ExperimentalODTCBackend(ip=ip, client_ip=client_ip)
        super().__init__(backend, simulated, 1, step_delay_s)


class OpentronsThermocycler(Thermocycler):
    """An Opentrons Thermocycler (GEN1/GEN2), by the OT-2 it is plugged into (PyLabRobot: legacy
    OpentronsThermocyclerBackend, over the OT-2's HTTP API; needs plr-ivoryos[opentrons]) or straight
    over USB (OpentronsThermocyclerUSBBackend).

    opentrons_id the module's id on its OT-2 (the HTTP API's module list)
    usb          drive it over USB instead
    """

    def __init__(self, opentrons_id: Optional[str] = None, usb: bool = False, simulated: bool = False,
                 step_delay_s: float = 0.0):
        backend = None
        if not simulated:
            if usb:
                from pylabrobot.legacy.thermocycling.opentrons_backend_usb import OpentronsThermocyclerUSBBackend
                backend = OpentronsThermocyclerUSBBackend()
            elif opentrons_id:
                from pylabrobot.legacy.thermocycling import OpentronsThermocyclerBackend
                backend = OpentronsThermocyclerBackend(opentrons_id=opentrons_id)
            else:
                raise ValueError("Give the module's opentrons_id, or usb=True, or simulated=True.")
        super().__init__(backend, simulated, 1, step_delay_s)


class _ThermoFisher(Thermocycler):
    _BACKEND = ""

    def __init__(self, ip: Optional[str] = None, use_ssl: bool = False, serial_number: Optional[str] = None,
                 port: Optional[int] = None, simulated: bool = False, zones: int = 1, step_delay_s: float = 0.0):
        backend = None
        if not simulated:
            if not ip:
                raise ValueError("Give the thermocycler's ip, or simulated=True.")
            from pylabrobot.legacy.thermocycling import thermo_fisher
            backend = getattr(thermo_fisher, self._BACKEND)(ip=ip, use_ssl=use_ssl, serial_number=serial_number,
                                                            port=port)
        super().__init__(backend, simulated, zones, step_delay_s)


class ProFlex(_ThermoFisher):
    """A Thermo Fisher ProFlex PCR system over the network (PyLabRobot: legacy ProflexBackend).

    ip, port, use_ssl, serial_number   how to reach it
    zones        simulated only: how many zones the simulated block has
    """
    _BACKEND = "ProflexBackend"


class ATC(_ThermoFisher):
    """A Thermo Fisher Automated Thermal Cycler over the network (PyLabRobot: legacy ATCBackend).

    ip, port, use_ssl, serial_number   how to reach it
    zones        simulated only: how many zones the simulated block has
    """
    _BACKEND = "ATCBackend"


class PlateReader(Reader):
    """Any PyLabRobot legacy plate reader backend, its plate and wells named on a liquid handler's
    worktable (device.Reader); simulated: this package's simulated reader.

    backend      a pylabrobot.legacy plate reader backend
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    _BACKEND: type = PlateReaderBackend

    def __init__(self, backend=None, simulated: bool = False, worktable: Optional[str] = None,
                 plate_type: str = worktable._PLATE, signal_liquids: str = "dye", step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s, worktable, plate_type, signal_liquids)
        if backend is None and not simulated:
            raise ValueError("Give a pylabrobot.legacy plate reader backend, or simulated=True.")
        if backend is not None and simulated:
            raise ValueError("simulated=True runs no reader, so a backend beside it would be ignored.")
        self._plr = SimulatedPlateReader(self._BACKEND, self) if self._simulated else backend


class CLARIOstar(PlateReader):
    """A BMG Labtech CLARIOstar over FTDI (PyLabRobot: legacy CLARIOstarBackend).

    device_id    the FTDI serial number; optional when there is one reader
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    _BACKEND = CLARIOstarBackend

    def __init__(self, device_id: Optional[str] = None, simulated: bool = False, worktable: Optional[str] = None,
                 plate_type: str = worktable._PLATE, signal_liquids: str = "dye", step_delay_s: float = 0.0):
        backend = None if simulated else CLARIOstarBackend(device_id=device_id)
        super().__init__(backend, simulated, worktable, plate_type, signal_liquids, step_delay_s)


class TecanSpark(PlateReader):
    """A Tecan Spark over USB (PyLabRobot: legacy ExperimentalSparkBackend, marked experimental by
    PyLabRobot).

    vid          its USB vendor id
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    _BACKEND = ExperimentalSparkBackend

    def __init__(self, vid: int = 3143, simulated: bool = False, worktable: Optional[str] = None,
                 plate_type: str = worktable._PLATE, signal_liquids: str = "dye", step_delay_s: float = 0.0):
        backend = None if simulated else ExperimentalSparkBackend(vid=vid)
        super().__init__(backend, simulated, worktable, plate_type, signal_liquids, step_delay_s)


class TecanInfinite200Pro(PlateReader):
    """A Tecan Infinite 200 PRO over USB (PyLabRobot: legacy ExperimentalTecanInfinite200ProBackend,
    marked experimental by PyLabRobot).

    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    _BACKEND = ExperimentalTecanInfinite200ProBackend

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, plate_type: str = worktable._PLATE,
                 signal_liquids: str = "dye", step_delay_s: float = 0.0):
        backend = None if simulated else ExperimentalTecanInfinite200ProBackend()
        super().__init__(backend, simulated, worktable, plate_type, signal_liquids, step_delay_s)


class SpectraMaxGeminiEM(PlateReader):
    """A Molecular Devices SpectraMax Gemini EM fluorescence reader over serial (PyLabRobot: legacy
    MolecularDevicesSpectraMaxGeminiEMBackend).

    port         the serial port
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    _BACKEND = MolecularDevicesSpectraMaxGeminiEMBackend

    def __init__(self, port: Optional[str] = None, simulated: bool = False, worktable: Optional[str] = None,
                 plate_type: str = worktable._PLATE, signal_liquids: str = "dye", step_delay_s: float = 0.0):
        backend = None
        if not simulated:
            if not port:
                raise ValueError("Give the reader's serial port, or simulated=True.")
            backend = MolecularDevicesSpectraMaxGeminiEMBackend(port=port)
        super().__init__(backend, simulated, worktable, plate_type, signal_liquids, step_delay_s)


# The legacy front ends' "**backend_kwargs" are offered as name/value rows; the resource tree
# (a Scale or a Thermocycler is a PyLabRobot resource) is not a step.
SKIPPED.update({
    "Scale": device_steps(Scale, PLRScale, exclude=("get_weight",)),  # read_weight is the same call
    "Pump": device_steps(Pump, PLRPump),
    "Centrifuge": device_steps(Centrifuge, PLRCentrifuge),
    "Fan": device_steps(Fan, PLRFan),
    "HeaterShaker": device_steps(HeaterShaker, PLRHeaterShaker),
    "Thermocycler": device_steps(Thermocycler, PLRThermocycler),
    "PlateReader": device_steps(PlateReader, PlateReaderBackend),
    "CLARIOstar": device_steps(CLARIOstar, CLARIOstarBackend, exclude=("read_command_status", "initialize")),
    "TecanSpark": device_steps(TecanSpark, ExperimentalSparkBackend),
    "TecanInfinite200Pro": device_steps(TecanInfinite200Pro, ExperimentalTecanInfinite200ProBackend),
    "SpectraMaxGeminiEM": device_steps(SpectraMaxGeminiEM, MolecularDevicesSpectraMaxGeminiEMBackend),
})
