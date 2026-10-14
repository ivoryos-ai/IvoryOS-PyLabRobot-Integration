"""Opentrons robots through PyLabRobot 1.0: the Flex (flex.py) and a simulated one (simulator.py)."""

from plr_ivoryos.opentrons.flex import (Flex, FlexGripperPart, FlexPipette1, FlexPipette8, FlexPipette96,
                                        check_equipment)
from plr_ivoryos.opentrons.simulator import FLEX_PIPETTES, SimulatedFlexServer

__all__ = ["Flex", "FlexPipette1", "FlexPipette8", "FlexPipette96", "FlexGripperPart", "check_equipment",
           "FLEX_PIPETTES", "SimulatedFlexServer"]
