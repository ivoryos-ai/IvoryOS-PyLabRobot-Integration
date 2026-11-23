"""A simulated Hamilton STARlet in IvoryOS NextGen, through PyLabRobot 1.0.

    pip install plr-ivoryos==1.0.0b2 ivoryos-edge
    python examples/star_simulated.py

PyLabRobot's own STAR simulator answers as the firmware would, so tips, volumes and PyLabRobot's
checks are real. The STARlet is the instrument `star`; each thing fitted to it is one too:
`star_pipettes` (8 channels), `star_head96`, `star_iswap`, `star_core_grippers`, `star_autoload`.
What sits where is star_worktable.json beside this script, written on the first change in the
Labware panel. deck_type="STARDeck" or "STARPlusDeck" for the bigger frames; the other liquid
handlers (Prep, OT-2, Nimbus, Vantage, EVO) are made the same way (README).
"""

import os

from plr_ivoryos.hamilton import STAR

HERE = os.path.dirname(os.path.abspath(__file__))

star = STAR(simulated=True, worktable=os.path.join(HERE, "star_worktable.json"), step_delay_s=0.3)

if __name__ == "__main__":
    import ivoryos_edge
    from plr_ivoryos.labware_view import plugin as labware_view
    ivoryos_edge.run(__name__, plugins=[labware_view])
