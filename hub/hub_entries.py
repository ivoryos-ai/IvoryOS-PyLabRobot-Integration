"""The IvoryOS Hub entries for this release of plr-ivoryos (README.md beside this file).

    python hub/hub_entries.py path/to/ivoryos_schema.json

reads IvoryOS's own description of every step (the schema `python -m ivoryos_edge --deck
hub/deck.json` dumps) and writes, beside this file:

    schemas-<version>.json   each class's schema, by class name
    update-<version>.sql     one transaction: the modules, their versions and parts, the Labware
                             plugin; it reads the schemas from a temporary table `_schemas` (one
                             jsonb row, the file above), so the SQL itself stays small
"""

import json
import os
import sys
import warnings

warnings.simplefilter("ignore")
from plr_ivoryos import __version__  # noqa: E402
from plr_ivoryos.opentrons.simulator import OT2_PIPETTES  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
dump = json.load(open(sys.argv[1], encoding="utf-8"))
# instrument name in hub/deck.json -> its class; and each class's schema
S = {name: meta["class"] for name, meta in dump["instrument_meta"].items()}
BUNDLE = {S[name]: schema for name, schema in dump["instruments"].items()}

VERSION = __version__
REQUIRES = {"pylabrobot": "==1.0.0b1"}
PIP = f"plr-ivoryos=={VERSION}"
PIP_USB = f"plr-ivoryos[usb]=={VERSION}"
NOTES = "PyLabRobot 1.0.0b1 (beta). Run in simulation and in IvoryOS NextGen; not yet on hardware."


def j(value):
    text = json.dumps(value, ensure_ascii=False)
    assert "$j$" not in text
    return f"$j${text}$j$::jsonb"


def sch(cls):
    """A class's schema, from the temporary table the SQL is run with."""
    assert cls in BUNDLE, cls
    return f"(select s->{t(cls)} from _schemas)"


def t(text):
    assert "$t$" not in text
    return f"$t${text}$t$"


def arg(name, type_, default=None, **more):
    out = {"name": name, "type": type_}
    if default is not None:
        out["default"] = default
    return {**out, **more}


SIM = arg("simulated", "bool", True)
WORKTABLE = arg("worktable", "str", "worktable.json")
DELAY = arg("step_delay_s", "float", 0)
SHARED = ("Decks on one computer share one Python environment, so this replaces the PyLabRobot that any "
          "older plr-ivoryos driver there needs. Add the Labware plugin after this driver to see and edit the "
          "worktable.")


def bools(parts, labels, defaults):
    return {p: {"type": "bool", "label": labels[p], "default": defaults.get(p, True)} for p in parts}


def pipette_choices(channels=None):
    return [{"label": spec["label"], "value": name} for name, spec in OT2_PIPETTES.items()
            if channels is None or spec["channels"] == channels]


MODULES = [
    {"id": 422, "name": "Flex", "pip": PIP, "path": "plr_ivoryos.opentrons", "cls": "Flex", "schema": S["flex"],
     "init_args": [SIM, arg("host", "str"), arg("port", "int", 31950), arg("serial_port", "str"), WORKTABLE, DELAY],
     "description": None,  # kept
     "equipment": "keep",
     "parts": [("left", "left", ["p50_single_flex", "p1000_single_flex"], "FlexPipette1", "1-channel pipette on the left mount", 10, S["flex_right"]),
               ("left", "left", ["p50_multi_flex", "p1000_multi_flex"], "FlexPipette8", "8-channel pipette on the left mount", 11, S["flex_left"]),
               ("right", "right", ["p50_single_flex", "p1000_single_flex"], "FlexPipette1", "1-channel pipette on the right mount", 20, S["flex_right"]),
               ("right", "right", ["p50_multi_flex", "p1000_multi_flex"], "FlexPipette8", "8-channel pipette on the right mount", 21, S["flex_left"]),
               ("head96", "head96", ["p1000_96", "p200_96"], "FlexPipette96", "96-channel head", 30, S["flex96_head96"]),
               ("gripper", "gripper", [], "FlexGripperPart", "Gripper", 40, S["flex_gripper"])]},
    {"id": 183, "name": "Opentrons OT-2", "pip": PIP, "path": "plr_ivoryos.opentrons", "cls": "OT2", "schema": S["ot2"],
     "init_args": [SIM, arg("host", "str"), arg("port", "int", 31950), WORKTABLE, DELAY],
     "description": "An Opentrons OT-2 through PyLabRobot 1.0. The robot is one instrument and each mounted pipette "
                    "another (ot2_left, ot2_right), each with PyLabRobot's own steps; wells are written as PyLabRobot "
                    "writes them (assay_plate[A1:H1]). What is mounted and what sits where is the worktable file. "
                    "Simulated (the default) runs PyLabRobot's OT-2 against a simulated robot-server, since "
                    "PyLabRobot has none for its 1.0 class: for a real robot, untick simulated and give host. Beta: "
                    "pinned to PyLabRobot 1.0.0b1, run in simulation only. " + SHARED,
     "equipment": {"left": {"label": "Left mount", "choices": pipette_choices(), "default": "p300_multi_gen2"},
                   "right": {"label": "Right mount", "choices": pipette_choices(), "default": "p300_single_gen2"}},
     "parts": [(m, m, [n for n, s in OT2_PIPETTES.items() if s["channels"] == c], cls, f"{c}-channel pipette on the {m} mount", o + i,
                S["ot2_right"] if c == 1 else S["ot2_left"])
               for o, m in ((10, "left"), (20, "right")) for i, (c, cls) in enumerate(((1, "OT2Pipette1"), (8, "OT2Pipette8")))]},
    {"id": 178, "name": "Hamilton STAR", "pip": PIP_USB, "path": "plr_ivoryos.hamilton", "cls": "STAR", "schema": S["star"],
     "init_args": [SIM, arg("deck_type", "str", "STARLetDeck"), WORKTABLE, arg("device_address", "int"),
                   arg("serial_number", "str"), DELAY],
     "description": "A Hamilton STAR, STARlet or STARplus (deck_type STARDeck, STARLetDeck or STARPlusDeck) through "
                    "PyLabRobot 1.0. The robot is one instrument and each thing fitted to it another (star_pipettes, "
                    "star_head96 or star_head384, star_iswap, star_core_grippers, star_autoload), each with "
                    "PyLabRobot's own steps. Simulated (the default) is PyLabRobot's own STAR simulator, answering as "
                    "the firmware would; for the real one on USB, untick simulated. Beta: pinned to PyLabRobot "
                    "1.0.0b1, run in simulation only. " + SHARED,
     "equipment": bools(("pipettes", "head96", "head384", "iswap", "core_grippers", "autoload"),
                        {"pipettes": "Independent channels", "head96": "96-head", "head384": "384-head (instead of the 96-head)",
                         "iswap": "iSWAP", "core_grippers": "CoRe grippers", "autoload": "Autoload"}, {"head384": False}),
     "parts": [("pipettes", "pipettes", [], "STARPipettes", "Independent channels", 10, S["star_pipettes"]),
               ("head96", "head96", [], "STARHead96", "96-head", 20, S["star_head96"]),
               ("head384", "head384", [], "STARHead384", "384-head", 21, S["star384_head384"]),
               ("iswap", "iswap", [], "STARiSWAP", "iSWAP", 30, S["star_iswap"]),
               ("core_grippers", "core_grippers", [], "STARCoreGrippers", "CoRe grippers", 40, S["star_core_grippers"]),
               ("autoload", "autoload", [], "STARAutoload", "Autoload", 50, S["star_autoload"])]},
    {"id": None, "name": "Hamilton Prep", "pip": PIP, "path": "plr_ivoryos.hamilton", "cls": "Prep", "schema": S["prep"],
     "init_args": [SIM, arg("host", "str"), arg("port", "int", 2000), WORKTABLE, DELAY],
     "description": "A Hamilton Prep through PyLabRobot 1.0. The robot is one instrument and each thing fitted to it "
                    "another (prep_pipettes, prep_head8, prep_core_grippers, prep_heater_shaker, prep_lights), each "
                    "with PyLabRobot's own steps; labware goes in its eight spots, 0 to 7. Simulated (the default) is "
                    "PyLabRobot's own Prep simulator; for a real Prep, untick simulated and give host. Beta: pinned to "
                    "PyLabRobot 1.0.0b1, run in simulation only. " + SHARED,
     "equipment": bools(("pipettes", "head8", "core_grippers", "heater_shaker", "lights"),
                        {"pipettes": "Independent channels", "head8": "8-channel head", "core_grippers": "CoRe grippers",
                         "heater_shaker": "Heater shaker", "lights": "Lights"}, {}),
     "parts": [("pipettes", "pipettes", [], "PrepPipettes", "Independent channels", 10, S["prep_pipettes"]),
               ("head8", "head8", [], "PrepHead8", "8-channel head", 20, S["prep_head8"]),
               ("core_grippers", "core_grippers", [], "PrepCoreGrippers", "CoRe grippers", 30, S["prep_core_grippers"]),
               ("heater_shaker", "heater_shaker", [], "PrepHeaterShaker", "Heater shaker", 40, S["prep_heater_shaker"]),
               ("lights", "lights", [], "PrepLights", "Lights", 50, S["prep_lights"])]},
]

LEGACY_NOTE = ("PyLabRobot 1.0 drives this robot only through pylabrobot.legacy, so it is one instrument with every "
               "LiquidHandler operation (pick_up_tips, aspirate, dispense, move_plate, ...), PyLabRobot's names and "
               "arguments; wells are written as PyLabRobot writes them (assay_plate[A1:H1]). Simulated (the default) is "
               "PyLabRobot's legacy chatterbox: its tip and volume tracking, not the robot's firmware. Beta: pinned to "
               "PyLabRobot 1.0.0b1, run in simulation only. ")
CHANNELS = arg("channels", "int", 8)
MODULES += [
    {"id": 184, "name": "Hamilton Nimbus", "pip": PIP, "path": "plr_ivoryos.legacy", "cls": "Nimbus", "schema": S["nimbus"],
     "init_args": [SIM, arg("host", "str"), arg("port", "int", 2000), WORKTABLE, CHANNELS, DELAY],
     "description": "A Hamilton Nimbus through PyLabRobot. " + LEGACY_NOTE + "For a real Nimbus, untick simulated and "
                    "give host. " + SHARED, "equipment": None, "parts": []},
    {"id": 185, "name": "Hamilton Vantage", "pip": PIP_USB, "path": "plr_ivoryos.legacy", "cls": "Vantage", "schema": S["vantage"],
     "init_args": [SIM, WORKTABLE, arg("device_address", "int"), arg("serial_number", "str"), CHANNELS, DELAY],
     "description": "A Hamilton Vantage (1.3 m deck) through PyLabRobot. " + LEGACY_NOTE + "For the real one on USB, "
                    "untick simulated. " + SHARED, "equipment": None, "parts": []},
    {"id": 186, "name": "Tecan EVO", "pip": PIP_USB, "path": "plr_ivoryos.legacy", "cls": "EVO", "schema": S["evo"],
     "init_args": [SIM, arg("deck_type", "str", "EVO150Deck"), WORKTABLE, arg("diti_count", "int", 0), CHANNELS, DELAY],
     "description": "A Tecan Freedom EVO 100, 150 or 200 (deck_type EVO100Deck, EVO150Deck or EVO200Deck) through "
                    "PyLabRobot. " + LEGACY_NOTE + "PyLabRobot 1.0.0b1 cannot make a Tecan tip rack yet, so the "
                    "worktable has no disposable tips. For the real one on USB, untick simulated. " + SHARED,
     "equipment": None, "parts": []},
    {"id": 177, "name": "Simulated Liquid Handler", "pip": PIP, "path": "plr_ivoryos.legacy", "cls": "LiquidHandler",
     "schema": S["lh"],
     "init_args": [SIM, CHANNELS, arg("deck_type", "str", "STARLetDeck"), WORKTABLE, DELAY],
     "description": "PyLabRobot's simulated liquid handler (the legacy chatterbox) on any worktable (deck_type: "
                    "STARLetDeck, STARDeck, OTDeck, NimbusDeck, EVO150Deck, ...): one instrument with every "
                    "LiquidHandler operation, PyLabRobot's names and arguments, wells written as assay_plate[A1:H1]. "
                    "For a specific robot, its own driver (Hamilton STAR, Opentrons OT-2, ...) simulates it better. "
                    "Beta: pinned to PyLabRobot 1.0.0b1. " + SHARED, "equipment": None, "parts": []},
]

OLD_PIP = {177: "plr-ivoryos>=0.2.0,<1", 178: "plr-ivoryos[usb]>=0.2.0,<1", 183: "plr-ivoryos[opentrons]>=0.2.0,<1",
           184: "plr-ivoryos>=0.2.0,<1", 185: "plr-ivoryos[usb]>=0.2.0,<1", 186: "plr-ivoryos[usb]>=0.2.0,<1"}

# Who added these drivers: whoever added the Flex's (so no account id is written here).
CONTRIBUTOR = "(select contributor_id from modules where id = 422)"
sql = ["begin;", """do $$ begin
  if (select count(*) from _schemas) <> 1 or (select s->'Flex' from _schemas) is null then
    raise exception 'create temp table _schemas (s jsonb) holding schemas-<version>.json first';
  end if;
end $$;"""]
sql.append(f"""insert into devices (name, vendor, category, official_url, contributor_id)
select 'Prep', 'Hamilton', 'Liquid Handler', 'https://www.hamiltoncompany.com', {CONTRIBUTOR}
where not exists (select 1 from devices where vendor = 'Hamilton' and name = 'Prep');""")
for m in MODULES:
    ident = str(m["id"]) if m["id"] else "(select id from modules where module_path = 'plr_ivoryos.hamilton' and module_name = 'Prep')"
    if m["id"] is None:
        sql.append(f"""insert into modules (name, pip_name, module_name, module_path, contributor_id, os, device_id,
  python_versions, is_tested_with_ivoryos, is_unlisted, init_args, is_original_developer, connection, description,
  schema, schema_source)
select {t(m['name'])}, {t(m['pip'])}, {t(m['cls'])}, {t(m['path'])}, {CONTRIBUTOR},
  array['Windows','Linux','macOS']::text[], (select id from devices where vendor = 'Hamilton' and name = 'Prep'),
  array['']::text[], false, false, {j(m['init_args'])}, false, '{{}}'::text[], {t(m['description'])}, {sch(m['schema'])},
  'introspection'
where not exists (select 1 from modules where module_path = 'plr_ivoryos.hamilton' and module_name = 'Prep');""")
    else:
        sets = [f"pip_name = {t(m['pip'])}", f"module_name = {t(m['cls'])}", f"module_path = {t(m['path'])}",
                f"init_args = {j(m['init_args'])}", f"schema = {sch(m['schema'])}", "schema_source = 'introspection'",
                "updated_at = now()"]
        if m["description"]:
            sets.append(f"description = {t(m['description'])}")
        sql.append(f"update modules set {', '.join(sets)} where id = {ident};")
    if m["id"] in OLD_PIP:  # what it was, for the record
        sql.append(f"""insert into module_versions (module_id, version, pip_name, requires, channel, notes, is_current)
select {ident}, '0.2', {t(OLD_PIP[m['id']])}, '{{"pylabrobot": "<1"}}'::jsonb, 'stable',
  'plr-ivoryos 0.2 on PyLabRobot 0.x: LiquidHandler(backend=..., deck_json=...). Workflows made with it need redoing on 1.0.', false
where not exists (select 1 from module_versions where module_id = {ident} and version = '0.2');""")
    sql.append(f"update module_versions set is_current = false where module_id = {ident};")
    equipment = "(select equipment from module_versions where id = 1)" if m["equipment"] == "keep" else \
        ("null" if m["equipment"] is None else j(m["equipment"]))
    sql.append(f"""insert into module_versions (module_id, version, pip_name, requires, channel, schema, equipment, notes, is_current)
values ({ident}, '{VERSION}', {t(m['pip'])}, {j(REQUIRES)}, 'beta', {sch(m['schema'])}, {equipment}, {t(NOTES)}, true);""")
    for part, key, values, cls, label, order, schema in m["parts"]:
        vals = "array[" + ", ".join(t(v) for v in values) + "]::text[]" if values else "'{}'::text[]"
        sql.append(f"""insert into module_parts (module_version_id, part, equipment_key, equipment_values, class_name, label, schema, sort_order)
values ((select id from module_versions where module_id = {ident} and version = '{VERSION}'), {t(part)}, {t(key)}, {vals},
  {t(cls)}, {t(label)}, {sch(schema)}, {order});""")

ids = ", ".join(str(m["id"]) for m in MODULES if m["id"])
sql.append(f"""update plugins set pip_name = {t(PIP)},
  module_ids = array[{ids}, (select id from modules where module_path = 'plr_ivoryos.hamilton' and module_name = 'Prep')]::int[],
  description = {t("Any plr-ivoryos liquid handler's worktable (Opentrons Flex and OT-2, Hamilton STAR, Prep, Nimbus and Vantage, Tecan EVO), drawn live beside every page: what each well holds, which tips are left, and the wells a step is working on. Edit layout to build it: drag labware from PyLabRobot's catalogue onto slots or carriers, fill wells with a liquid, or import a layout you already have; on a Flex, also choose what is mounted. Saved as plr-ivoryos's worktable.json. Add the liquid handler's driver to the deck first: this plugin installs with its PyLabRobot.")}
where id = 7;""")
sql.append("commit;")
with open(os.path.join(HERE, f"schemas-{VERSION}.json"), "w", encoding="utf-8") as f:
    json.dump(BUNDLE, f, ensure_ascii=False, sort_keys=True, indent=1)
    f.write("\n")
with open(os.path.join(HERE, f"update-{VERSION}.sql"), "w", encoding="utf-8") as f:
    f.write(f"-- plr-ivoryos {VERSION} on the IvoryOS Hub. Generated by hub/hub_entries.py; see hub/README.md.\n\n")
    f.write("\n\n".join(sql) + "\n")
print(f"schemas-{VERSION}.json: {len(BUNDLE)} classes; update-{VERSION}.sql: {sum(len(x) for x in sql)} chars")
