# Controlling an Opentrons Flex: what exists

Notes from a survey on 2026-11-22, kept so it does not have to be repeated. It covers what
PyLabRobot 1.0.0b1 (the version this package is pinned to) does on a Flex, the ways Opentrons
itself offers to control one, and the other open-source projects found. Stars and dates are as
seen that day.

## What PyLabRobot 1.0.0b1 covers

Read from the installed package (`pylabrobot/opentrons`).

**Included**

- Connection over Ethernet or USB, runs, homing, rail lights, status bar, comments, timed waits.
- 1-, 8- and 96-channel pipettes: tips (pick up, drop, discard, presence check), aspirate,
  dispense, blow out, air gap, touch tip, configure for volume, move to a well or a coordinate.
  Liquid level probing on the 1- and 8-channel; `mix` and single-nozzle use on the 8-channel.
- Gripper: `move_labware(resource, to_slot)`, slot to slot only, including staging slots A4 to D4.
  Also low-level `move_to_position`, `grip`, `ungrip`.
- Labware: any PyLabRobot definition is converted and uploaded to the robot; official Opentrons
  tip racks are used as they are.
- Reading what is attached: pipettes, gripper, modules, deck fixtures.
- `Flex.send_command(command_type, params)`: any robot command by name. It validates nothing and
  does not update PyLabRobot's tip, volume or labware tracking.
- `labware_moved_off_deck` and `reload_labware`, for labware a person or another arm moved.

**Not included** (no code found)

- Running a module: Heater-Shaker, Temperature Module, Thermocycler, Magnetic Block, Absorbance
  Plate Reader, Flex Stacker. Attached modules can be listed, not driven.
- Moving labware onto a module or an adapter with the gripper, and pick-up or drop offsets.
- Lids, the waste chute.
- Opentrons liquid classes, and the robot's saved labware offsets (Labware Position Check).
- Pausing until a person resumes.
- Uploading or running an Opentrons protocol file: PyLabRobot sends one command at a time.

The OT-2 class is much thinner than the Flex one (not thinner than the OT-2 in PyLabRobot 0.2:
see [liquid-handlers.md](liquid-handlers.md)): connect, home, and single- or 8-channel pipettes
with aspirate, dispense, mix, tips and move-to. Thermocyclers (Opentrons, Inheco, Thermo Fisher) exist only under
`pylabrobot.legacy`, which this package does not use.

## What Opentrons itself offers

- **Protocol API** (`opentrons.protocol_api`): a Python file with a `run(protocol)` function,
  uploaded and run as a whole. Covers every module, lids, adapters, the waste chute. A run can be
  paused, resumed and stopped from outside, and the Flex has an error-recovery state for some
  failures, but what the run does next cannot be changed once it has started.
- **HTTP API** (the robot-server, port 31950): protocol upload and runs (`/protocols`, `/runs`,
  `/runs/{id}/actions`), result files (`/dataFiles`), and **single commands** posted to a run with
  no protocol (`/runs/{id}/commands`). Every Protocol API call has a command underneath
  (`heaterShaker/closeLabwareLatch`, `absorbanceReader/read`, `moveLabware` to a module, ...).
  This is the interface PyLabRobot uses, and what `send_command` passes through to.
  Reference: <https://docs.opentrons.com/http/api_reference.html>
- **Jupyter on the robot**: Protocol API calls one cell at a time
  (<https://docs.opentrons.com/python-api/advanced-control/jupyter/>). Labware offsets have to be
  set by hand in this mode. Not a route this package takes.
- **Definitions**: labware, deck and module geometry are JSON files in Opentrons' `shared-data`
  (<https://github.com/Opentrons/opentrons>). A custom labware is the same kind of file, uploaded
  with a protocol. On GitHub the Flex is called `ot3`.

## Other open-source projects

Found by GitHub repository search, GitHub code search for module commands
(`"heaterShaker/closeLabwareLatch"`, `"absorbanceReader/read"`, `"flexStacker/retrieve"`), and web
search. None is widely adopted.

| Project | What it is | Flex and modules | Seen 2026-11-22 |
| :--- | :--- | :--- | :--- |
| [AccelerationConsortium/opentrons-flex](https://github.com/AccelerationConsortium/opentrons-flex) | SiLA 2 connector (UniteLabs CDK) that runs on the Flex in place of the robot-server; has a simulator | Heater-Shaker, Absorbance Plate Reader, Stacker, Temperature Module, Thermocycler, lids, gripper moves; can keep the HTTP API available | 3 stars, pushed 2026-11-02, no license file |
| [AccelerationConsortium/opentrons-ot2](https://github.com/AccelerationConsortium/opentrons-ot2) | The same idea for the OT-2 | OT-2 | 6 stars, pushed 2026-10-14, no license file |
| [usnistgov/AFL-automation](https://github.com/usnistgov/AFL-automation) (`AFL/automation/prepare/OT2HTTPDriver.py`) | Lab framework with a driver that posts single commands to the HTTP API and keeps deck state | Written for the OT-2; loads modules, moves labware | 19 stars, pushed 2026-11-13 |
| [AD-SDL/ot2_module](https://github.com/AD-SDL/ot2_module) | Node for Argonne's MADSci framework | README says OT-2 and Flex; depth not checked | 1 star, pushed 2026-10-29 |
| [rickwierenga/opentrons-python-api](https://github.com/rickwierenga/opentrons-python-api) | Thin wrapper around the HTTP API (used by PyLabRobot's legacy OT-2 backend) | Describes itself as incomplete | 11 stars, pushed 2025-11-26, MIT |
| [FlorianBauer/ot2-controller](https://github.com/FlorianBauer/ot2-controller) | SiLA 2 controller | OT-2 only | 15 stars, pushed 2023-06-04, Apache-2.0 |
| [Hendricks-Laboratory/OT2Control](https://github.com/Hendricks-Laboratory/OT2Control) | OT-2 control software | OT-2 only | 8 stars, pushed 2026-11-16, no license file |
| [Opentrons/opentrons-integration-tools](https://github.com/Opentrons/opentrons-integration-tools) | Opentrons' own guides for external devices | Guides, not a driver | 34 stars, pushed 2023-08-30 |
| [y3rsh/flex-talk](https://github.com/y3rsh/flex-talk) | TypeScript client for the Flex HTTP API | Not checked | 0 stars, pushed 2026-03-29 |

Several MCP servers for Opentrons also exist (for example
[yerbymatey/opentrons-mcp](https://github.com/yerbymatey/opentrons-mcp)); they generate or submit
protocols and are not drivers.

## What this means for this package

A step for something PyLabRobot does not wrap (a Heater-Shaker, the plate reader, a lid) does not
have to wait for PyLabRobot: the robot command exists, and `send_command` sends it. Such a step
would be this package's own to write and maintain, PyLabRobot would not track labware it moves,
and it cannot be tested without a Flex that has the module, since the simulator here does not model
modules.
