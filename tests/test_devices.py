"""The single-purpose devices on simulators: each steps' plain arguments reach PyLabRobot.

    pytest tests/test_devices.py
"""

import inspect
import typing

import pytest

from plr_ivoryos import BarcodeScanner, Peeler, Sealer, TemperatureController, Tilter
from plr_ivoryos.simple import SimulatedBarcodeScannerBackend


def test_a_temperature_controller_heats_and_reads_back():
    tc = TemperatureController(simulated=True)
    tc.set_temperature(42.0)
    assert tc.get_temperature() == 42.0
    tc.wait_for_temperature(timeout=5, tolerance=0.5)
    tc.deactivate()
    tc.shutdown()


def test_a_sealer_seals_at_a_temperature_it_was_given():
    sealer = Sealer(simulated=True)
    sealer.open()
    sealer.close()
    sealer.seal(temperature=170, duration=2.5)
    assert sealer.get_temperature() == 170
    sealer.set_temperature(160)
    assert sealer.get_temperature() == 160
    # No default for the sealing temperature: it is a choice for whoever writes the step.
    assert inspect.signature(Sealer.seal).parameters["temperature"].default is inspect.Parameter.empty


def test_a_peeler_peels_with_the_xpeel_arguments():
    peeler = Peeler(simulated=True)
    peeler.peel(begin_location=2, fast=True, adhere_time=1.0)
    peeler.restart()


def test_a_tilter_tilts_on_the_hamilton_modules_geometry():
    tilter = Tilter(simulated=True)
    tilter.set_angle(10)
    tilter.tilt(-5)
    assert tilter._tilter.get_absolute_size_x() == 132
    with pytest.raises(ValueError, match="com_port"):
        Tilter()


def test_a_barcode_scanner_returns_the_text_it_read():
    scanner = BarcodeScanner(backend=SimulatedBarcodeScannerBackend(codes=["PLATE-42"]))
    assert scanner.scan() == "PLATE-42"
    assert scanner.scan() == "SIM-0002"
    assert BarcodeScanner(simulated=True).scan() == "SIM-0001"


@pytest.mark.parametrize("cls", [TemperatureController, Sealer, Peeler, Tilter, BarcodeScanner])
def test_every_step_takes_plain_values_ivoryos_can_render(cls):
    """IvoryOS builds a form from each step's signature: nothing a form cannot fill in."""
    allowed = {float, int, str, bool}
    for name, method in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        hints = typing.get_type_hints(method)
        for p in list(inspect.signature(method).parameters.values())[1:]:
            ann = hints.get(p.name)
            assert ann in allowed or typing.get_origin(ann) is typing.Literal, (cls.__name__, name, p)
