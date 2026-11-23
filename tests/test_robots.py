"""Every liquid handler PyLabRobot 1.0.0b1 drives, simulated, through the same worktable file,
wells-as-text and liquid tracking as the Flex (test_flex.py).

STAR and Prep run on PyLabRobot's own simulators, the OT-2 on this package's simulated
robot-server, and the Nimbus, Vantage and EVO on PyLabRobot's legacy chatterbox. So what passes here
is what PyLabRobot accepts, with its own refusals.
"""

import inspect

import pytest

from plr_ivoryos import worktable
from plr_ivoryos.hamilton import STAR, Prep
from plr_ivoryos.hamilton import prep as prep_module
from plr_ivoryos.hamilton import star as star_module
from plr_ivoryos.legacy import EVO, LiquidHandler, Nimbus, Vantage
from plr_ivoryos.legacy import SKIPPED as LEGACY_SKIPPED
from plr_ivoryos.opentrons import OT2, OT2Pipette1, OT2Pipette8
from plr_ivoryos.opentrons.ot2 import check_equipment as ot2_equipment


def _steps(obj):
    cls = obj if isinstance(obj, type) else type(obj)
    return {name for name in dir(cls) if not name.startswith("_") and callable(getattr(cls, name))}


# --- the bridge -------------------------------------------------------------------------------------

def test_an_argument_taking_labware_or_a_coordinate_is_offered_as_the_labware():
    # STAR's drop_tips(destinations: Sequence[Union[TipSpot, Coordinate]]) and the legacy
    # drop_tips(tip_spots: Sequence[Union[TipSpot, Trash]]) are steps.
    assert "drop_tips" in _steps(star_module.STARPipettes)
    assert not star_module.SKIPPED["STARPipettes"]
    assert "drop_tips" not in LEGACY_SKIPPED["LiquidHandler"]
    param = inspect.signature(star_module.STARPipettes.drop_tips).parameters["destinations"]
    assert "Wells" in repr(param.annotation)


def test_a_robot_that_is_a_resource_does_not_offer_the_resource_tree_as_steps():
    for cls in (STAR, Prep, LiquidHandler):
        steps = {n for n in dir(cls) if not n.startswith("_")}
        assert not steps & {"serialize", "assign_child_resource", "get_absolute_location", "rotate", "LLDMode"}


# --- worktables -------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(worktable.DECKS))
def test_every_liquid_handlers_worktable_builds_from_its_starter(kind):
    config = worktable.starter(kind)
    deck = worktable.build_deck(config)
    worktable.apply_liquids(deck, config)
    assert worktable.kind_of(deck) == kind
    assert worktable.catalog(kind)


def test_a_tecan_carrier_goes_on_rails_and_a_prep_plate_in_a_spot():
    evo = worktable.build_deck({"deck_type": "EVO150Deck", "resources": [
        {"name": "carrier", "type": "MP_3Pos", "rails": 20,
         "children": [{"name": "plate", "type": "Microplate_96_Well", "site": 0}]}]})
    assert evo.get_resource("plate").parent.parent.name == "carrier"
    assert worktable._rail_of(evo, evo.get_resource("carrier")) == 20
    prep = worktable.build_deck({"deck_type": "PrepDeck", "resources": [
        {"name": "plate", "type": "cor_96_wellplate_360uL_Fb", "slot": 5}]})
    holder = prep.get_resource("plate").parent
    assert worktable.slot_label(holder) == "5"
    with pytest.raises(ValueError, match="not a spot on a Prep"):
        worktable.build_deck({"deck_type": "PrepDeck", "resources": [
            {"name": "plate", "type": "cor_96_wellplate_360uL_Fb", "slot": 8}]})


# --- Hamilton STAR (PyLabRobot's simulator) -----------------------------------------------------------

@pytest.fixture
def star():
    robot = STAR(simulated=True)
    yield robot
    robot.stop()


def test_a_simulated_star_is_its_recording_and_each_fitted_thing_an_instrument(star):
    assert star.equipment == {"pipettes": True, "head96": True, "head384": False, "iswap": True,
                              "core_grippers": True, "autoload": True}
    parts = star.__ivoryos_instruments__()
    assert set(parts) == {"pipettes", "head96", "iswap", "core_grippers", "autoload"}
    assert {"pick_up_tips", "aspirate", "dispense", "drop_tips", "discard_tips"} <= _steps(parts["pipettes"])
    assert {"pick_up_tips", "aspirate", "dispense", "discard_tips"} <= _steps(parts["head96"])
    assert "request_firmware_version" in _steps(star)


def test_star_channels_move_liquid_and_the_ledger_knows_which(star):
    pipettes = star.__ivoryos_instruments__()["pipettes"]
    star.load_liquid("assay_plate[A1:H1]", "water", 100)
    pipettes.pick_up_tips(tip_spots="tips[A1:H1]")
    assert star.__ivoryos_labware_state__()["channels"] == [True] * 8
    pipettes.aspirate(containers="assay_plate[A1:H1]", volumes="30, 30, 30, 30, 30, 30, 30, 30")
    pipettes.dispense(containers="sample_plate[A1:H1]", volumes=[30] * 8)
    pipettes.drop_tips(destinations="tips[A1:H1]")
    assert star.read_volumes("sample_plate[A1:B1]") == {"sample_plate[A1]": 30.0, "sample_plate[B1]": 30.0}
    assert star.__ivoryos_labware_state__()["labware"]["sample_plate"]["H1"]["liquids"] == {"water": 30.0}
    assert star.tips_left("tips") == 96


def test_star_refuses_what_pylabrobot_refuses(star):
    pipettes = star.__ivoryos_instruments__()["pipettes"]
    pipettes.pick_up_tips(tip_spots="tips[A1:H1]")
    with pytest.raises(ValueError, match="one entry per container"):
        pipettes.aspirate(containers="assay_plate[A1:H1]", volumes=[30])


def test_the_star_96_head_takes_a_whole_rack(star):
    head = star.__ivoryos_instruments__()["head96"]
    head.pick_up_tips(tip_rack="tips_b")
    assert star.tips_left("tips_b") == 0
    head.discard_tips()
    assert not star._any_tips()


def test_a_star_frame_is_the_files_deck_type(data_folder):
    robot = STAR(simulated=True, deck_type="STARDeck")
    assert robot.__ivoryos_labware__()["deck"]["label"] == "Hamilton STAR"
    assert len(robot.__ivoryos_labware__()["deck"]["rails"]) == 54
    with pytest.raises(ValueError, match="not something fitted to a STAR"):
        star_module.check_equipment({"gripper": True})


def test_a_star_worktable_edit_is_kept_in_the_file(star):
    placed = star.__ivoryos_labware_edit__("place", definition="Cor_96_wellplate_360ul_Fb", site="plate_carrier-3")
    star.__ivoryos_labware_edit__("liquid", labware=placed["name"], wells="A1", liquid="dye", volume_ul=50)
    again = STAR(simulated=True, worktable=star._path)
    assert again.read_volumes(f"{placed['name']}[A1]") == {f"{placed['name']}[A1]": 50.0}
    assert again.__ivoryos_labware__()["deck"]["pylabrobot_error"] is None


# --- Hamilton Prep (PyLabRobot's simulator) -----------------------------------------------------------

def test_a_simulated_prep_runs_its_channels_and_head():
    prep = Prep(simulated=True)
    try:
        parts = prep.__ivoryos_instruments__()
        assert set(parts) == {"pipettes", "head8", "core_grippers", "heater_shaker", "lights"}
        prep.load_liquid("assay_plate[A1:B1]", "buffer", 100)
        pipettes = parts["pipettes"]
        pipettes.pick_up_tips(tip_spots="tips[A1:B1]")
        pipettes.aspirate(containers="assay_plate[A1:B1]", volumes=[20, 20])
        pipettes.dispense(containers="sample_plate[A1:B1]", volumes=[20, 20])
        pipettes.discard_tips()
        assert prep.read_volumes("sample_plate[A1]") == {"sample_plate[A1]": 20.0}
        assert prep.__ivoryos_labware_state__()["labware"]["sample_plate"]["A1"]["liquids"] == {"buffer": 20.0}
        assert sorted(s["label"] for s in prep.__ivoryos_labware__()["sites"]) == [str(n) for n in range(8)]
    finally:
        prep.stop()
    assert "drop_tips" not in prep_module.SKIPPED["PrepPipettes"]


def test_a_real_prep_needs_a_host():
    with pytest.raises(ValueError, match="host"):
        Prep()
    with pytest.raises(ValueError, match="would be ignored"):
        Prep(host="10.0.0.9", simulated=True)


# --- Opentrons OT-2 (this package's simulated robot-server) -------------------------------------------

def test_a_simulated_ot2_runs_both_mounts():
    ot2 = OT2(simulated=True)
    try:
        parts = ot2.__ivoryos_instruments__()
        assert isinstance(parts["left"], OT2Pipette8) and isinstance(parts["right"], OT2Pipette1)
        ot2.load_liquid("assay_plate[A1:H1]", "water", 100)
        parts["left"].pick_up_tips(tip_spots="tips[A1:H1]")
        parts["left"].aspirate(containers="assay_plate[A1:H1]", volume=40)
        parts["left"].dispense(containers="sample_plate[A1:H1]", volume=40)
        parts["left"].discard_tips()
        parts["right"].pick_up_tip(tip_spot="tips[A2]")
        parts["right"].discard_tip()
        assert ot2.read_volumes("sample_plate[H1]") == {"sample_plate[H1]": 40.0}
        assert ot2.__ivoryos_labware_state__()["labware"]["sample_plate"]["A1"]["liquids"] == {"water": 40.0}
        assert ot2.tips_left("tips") == 87
        sent = {c["commandType"] for c in ot2._plr.io.log}
        assert {"loadPipette", "pickUpTip", "aspirateInPlace", "dispenseInPlace"} <= sent
    finally:
        ot2.stop()


def test_ot2_equipment_is_checked():
    assert ot2_equipment({"left": "p20_single_gen2"}) == {"left": "p20_single_gen2"}
    with pytest.raises(ValueError, match="not an OT-2 pipette"):
        ot2_equipment({"left": "p1000_single_flex"})
    with pytest.raises(ValueError, match="needs a pipette"):
        ot2_equipment({})
    with pytest.raises(ValueError, match="would be ignored"):
        OT2(host="10.0.0.6", simulated=True)


# --- pylabrobot.legacy: Nimbus, Vantage, EVO -----------------------------------------------------------

@pytest.mark.parametrize("cls", [Nimbus, Vantage])
def test_a_legacy_hamilton_moves_liquid_with_pylabrobots_own_steps(cls):
    lh = cls(simulated=True)
    try:
        lh.load_liquid("assay_plate[A1:H1]", "water", 100)
        lh.pick_up_tips(tip_spots="tips[A1:H1]")
        lh.aspirate(resources="assay_plate[A1:H1]", vols=[30] * 8)
        lh.dispense(resources="sample_plate[A1:H1]", vols=[30] * 8)
        lh.drop_tips(tip_spots="tips[A1:H1]")
        assert lh.read_volumes("sample_plate[A1]") == {"sample_plate[A1]": 30.0}
        assert lh.__ivoryos_labware_state__()["labware"]["sample_plate"]["A1"]["liquids"] == {"water": 30.0}
        assert lh.tips_left("tips") == 96
    finally:
        lh.stop()


def test_a_legacy_robot_moves_a_plate_to_a_carrier_position():
    lh = Vantage(simulated=True)
    try:
        lh.move_plate(plate="sample_plate", to="plate_carrier-4")
        assert lh._place_of(lh.deck.get_resource("sample_plate")) == "plate_carrier-4"
    finally:
        lh.stop()


def test_an_evo_worktable_has_rails_and_no_tips_yet():
    evo = EVO(simulated=True)
    layout = evo.__ivoryos_labware__()
    assert layout["deck"]["label"] == "Tecan Freedom EVO 150" and len(layout["deck"]["rails"]) == 45
    assert not any(v["category"] == "tip_rack" for v in layout["labware"].values())
    evo.load_liquid("assay_plate[A1]", "water", 100)
    assert evo.read_volumes("assay_plate[A1]") == {"assay_plate[A1]": 100.0}


def test_a_legacy_robot_needs_a_backend_or_simulated():
    with pytest.raises(ValueError, match="legacy backend"):
        LiquidHandler()
    with pytest.raises(ValueError, match="host"):
        Nimbus()
    assert LiquidHandler.KINDS[0] == "STARLetDeck" and "FlexDeck" not in LiquidHandler.KINDS


def test_every_steps_defaults_are_data_ivoryos_can_keep():
    """IvoryOS stores a deck's steps, with their defaults, as JSON: a Coordinate or enum default is
    shown as its fields or name, and made PyLabRobot's again when the step runs."""
    import json

    from plr_ivoryos.opentrons import flex, ot2
    classes = [STAR, *star_module.PART_CLASSES.values(), Prep, *prep_module.PART_CLASSES.values(), flex.Flex,
               flex.FlexPipette1, flex.FlexPipette8, flex.FlexPipette96, flex.FlexGripperPart, OT2, ot2.OT2Pipette1,
               ot2.OT2Pipette8, LiquidHandler]
    for cls in classes:
        for name in _steps(cls):
            for param in inspect.signature(getattr(cls, name)).parameters.values():
                if param.default is not inspect.Parameter.empty:
                    json.dumps(param.default)  # raises for a Coordinate or an enum member


def test_a_coordinate_or_enum_given_as_data_reaches_pylabrobot_as_its_own():
    lh = Vantage(simulated=True)
    try:
        lh.move_plate(plate="sample_plate", to="plate_carrier-4", pickup_direction="FRONT", drop_direction=1,
                      destination_offset={"x": 0, "y": 0, "z": 0})
        assert lh._place_of(lh.deck.get_resource("sample_plate")) == "plate_carrier-4"
    finally:
        lh.stop()
