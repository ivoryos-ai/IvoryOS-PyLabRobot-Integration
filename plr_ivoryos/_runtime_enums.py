"""
plr_ivoryos — runtime Enum registry
====================================
This module is a stable, importable home for Enum classes that are generated
dynamically from a PyLabRobot deck at startup.

IvoryOS resolves saved Enum types via importlib.import_module(module_name),
so the Enums must live at a known module path.  The liquid_handler module
populates this module at deck-load time by calling register_enum().

Do NOT import symbols from here directly in user code — use the PLRLiquidHandler
class instead.  These Enums are accessed by IvoryOS's form renderer via
importlib.import_module("plr_ivoryos._runtime_enums").
"""

# Populated at runtime by plr_ivoryos.liquid_handler._build_deck_enums()
PlateResource = None      # Enum: plate instance names on the loaded deck
TipRackResource = None    # Enum: tip-rack instance names on the loaded deck
WellPosition = None       # Enum: A1..H12 (standard 96-well)


def register_enum(name: str, enum_class) -> None:
    """Register a runtime-generated Enum into this module so IvoryOS can import it."""
    import sys
    setattr(sys.modules[__name__], name, enum_class)
    enum_class.__module__ = __name__
    enum_class.__qualname__ = name
