"""Layouts saved by name: saving the worktable in use, switching, going back, and what a restart is for."""

import json
import os

import pytest

from plr_ivoryos import worktable
from plr_ivoryos.opentrons import Flex

from conftest import write
from test_flex import FILE

PLATE = "cor_96_wellplate_360uL_Fb"


@pytest.fixture
def flex(data_folder):
    robot = Flex(simulated=True, worktable=write(data_folder, FILE))
    yield robot
    robot.stop()


def status(robot) -> dict:
    return robot.__ivoryos_labware__()["deck"]["layout"]


def folder(data_folder) -> str:
    return os.path.join(str(data_folder), "worktable.layouts")


def test_two_files_that_say_the_same_thing_are_the_same_layout():
    other = json.loads(json.dumps(FILE))
    other["resources"] = [{**entry, "slot": entry["slot"].lower()} for entry in reversed(other["resources"])]
    other["liquids"] = [{"labware": "reservoir", "wells": ["A2"], "liquid": "dye", "volume_ul": 5000.0},
                        {"labware": "reservoir", "wells": "A1:A1", "liquid": "buffer", "volume_ul": 10000}]
    assert worktable.fingerprint(other) == worktable.fingerprint(FILE)
    moved = json.loads(json.dumps(FILE))
    moved["resources"][2]["slot"] = "D3"
    assert worktable.fingerprint(moved)["layout"] != worktable.fingerprint(FILE)["layout"]
    assert worktable.fingerprint(moved)["liquids"] == worktable.fingerprint(FILE)["liquids"]


def test_a_worktable_never_saved_says_so_and_saving_it_names_it(flex, data_folder):
    assert status(flex)["name"] is None and not status(flex)["saved"]
    assert flex.__ivoryos_labware_catalog__()["layouts"] == {"folder": folder(data_folder), "saved": []}
    with pytest.raises(ValueError, match="Give the layout a name"):
        flex.__ivoryos_labware_edit__("save_layout")
    assert flex.__ivoryos_labware_edit__("save_layout", name="  Standard   screen ") == \
        {"name": "Standard screen", "restart": False}
    saved = json.load(open(os.path.join(folder(data_folder), "Standard screen.json")))
    assert saved == {"format": worktable.FORMAT, **FILE}, "a saved layout is a worktable file anyone can import"
    assert json.load(open(os.path.join(str(data_folder), "worktable.json")))["based_on"] == "Standard screen"
    assert status(flex) == {"name": "Standard screen", "saved": True,
                            "changed": {"layout": False, "liquids": False}}
    assert flex.__ivoryos_labware_catalog__()["layouts"]["saved"] == ["Standard screen"]


@pytest.mark.parametrize("name", ["a/b", "..\\up", ".hidden", "what?", "x" * 81])
def test_a_name_a_file_cannot_have_is_refused(flex, name):
    with pytest.raises(ValueError, match="name"):
        flex.__ivoryos_labware_edit__("save_layout", name=name)


def test_filling_wells_is_liquids_changed_and_moving_a_plate_is_layout_changed(flex):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Screen")
    edit("liquid", labware="assay_plate", wells="A1:H1", liquid="sample", volume_ul=50)
    assert status(flex)["changed"] == {"layout": False, "liquids": True}
    edit("move", name="assay_plate", site="D3")
    assert status(flex)["changed"] == {"layout": True, "liquids": True}
    edit("save_layout")
    assert status(flex)["changed"] == {"layout": False, "liquids": False}


def test_going_back_restores_the_layout_as_it_was_saved(flex, data_folder):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Screen")
    edit("place", definition=PLATE, site="B2", name="extra")
    edit("remove", name="assay_plate")
    edit("liquid", labware="reservoir", wells="A3", liquid="acid", volume_ul=100)
    assert status(flex)["changed"] == {"layout": True, "liquids": True}
    assert edit("revert") == {"name": "Screen", "restart": False}, "back to what the deck started with"
    assert sorted(flex.__ivoryos_labware__()["labware"]) == ["assay_plate", "reservoir", "tips"]
    assert "A3" not in flex.__ivoryos_labware_state__()["labware"]["reservoir"]
    assert status(flex)["changed"] == {"layout": False, "liquids": False}
    on_disk = json.load(open(os.path.join(str(data_folder), "worktable.json")))
    assert {k: on_disk[k] for k in FILE} == FILE and on_disk["based_on"] == "Screen"


def test_going_back_on_liquids_alone_touches_only_those_wells(flex):
    edit, right = flex.__ivoryos_labware_edit__, flex.__ivoryos_instruments__()["right"]
    edit("save_layout", name="Screen")
    right.pick_up_tips("tips[A1]")
    right.aspirate("reservoir[A1]", 100)
    right.dispense("assay_plate[A1]", 100)
    right.drop_tips("trash")
    edit("liquid", labware="reservoir", wells="A2", liquid="dye", volume_ul=9000)
    flex.setup()
    edit("revert")
    held = flex.__ivoryos_labware_state__()["labware"]
    assert held["reservoir"]["A2"]["volume_ul"] == 5000, "the well that was topped up is as saved"
    assert held["reservoir"]["A1"]["volume_ul"] == 9900, "a well a step drew from is as the step left it"
    assert held["assay_plate"]["A1"]["volume_ul"] == 100 and flex.tips_left("tips") == 95
    assert flex._ready, "a change of liquids alone does not end the robot's session"


def test_switching_layouts_and_what_a_restart_is_for(flex, data_folder):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Screen")
    assert edit("move", name="assay_plate", site="D3")["restart"] is False, \
        "steps name the plate, not its slot: moving it needs no restart"
    assert edit("save_layout", name="Screen, plate at the back") == \
        {"name": "Screen, plate at the back", "restart": False}
    edit("rename", name="assay_plate", to="samples")
    assert flex.__ivoryos_labware__()["deck"]["restart_needed"] is True, "steps do not offer `samples` yet"
    edit("save_layout", name="Samples")

    assert edit("use_layout", name="Screen") == {"name": "Screen", "restart": False}
    assert flex.__ivoryos_labware__()["labware"]["assay_plate"]["site"] == "D2"
    assert edit("use_layout", name="samples") == {"name": "Samples", "restart": True}, "found ignoring case"
    assert "samples" in flex.__ivoryos_labware__()["labware"]
    assert flex.__ivoryos_labware_catalog__()["layouts"]["saved"] == ["Samples", "Screen", "Screen, plate at the back"]


def test_switching_away_from_unsaved_changes_is_refused_unless_they_are_given_up(flex):
    edit = flex.__ivoryos_labware_edit__
    with pytest.raises(ValueError, match="No layout called 'Nowhere' is saved"):
        edit("use_layout", name="Nowhere", discard=True)
    edit("save_layout", name="Screen")
    edit("move", name="assay_plate", site="D3")
    edit("save_layout", name="Other")
    edit("liquid", labware="assay_plate", wells="A1", liquid="sample", volume_ul=10)
    with pytest.raises(ValueError, match="Other has changes that are not saved"):
        edit("use_layout", name="Screen")
    assert status(flex)["name"] == "Other", "a refused switch changes nothing"
    assert edit("use_layout", name="Screen", discard=True)["name"] == "Screen"
    assert "A1" not in flex.__ivoryos_labware_state__()["labware"]["assay_plate"]


def test_saving_over_another_layout_has_to_be_meant(flex):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Screen")
    edit("move", name="assay_plate", site="D3")
    edit("save_layout", name="Other")
    with pytest.raises(ValueError, match="A layout called 'Screen' is already saved"):
        edit("save_layout", name="screen")
    assert edit("save_layout", name="screen", replace=True)["name"] == "Screen"
    assert status(flex)["name"] == "Screen" and not any(status(flex)["changed"].values())


def test_a_deleted_layout_leaves_the_worktable_as_it_is(flex, data_folder):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Screen")
    edit("delete_layout")
    assert os.listdir(folder(data_folder)) == [] and status(flex)["name"] is None
    assert sorted(flex.__ivoryos_labware__()["labware"]) == ["assay_plate", "reservoir", "tips"]
    with pytest.raises(ValueError, match="nothing to go back to"):
        edit("revert")


def test_a_layout_file_put_in_the_folder_by_hand_is_a_saved_layout(flex, data_folder):
    os.makedirs(folder(data_folder))
    other = {"deck_type": "FlexDeck", "resources": [{"name": "p", "type": PLATE, "slot": "A1"}]}
    write(folder(data_folder), other, "From a colleague.json")
    write(folder(data_folder), {"deck_type": "OTDeck", "resources": []}, "An OT-2.json")
    with open(os.path.join(folder(data_folder), "notes.txt"), "w") as f:
        f.write("not a layout")
    assert flex.__ivoryos_labware_catalog__()["layouts"]["saved"] == ["From a colleague"], \
        "another robot's layout is not offered"
    flex.__ivoryos_labware_edit__("use_layout", name="From a colleague", discard=True)
    assert list(flex.__ivoryos_labware__()["labware"]) == ["p"]
    assert flex.equipment["left"] == "p1000_multi_flex", "what is mounted stays when the layout does not say"
    assert not any(status(flex)["changed"].values())


def test_a_layout_with_other_pipettes_changes_what_is_mounted_and_needs_a_restart(flex, data_folder):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Two pipettes")
    edit("equipment", head96="p1000_96")
    edit("save_layout", name="96 head")
    assert edit("use_layout", name="Two pipettes") == {"name": "Two pipettes", "restart": False}
    assert edit("use_layout", name="96 head")["restart"] is True, "the head is an instrument of its own"
    assert set(flex.equipment) == {"head96", "gripper", "trash"}
    write(folder(data_folder), {**FILE, "equipment": {"left": "p9000"}}, "Bad.json")
    with pytest.raises(ValueError, match="'p9000' is not a Flex pipette"):
        edit("use_layout", name="Bad")


def test_the_layout_in_use_or_a_saved_one_is_exported_as_a_file_to_import(flex):
    edit = flex.__ivoryos_labware_edit__
    assert flex.__ivoryos_labware_export__()["filename"] == "worktable.json"
    edit("save_layout", name="Screen")
    edit("move", name="assay_plate", site="D3")
    now, saved = flex.__ivoryos_labware_export__(), flex.__ivoryos_labware_export__("Screen")
    assert now["filename"] == saved["filename"] == "Screen.json"
    assert "based_on" not in now["layout"] and now["layout"]["format"] == worktable.FORMAT
    assert now["layout"]["resources"][-1]["slot"] == "D3" and saved["layout"]["resources"] == FILE["resources"]
    assert worktable.read_layout(json.dumps(now["layout"]))["resources"] == now["layout"]["resources"]


def test_an_imported_layout_is_not_a_saved_one(flex):
    edit = flex.__ivoryos_labware_edit__
    edit("save_layout", name="Screen")
    other = {"deck_type": "FlexDeck", "based_on": "Theirs", "resources": [{"name": "p", "type": PLATE, "slot": "A1"}]}
    edit("import", content=json.dumps(other), filename="other.json")
    assert status(flex)["name"] is None, "where someone else's file came from is not where this one did"


def test_layouts_can_live_in_a_folder_of_their_own(data_folder):
    robot = Flex(simulated=True, worktable=write(data_folder, FILE), layouts_folder="shared layouts")
    robot.__ivoryos_labware_edit__("save_layout", name="Screen")
    assert os.listdir(os.path.join(str(data_folder), "shared layouts")) == ["Screen.json"]


# --- every other liquid handler ------------------------------------------------------------------------

@pytest.mark.parametrize("cls", ["STAR", "Prep", "OT2", "Nimbus", "Vantage", "EVO"])
def test_every_liquid_handler_saves_switches_and_reverts_layouts(cls, data_folder):
    import plr_ivoryos
    robot = getattr(plr_ivoryos, cls)(simulated=True, layouts_folder="layouts")
    edit = robot.__ivoryos_labware_edit__
    try:
        assert edit("save_layout", name="Screen") == {"name": "Screen", "restart": False}
        edit("liquid", labware="assay_plate", wells="A1", liquid="dye", volume_ul=50)
        assert status(robot)["changed"] == {"layout": False, "liquids": True}
        edit("save_layout", name="Dyed")
        assert edit("use_layout", name="Screen") == {"name": "Screen", "restart": False}, "liquids only"
        assert robot.read_volumes("assay_plate[A1]") == {"assay_plate[A1]": 0.0}
        edit("remove", name="sample_plate")
        assert robot.__ivoryos_labware__()["deck"]["restart_needed"] is True
        assert edit("revert") == {"name": "Screen", "restart": False}, "back to what the deck started with"
        assert "sample_plate" in robot.__ivoryos_labware__()["labware"]
        assert edit("use_layout", name="Dyed")["restart"] is False
        assert robot.read_volumes("assay_plate[A1]") == {"assay_plate[A1]": 50.0}
        assert robot.__ivoryos_labware_export__()["filename"] == "Dyed.json"
        assert sorted(os.listdir(os.path.join(str(data_folder), "layouts"))) == ["Dyed.json", "Screen.json"]
    finally:
        robot.stop()


def test_an_ot2_layout_says_its_pipettes_and_other_ones_need_a_restart(data_folder):
    from plr_ivoryos import OT2
    robot = OT2(simulated=True)
    edit = robot.__ivoryos_labware_edit__
    try:
        edit("save_layout", name="Screen")
        saved = json.load(open(os.path.join(folder(data_folder), "Screen.json")))
        write(folder(data_folder), {**saved, "equipment": {"left": "p20_single_gen2"}}, "One pipette.json")
        write(folder(data_folder), {**saved, "equipment": {"left": "p1000_single_flex"}}, "Bad.json")
        assert edit("use_layout", name="One pipette")["restart"] is True, "the right mount is gone"
        assert robot.equipment == {"left": "p20_single_gen2"}
        with pytest.raises(ValueError, match="not an OT-2 pipette"):
            edit("use_layout", name="Bad")
        assert edit("use_layout", name="Screen")["restart"] is False
    finally:
        robot.stop()
