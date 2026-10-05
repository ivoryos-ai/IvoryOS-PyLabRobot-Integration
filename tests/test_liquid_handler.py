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
from plr_ivoryos.wells import expand_references, parse_references

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
        # Before 3.11, `Annotated[Optional[str], ...] = None` comes back wrapped in another Optional.
        for candidate in [hint, *(typing.get_args(hint) if typing.get_origin(hint) is typing.Union else ())]:
            if typing.get_origin(candidate) is typing.Annotated:
                for meta in typing.get_args(candidate)[1:]:
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


def test_wells_are_written_with_their_labware_as_pyLabRobot_writes_them():
    assert parse_references("assay_plate[A1:H1]") == [("assay_plate", "A1:H1")]
    assert parse_references("p1[A1, B2], p2[C3]; p3") == [("p1", "A1, B2"), ("p2", "C3"), ("p3", None)]
    assert parse_references(["p1[A1]", "p1[B1]"]) == [("p1", "A1"), ("p1", "B1")]
    grids, kinds = {"p1": PLATE96, "tips": PLATE96}, {"p1": "plate", "tips": "tip_rack"}
    assert expand_references("p1[A1:B1], p1[H12]", grids) == [("p1", "A1"), ("p1", "B1"), ("p1", "H12")]
    assert len(expand_references("p1", grids)) == 96, "a bare name is every well"
    for bad, why in [("A1", "write wells with their labware"), ("p9[A1]", "not on this worktable"),
                     ("p1[A13]", "'A13' is not a position on p1"), ("p1[A1", "labware\\[wells\\]")]:
        with pytest.raises(ValueError, match=why):
            expand_references(bad, grids)
    with pytest.raises(ValueError, match="is a tip rack, not a plate"):
        expand_references("tips[A1]", grids, kinds, ("plate",))


# --- what IvoryOS reads ---------------------------------------------------------------------------

def test_steps_say_which_arguments_are_labware_wells_and_values_per_well():
    found = markers(LiquidHandler.transfer)
    assert found["source"] == {"type": "wells", "wells": {"labware": ["plate", "reservoir", "tube_rack"]}}
    assert found["targets"] == found["source"]
    assert found["target_vols"]["per_well"] == "targets" and found["ratios"]["per_well"] == "targets"
    assert found["tip_rack"] == {"labware": ["tip_rack"]}
    assert markers(LiquidHandler.pick_up_tips)["tip_spots"] == {"type": "wells", "wells": {"labware": ["tip_rack"]}}
    assert markers(LiquidHandler.move_plate)["to"] == {"labware_site": True}
    # A plain class with plain methods: introspecting the class finds the steps (0.1 built a
    # class per instance, so a schema extractor had to construct one first).
    assert {"transfer", "aspirate", "dispense", "pick_up_tips", "move_plate"} <= set(vars(LiquidHandler))


def test_the_steps_keep_pyLabRobots_names_and_arguments():
    import inspect
    from pylabrobot.liquid_handling import LiquidHandler as PLR

    def arguments(cls, name):
        return [p for p in inspect.signature(getattr(cls, name)).parameters if p not in ("self", "backend_kwargs")]

    for step in ("transfer", "aspirate", "dispense", "pick_up_tips", "drop_tips", "return_tips", "discard_tips", "move_plate"):
        assert hasattr(PLR, step)
    # transfer: PyLabRobot's arguments, in its order, then ours.
    assert arguments(LiquidHandler, "transfer")[:7] == arguments(PLR, "transfer")
    for step in ("aspirate", "dispense", "pick_up_tips", "drop_tips"):
        ours, theirs = arguments(LiquidHandler, step), arguments(PLR, step)
        assert ours[:2] == theirs[:2], step  # resources/tip_spots, then vols/use_channels
        assert set(ours) - {"mix_volume", "mix_repetitions", "mix_flow_rate"} <= set(theirs), step
    assert arguments(LiquidHandler, "move_plate") == arguments(PLR, "move_plate")[:2]


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
    delivered = lh.transfer(source="reservoir[A1]", targets="assay_plate[A1:H3]", target_vols=100, tip_rack="tips_300")
    assert len(delivered) == 24 and set(delivered.values()) == {100.0}
    assert list(delivered)[:2] == ["assay_plate[A1]", "assay_plate[B1]"]
    assert lh.tips_left("tips_300") == 96 - 24
    assert lh.read_volumes("reservoir[A1]") == {"reservoir[A1]": 10000 - 2400}
    assert [e["action"] for e in events] == ["pick_up_tips", "aspirate", "dispense", "drop_tips"] * 3
    assert events[2]["labware"] == "assay_plate" and events[2]["wells"] == expand_wells("A1:H1", PLATE96)

    # One volume per well (as a list, or as text the way a form sends it), a well given 0 skipped,
    # and the rows of a batch step as a list of wells.
    second = lh.transfer(source="reservoir[A2]", targets=["assay_plate[A1]", "assay_plate[B1]", "assay_plate[C1]"],
                         target_vols="10, 0, 30", tip_rack="tips_300", new_tip="once", dispense_flow_rates=50,
                         mix_after_volume=20, mix_after_repetitions=2)
    assert second == {"assay_plate[A1]": 10.0, "assay_plate[C1]": 30.0}
    state = lh.__ivoryos_labware_state__()
    assert state["labware"]["assay_plate"]["A1"] == {"volume_ul": 110.0, "liquids": {"buffer": 100.0, "dye": 10.0}}
    assert state["labware"]["tips_300"]["A1"] == {"tip": False} and state["channels"] == [False] * 8


def test_pyLabRobots_transfer_split_by_source_vol_and_ratios(lh):
    """`lh.transfer(plate["A1"], plate["B1:C1"], source_vol=60, ratios=[2, 1])`, from its docstring."""
    assert lh.transfer(source="reservoir[A1]", targets="assay_plate[B1:C1]", source_vol=60, ratios=[2, 1],
                       tip_rack="tips_300") == {"assay_plate[B1]": 40.0, "assay_plate[C1]": 20.0}
    assert lh.transfer(source="reservoir[A1]", targets="assay_plate[A2:H2]", source_vol=80,
                       tip_rack="tips_300") == {f"assay_plate[{r}2]": 10.0 for r in "ABCDEFGH"}
    # Without tip_rack, as PyLabRobot's: the tips already on the head.
    lh.pick_up_tips("tips_300[A12:B12]")
    assert lh.transfer(source="reservoir[A1]", targets="assay_plate[A3:B3]", target_vols=[5, 6]) == \
        {"assay_plate[A3]": 5.0, "assay_plate[B3]": 6.0}
    assert lh.__ivoryos_labware_state__()["channels"][:2] == [True, True], "its tips stay on, as in PyLabRobot"


def test_single_steps_follow_the_tips_on_the_head(lh):
    assert lh.pick_up_tips("tips_300", use_channels=[0, 1]) == ["tips_300[A1]", "tips_300[B1]"]
    lh.aspirate("reservoir[A1]", vols=[40, 60], flow_rates=100)
    lh.dispense("assay_plate[A1:B1]", vols=[40, 60], mix_volume=20, mix_repetitions=2)
    lh.mix("assay_plate[A1:B1]", vols=10, repetitions=2)
    lh.return_tips()
    assert lh.read_volumes("assay_plate[A1:B1]") == {"assay_plate[A1]": 40.0, "assay_plate[B1]": 60.0}
    assert lh.tips_left("tips_300") == 96, "returned to where they came from"
    lh.pick_up_tips("tips_300[A1:B1]")
    with pytest.raises(Exception, match="already has a tip"):
        lh.drop_tips("tips_300[C1:D1]")  # PyLabRobot's own tip tracking: those spots are full
    lh.drop_tips("tips_300[B1], tips_300[A1]")  # swapped, both empty
    assert lh.tips_left("tips_300") == 96 and lh.__ivoryos_labware_state__()["channels"][:2] == [False, False]
    lh.load_liquid("assay_plate[C1]", "sample", 25)
    assert lh.__ivoryos_labware_state__()["labware"]["assay_plate"]["C1"]["liquids"] == {"sample": 25.0}


def test_what_cannot_be_done_is_said_before_anything_moves(lh):
    def refused(**changes):
        call = {"source": "reservoir[A1]", "targets": "assay_plate[A1]", "target_vols": 10, "tip_rack": "tips_300", **changes}
        with pytest.raises(ValueError) as error:
            lh.transfer(**{k: v for k, v in call.items() if v is not None})
        return str(error.value)

    assert "'A13' is not a position on assay_plate" in refused(targets="assay_plate[A13]")
    assert "'plate_9' is not on this worktable" in refused(targets="plate_9[A1]")
    assert "write wells with their labware" in refused(targets="A1")
    assert "is a tip rack, not a plate" in refused(targets="tips_300[A1]")
    assert "3 source wells for 2 targets" in refused(source="reservoir[A1:A3]", targets="assay_plate[A1:B1]")
    assert "2 values for 3 wells" in refused(targets="assay_plate[A1:C1]", target_vols=[1, 2])
    assert "not both" in refused(source_vol=10)
    assert "Give source_vol" in refused(target_vols=None)
    assert "no tips on the head" in refused(tip_rack=None)
    assert "no tips on the head" in refused(new_tip="never")
    with pytest.raises(ValueError, match="need 2 tips on the head"):
        lh.aspirate("reservoir[A1:A2]", vols=10)
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
    assert star.transfer(source="reservoir[A1]", targets="assay_plate[A1:H1]", target_vols=50,
                         tip_rack="tips_300") == {f"assay_plate[{r}1]": 50.0 for r in "ABCDEFGH"}


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
    lh.transfer(source="reservoir[A1]", targets="assay_plate[A1]", target_vols=10, tip_rack="tips_300")
    lh.__ivoryos_labware_edit__("deck", deck="STARLetDeck")
    assert lh.__ivoryos_labware__()["deck"]["kind"] == "STARLetDeck"
    assert lh.read_volumes("assay_plate[A1]") == {"assay_plate[A1]": 0}, "a new worktable starts clean"
    assert lh.transfer(source="reservoir[A1]", targets="assay_plate[A1]", target_vols=10,
                       tip_rack="tips_300") == {"assay_plate[A1]": 10.0}
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
