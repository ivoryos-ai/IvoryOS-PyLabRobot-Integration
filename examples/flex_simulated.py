"""A simulated Opentrons Flex in IvoryOS NextGen, through PyLabRobot 1.0.

    pip install plr-ivoryos ivoryos-edge
    python examples/flex_simulated.py

PyLabRobot's own Flex runs against a simulated robot (plr_ivoryos.opentrons.simulator), so tips,
volumes and PyLabRobot's checks are real. The Flex is the instrument `flex`; each thing mounted on
it is one too: `flex_left` (an 8-channel), `flex_right` (a 1-channel), `flex_gripper`. What is
mounted and what sits where is worktable.json beside this script, written on the first change in
the Labware panel.
"""

import os

from plr_ivoryos.opentrons import Flex

HERE = os.path.dirname(os.path.abspath(__file__))

flex = Flex(simulated=True, worktable=os.path.join(HERE, "worktable.json"), step_delay_s=0.3)

if __name__ == "__main__":
    import ivoryos_edge
    from plr_ivoryos.labware_view import plugin as labware_view
    ivoryos_edge.run(__name__, plugins=[labware_view])
