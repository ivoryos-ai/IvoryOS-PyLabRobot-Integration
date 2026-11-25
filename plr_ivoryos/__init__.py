"""
plr_ivoryos
============
PyLabRobot 1.0 devices in IvoryOS, with PyLabRobot's own steps.

Supported liquid handlers (every one PyLabRobot 1.0.0b1 drives)
---------------------------------------------------------------
PyLabRobot 1.0 classes, each robot an instrument and each thing fitted to it one too, with the
steps PyLabRobot gives each:
    Opentrons Flex          plr_ivoryos.opentrons.Flex      simulated: this package's robot-server
    Opentrons OT-2          plr_ivoryos.opentrons.OT2       simulated: this package's robot-server
    Hamilton STAR, STARlet, STARplus   plr_ivoryos.hamilton.STAR   simulated: PyLabRobot's simulator
    Hamilton Prep           plr_ivoryos.hamilton.Prep       simulated: PyLabRobot's simulator
PyLabRobot's legacy LiquidHandler (pylabrobot.legacy), one instrument with every operation:
    Hamilton Nimbus, Vantage; Tecan Freedom EVO; any legacy backend
                            plr_ivoryos.legacy.Nimbus, Vantage, EVO, LiquidHandler
                            simulated: PyLabRobot's LiquidHandlerChatterboxBackend
What is fitted, and what sits where on the deck, is the worktable file (worktable.py).

Devices (device.py), each one instrument with PyLabRobot's own steps
--------------------------------------------------------------------
PyLabRobot 1.0 classes, simulated by this package (simulators.py):
    plr_ivoryos.mettler_toledo.MettlerToledoWXS205SDU, cole_parmer.Masterflex, agilent.VSpin,
    qinstruments.BioShake, inheco.InhecoThermoShake, agilent.Cytation5, agilent.SynergyH1,
    molecular_devices.SpectraMaxM5, molecular_devices.SpectraMax384Plus,
    byonoy.ByonoyAbsorbance96, byonoy.ByonoyLuminescence96
PyLabRobot's legacy front ends and backends, simulated by PyLabRobot's legacy simulators:
    plr_ivoryos.legacy.CLARIOstar, TecanSpark, TecanInfinite200Pro, SpectraMaxGeminiEM,
    HamiltonHeaterShaker, HamiltonHepaFan, InhecoODTC, OpentronsThermocycler, ProFlex, ATC, and
    Scale, Pump, Centrifuge, HeaterShaker, Thermocycler, Fan, PlateReader with any legacy backend
A plate reader reads a plate where it sits on a liquid handler's worktable (device.Reader).

How a PyLabRobot method becomes a step (wells as `plate[A1:H1]` text, labware by name) is
bridge.py; the worktable, the Labware view's hooks and running a step are robot.py, and the Labware
view itself is labware_view (an IvoryOS NextGen plugin).
"""

from plr_ivoryos.wells import Labware, PerWell, Site, WellSelection, Wells, expand_wells
from plr_ivoryos import worktable
from plr_ivoryos.opentrons import OT2, Flex
from plr_ivoryos.hamilton import STAR, Prep
from plr_ivoryos.legacy import EVO, Nimbus, Vantage
from plr_ivoryos.legacy import LiquidHandler as LegacyLiquidHandler
from plr_ivoryos.async_bridge import run_async, shutdown as shutdown_async

__all__ = [
    "Flex",
    "OT2",
    "STAR",
    "Prep",
    "Nimbus",
    "Vantage",
    "EVO",
    "LegacyLiquidHandler",
    "Labware",
    "Wells",
    "PerWell",
    "Site",
    "WellSelection",
    "expand_wells",
    "worktable",
    "run_async",
    "shutdown_async",
]

__version__ = "1.0.0b3"
