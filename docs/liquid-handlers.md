# Liquid handlers: where each one is

Checked 2026-11-23 against PyLabRobot 0.2.2 and 1.0.0b1. No robot in this table has been run on
real hardware with this package, in either line. Which simulator each one runs on, and what
PyLabRobot lacks, is in [simulators.md](simulators.md).

## The two lines of this package

- **0.2.x** is for PyLabRobot 0.2.x. Every robot is one instrument, PyLabRobot's old
  `LiquidHandler`, with the same steps on each (`aspirate`, `dispense`, `transfer`, `pick_up_tips`,
  `move_plate`, ...) and PyLabRobot's generic simulator.
- **1.0** is for PyLabRobot 1.0. A robot PyLabRobot 1.0 has a class for has its class here, and
  each thing fitted to it is an instrument of its own, with PyLabRobot's step names. A robot only
  `pylabrobot.legacy` drives is that legacy `LiquidHandler`, one instrument. Since 1.0.0b2 every
  liquid handler PyLabRobot 1.0.0b1 drives is here.

## Robot by robot

| Robot | This package 0.2.x | Where it is in PyLabRobot 1.0.0b1 | This package 1.0 (since 1.0.0b2) |
| :--- | :--- | :--- | :--- |
| Opentrons Flex | not included | `pylabrobot.opentrons`: `Flex`, `FlexHead1`, `FlexHead8`, `FlexHead96`, `FlexGripper`. No simulator. | `opentrons.Flex` (since 1.0.0b1), on this package's simulated robot-server |
| Opentrons OT-2 | included | `pylabrobot.opentrons`: `OT2`, `OT2SingleChannelPipette`, `OT2_8ChannelPipette`. No simulator. | `opentrons.OT2`, on the same simulated robot-server |
| Hamilton STAR, STARlet, STARplus | included (STAR, STARlet) | `pylabrobot.hamilton.star`: `STAR`, `STARlet`, `STARPlus`, with `STARSimulationDriver` | `hamilton.STAR`, on PyLabRobot's simulator |
| Hamilton Prep | not included | `pylabrobot.hamilton.prep`: `Prep`, with `PrepSimulationDriver` | `hamilton.Prep`, on PyLabRobot's simulator |
| Hamilton Nimbus | included | only `pylabrobot.legacy` | `legacy.Nimbus`, on PyLabRobot's legacy chatterbox |
| Hamilton Vantage | included | only `pylabrobot.legacy` | `legacy.Vantage`, the same |
| Tecan EVO 100, 150, 200 | included | only `pylabrobot.legacy` | `legacy.EVO`, the same; no disposable tips yet (PyLabRobot cannot make a Tecan tip rack) |

Every one of them has a worktable file, is drawn in the Labware view, and keeps saved layouts.

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
run on two kinds of robot. A Nimbus, Vantage or EVO keeps the old step names, being PyLabRobot's
legacy `LiquidHandler`, but is a different instrument class, so its workflows need redoing too.

## The legacy route

`pylabrobot.legacy` in 1.0.0b1 still holds the old `LiquidHandler`, its backends and its
simulator. PyLabRobot marks it legacy and tells callers to move off it, but it is the only route to
a Nimbus, Vantage or EVO on PyLabRobot 1.0, so this package uses it for those three
(`plr_ivoryos.legacy`), and for any other legacy backend handed to `legacy.LiquidHandler`. When
PyLabRobot gives one of them a 1.0 class, it moves to that class here, as the STAR and OT-2 did.

## Versions

- The first two numbers follow PyLabRobot; the third is this package's own.
- While PyLabRobot 1.0 is in beta, each beta here (1.0.0b2, 1.0.0b3, ...) is pinned to exactly one
  PyLabRobot beta. After PyLabRobot 1.0.0: `pylabrobot>=1.0,<1.1`, and 1.0.1, 1.0.2 at our pace.
- 0.2.x gets fixes only. **0.2.1 is prepared and not published**: branch
  `fix/pylabrobot-below-1` requires `pylabrobot>=0.2.2,<1.0`. The published 0.2.0 has no upper
  bound, so it will break when PyLabRobot 1.0 is final. On 2026-11-22 that branch passed its tests
  on PyLabRobot 0.2.2 and ran a simulated STARlet and OT-2 with the current IvoryOS edge.

## What is left

What PyLabRobot lacks for these robots (an OT-2 and Flex simulator, 1.0 classes for the Nimbus,
Vantage and EVO, Tecan tip racks, decks that cannot be read back from their own `serialize()`) is
listed with what to send upstream in [simulators.md](simulators.md).
