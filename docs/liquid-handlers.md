# Liquid handlers: where each one is

Checked 2026-11-22 by reading and running PyLabRobot 0.2.2 and 1.0.0b1. No robot in this table has
been run on real hardware with this package, in either line.

## The two lines of this package

- **0.2.x** is for PyLabRobot 0.2.x. Every robot is one instrument, PyLabRobot's old
  `LiquidHandler`, with the same steps on each (`aspirate`, `dispense`, `transfer`, `pick_up_tips`,
  `move_plate`, ...) and PyLabRobot's generic simulator.
- **1.0** is for PyLabRobot 1.0. Each robot has its own class and each thing mounted on it is an
  instrument of its own, with PyLabRobot's step names. Only the Flex is done.

## Robot by robot

| Robot | This package 0.2.x | Where it is in PyLabRobot 1.0.0b1 | This package 1.0 |
| :--- | :--- | :--- | :--- |
| Opentrons Flex | not included | `pylabrobot.opentrons`: `Flex`, `FlexHead1`, `FlexHead8`, `FlexHead96`, `FlexGripper`. No simulator. | Done, with this package's simulator |
| Opentrons OT-2 | included | `pylabrobot.opentrons`: `OT2`, `OT2SingleChannelPipette`, `OT2_8ChannelPipette`. No simulator. | Not done. Needs a simulator written first. |
| Hamilton STAR, STARlet | included | `pylabrobot.hamilton.star`: `STAR`, `STARlet`, `STARPlus`, with `STARSimulationDriver` | Not done. Can be built against PyLabRobot's simulator. |
| Hamilton Prep | not included | `pylabrobot.hamilton.prep`: `Prep`, with `PrepSimulationDriver` | Not done |
| Hamilton Nimbus | included | only `pylabrobot.legacy` | Not planned |
| Hamilton Vantage | included | only `pylabrobot.legacy` | Not planned |
| Tecan EVO 100, 150, 200 | included | only `pylabrobot.legacy` | Not planned |

Already in the 1.0 line for the OT-2 and the STAR: the worktable file builds their decks
(`OTDeck`, `STARDeck`, `STARLetDeck` in `worktable.py`), and the Labware view draws any robot.
What is missing is the driver class for each, like `opentrons/flex.py` for the Flex.

## What the robot can do, 0.2 against 1.0

| | PyLabRobot 0.2.2 | PyLabRobot 1.0.0b1 |
| :--- | :--- | :--- |
| OT-2 | tips, aspirate, dispense, home | the same, plus mix, return and discard tips, move-to, and the 8-channel as its own class |
| STAR | channels, 96 head, iSWAP, CoRe grippers, autoload | the same, plus 384 head and STARPlus |

So 1.0 is not a step down for these two. The OT-2 is thin only next to the Flex.

## What does not carry over

A workflow written for a 0.2 robot has to be rewritten for the same robot on 1.0: the instrument
names and the step names are different (`star.aspirate` becomes a step on one of the STAR's
parts). This is on purpose: 1.0 uses PyLabRobot's own names and does not try to make one workflow
run on two kinds of robot.

## The legacy route

`pylabrobot.legacy` in 1.0.0b1 still holds the old `LiquidHandler`, its backends (STAR, Vantage,
Nimbus, EVO, OT-2) and its simulator. It started and stopped on all eight old worktables; no step
was run on it. PyLabRobot marks it legacy and tells callers to move off it, and this package's 0.2
code does not run on it as it is (14 of its 32 tests fail on 1.0.0b1). This package does not use
it. It is the only route to a Nimbus, Vantage or EVO on PyLabRobot 1.0, if someone asks for one.

## Versions

- The first two numbers follow PyLabRobot; the third is this package's own.
- While PyLabRobot 1.0 is in beta, each beta here (1.0.0b2, 1.0.0b3, ...) is pinned to exactly one
  PyLabRobot beta. After PyLabRobot 1.0.0: `pylabrobot>=1.0,<1.1`, and 1.0.1, 1.0.2 at our pace.
- 0.2.x gets fixes only. **0.2.1 is prepared and not published**: branch
  `fix/pylabrobot-below-1` requires `pylabrobot>=0.2.2,<1.0`. The published 0.2.0 has no upper
  bound, so it will break when PyLabRobot 1.0 is final. On 2026-11-22 that branch passed its tests
  on PyLabRobot 0.2.2 and ran a simulated STARlet and OT-2 with the current IvoryOS edge.

## Order of work, when picked up

1. Hamilton STAR and STARlet on 1.0 (a simulator exists).
2. Opentrons OT-2 on 1.0 (write the simulator first, as was done for the Flex).
3. Nimbus, Vantage, EVO only when someone needs one.
