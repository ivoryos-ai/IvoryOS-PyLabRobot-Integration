"""
plr-ivoryos example — PLR Visual Simulator
==========================================

This example demonstrates how to use PyLabRobot's built-in visual simulator 
instead of the headless chatterbox simulator. 

When you run this script:
1. A browser window will open showing the 3D robot deck.
2. IvoryOS will start as usual.
3. Every command you run in IvoryOS (aspirate, pick_up_tips, etc.) 
   will be animated in the 3D simulator.

Run with:
    python example_visual_simulator.py
"""

import sys
import os

# Allow running from the examples directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plr_ivoryos import LiquidHandler
from pylabrobot.liquid_handling.backends import SimulatorBackend

# ─── Initialize with the PLR SimulatorBackend ────────────────────────────────
# open_browser=True will automatically launch the visualizer
lh = LiquidHandler(
    backend=SimulatorBackend(open_browser=True),
    deck_json=os.path.join(os.path.dirname(__file__), "layout.json"),
)

if __name__ == "__main__":
    import ivoryos
    # Start IvoryOS
    ivoryos.run(__name__)
