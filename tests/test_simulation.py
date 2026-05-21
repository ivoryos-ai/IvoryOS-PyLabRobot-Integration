"""
plr_ivoryos -- Full Device Simulation Check
==========================================
Run this script to verify every proxy method works correctly using the
built-in simulation backends for all devices.

No IvoryOS UI, no hardware, no browser needed.

Usage:
    python tests/test_simulation.py
"""

import sys
import os

# Allow running from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plr_ivoryos import (
    LiquidHandler, Scale, Pump, HeaterShaker, 
    Centrifuge, PlateReader, Fan, Thermocycler
)

LAYOUT = os.path.join(os.path.dirname(__file__), "layout.json")

PASS_LABEL = "[PASS]"
FAIL_LABEL = "[FAIL]"

results = []

def check(label, fn, expect_error=False):
    try:
        result = fn()
        ok = (result is not False) and not expect_error
        results.append((label, ok))
        tag = PASS_LABEL if ok else FAIL_LABEL
        print(f"  {tag}  {label}")
    except Exception as e:
        ok = expect_error
        results.append((label, ok))
        tag = PASS_LABEL if ok else FAIL_LABEL
        short = str(e)[:80]
        print(f"  {tag}  {label}  ->  {type(e).__name__}: {short}")


# -----------------------------------------------------------------------------
print("\n--- Liquid Handler (Chatterbox) ---")
lh = LiquidHandler(simulated=True, deck_json=LAYOUT)

check("pick_up_tips(htf_tips, A1)",
      lambda: lh.pick_up_tips(tip_rack_name="htf_tips", position="A1"))
check("aspirate(source_plate, B2, 50 uL)",
      lambda: lh.aspirate(plate_name="source_plate", well="B2", volume_ul=50))
check("dispense(source_plate, C3, 50 uL)",
      lambda: lh.dispense(plate_name="source_plate", well="C3", volume_ul=50))
check("return_tips()",
      lambda: lh.return_tips())

# -----------------------------------------------------------------------------
print("\n--- Scale (Simulated) ---")
scale = Scale(simulated=True, name="sim_balance")
check("zero()",  lambda: scale.zero())
check("read_weight() returns float", lambda: isinstance(scale.read_weight(), float))

# -----------------------------------------------------------------------------
print("\n--- Pump (Simulated) ---")
pump = Pump(simulated=True)
check("run_continuously(speed=50)", lambda: pump.run_continuously(speed=50))
check("halt()", lambda: pump.halt())

# -----------------------------------------------------------------------------
print("\n--- HeaterShaker (Simulated) ---")
hs = HeaterShaker(simulated=True, name="sim_hs")
check("set_temperature(37)", lambda: hs.set_temperature(37.0))
check("shake(500)", lambda: hs.shake(500))
check("stop_shaking()", lambda: hs.stop_shaking())

# -----------------------------------------------------------------------------
print("\n--- Centrifuge (Simulated) ---")
cf = Centrifuge(simulated=True, name="sim_cf")
check("spin(g=400, duration=10)", lambda: cf.spin(g=400, duration=10))

# -----------------------------------------------------------------------------
print("\n--- PlateReader (Simulated) ---")
pr = PlateReader(simulated=True, name="sim_pr")
# PLR frontends require a plate to be assigned before reading
from pylabrobot.resources.corning.plates import Cor_96_wellplate_360ul_Fb
pr._pr.assign_child_resource(Cor_96_wellplate_360ul_Fb(name="test_plate"))
check("read_absorbance(450)", lambda: isinstance(pr.read_absorbance(450), list))
check("read_luminescence(focal_height=10)", lambda: isinstance(pr.read_luminescence(10.0), list))
check("read_fluorescence(485, 535, focal_height=10)",
      lambda: isinstance(pr.read_fluorescence(485, 535, 10.0), list))

# -----------------------------------------------------------------------------
print("\n--- Fan (Simulated) ---")
fan = Fan(simulated=True, name="sim_fan")
check("turn_on(intensity=80)", lambda: fan.turn_on(intensity=80))
check("turn_off()", lambda: fan.turn_off())

# -----------------------------------------------------------------------------
print("\n--- Thermocycler (Simulated) ---")
tc = Thermocycler(simulated=True, name="sim_tc")
check("set_temperature(95)", lambda: tc.set_temperature(95.0))

# -----------------------------------------------------------------------------
passed = sum(1 for _, ok in results if ok)
total  = len(results)

print(f"\n{'=' * 52}")
print(f"  Results: {passed}/{total} passed")
if passed == total:
    print(f"  \033[92mAll systems functional!\033[0m")
else:
    failed = [label for label, ok in results if not ok]
    print(f"  \033[91mFailed:\033[0m {failed}")
print(f"{'=' * 52}\n")

sys.exit(0 if passed == total else 1)
