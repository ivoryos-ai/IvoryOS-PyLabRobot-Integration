"""An Opentrons Flex through PyLabRobot 1.0, on the simulated robot-server.

Everything above the HTTP transport is PyLabRobot's own Flex, so what passes here is what PyLabRobot
accepts: its tip and volume tracking, and its refusals.
"""

import asyncio
import inspect
import json
import os

import pytest
from pylabrobot.opentrons import Flex as PLRFlex
from pylabrobot.opentrons.flex.flex_gripper import FlexGripper
from pylabrobot.opentrons.flex.flex_head import FlexHead1, FlexHead8, FlexHead96
from pylabrobot.resources import (FlexDeck, cor_96_wellplate_360uL_Fb, flex_96_tiprack_200ul, set_tip_tracking,
                                  set_volume_tracking)

from plr_ivoryos import worktable
from plr_ivoryos.opentrons import (Flex, FlexGripperPart, FlexPipette1, FlexPipette8, FlexPipette96,
                                   SimulatedFlexServer, check_equipment)
from plr_ivoryos.opentrons.flex import SKIPPED

from conftest import write

FILE = {"deck_type": "FlexDeck",
        "equipment": {"left": "p1000_multi_flex", "right": "p1000_single_flex", "gripper": True, "trash": "A3"},
        "resources": [
            {"name": "tips", "type": "flex_96_tiprack_200ul", "slot": "C1"},
            {"name": "reservoir", "type": "nest_12_troughplate_15000uL_Vb", "slot": "C2"},
            {"name": "assay_plate", "type": "cor_96_wellplate_360uL_Fb", "slot": "D2"},
        ],
        "liquids": [{"labware": "reservoir", "wells": "A1", "liquid": "buffer", "volume_ul": 10000},
                    {"labware": "reservoir", "wells": "A2", "liquid": "dye", "volume_ul": 5000}]}


@pytest.fixture
def flex(data_folder):
    robot = Flex(simulated=True, worktable=write(data_folder, FILE))
    yield robot
    robot.stop()


# --- the simulated robot-server, under PyLabRobot's own Flex -----------------------------------------

def test_pylabrobots_flex_runs_a_whole_session_against_the_simulator():
    set_tip_tracking(True)
    set_volume_tracking(True)
    deck = FlexDeck()
    tips, plate = flex_96_tiprack_200ul(name="tips"), cor_96_wellplate_360uL_Fb(name="plate")
    deck.assign_child_at_slot(tips, "C1")
    deck.assign_child_at_slot(plate, "C2")
    plate.get_item("A1").tracker.set_volume(100)
    server = SimulatedFlexServer({"left": "p1000_single_flex"}, gripper=True)
    robot = PLRFlex(host="simulated", io=server, deck=deck, command_poll_interval=0)

    async def session():
        await robot.setup()
        assert isinstance(robot.left, FlexHead1) and robot.right is None and robot.gripper is not None
        await robot.left.pick_up_tips(tips.get_item("A1"))
        await robot.left.aspirate(plate.get_item("A1"), 40)
        await robot.left.dispense(plate.get_item("B1"), 40)
        await robot.left.discard_tips(robot.deck.get_trash_area())
        await robot.gripper.move_labware(plate, "D2")
        await robot.stop()

    asyncio.run(session())
    assert plate.get_item("B1").tracker.get_used_volume() == 40
    assert robot.deck.get_slot(plate) == "D2"
    sent = [c["commandType"] for c in server.log]
    assert {"loadPipette", "pickUpTip", "aspirateInPlace", "dispenseInPlace", "moveLabware"} <= set(sent)
    assert server.runs and all(run["status"] == "stopped" for run in server.runs.values())


def test_the_tip_sensor_reads_what_was_picked_up_and_dropped():
    server = SimulatedFlexServer({"right": "p50_single_flex"}, gripper=False)
    run = {"status": "idle", "commands": {}, "tips": {}}
    assert server._execute(run, "getTipPresence", {"pipetteId": "p"})[1] == {"status": "unknown"}
    server._execute(run, "pickUpTip", {"pipetteId": "p"})
    assert server._execute(run, "getTipPresence", {"pipetteId": "p"})[1] == {"status": "present"}
    assert server._execute(run, "verifyTipPresence", {"pipetteId": "p", "expectedState": "absent"})[0] == "failed"


# --- what is mounted ------------------------------------------------------------------------------------

def test_each_mounted_thing_is_an_instrument_of_the_class_its_channels_say(flex):
    parts = flex.__ivoryos_instruments__()
    assert list(parts) == ["left", "right", "gripper"]
    assert isinstance(parts["left"], FlexPipette8) and isinstance(parts["right"], FlexPipette1)
    assert isinstance(parts["gripper"], FlexGripperPart)


def test_a_96_channel_head_is_one_part_and_takes_both_mounts(data_folder):
    robot = Flex(simulated=True, worktable=write(data_folder, {**FILE, "equipment": {"head96": "p200_96", "trash": "A3"}}))
    assert list(robot.__ivoryos_instruments__()) == ["head96"]
    assert isinstance(robot.__ivoryos_instruments__()["head96"], FlexPipette96)
    robot.setup()
    assert isinstance(robot._plr.head96, FlexHead96)
    robot.stop()


@pytest.mark.parametrize("equipment, problem", [
    ({"left": "p1000_96"}, "goes on the 96-channel position"),
    ({"head96": "p1000_96", "left": "p50_single_flex"}, "takes both mounts"),
    ({"left": "p300_single_gen2"}, "is not a Flex pipette"),
    ({"gripper": True}, "needs a pipette"),
    ({"left": "p50_single_flex", "trash": "B2"}, "A trash bin goes in"),
    ({"left": "p50_single_flex", "tool": "x"}, "is not something fitted"),
])
def test_equipment_that_cannot_be_is_refused_saying_why(equipment, problem):
    with pytest.raises(ValueError, match=problem):
        check_equipment(equipment)


def test_a_simulated_flex_with_no_file_starts_from_a_ready_made_one(data_folder):
    robot = Flex(simulated=True)
    assert robot.equipment == {"left": "p1000_multi_flex", "right": "p1000_single_flex", "gripper": True, "trash": "A3"}
    assert {"tips", "reservoir", "assay_plate"} <= set(robot.__ivoryos_labware__()["labware"])
    assert not os.path.exists(os.path.join(str(data_folder), "worktable.json")), "written on the first change"


def test_equipment_given_starts_the_file_and_the_file_wins_after(data_folder):
    path = os.path.join(str(data_folder), "w.json")
    robot = Flex(simulated=True, worktable=path, equipment={"right": "p50_single_flex", "trash": "D1"})
    assert list(robot.__ivoryos_instruments__()) == ["right"]
    robot.__ivoryos_labware_edit__("liquid", labware="reservoir", wells="A3", liquid="water", volume_ul=100)
    again = Flex(simulated=True, worktable=path, equipment={"left": "p1000_multi_flex"})
    assert again.equipment["right"] == "p50_single_flex" and "left" not in again.equipment


def test_the_robot_having_something_else_mounted_stops_the_first_step(flex):
    flex._plr.io.mounts = {"left": "p50_single_flex"}  # what the robot reports, unlike the file
    with pytest.raises(RuntimeError) as e:
        flex.__ivoryos_instruments__()["left"].pick_up_tips("tips", column=0)
    assert "left has a 1-channel pipette (the file says p1000_multi_flex)" in str(e.value)
    assert "nothing is on right" in str(e.value) and "Change equipment" in str(e.value)


def test_a_real_flex_that_cannot_be_asked_what_it_has_says_how_to_go_on(data_folder):
    with pytest.raises(ValueError) as e:
        Flex(host="127.0.0.1", port=9, worktable="real.json", command_timeout=2)
    assert "does not say what is mounted" in str(e.value) and "write equipment in the file" in str(e.value)


# --- steps are PyLabRobot's own -------------------------------------------------------------------------

@pytest.mark.parametrize("ours, theirs", [(FlexPipette1, FlexHead1), (FlexPipette8, FlexHead8),
                                          (FlexPipette96, FlexHead96), (FlexGripperPart, FlexGripper)])
def test_every_public_method_is_a_step_with_pylabrobots_names(ours, theirs):
    public = {n for n in dir(theirs) if not n.startswith("_") and callable(getattr(theirs, n))
              and not isinstance(inspect.getattr_static(theirs, n), property)}
    steps = {n for n, v in vars(ours).items() if callable(v) and not n.startswith("_")}
    assert public == steps
    assert SKIPPED[ours.__name__] == {}
    for name in public:
        plr = [p for p in inspect.signature(getattr(theirs, name)).parameters if p != "self"]
        mine = [p for p in inspect.signature(getattr(ours, name)).parameters if p != "self"]
        assert mine == plr, name


def test_wells_and_labware_are_text_and_plain_values_stay_as_they_are():
    aspirate = inspect.signature(FlexPipette8.aspirate).parameters
    marker = aspirate["target"].annotation.__metadata__[0]
    assert marker.ivoryos_schema() == {"type": "wells", "wells": {"labware": ["plate", "reservoir", "tube_rack"]}}
    assert aspirate["volume"].annotation is float
    assert aspirate["column"].kind is inspect.Parameter.KEYWORD_ONLY, "PyLabRobot's kinds are kept"
    discard = inspect.signature(FlexPipette1.discard_tips).parameters["trash"]
    assert discard.default == "trash" and discard.annotation.__metadata__[0].ivoryos_schema() == {"labware": ["trash"]}
    move = inspect.signature(FlexGripperPart.move_labware).parameters
    assert move["to_slot"].annotation.__metadata__[0].ivoryos_schema() == {"labware_site": True}


def test_a_step_reads_text_as_pylabrobot_objects_and_says_what_it_cannot_read(flex):
    left, right = flex.__ivoryos_instruments__()["left"], flex.__ivoryos_instruments__()["right"]
    with pytest.raises(ValueError, match="target takes one well; 'assay_plate\\[A1:B1\\]' names 2"):
        right.aspirate("assay_plate[A1:B1]", 10)
    with pytest.raises(ValueError, match="'plate_9' is not on this worktable"):
        right.aspirate("plate_9[A1]", 10)
    with pytest.raises(ValueError, match="use_channels: expected a list of int"):
        left.pick_up_tips("tips", column=0, use_channels="one, two")


# --- a run, as the Labware view sees it ---------------------------------------------------------------

def test_liquids_follow_each_channel_and_the_view_hears_every_step(flex):
    events = []
    flex.__ivoryos_labware_events__(events.append)
    left, right = flex.__ivoryos_instruments__()["left"], flex.__ivoryos_instruments__()["right"]
    left.pick_up_tips("tips", column=0)
    left.aspirate_container("reservoir[A2]", 40)
    left.dispense("assay_plate[A1:H1]", 40)
    left.discard_tips()
    right.pick_up_tips("tips[A12]")
    right.aspirate("reservoir[A1]", 100)
    right.dispense("assay_plate[A1]", 100)
    right.drop_tips("trash")
    state = flex.__ivoryos_labware_state__()["labware"]
    assert state["assay_plate"]["A1"] == {"volume_ul": 140, "liquids": {"dye": 40.0, "buffer": 100.0}}
    assert state["assay_plate"]["H1"] == {"volume_ul": 40, "liquids": {"dye": 40.0}}
    assert state["reservoir"]["A2"]["volume_ul"] == 5000 - 8 * 40
    assert sum(1 for spot in state["tips"].values() if not spot["tip"]) == 9
    assert [(e["action"], e["labware"]) for e in events] == [
        ("pick_up_tips", "tips"), ("aspirate", "reservoir"), ("dispense", "assay_plate"), ("drop_tips", None),
        ("pick_up_tips", "tips"), ("aspirate", "reservoir"), ("dispense", "assay_plate"), ("drop_tips", None)]
    assert flex.read_volumes("assay_plate[A1, H1]") == {"assay_plate[A1]": 140, "assay_plate[H1]": 40}
    assert flex.tips_left("tips") == 96 - 9


def test_the_gripper_moves_labware_and_the_drawing_follows(flex):
    events = []
    flex.__ivoryos_labware_events__(events.append)
    flex.__ivoryos_instruments__()["gripper"].move_labware("assay_plate", "B2")
    assert flex.__ivoryos_labware__()["labware"]["assay_plate"]["site"] == "B2"
    assert ("move", "assay_plate") in [(e["action"], e["labware"]) for e in events]


def test_pylabrobots_refusals_reach_the_step(flex):
    left = flex.__ivoryos_instruments__()["left"]
    left.pick_up_tips("tips", column=0)
    with pytest.raises(RuntimeError, match="Single-tip op requires exactly one mounted tip"):
        left.aspirate("reservoir[A1]", 10)  # eight tips in one trough well: PyLabRobot's aspirate_container


def test_stop_hands_the_robot_back_and_the_next_step_takes_it_again(flex):
    right = flex.__ivoryos_instruments__()["right"]
    right.pick_up_tips("tips[A1]")
    flex.stop()
    assert not flex._ready and flex._tip_count("right") == 0
    right.pick_up_tips("tips[B1]")
    assert flex._ready and flex._tip_count("right") == 1


# --- the worktable and the Labware view ---------------------------------------------------------------

def test_the_flex_draws_its_slots_its_trash_and_its_equipment(flex):
    layout = flex.__ivoryos_labware__()
    assert layout["deck"]["kind"] == "FlexDeck" and layout["deck"]["label"] == "Opentrons Flex"
    assert layout["deck"]["equipment"]["left"] == "p1000_multi_flex"
    assert layout["deck"]["equipment"]["labels"]["left"] == "Flex 8-Channel 1000 µL"
    labels = [s["label"] for s in layout["sites"]]
    assert "A3" not in labels and {"C1", "D4"} <= set(labels), "the trash slot is not a place for labware"
    assert [f["category"] for f in layout["fixtures"]] == ["trash"]
    assert layout["labware"]["assay_plate"]["site"] == "D2"
    part = flex.__ivoryos_instruments__()["left"].__ivoryos_labware__()
    assert "deck" not in part and part["labware"]["trash"]["category"] == "trash"


def test_labware_is_placed_moved_renamed_and_removed_in_the_file(flex, data_folder):
    edit = flex.__ivoryos_labware_edit__
    assert edit("place", definition="cor_96_wellplate_360uL_Fb", site="d3") == {"name": "plate_1", "restart": True}
    edit("liquid", labware="plate_1", wells="A1:H1", liquid="sample", volume_ul=50)
    edit("move", name="plate_1", site="B3")
    edit("rename", name="plate_1", to="samples")
    saved = json.load(open(os.path.join(str(data_folder), "worktable.json")))
    entry = next(e for e in saved["resources"] if e["name"] == "samples")
    assert entry == {"name": "samples", "type": "cor_96_wellplate_360uL_Fb", "slot": "B3"}
    assert {"labware": "samples", "wells": "A1:H1", "liquid": "sample", "volume_ul": 50.0} in saved["liquids"]
    state = flex.__ivoryos_labware_state__()["labware"]["samples"]
    assert state["H1"] == {"volume_ul": 50.0, "liquids": {"sample": 50.0}}, "a renamed plate holds what it held"
    with pytest.raises(ValueError, match="B3 already holds samples"):
        edit("place", definition="flex_96_tiprack_200ul", site="B3")
    with pytest.raises(ValueError, match="already called 'trash'"):
        edit("rename", name="samples", to="trash")
    edit("remove", name="samples")
    assert "samples" not in flex.__ivoryos_labware__()["labware"]


def test_a_renamed_tip_rack_keeps_its_used_tips(flex):
    flex.__ivoryos_instruments__()["right"].pick_up_tips("tips[A1]")
    flex.__ivoryos_instruments__()["right"].drop_tips("trash")
    flex.__ivoryos_labware_edit__("rename", name="tips", to="tips_200")
    assert flex.tips_left("tips_200") == 95


def test_the_catalogue_is_what_fits_a_flex(flex):
    catalog = flex.__ivoryos_labware_catalog__()
    names = {e["definition"]: e["category"] for e in catalog["labware"]}
    assert names["flex_96_tiprack_200ul"] == "tip_rack" and "opentrons_96_tiprack_300ul" not in names
    assert names["cor_96_wellplate_360uL_Fb"] == "plate" and "carrier" not in names.values()
    assert catalog["decks"] == [], "a Flex is a Flex"
    assert {"p1000_multi_flex", "p200_96"} <= {p["name"] for p in catalog["equipment"]["pipettes"]}


def test_equipment_changes_in_the_file_and_after_a_restart(flex, data_folder):
    assert flex.__ivoryos_labware_edit__("equipment", right="p50_single_flex", trash="D1") == \
        {"name": "equipment", "restart": True}
    saved = json.load(open(os.path.join(str(data_folder), "worktable.json")))
    assert saved["equipment"] == {"left": "p1000_multi_flex", "right": "p50_single_flex", "gripper": True, "trash": "D1"}
    assert [f for f in flex.__ivoryos_labware__()["fixtures"] if f["category"] == "trash"][0]["x"] == 0
    with pytest.raises(ValueError, match="C1 holds tips"):
        flex.__ivoryos_labware_edit__("equipment", trash="C1")
    flex.__ivoryos_labware_edit__("equipment", head96="p1000_96")
    assert set(json.load(open(os.path.join(str(data_folder), "worktable.json")))["equipment"]) == {"head96", "gripper", "trash"}


def test_a_connected_simulated_flex_starts_a_fresh_session_after_a_change(flex):
    flex.setup()
    flex.__ivoryos_labware_edit__("place", definition="cor_96_wellplate_360uL_Fb", site="B2", name="extra")
    assert not flex._ready
    flex.__ivoryos_instruments__()["gripper"].move_labware("extra", "B3")
    assert flex.__ivoryos_labware__()["labware"]["extra"]["site"] == "B3"


def test_another_layout_is_imported_and_the_old_file_kept(flex, data_folder):
    other = {"deck_type": "FlexDeck", "resources": [{"name": "p", "type": "cor_96_wellplate_360uL_Fb", "slot": "A1"}]}
    result = flex.__ivoryos_labware_edit__("import", content=json.dumps(other), filename="other.json")
    assert os.path.basename(result["kept"]) == "worktable.before-import.json"
    assert list(flex.__ivoryos_labware__()["labware"]) == ["p"]
    assert flex.equipment["left"] == "p1000_multi_flex", "what is mounted stays with the robot"
    with pytest.raises(ValueError, match="takes an Opentrons Flex worktable, not an Opentrons OT-2 one"):
        flex.__ivoryos_labware_edit__("import", content=json.dumps({"deck_type": "OTDeck", "resources": []}))


def test_pylabrobot_cannot_read_its_own_flex_deck_back_yet(flex):
    # PyLabRobot 1.0.0b1: FlexDeck.__init__() takes no size_x, which its own save writes. So there is
    # no PyLabRobot copy of a Flex worktable, and the view says why. Flips when PyLabRobot fixes it.
    assert "PyLabRobot cannot read this worktable back" in (worktable.export_pylabrobot(FILE, "/tmp/x.json") or "")
    assert flex.__ivoryos_labware__()["deck"]["pylabrobot_files"] == {}
