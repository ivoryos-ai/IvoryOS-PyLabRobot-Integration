"""
plr_ivoryos
============
IvoryOS-compatible wrappers for PyLabRobot lab automation devices.

Supported devices
-----------------
LiquidHandler (Hamilton STAR, Opentrons OT-2, Tecan EVO, Chatterbox simulator)
    LiquidHandler  — proxy with Enum dropdowns for plate/well selection

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
"""

from plr_ivoryos.liquid_handler import LiquidHandler, AdvancedLiquidHandler
from plr_ivoryos.simple import (
    Scale,
    Pump,
    HeaterShaker,
    Centrifuge,
    PlateReader,
    Fan,
    Thermocycler,
    SimulatedScaleBackend,
)
from plr_ivoryos.async_bridge import run_async, shutdown as shutdown_async

__all__ = [
    "LiquidHandler",
    "AdvancedLiquidHandler",
    "Scale",
    "Pump",
    "HeaterShaker",
    "Centrifuge",
    "PlateReader",
    "Fan",
    "Thermocycler",
    "SimulatedScaleBackend",
    "run_async",
    "shutdown_async",
]

__version__ = "0.1.0"
