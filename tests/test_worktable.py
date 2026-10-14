"""The worktable file on PyLabRobot 1.0: decks, slots, tracks, the catalogue, layouts from PyLabRobot."""

import json

import pytest
from pylabrobot.resources import OTDeck, STARLetDeck, Trash, cor_96_wellplate_360uL_Fb, opentrons_96_tiprack_300ul

from plr_ivoryos import bridge, worktable


def test_a_flex_worktable_puts_labware_in_lettered_slots_and_the_trash_bin_where_equipment_says():
    deck = worktable.build_deck({"deck_type": "FlexDeck", "equipment": {"trash": "a3"}, "resources": [
        {"name": "plate", "type": "cor_96_wellplate_360uL_Fb", "slot": "c2"},
        {"name": "staged", "type": "cor_96_wellplate_360uL_Fb", "slot": "D4"}]})
    assert deck.get_slot(deck.get_resource("plate")) == "C2"
    assert deck.get_slot(deck.get_resource("staged")) == "D4"
    assert isinstance(deck.get_trash_area(), Trash) and deck.get_slot(deck.get_trash_area()) == "A3"
    with pytest.raises(ValueError, match="'E1' is not a slot on a Flex"):
        worktable.build_deck({"deck_type": "FlexDeck", "resources": [
            {"name": "p", "type": "cor_96_wellplate_360uL_Fb", "slot": "E1"}]})


def test_a_hamilton_worktable_puts_carriers_on_tracks():
    deck = worktable.build_deck({"deck_type": "STARLetDeck", "resources": [
        {"name": "plates", "type": "hamilton_plate_carrier_L5_ac", "rails": 7, "children": [
            {"name": "plate", "type": "cor_96_wellplate_360uL_Fb", "site": 0}]}]})
    assert deck.get_resource("plate").parent.parent.name == "plates"
    tracks = worktable.rails_of(deck)
    assert len(tracks) == 30 and tracks[6]["rail"] == 7, "PyLabRobot 1.0 counts 30 tracks on a STARlet"


def test_the_catalogue_reads_each_definitions_class_not_its_name():
    by_name = {e["definition"]: e for e in worktable._all_definitions()}
    # PyLabRobot 1.0 split TipRack into standing and embedded racks: both are tip racks.
    assert by_name["flex_96_tiprack_200ul"]["category"] == "tip_rack"
    assert by_name["hamilton_96_tiprack_300uL_filter"]["category"] == "tip_rack"
    assert by_name["hamilton_plate_carrier_L5_ac"]["category"] == "carrier"
    assert "PLT_CAR_L5AC_A00" not in by_name, "an old spelling kept as an alias is left out"
    flex = {e["definition"] for e in worktable.catalog("FlexDeck")}
    assert "flex_96_tiprack_1000ul" in flex and "opentrons_96_tiprack_300ul" not in flex
    assert "hamilton_96_tiprack_300uL_filter" not in flex and "hamilton_plate_carrier_L5_ac" not in flex
    star = {e["definition"] for e in worktable.catalog("STARLetDeck")}
    assert "hamilton_plate_carrier_L5_ac" in star and "flex_96_tiprack_1000ul" not in star


def test_a_pylabrobot_deck_file_becomes_a_worktable_by_name():
    deck = OTDeck()
    deck.assign_child_at_slot(opentrons_96_tiprack_300ul(name="tips"), 1)
    deck.assign_child_at_slot(cor_96_wellplate_360uL_Fb(name="plate"), 5)
    config = worktable.read_layout(json.dumps(deck.serialize()))
    assert config["deck_type"] == "OTDeck"
    assert {"name": "plate", "type": "cor_96_wellplate_360uL_Fb", "slot": 5} in config["resources"]

    config = worktable.read_layout(json.dumps(STARLetDeck().serialize()))
    assert config == {"deck_type": "STARLetDeck", "resources": [], "liquids": []}


def test_a_layout_that_is_not_one_says_what_it_is():
    with pytest.raises(ValueError, match="not a JSON layout"):
        worktable.read_layout("{")
    with pytest.raises(ValueError, match="'EVO150Deck' is not a worktable this knows"):
        worktable.read_layout(json.dumps({"deck_type": "EVO150Deck", "resources": []}))
    with pytest.raises(ValueError, match="state file"):
        worktable.read_layout(json.dumps({"plate_well_A1": {"volume": 10}}))


def test_return_values_become_plain_data():
    from pylabrobot.resources import Coordinate
    from pylabrobot.opentrons.flex.pipette_defaults import FlowRates
    assert bridge.jsonable(Coordinate(1, 2, 3)) == {"x": 1, "y": 2, "z": 3}
    assert bridge.jsonable(FlowRates(1, 2, 3)) == {"aspirate": 1, "dispense": 2, "blow_out": 3}
    assert bridge.jsonable((cor_96_wellplate_360uL_Fb(name="p"), None)) == ["p", None]
    assert bridge._return_annotation(Coordinate) is Coordinate, "IvoryOS can save x, y and z"
    assert bridge._return_annotation(FlowRates) == bridge.Dict[str, bridge.Any]
