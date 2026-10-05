"""The LiquidHandler on PyLabRobot's simulator: worktable files, steps, and what IvoryOS reads.

    pytest tests/test_liquid_handler.py

Nothing here imports IvoryOS: what IvoryOS reads (argument markers, `__ivoryos_labware__`) is
checked the way it reads them, by duck typing.
"""

import json
import os
import typing

import pytest

from plr_ivoryos import LiquidHandler, expand_wells, worktable

HERE = os.path.dirname(__file__)
PLATE96 = [[f"{chr(65 + r)}{c + 1}" for c in range(12)] for r in range(8)]
OT2 = {"deck_type": "OTDeck", "resources": [
    {"name": "tips_300", "type": "opentrons_96_tiprack_300ul", "slot": 1},
    {"name": "reservoir", "type": "nest_12_troughplate_15000uL_Vb", "slot": 2},
    {"name": "assay_plate", "type": "cor_96_wellplate_360uL_Fb", "slot": 5},
], "liquids": [{"labware": "reservoir", "wells": "A1", "liquid": "buffer", "volume_ul": 10000},
               {"labware": "reservoir", "wells": "A2", "liquid": "dye", "volume_ul": 5000}]}


def write(tmp_path, config, name="worktable.json"):
    path = tmp_path / name
    path.write_text(json.dumps(config))
    return str(path)


@pytest.fixture
def lh(tmp_path, capsys):
    return LiquidHandler(simulated=True, deck_json=write(tmp_path, OT2))


def markers(method):
    """What IvoryOS NextGen adds to each parameter's schema entry."""
    out = {}
    for name, hint in typing.get_type_hints(method, include_extras=True).items():
        if typing.get_origin(hint) is typing.Annotated:
            for meta in typing.get_args(hint)[1:]:
                if hasattr(meta, "ivoryos_schema"):
                    out.setdefault(name, {}).update(meta.ivoryos_schema())
    return out


# --- well selections ------------------------------------------------------------------------------

def test_a_selection_runs_down_a_column_along_a_row_or_over_a_rectangle_column_by_column():
    assert expand_wells("A1:H1", PLATE96) == [f"{r}1" for r in "ABCDEFGH"]
    assert expand_wells("A1:A4", PLATE96) == ["A1", "A2", "A3", "A4"]
    assert expand_wells("A1:B2", PLATE96) == ["A1", "B1", "A2", "B2"]
    assert expand_wells("A1:H1, A3 B3", PLATE96)[-3:] == ["H1", "A3", "B3"]
    assert len(expand_wells("all", PLATE96)) == 96
    for bad in ("A13", "A1:H13", "a1"):
        with pytest.raises(ValueError, match="is not a position"):
            expand_wells(bad, PLATE96)


# --- what IvoryOS reads ---------------------------------------------------------------------------

def test_steps_say_which_arguments_are_labware_wells_and_values_per_well():
    found = markers(LiquidHandler.transfer)
    assert found["source"] == {"labware": ["plate", "reservoir", "tube_rack"]}
    assert found["dest_wells"] == {"type": "wells", "wells": {"on": "dest"}}
    assert found["vols"]["per_well"] == "dest_wells"
    assert found["tip_rack"] == {"labware": ["tip_rack"]}
    assert markers(LiquidHandler.move_plate)["to"] == {"labware_site": True}
    # A plain class with plain methods: introspecting the class finds the steps (0.1 built a
    # class per instance, so a schema extractor had to construct one first).
    assert {"transfer", "aspirate", "dispense", "pick_up_tips", "move_plate"} <= set(vars(LiquidHandler))


def test_the_worktable_is_reported_from_the_file(lh):
    layout = lh.__ivoryos_labware__()
    assert layout["deck"]["kind"] == "OTDeck" and layout["deck"]["label"] == "Opentrons OT-2"
    assert layout["deck"]["simulated"] is True
    plate = layout["labware"]["assay_plate"]
    assert plate["category"] == "plate" and plate["site"] == "5" and plate["max_volume_ul"] == 360
    assert len(plate["grid"]) == 8 and plate["grid"][7][11] == "H12" and len(plate["spots"]) == 96
    assert layout["labware"]["reservoir"]["category"] == "reservoir"
    assert set(layout["labware"]) == {"tips_300", "reservoir", "assay_plate"}, "the trash is not a place to pipette"
    assert [f["category"] for f in layout["fixtures"]] == ["trash"] and len(layout["sites"]) == 12
    state = lh.__ivoryos_labware_state__()
    assert state["labware"]["reservoir"]["A2"] == {"volume_ul": 5000.0, "liquids": {"dye": 5000.0}}


# --- steps ----------------------------------------------------------------------------------------

def test_a_reservoir_feeds_three_columns_eight_channels_at_a_time(lh):
    events = []
    lh.__ivoryos_labware_events__(events.append)
    delivered = lh.transfer(source="reservoir", source_wells="A1", dest="assay_plate", dest_wells="A1:H3",
                            vols=100, tip_rack="tips_300")
    assert len(delivered) == 24 and set(delivered.values()) == {100.0}
    assert lh.tips_left("tips_300") == 96 - 24
    assert lh.read_volumes("reservoir", "A1") == {"A1": 10000 - 2400}
    assert [e["action"] for e in events] == ["pick_up_tips", "aspirate", "dispense", "drop_tips"] * 3
    assert events[2]["labware"] == "assay_plate" and events[2]["wells"] == expand_wells("A1:H1", PLATE96)

    # One volume per well (as a list, or as text the way a form sends it), a well given 0 skipped.
    second = lh.transfer(source="reservoir", source_wells="A2", dest="assay_plate", dest_wells=["A1", "B1", "C1"],
                         vols="10, 0, 30", tip_rack="tips_300", new_tip="once", dispense_flow_rate=50,
                         mix_after_volume=20, mix_after_repetitions=2)
    assert second == {"A1": 10.0, "C1": 30.0}
    state = lh.__ivoryos_labware_state__()
    assert state["labware"]["assay_plate"]["A1"] == {"volume_ul": 110.0, "liquids": {"buffer": 100.0, "dye": 10.0}}
    assert state["labware"]["tips_300"]["A1"] == {"tip": False} and state["channels"] == [False] * 8


def test_single_steps_follow_the_tips_on_the_head(lh):
    assert lh.pick_up_tips("tips_300", count=2) == ["A1", "B1"]
    lh.aspirate("reservoir", "A1", vols=[40, 60], flow_rates=100)
    lh.dispense("assay_plate", "A1:B1", vols=[40, 60], mix_volume=20, mix_repetitions=2)
    lh.mix("assay_plate", "A1:B1", vols=10, repetitions=2)
    lh.return_tips()
    assert lh.read_volumes("assay_plate", "A1:B1") == {"A1": 40.0, "B1": 60.0}
    assert lh.tips_left("tips_300") == 96, "returned to where they came from"
    lh.load_liquid("assay_plate", "C1", "sample", 25)
    assert lh.__ivoryos_labware_state__()["labware"]["assay_plate"]["C1"]["liquids"] == {"sample": 25.0}


def test_what_cannot_be_done_is_said_before_anything_moves(lh):
    def refused(**changes):
        call = {"source": "reservoir", "source_wells": "A1", "dest": "assay_plate", "dest_wells": "A1",
                "vols": 10, "tip_rack": "tips_300", **changes}
        with pytest.raises(ValueError) as error:
            lh.transfer(**call)
        return str(error.value)

    assert "'A13' is not a position on assay_plate" in refused(dest_wells="A13")
    assert "not a labware on this worktable" in refused(dest="plate_9")
    assert "do not pair up" in refused(source_wells="A1:A3", dest_wells="A1:B1")
    assert "2 values for 3 wells" in refused(dest_wells="A1:C1", vols=[1, 2])
    assert "no tips are on the head" in refused(new_tip="never")
    with pytest.raises(ValueError, match="need 2 tips on the head"):
        lh.aspirate("reservoir", "A1:A2", vols=10)
    assert lh.tips_left("tips_300") == 96


def test_moving_a_plate(lh):
    lh.move_plate("assay_plate", "6")
    layout = lh.__ivoryos_labware__()
    assert layout["labware"]["assay_plate"]["site"] == "6"
    assert next(s for s in layout["sites"] if s["label"] == "5")["holds"] is None
    with pytest.raises(ValueError, match="already holds reservoir"):
        lh.move_plate("assay_plate", "2")


# --- worktable files ------------------------------------------------------------------------------

def test_a_hamilton_worktable_puts_labware_on_carriers(tmp_path, capsys):
    star = LiquidHandler(simulated=True, deck_json=write(tmp_path, worktable.starter("STARLetDeck")))
    layout = star.__ivoryos_labware__()
    assert layout["deck"]["kind"] == "STARLetDeck" and layout["deck"]["label"] == "Hamilton STARlet"
    assert layout["labware"]["assay_plate"]["site"] == "plate_carrier-1"
    assert {f["name"] for f in layout["fixtures"] if f["category"] == "carrier"} == {"tip_carrier", "plate_carrier"}
    # The same names on every robot's starter, so one workflow runs on either.
    assert star.transfer(source="reservoir", source_wells="A1", dest="assay_plate", dest_wells="A1:H1",
                         vols=50, tip_rack="tips_300") == {f"{r}1": 50.0 for r in "ABCDEFGH"}


def test_a_layout_written_for_0_1_still_loads(capsys):
    old = LiquidHandler(simulated=True, deck_json=os.path.join(HERE, "layout.json"))
    assert "source_plate" in old.__ivoryos_labware__()["labware"]


def test_simulated_with_no_file_starts_from_a_working_worktable(capsys):
    lh = LiquidHandler(simulated=True)
    assert {"tips_300", "reservoir", "assay_plate"} <= set(lh.__ivoryos_labware__()["labware"])
    assert lh.__ivoryos_labware_catalog__() == {"labware": [], "decks": [], "deck": "STARLetDeck"}, \
        "no file to save to, so nothing to edit"


def test_a_missing_file_or_bad_definition_is_said_plainly(tmp_path):
    from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
    with pytest.raises(FileNotFoundError, match="Worktable file not found"):
        LiquidHandler(backend=LiquidHandlerChatterboxBackend(), deck_json=str(tmp_path / "nope.json"))
    bad = {"deck_type": "OTDeck", "resources": [{"name": "p", "type": "cor_96_wellplate_360ul", "slot": 1}]}
    with pytest.raises(ValueError, match="Did you mean"):
        LiquidHandler(simulated=True, deck_json=write(tmp_path, bad))


def test_the_worktable_is_edited_and_saved_and_used_next_time(tmp_path, capsys):
    path = write(tmp_path, OT2)
    lh = LiquidHandler(simulated=True, deck_json=path)
    catalog = lh.__ivoryos_labware_catalog__()
    kinds = {e["definition"]: e["category"] for e in catalog["labware"]}
    assert kinds["cor_96_wellplate_360uL_Fb"] == "plate" and kinds["opentrons_96_tiprack_300ul"] == "tip_rack"
    assert kinds["nest_12_troughplate_15000uL_Vb"] == "reservoir"
    assert "Cor_96_wellplate_360ul_Fb" not in kinds, "a deprecated alias is not offered twice"
    assert catalog["deck"] == "OTDeck" and "STARLetDeck" in [d["kind"] for d in catalog["decks"]]

    seen = []
    lh.__ivoryos_labware_events__(seen.append)
    lh.__ivoryos_labware_edit__("place", site="6", definition="cor_96_wellplate_360uL_Fb", name="plate_2")
    assert lh.__ivoryos_labware__()["labware"]["plate_2"]["site"] == "6" and seen[-1]["action"] == "layout"
    for change, why in [
        ({"site": "6", "definition": "cor_96_wellplate_360uL_Fb", "name": "plate_3"}, "already holds plate_2"),
        ({"site": "7", "definition": "cor_96_wellplate_360uL_Fb", "name": "plate_2"}, "already called 'plate_2'"),
        ({"site": "7", "definition": "cor_96_wellplate_360uL_Fb", "name": "my plate"}, "starts with a letter"),
        ({"site": "7", "definition": "no_such_plate", "name": "plate_3"}, "not a deck or labware definition"),
        ({"site": "99", "definition": "cor_96_wellplate_360uL_Fb", "name": "plate_3"}, "not a place"),
    ]:
        with pytest.raises(ValueError, match=why):
            lh.__ivoryos_labware_edit__("place", **change)
    lh.__ivoryos_labware_edit__("remove", name="reservoir")

    saved = json.loads(open(path).read())
    assert saved["format"] == worktable.FORMAT
    assert [e["name"] for e in saved["resources"]] == ["tips_300", "assay_plate", "plate_2"]
    assert saved["liquids"] == [], "a liquid for a labware that is gone is dropped with it"
    again = LiquidHandler(simulated=True, deck_json=path)
    assert set(again.__ivoryos_labware__()["labware"]) == {"tips_300", "assay_plate", "plate_2"}


def test_a_carrier_position_is_filled_and_emptied_the_same_way(tmp_path, capsys):
    path = write(tmp_path, {"deck_type": "STARLetDeck",
                            "resources": [{"name": "plates", "type": "PLT_CAR_L5AC_A00", "rails": 15}]})
    LiquidHandler(simulated=True, deck_json=path).__ivoryos_labware_edit__(
        "place", site="plates-2", definition="cor_96_wellplate_360uL_Fb", name="assay_plate")
    again = LiquidHandler(simulated=True, deck_json=path)
    assert again.__ivoryos_labware__()["labware"]["assay_plate"]["site"] == "plates-2"
    again.__ivoryos_labware_edit__("remove", name="assay_plate")
    left = LiquidHandler(simulated=True, deck_json=path).__ivoryos_labware__()["labware"]
    assert set(left) == {"teaching_tip_rack"}, "only what the deck itself comes with"


def test_the_simulator_switches_robot_from_configuration_not_a_flag(tmp_path, capsys):
    path = write(tmp_path, OT2)
    lh = LiquidHandler(simulated=True, deck_json=path)
    lh.transfer(source="reservoir", source_wells="A1", dest="assay_plate", dest_wells="A1", vols=10, tip_rack="tips_300")
    lh.__ivoryos_labware_edit__("deck", deck="STARLetDeck")
    assert lh.__ivoryos_labware__()["deck"]["kind"] == "STARLetDeck"
    assert lh.read_volumes("assay_plate", "A1") == {"A1": 0}, "a new worktable starts clean"
    assert lh.transfer(source="reservoir", source_wells="A1", dest="assay_plate", dest_wells="A1",
                       vols=10, tip_rack="tips_300") == {"A1": 10.0}
    assert LiquidHandler(simulated=True, deck_json=path).__ivoryos_labware__()["deck"]["kind"] == "STARLetDeck"
    with pytest.raises(ValueError, match="not a robot"):
        lh.__ivoryos_labware_edit__("deck", deck="VantageDeck")


def test_a_real_robot_or_a_deck_built_in_code_is_not_rearranged_from_ivoryos(tmp_path, capsys):
    from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend

    class Robot(LiquidHandlerChatterboxBackend):  # stands in for a real backend: not the simulator by name
        pass

    real = LiquidHandler(backend=Robot(), deck_json=write(tmp_path, OT2))
    assert real.__ivoryos_labware_catalog__()["decks"] == [] and real.__ivoryos_labware_catalog__()["labware"]
    real.__ivoryos_labware_edit__("place", site="7", definition="cor_96_wellplate_360uL_Fb", name="extra")
    with pytest.raises(ValueError, match="only the simulator"):
        real.__ivoryos_labware_edit__("deck", deck="STARLetDeck")

    built = LiquidHandler(simulated=True, deck=worktable.build_deck(OT2))
    assert built.__ivoryos_labware_catalog__()["labware"] == []
    with pytest.raises(ValueError, match="no file to save to"):
        built.__ivoryos_labware_edit__("remove", name="assay_plate")
