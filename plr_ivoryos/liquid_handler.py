"""
plr_ivoryos.liquid_handler
===========================
IvoryOS-compatible proxy for a PyLabRobot LiquidHandler.

The user instantiates PLRLiquidHandler in their deck file — that's all they write.
On construction this class:

  1. Reads the loaded PLR deck to discover all Plate, TipRack and Well resources.
  2. Generates three Enum classes at runtime:
       PlateResource  — one member per Plate on the deck  (name → name)
       TipRackResource— one member per TipRack on the deck (name → name)
       WellPosition   — A1..H12 for standard 96-well plates
  3. Registers those Enums in plr4ivoryos._runtime_enums so that IvoryOS's
     form renderer can locate them via importlib (it resolves Enum types by
     module path).
  4. Calls lh.setup() on the shared background asyncio loop.

IvoryOS will introspect the LiquidHandler *instance* (not the class), so the
methods are defined on a per-instance dynamically-generated subclass that carries
the right Enum type annotations.  This makes IvoryOS render plate_name and
tip_rack_name as dropdowns populated from the actual loaded deck, while still
accepting a free-form str fallback.

Usage in a deck file
---------------------
    from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
    from pylabrobot.resources import Deck
    from plr_ivoryos import LiquidHandler

    deck = Deck.load_from_json_file("hamilton-layout.json")
    lh = LiquidHandler(
        backend=LiquidHandlerChatterboxBackend(),
        deck=deck,
    )

    if __name__ == "__main__":
        import ivoryos
        ivoryos.run(__name__)
"""


import types as _types
from enum import Enum
from typing import Optional, Union

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import LiquidHandlerBackend
from pylabrobot.resources import Deck, Plate, TipRack, Well, TipSpot

from plr_ivoryos import _runtime_enums
from plr_ivoryos.async_bridge import run_async


# ---------------------------------------------------------------------------
# JSON deck loader
# ---------------------------------------------------------------------------

def _resolve_plr_class(class_name: str):
    """
    Find a PLR resource or deck class by name, searching common submodules.
    Users write type names as strings in JSON (e.g. "Cor_96_wellplate_360ul_Fb")
    and this resolves them to the actual class.
    """
    import importlib
    search_modules = [
        "pylabrobot.resources",           # umbrella (__init__ re-exports all)
        "pylabrobot.resources.hamilton",   # Hamilton-specific extras
        "pylabrobot.resources.corning",
        "pylabrobot.resources.opentrons",
        "pylabrobot.resources.thermo_fisher",
        "pylabrobot.resources.greiner",
    ]
    for mod_path in search_modules:
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, class_name, None)
            if cls is not None:
                return cls
        except Exception:
            pass
    raise ValueError(
        f"PLR class '{class_name}' not found. "
        f"Check pylabrobot.resources for the exact name (e.g. 'Cor_96_wellplate_360ul_Fb')."
    )


def _load_deck_from_json(json_path: str) -> "Deck":
    """
    Build a PLR Deck from a simple layout JSON file.

    JSON format
    -----------
    {
      "deck_type": "STARLetDeck",
      "resources": [
        {
          "name": "source_plate",
          "type": "Cor_96_wellplate_360ul_Fb",
          "location": {"x": 100, "y": 0, "z": 0}
        },
        {
          "name": "htf_tips",
          "type": "hamilton_96_tiprack_1000uL_filter",
          "location": {"x": 100, "y": 200, "z": 0}
        }
      ]
    }

    ``deck_type`` defaults to ``STARLetDeck`` if omitted.
    ``location`` defaults to ``{x:0, y:0, z:0}`` if omitted.
    """
    import json
    from pylabrobot.resources.coordinate import Coordinate

    with open(json_path, encoding="utf-8") as f:
        config = json.load(f)

    deck_class = _resolve_plr_class(config.get("deck_type", "STARLetDeck"))
    deck = deck_class()

    def build_resource(resource_config: dict):
        res_class = _resolve_plr_class(resource_config["type"])
        resource = res_class(name=resource_config["name"])

        for child_config in resource_config.get("children", []):
            child = build_resource(child_config)
            site = child_config.get("site")
            if site is not None and hasattr(resource, "assign_resource_to_site"):
                resource.assign_resource_to_site(child, spot=site)
            else:
                child_loc = child_config.get("location", {})
                resource.assign_child_resource(
                    child,
                    location=Coordinate(
                        child_loc.get("x", 0),
                        child_loc.get("y", 0),
                        child_loc.get("z", 0),
                    ),
                )

        return resource

    for r in config.get("resources", []):
        loc = r.get("location", {})
        coord = Coordinate(
            loc.get("x", 0), loc.get("y", 0), loc.get("z", 0)
        )
        deck.assign_child_resource(build_resource(r), location=coord)

    return deck


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_well_position_enum() -> type:
    """Return WellPosition Enum covering A1..H12 (standard 96-well layout)."""
    members = {
        f"{row}{col}": f"{row}{col}"
        for row in "ABCDEFGH"
        for col in range(1, 13)
    }
    return Enum("WellPosition", members)  # type: ignore[return-value]


def _make_resource_name_enum(name: str, resource_names: list[str]) -> type:
    """
    Build an Enum whose members are the resource instance names on the deck.
    Falls back to a single placeholder member if the deck has no such resources
    (avoids an empty-Enum crash).
    """
    if not resource_names:
        resource_names = ["(none)"]
    members = {n: n for n in resource_names}
    return Enum(name, members)  # type: ignore[return-value]


def _build_deck_enums(lh: LiquidHandler):
    """
    Inspect the loaded deck and generate PlateResource, TipRackResource,
    WellPosition Enums.  Register them in _runtime_enums so IvoryOS can
    resolve them by importlib path.
    """
    all_resources = lh.deck.get_all_resources()

    plate_names = [r.name for r in all_resources if isinstance(r, Plate)]
    tip_rack_names = [r.name for r in all_resources if isinstance(r, TipRack)]

    PlateResourceEnum = _make_resource_name_enum("PlateResource", plate_names)
    TipRackResourceEnum = _make_resource_name_enum("TipRackResource", tip_rack_names)
    WellPositionEnum = _make_well_position_enum()

    _runtime_enums.register_enum("PlateResource", PlateResourceEnum)
    _runtime_enums.register_enum("TipRackResource", TipRackResourceEnum)
    _runtime_enums.register_enum("WellPosition", WellPositionEnum)

    return PlateResourceEnum, TipRackResourceEnum, WellPositionEnum


def _resolve_name(value) -> str:
    """Accept either an Enum member or a plain string; return the string value."""
    if isinstance(value, Enum):
        return value.value
    return str(value)


# ---------------------------------------------------------------------------
# Dynamic proxy class builder
# ---------------------------------------------------------------------------

def _build_proxy_class(
    lh: LiquidHandler,
    resource_map: dict,
    PlateResource,
    TipRackResource,
    WellPosition,
) -> type:
    """
    Construct a new class (unique per LiquidHandler instance) whose method
    signatures carry the runtime Enum types as annotations.

    Because the functions are defined inside this closure, their annotations
    reference the local Enum classes directly — inspect.signature() will
    return Union[PlateResource, str] with the *actual* Enum class object.
    IvoryOS's _is_enum_type() / _unwrap_enum_type() will find the Enum inside
    the Union and render a FlexibleEnumField dropdown.

    ⚠ Methods are SYNC (not async) on purpose.
    IvoryOS dispatches coroutines with asyncio.run(), which creates a fresh
    event loop — conflicting with the background loop that lh.setup() ran on.
    Keeping methods sync and routing PLR calls through run_async() ensures
    every PLR call goes to the correct persistent background loop.

    Multi-step operations (transfer, mix) compose a single inner coroutine and
    dispatch it once via run_async() — this keeps the whole sequence atomic on
    the background loop, preventing interleaving.
    """
    from plr_ivoryos.async_bridge import run_async

    # Known names for error messages
    _plate_names = list(PlateResource.__members__.keys())
    _rack_names  = list(TipRackResource.__members__.keys())
    _well_names  = list(WellPosition.__members__.keys())

    def _get_resource(container_name: str, position: str, container_type: str):
        """Resolve resource_map[name][pos] with a clear error on bad inputs."""
        known = _plate_names if container_type == "plate" else _rack_names
        if container_name not in resource_map:
            raise ValueError(
                f"Unknown {container_type} '{container_name}'. "
                f"Available: {known}"
            )
        try:
            return resource_map[container_name][position]
        except Exception:
            raise ValueError(
                f"Well/position '{position}' not found on '{container_name}'. "
                f"Valid positions: {_well_names[:6]} ... {_well_names[-3:]}"
            )

    def aspirate(
        self,
        plate_name: Union[PlateResource, str] = None,
        well: Union[WellPosition, str] = None,
        volume_ul: float = 100.0,
    ):
        """Aspirate liquid from a plate well.
        Requires a tip to be loaded first (call pick_up_tips)."""
        resource = _get_resource(_resolve_name(plate_name), _resolve_name(well), "plate")
        run_async(lh.aspirate(resource, vols=[volume_ul]))

    def dispense(
        self,
        plate_name: Union[PlateResource, str] = None,
        well: Union[WellPosition, str] = None,
        volume_ul: float = 100.0,
    ):
        """Dispense liquid into a plate well.
        Requires a tip to be loaded first (call pick_up_tips)."""
        resource = _get_resource(_resolve_name(plate_name), _resolve_name(well), "plate")
        run_async(lh.dispense(resource, vols=[volume_ul]))

    def pick_up_tips(
        self,
        tip_rack_name: Union[TipRackResource, str] = None,
        position: Union[WellPosition, str] = None,
    ):
        """Pick up a tip from a tip rack. Call before aspirate/dispense."""
        tip_spot = _get_resource(_resolve_name(tip_rack_name), _resolve_name(position), "rack")
        run_async(lh.pick_up_tips(tip_spot))

    def drop_tips(
        self,
        tip_rack_name: Union[TipRackResource, str] = None,
        position: Union[WellPosition, str] = None,
    ):
        """Drop tips back to a specific tip rack position."""
        tip_spot = _get_resource(_resolve_name(tip_rack_name), _resolve_name(position), "rack")
        run_async(lh.drop_tips(tip_spot))

    def return_tips(self):
        """Return all currently held tips to their original positions."""
        run_async(lh.return_tips())

    def discard_tips(self):
        """Permanently discard all currently held tips to the trash."""
        run_async(lh.discard_tips())

    def transfer(
        self,
        source_plate: Union[PlateResource, str] = None,
        source_well: Union[WellPosition, str] = None,
        dest_plate: Union[PlateResource, str] = None,
        dest_well: Union[WellPosition, str] = None,
        tip_rack_name: Union[TipRackResource, str] = None,
        tip_position: Union[WellPosition, str] = None,
        volume_ul: float = 100.0,
    ):
        """
        High-level transfer: pick up tip → aspirate → dispense → return tip.
        All in one step. Runs as a single atomic coroutine on the background loop.
        """
        src_plate = _resolve_name(source_plate)
        src_well  = _resolve_name(source_well)
        dst_plate = _resolve_name(dest_plate)
        dst_well  = _resolve_name(dest_well)
        rack      = _resolve_name(tip_rack_name)
        tip_pos   = _resolve_name(tip_position)

        async def _transfer():
            await lh.pick_up_tips(resource_map[rack][tip_pos])
            await lh.aspirate(resource_map[src_plate][src_well], vols=[volume_ul])
            await lh.dispense(resource_map[dst_plate][dst_well], vols=[volume_ul])
            await lh.return_tips()

        run_async(_transfer())

    def mix(
        self,
        plate_name: Union[PlateResource, str] = None,
        well: Union[WellPosition, str] = None,
        volume_ul: float = 50.0,
        repetitions: int = 3,
    ):
        """Mix liquid in a well by repeatedly aspirating and dispensing."""
        plate    = _resolve_name(plate_name)
        pos      = _resolve_name(well)
        resource = resource_map[plate][pos]

        async def _mix():
            for _ in range(repetitions):
                await lh.aspirate(resource, vols=[volume_ul])
                await lh.dispense(resource, vols=[volume_ul])

        run_async(_mix())

    def summary(self) -> str:
        """Return a text summary of the current deck layout."""
        return lh.deck.summary()

    def start_visualizer(
        self,
        host: str = "127.0.0.1",
        ws_port: int = 2121,
        fs_port: int = 1337,
        open_browser: bool = True,
        name: str = None,
        favicon: str = None,
        liquid_color: str = "F39C12",
    ) -> str:
        """Start PyLabRobot's browser visualizer for the current deck."""
        from pylabrobot.resources.tip_tracker import set_tip_tracking
        from pylabrobot.resources.volume_tracker import set_volume_tracking
        from pylabrobot.visualizer import Visualizer

        # set_tip_tracking(True)
        # set_volume_tracking(True)

        if favicon == "":
            favicon = None

        visualizer = Visualizer(
            lh.deck,
            host=host,
            ws_port=ws_port,
            fs_port=fs_port,
            open_browser=open_browser,
            name=name,
            favicon=favicon,
            liquid_color=liquid_color,
        )
        run_async(visualizer.setup())
        self._visualizer = visualizer
        return f"http://{visualizer.host}:{visualizer.fs_port}"

    # Build the class dynamically — each instance gets its own class so
    # the annotations embed *this* deck's Enum classes, not a shared global.
    ProxyClass = type(
        "LiquidHandlerProxy",
        (),
        {
            "aspirate": aspirate,
            "dispense": dispense,
            "pick_up_tips": pick_up_tips,
            "drop_tips": drop_tips,
            "return_tips": return_tips,
            "discard_tips": discard_tips,
            "transfer": transfer,
            "mix": mix,
            "summary": summary,
            "start_visualizer": start_visualizer,
        },
    )
    return ProxyClass


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class LiquidHandler:
    """
    IvoryOS-compatible liquid handler backed by PyLabRobot.

    Drop this into your deck file instead of a raw PLR LiquidHandler.
    IvoryOS will see it as a normal device and render dropdown forms
    for plate_name (from the actual plates on your deck) and well (A1..H12).

    Parameters
    ----------
    backend : LiquidHandlerBackend, optional
        Any PLR backend — STARBackend, OpentronsOT2Backend, EVOBackend,
        or LiquidHandlerChatterboxBackend for simulation.
    deck : Deck, optional
        A pre-built PLR Deck.  Mutually exclusive with *deck_json*.
    deck_json : str, optional
        Path to a layout JSON file.  Mutually exclusive with *deck*.
        When provided the deck is built internally.
    simulated : bool
        If True, use LiquidHandlerChatterboxBackend and a default STARLet deck
        if no other backend/deck is provided.

    Layout JSON format
    ------------------
    {
      "deck_type": "STARLetDeck",
      "resources": [
        {"name": "source_plate", "type": "Cor_96_wellplate_360ul_Fb",
         "location": {"x": 100, "y": 0, "z": 0}},
        {"name": "htf_tips",    "type": "hamilton_96_tiprack_1000uL_filter",
         "location": {"x": 100, "y": 200, "z": 0}}
      ]
    }
    """

    def __new__(cls, backend: LiquidHandlerBackend = None,
                deck: Deck = None, deck_json: str = None,
                simulated: bool = False, **kwargs):
        if simulated:
            from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
            backend = backend or LiquidHandlerChatterboxBackend()
            if deck is None and deck_json is None:
                from pylabrobot.resources.hamilton import STARLetDeck
                from pylabrobot.resources.corning.plates import Cor_96_wellplate_360ul_Fb
                from pylabrobot.resources.hamilton import hamilton_96_tiprack_1000uL_filter
                from pylabrobot.resources.coordinate import Coordinate
                deck = STARLetDeck()
                deck.assign_child_resource(Cor_96_wellplate_360ul_Fb(name="sim_plate"),
                                            location=Coordinate(100, 100, 0))
                deck.assign_child_resource(hamilton_96_tiprack_1000uL_filter(name="sim_tips"),
                                            location=Coordinate(300, 100, 0))

        if deck is None and deck_json is not None:
            deck = _load_deck_from_json(deck_json)
        elif deck is None:
            raise ValueError("Provide either 'deck', 'deck_json', or 'simulated=True'.")

        if backend is None:
            raise ValueError("Provide a 'backend' or set 'simulated=True'.")

        # Build the underlying PLR LiquidHandler
        from pylabrobot.liquid_handling import LiquidHandler as _LiquidHandler
        _lh = _LiquidHandler(backend=backend, deck=deck, **kwargs)

        # Call setup() on the shared background loop
        run_async(_lh.setup())

        # Build resource map: {resource_name: ItemizedResource}
        resource_map = {
            r.name: r
            for r in _lh.deck.get_all_resources()
        }

        # Generate Enums from the loaded deck and register them
        PlateEnum, TipRackEnum, WellEnum = _build_deck_enums(_lh)

        # Create a proxy class whose method signatures embed these Enums
        ProxyClass = _build_proxy_class(_lh, resource_map, PlateEnum, TipRackEnum, WellEnum)

        # Instantiate the proxy — this is what IvoryOS will introspect
        instance = object.__new__(ProxyClass)
        instance._lh = _lh
        instance._resource_map = resource_map
        return instance

    def __init__(self, backend, deck=None, deck_json=None, **kwargs):
        # __init__ is called on the ProxyClass instance; nothing to do here
        # because __new__ already set everything up.
        pass
