"""
plr4ivoryos example — Chatterbox simulator (no real hardware needed)
=====================================================================

The LiquidHandlerChatterboxBackend prints every command to the console instead
of sending it to a real robot.  This lets you develop and demo the integration
without owning a Hamilton, Opentrons, or Tecan instrument.

The deck layout (plates, tip racks, locations) lives in layout.json — no PLR
resource imports needed in this file.  IvoryOS will only see `lh`.

Run with:
    python example_chatterbox.py

IvoryOS will start at http://localhost:8000/ivoryos
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plr_ivoryos import LiquidHandler

lh = LiquidHandler(
    simulated=True,
    deck_json=os.path.join(os.path.dirname(__file__), "layout.json"),
)


if __name__ == "__main__":
    import ivoryos
    ivoryos.run(__name__)
