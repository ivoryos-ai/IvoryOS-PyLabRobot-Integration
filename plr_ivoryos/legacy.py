"""Liquid handlers PyLabRobot 1.0.0b1 drives only through `pylabrobot.legacy`: the Hamilton Nimbus,
the Hamilton Vantage and the Tecan Freedom EVO, and any other legacy backend.

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
    """

    # Any worktable but the Flex's (PyLabRobot's legacy front end has no Flex backend); a STARlet by
    # default, as PyLabRobot's own examples simulate.
    KINDS = ["STARLetDeck"] + [kind for kind in worktable.DECKS if kind not in ("FlexDeck", "STARLetDeck")]

    def __init__(self, backend=None, simulated: bool = False, channels: int = 8, worktable: Optional[str] = None,
                 deck_type: Optional[str] = None, step_delay_s: float = 0.0, tracking: bool = True):
        if backend is None and not simulated:
            raise ValueError("Give a pylabrobot.legacy backend, or simulated=True.")
        if backend is not None and simulated:
            raise ValueError("simulated=True runs no robot, so a backend beside it would be ignored.")
        super().__init__(worktable, deck_type, simulated, step_delay_s, tracking)
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
                 worktable: Optional[str] = None, channels: int = 8, step_delay_s: float = 0.0, tracking: bool = True):
        backend = None
        if host and not simulated:
            from pylabrobot.legacy.liquid_handling.backends.hamilton.nimbus_backend import NimbusBackend
            backend = NimbusBackend(host=host, port=port)
        elif not simulated:
            raise ValueError("Give the Nimbus's host, or simulated=True.")
        elif host:
            raise ValueError("simulated=True runs no robot, so a host beside it would be ignored.")
        super().__init__(backend, simulated, channels, worktable, "NimbusDeck", step_delay_s, tracking)


class Vantage(LiquidHandler):
    """A Hamilton Vantage, 1.3 m deck (PyLabRobot: legacy VantageBackend, over USB)."""

    KINDS = ["VantageDeck"]

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, device_address: Optional[int] = None,
                 serial_number: Optional[str] = None, channels: int = 8, step_delay_s: float = 0.0,
                 tracking: bool = True):
        backend = None
        if not simulated:
            from pylabrobot.legacy.liquid_handling.backends import VantageBackend
            backend = VantageBackend(device_address=device_address, serial_number=serial_number)
        super().__init__(backend, simulated, channels, worktable, "VantageDeck", step_delay_s, tracking)


class EVO(LiquidHandler):
    """A Tecan Freedom EVO 100, 150 or 200 (PyLabRobot: legacy EVOBackend, over USB).

    PyLabRobot 1.0.0b1 cannot make a Tecan tip rack yet (its tip diameters are not measured), so
    disposable tips cannot be put on an EVO worktable until it can."""

    KINDS = ["EVO150Deck", "EVO100Deck", "EVO200Deck"]

    def __init__(self, simulated: bool = False, worktable: Optional[str] = None, deck_type: Optional[str] = None,
                 diti_count: int = 0, channels: int = 8, step_delay_s: float = 0.0, tracking: bool = True):
        backend = None
        if not simulated:
            from pylabrobot.legacy.liquid_handling.backends import EVOBackend
            backend = EVOBackend(diti_count=diti_count)
        super().__init__(backend, simulated, channels, worktable, deck_type, step_delay_s, tracking)


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
