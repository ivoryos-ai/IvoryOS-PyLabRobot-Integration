"""
plr4ivoryos example — Advanced Liquid Handler (Pro Mode)
=====================================================================

This example uses the AdvancedLiquidHandler, which exposes core PyLabRobot 
mixing parameters (like mix_volume, mix_repetitions, mix_flow_rate) directly
into the IvoryOS UI dropdown forms for aspirate, dispense, and transfer.

Run with:
    python example_advanced_lh.py

IvoryOS will start at http://localhost:8000/ivoryos
"""

import sys
import os

from pylabrobot.liquid_handling import LiquidHandlerChatterboxBackend

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plr_ivoryos import AdvancedLiquidHandler

lh = AdvancedLiquidHandler(
    backend=LiquidHandlerChatterboxBackend(),
    deck_json=os.path.join(os.path.dirname(__file__), "layout.json"),
)

lh.start_visualizer(open_browser=False)

if __name__ == "__main__":
    import ivoryos
    ivoryos.run(__name__)
