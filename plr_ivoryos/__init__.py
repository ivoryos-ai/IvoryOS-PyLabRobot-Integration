"""
plr_ivoryos
============
PyLabRobot 1.0 devices in IvoryOS, with PyLabRobot's own steps.

Supported devices
-----------------
Opentrons Flex (plr_ivoryos.opentrons.Flex)
    The robot is an instrument, and each thing mounted on it is one too: the pipette on each
    mount (FlexPipette1, FlexPipette8), the 96-channel head (FlexPipette96) and the gripper
    (FlexGripperPart), with the steps PyLabRobot gives each. What is mounted, and what sits where
    on the deck, is the worktable file (worktable.py). `simulated=True` runs PyLabRobot's Flex
    against a simulated robot (opentrons/simulator.py).

How a PyLabRobot method becomes a step (wells as `plate[A1:H1]` text, labware by name) is
bridge.py; the worktable, the Labware view's hooks and running a step are robot.py, and the Labware
view itself is labware_view (an IvoryOS NextGen plugin).
"""

from plr_ivoryos.wells import Labware, PerWell, Site, WellSelection, Wells, expand_wells
from plr_ivoryos import worktable
from plr_ivoryos.opentrons import Flex
from plr_ivoryos.async_bridge import run_async, shutdown as shutdown_async

__all__ = [
    "Flex",
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

__version__ = "1.0.0b1"
