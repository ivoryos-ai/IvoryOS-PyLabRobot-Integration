"""
plr_ivoryos
============
IvoryOS-compatible wrappers for PyLabRobot lab automation devices.

Supported devices
-----------------
LiquidHandler (Hamilton STAR, Opentrons OT-2, Tecan EVO, Chatterbox simulator)
    LiquidHandler  — steps that take labware names and well selections, on a worktable
                     described by a file (worktable.py)

Scale (MettlerToledo, etc.)
    Scale

Pump (Cole-Parmer Masterflex, etc.)
    Pump

HeaterShaker (Inheco ThermoShake, etc.)
    HeaterShaker

Centrifuge (VSpin, etc.)
    Centrifuge

PlateReader (CLARIOstar, Cytation5, etc.)
    PlateReader

Fan (Hamilton HEPA, etc.)
    Fan

Thermocycler
    Thermocycler
TemperatureController (Inheco CPAC, Opentrons Temperature Module)
    TemperatureController
Sealer (Azenta a4S)
    Sealer
Peeler (Azenta XPeel)
    Peeler
Tilter (Hamilton tilt module)
    Tilter
BarcodeScanner (Keyence)
    BarcodeScanner
"""

from plr_ivoryos.liquid_handler import LiquidHandler
from plr_ivoryos.wells import Labware, PerWell, Site, WellSelection, Wells, expand_wells
from plr_ivoryos import worktable
from plr_ivoryos.simple import (
    Scale,
    Pump,
    HeaterShaker,
    Centrifuge,
    PlateReader,
    Fan,
    Thermocycler,
    TemperatureController,
    Sealer,
    Peeler,
    Tilter,
    BarcodeScanner,
    SimulatedScaleBackend,
)
from plr_ivoryos.async_bridge import run_async, shutdown as shutdown_async

__all__ = [
    "LiquidHandler",
    "Labware",
    "Wells",
    "PerWell",
    "Site",
    "WellSelection",
    "expand_wells",
    "worktable",
    "Scale",
    "Pump",
    "HeaterShaker",
    "Centrifuge",
    "PlateReader",
    "Fan",
    "Thermocycler",
    "TemperatureController",
    "Sealer",
    "Peeler",
    "Tilter",
    "BarcodeScanner",
    "SimulatedScaleBackend",
    "run_async",
    "shutdown_async",
]

__version__ = "0.2.1"
