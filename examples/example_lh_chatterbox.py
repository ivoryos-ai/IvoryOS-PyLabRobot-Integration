"""
plr-ivoryos example: PyLabRobot's simulator (no hardware needed)
=================================================================

The worktable (which robot, what sits where, what is in it) lives in worktable.json, not here.
Edit that file, or use the Labware panel in IvoryOS NextGen, to change it.

    python examples/example_lh_chatterbox.py
"""

import os

from plr_ivoryos import LiquidHandler

lh = LiquidHandler(
    simulated=True,
    deck_json=os.path.join(os.path.dirname(__file__), "worktable.json"),
)

if __name__ == "__main__":
    try:
        import ivoryos_edge as server    # IvoryOS NextGen
    except ImportError:
        import ivoryos as server         # the original IvoryOS
    server.run(__name__)
