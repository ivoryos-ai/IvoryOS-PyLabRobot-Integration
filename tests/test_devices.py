"""Every device the IvoryOS Hub listed on plr-ivoryos 0.2, on PyLabRobot 1.0.0b1, simulated.

Eleven are PyLabRobot 1.0 classes (Mettler Toledo, Masterflex, VSpin, BioShake, Inheco
ThermoShake, Cytation 5, Synergy H1, SpectraMax M5 and 384 Plus, Byonoy A96 and L96), simulated by
this package; the rest are PyLabRobot's legacy front ends and backends, simulated by PyLabRobot's
own legacy simulators, except plate readers, which read plates on a liquid handler's worktable.
"""

import inspect

import pytest

from plr_ivoryos import agilent, bridge, byonoy, cole_parmer, inheco, legacy, mettler_toledo, molecular_devices, \
    qinstruments
from plr_ivoryos.device import OWN_PLATE, Device, Reader
from plr_ivoryos.opentrons import Flex

# The Hub's 0.2 rows, by name, and what each is now.
HUB_ROWS = {
    "Mettler Toledo Scale": mettler_toledo.MettlerToledoWXS205SDU,
    "Masterflex Pump": cole_parmer.Masterflex,
    "VSpin Centrifuge": agilent.VSpin,
    "BioTek Cytation 5": agilent.Cytation5,
    "BioTek Synergy H1": agilent.SynergyH1,
    "Molecular Devices SpectraMax M5": molecular_devices.SpectraMaxM5,
    "Molecular Devices SpectraMax 384 Plus": molecular_devices.SpectraMax384Plus,
    "Byonoy Absorbance 96 Automate": byonoy.ByonoyAbsorbance96,
    "Byonoy Luminescence 96 Automate": byonoy.ByonoyLuminescence96,
    "QInstruments BioShake": qinstruments.BioShake,
    "Inheco Thermoshake": inheco.InhecoThermoShake,
    "BMG CLARIOstar": legacy.CLARIOstar,
    "Tecan Spark": legacy.TecanSpark,
    "Tecan Infinite 200 PRO": legacy.TecanInfinite200Pro,
    "Molecular Devices SpectraMax Gemini EM": legacy.SpectraMaxGeminiEM,
    "Hamilton HeaterShaker": legacy.HamiltonHeaterShaker,
    "Hamilton HEPA Fan": legacy.HamiltonHepaFan,
    "Inheco ODTC": legacy.InhecoODTC,
    "Opentrons Thermocycler": legacy.OpentronsThermocycler,
    "Thermo Fisher ProFlex": legacy.ProFlex,
    "Thermo Fisher ATC": legacy.ATC,
    "Simulated Scale": legacy.Scale,
    "Simulated PLR Pump": legacy.Pump,
    "Simulated Centrifuge": legacy.Centrifuge,
    "Simulated HeaterShaker": legacy.HeaterShaker,
    "Simulated PlateReader": legacy.PlateReader,
    "Simulated Fan": legacy.Fan,
    "Simulated PLR Thermocycler": legacy.Thermocycler,
}

SKIPPED = {**mettler_toledo.SKIPPED, **cole_parmer.SKIPPED, **agilent.SKIPPED, **molecular_devices.SKIPPED,
           **byonoy.SKIPPED, **qinstruments.SKIPPED, **inheco.SKIPPED, **legacy.SKIPPED}


def _steps(cls):
    return {name for name in dir(cls) if not name.startswith("_") and callable(getattr(cls, name))}


def test_all_28_hub_devices_have_a_class():
    assert len(HUB_ROWS) == 28


@pytest.mark.parametrize("row", sorted(HUB_ROWS))
def test_every_hub_device_simulates_and_offers_pylabrobots_steps(row):
    cls = HUB_ROWS[row]
    device = cls(simulated=True)
    assert isinstance(device, Device)
    steps = _steps(cls)
    assert {"setup", "stop"} <= steps
    assert len(steps) > 3
    # Nothing a person needs was left out because the bridge could not offer it. (A named legacy
    # device with a front end, HamiltonHepaFan, has its front end's steps: Fan's.)
    owner = next(c.__name__ for c in cls.__mro__ if c.__name__ in SKIPPED)
    assert not SKIPPED[owner], SKIPPED[owner]
    # No class, nested enum or resource-tree method is offered as a step.
    assert not steps & {"serialize", "assign_child_resource", "get_absolute_location", "send_command",
                        "get_all_instances", "ShakeType"}


@pytest.mark.parametrize("make", [
    lambda: cole_parmer.Masterflex(),
    lambda: qinstruments.BioShake(),
    lambda: molecular_devices.SpectraMaxM5(),
    lambda: legacy.SpectraMaxGeminiEM(),
    lambda: legacy.InhecoODTC(),
    lambda: legacy.ProFlex(),
    lambda: legacy.OpentronsThermocycler(),
    lambda: legacy.Scale(),
    lambda: legacy.PlateReader(),
])
def test_a_real_device_needs_its_connection(make):
    with pytest.raises(ValueError, match="simulated=True"):
        make()


# --- the PyLabRobot 1.0 classes, on this package's simulators ---------------------------------------

def test_a_scale_tares_and_reads():
    scale = mettler_toledo.MettlerToledoWXS205SDU(simulated=True)
    scale.tare()
    assert scale.read_weight() == 0.0
    assert scale.request_tare_weight() == 0.0
    assert scale.request_serial_number() == "simulated"  # a stand-in of the type it returns
    assert isinstance(scale.request_capacity(), float)


def test_a_centrifuge_will_not_spin_with_its_door_open():
    vspin = agilent.VSpin(simulated=True)
    vspin.open_door()
    assert vspin.request_door_open() is True
    with pytest.raises(RuntimeError, match="door is open"):
        vspin.spin(g=100, duration=0.05)
    vspin.close_door()
    vspin.spin(g=100, duration=0.05)
    assert vspin.request_spinning() is False


def test_heater_shakers_reach_their_temperature_and_shake():
    for shaker in (qinstruments.BioShake(simulated=True), inheco.InhecoThermoShake(simulated=True)):
        shaker.set_temperature(temperature=37)
        assert shaker.request_current_temperature() == 37.0
        shaker.shake(speed=500, duration=0.05)


def test_bioshake_offers_the_models_pylabrobot_can_make():
    import pylabrobot.qinstruments as q
    for model in qinstruments.MODELS:
        try:
            getattr(q, model)(name="bs", port="/dev/null")
        except NotImplementedError as e:  # "missing resource definition": PyLabRobot cannot make it
            pytest.fail(f"{model}: {e}")
        except RuntimeError:  # no pyserial here, which is the next thing a real one needs
            pass
    assert set(qinstruments.Model.__args__) == set(qinstruments.MODELS)
    for model in ("BioShake3000T", "Heatplate", "BioShake9000"):
        with pytest.raises(ValueError, match="can make a BioShake of model"):
            qinstruments.BioShake(model=model, simulated=True)


def test_a_simulated_bioshake_refuses_what_its_model_cannot_do():
    shaker = qinstruments.BioShake(model="BioShake3000", simulated=True)
    shaker.shake(speed=500, duration=0.01)
    with pytest.raises(RuntimeError, match="does not support temperature control"):
        shaker.set_temperature(temperature=37)
    with pytest.raises(RuntimeError, match="cannot lock plates"):
        shaker.lock_plate()
    q1 = qinstruments.BioShake(simulated=True)  # the default, a Q1, heats and locks
    q1.set_temperature(temperature=37)
    q1.lock_plate()


def test_a_pump_runs_and_halts():
    pump = cole_parmer.Masterflex(simulated=True)
    pump.run_continuously(speed=20)
    assert pump._plr.speed == 20.0
    pump.halt()
    assert pump._plr.speed == 0.0


def test_a_tuple_of_numbers_is_offered_as_a_list():
    param = inspect.signature(byonoy.ByonoyAbsorbance96.set_led_color).parameters["color"]
    assert "List[int]" in repr(param.annotation)
    reader = byonoy.ByonoyAbsorbance96(simulated=True)
    reader.set_led_color(color="0, 255, 0")
    with pytest.raises(ValueError, match="expected 3 int values"):
        reader.set_led_color(color="0, 255")


# --- PyLabRobot's legacy front ends, on PyLabRobot's simulators -------------------------------------

def test_legacy_heater_shaker_waits_for_its_temperature():
    hs = legacy.HamiltonHeaterShaker(simulated=True)
    hs.set_temperature(temperature=40)
    hs.wait_for_temperature()
    assert hs.get_temperature() == 40
    hs.shake(speed=300, duration=0.05)


def test_legacy_centrifuge_spins_without_an_acceleration():
    centrifuge = legacy.Centrifuge(simulated=True)
    centrifuge.close_door()
    centrifuge.lock_door()
    centrifuge.spin(g=500, duration=0.05)


def test_a_thermocycler_protocol_is_typed_as_json_and_becomes_pylabrobots_stages_and_steps():
    tc = legacy.ProFlex(simulated=True)
    tc.set_block_temperature(temperature=[95])
    tc.wait_for_block()
    assert tc.get_block_current_temperature() == [95.0]
    tc.run_protocol(protocol={"stages": [{"repeats": 1, "steps": [{"temperature": [95], "hold_seconds": 1},
                                                                  {"temperature": [60], "hold_seconds": 1}]}]},
                    block_max_volume=25)
    tc.run_pcr_profile(denaturation_temp=[95], denaturation_time=1, annealing_temp=[55], annealing_time=1,
                       extension_temp=[72], extension_time=1, num_cycles=1, block_max_volume=25,
                       lid_temperature=[105])


def test_a_protocol_that_is_not_one_says_why():
    from pylabrobot.legacy.thermocycling.standard import Protocol, Stage, Step
    built = bridge._build(Protocol, {"stages": [{"repeats": 2, "steps": [{"temperature": [4], "hold_seconds": 10}]}]})
    assert isinstance(built.stages[0], Stage) and isinstance(built.stages[0].steps[0], Step)
    with pytest.raises(ValueError, match="Protocol"):
        bridge._dataclass_value(Protocol)({"stages": [{"steps": []}]}, None)  # a stage with no repeats


def test_fans_and_pumps():
    fan = legacy.HamiltonHepaFan(simulated=True)
    fan.turn_on(intensity=50)
    fan.turn_off()
    legacy.Pump(simulated=True).run_for_duration(speed=5, duration=0.05)
    assert legacy.Scale(simulated=True).read_weight() == 0.0


# --- plate readers: a plate on a liquid handler's worktable -----------------------------------------

READERS = [agilent.Cytation5, agilent.SynergyH1, molecular_devices.SpectraMaxM5, molecular_devices.SpectraMax384Plus,
           byonoy.ByonoyAbsorbance96, legacy.CLARIOstar, legacy.TecanSpark, legacy.TecanInfinite200Pro,
           legacy.SpectraMaxGeminiEM, legacy.PlateReader]


@pytest.fixture
def flex_with_dye():
    flex = Flex(simulated=True, worktable="flex.json")
    flex.load_liquid(resources="assay_plate[B1]", liquid="dye", vols=10)
    flex.load_liquid(resources="assay_plate[C1]", liquid="water", vols=10)
    return flex


@pytest.mark.parametrize("cls", READERS)
def test_a_reader_reads_the_plate_where_it_sits_and_the_dye_in_it(cls, flex_with_dye):
    reader = cls(simulated=True, worktable="flex.json")
    plate = "assay_plate"
    assert plate in reader.__ivoryos_labware__()["labware"]
    result = reader.read_absorbance(plate=plate, wells=f"{plate}[A1:C1]", wavelength=450)
    data = result[0]["data"]
    blank, dye, water = data[0][0], data[1][0], data[2][0]
    assert abs(blank - 0.04) < 0.02 and abs(water - 0.04) < 0.02  # nothing that absorbs
    assert abs(dye - 0.29) < 0.02  # 0.04 + 10 uL x 0.025
    assert data[0][1] is None  # not read
    assert result[0]["wavelength"] == 450


def test_a_reader_returns_what_its_pylabrobot_class_returns(flex_with_dye):
    new = agilent.SynergyH1(simulated=True, worktable="flex.json").read_absorbance(
        plate="assay_plate", wells="assay_plate[A1]", wavelength=450)
    old = legacy.CLARIOstar(simulated=True, worktable="flex.json").read_absorbance(
        plate="assay_plate", wells="assay_plate[A1]", wavelength=450)
    assert "timestamp" in new[0] and "time" not in new[0]  # PyLabRobot 1.0's AbsorbanceResult
    assert "time" in old[0]  # a legacy backend's dict
    assert old[0]["temperature"] is None  # never NaN: IvoryOS keeps results as JSON


def test_a_reader_made_before_its_robot_finds_it(data_folder):
    reader = agilent.SynergyH1(simulated=True, worktable="later.json")
    Flex(simulated=True, worktable="later.json")
    assert "assay_plate" in reader.__ivoryos_labware__()["labware"]


def test_a_reader_without_a_liquid_handler_holds_a_plate_of_its_own():
    reader = byonoy.ByonoyAbsorbance96(simulated=True, worktable="nobody.json")
    assert list(reader.__ivoryos_labware__()["labware"]) == [OWN_PLATE]
    result = reader.read_absorbance(plate=OWN_PLATE, wells=f"{OWN_PLATE}[A1:H1]", wavelength=600)
    assert [row[0] is not None for row in result[0]["data"]] == [True] * 8


def test_a_reader_refuses_a_plate_that_is_not_there(flex_with_dye):
    reader = agilent.SynergyH1(simulated=True, worktable="flex.json")
    with pytest.raises(ValueError, match="not on this worktable"):
        reader.read_absorbance(plate="nope", wells="nope[A1]", wavelength=450)


def test_fluorescence_and_luminescence_follow_the_dye_too(flex_with_dye):
    fl = molecular_devices.SpectraMaxM5(simulated=True, worktable="flex.json").read_fluorescence(
        plate="assay_plate", wells="assay_plate[A1:B1]", excitation_wavelength=485, emission_wavelength=520,
        focal_height=5)
    assert fl[0]["data"][1][0] > 10 * fl[0]["data"][0][0]
    lum = byonoy.ByonoyLuminescence96(simulated=True, worktable="flex.json").read_luminescence(
        plate="assay_plate", wells="assay_plate[A1:B1]")
    assert lum[0]["data"][1][0] > 10 * lum[0]["data"][0][0]


def test_a_readers_plate_and_wells_are_offered_as_labware_and_wells():
    params = inspect.signature(agilent.SynergyH1.read_absorbance).parameters
    assert "Labware" in repr(params["plate"].annotation)
    assert "Wells" in repr(params["wells"].annotation)
    assert issubclass(agilent.SynergyH1, Reader)


def test_jsonable_has_no_nan():
    assert bridge.jsonable(float("nan")) is None
    assert bridge.jsonable([1.0, float("inf")]) == [1.0, None]
