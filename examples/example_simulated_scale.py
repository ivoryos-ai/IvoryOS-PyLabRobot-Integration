import sys
import os

# Allow running from the examples directory with the package installed editable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plr_ivoryos import Scale

# ─── Simulated balance ────────────────────────────────────────────────────────
# simulated=True uses the SimulatedScaleBackend automatically.
scale = Scale(
    simulated=True,
    name="sim_balance",
)


# ─── Start IvoryOS ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import ivoryos
    ivoryos.run(__name__)
