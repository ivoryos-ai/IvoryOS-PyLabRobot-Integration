"""Opentrons robots through PyLabRobot 1.0: the Flex (flex.py), the OT-2 (ot2.py), and a simulated
robot-server for both (simulator.py)."""

from plr_ivoryos.opentrons.flex import (Flex, FlexGripperPart, FlexPipette1, FlexPipette8, FlexPipette96,
                                        check_equipment)
from plr_ivoryos.opentrons.ot2 import OT2, OT2Pipette1, OT2Pipette8
from plr_ivoryos.opentrons.simulator import FLEX_PIPETTES, OT2_PIPETTES, SimulatedFlexServer, SimulatedOT2Server

__all__ = ["Flex", "FlexPipette1", "FlexPipette8", "FlexPipette96", "FlexGripperPart", "check_equipment",
           "OT2", "OT2Pipette1", "OT2Pipette8",
           "FLEX_PIPETTES", "OT2_PIPETTES", "SimulatedFlexServer", "SimulatedOT2Server"]
