# Simulators: what PyLabRobot 1.0.0b1 has, and what to do about what it lacks

Checked against the installed `pylabrobot==1.0.0b1`, November 2026.

## Liquid handlers

| Robot | PyLabRobot 1.0.0b1 drives it with | Simulator in PyLabRobot | What `simulated=True` runs here |
| :--- | :--- | :--- | :--- |
| Hamilton STAR, STARlet, STARplus | `pylabrobot.hamilton` (1.0) | **yes**: `STARSimulationDriver`, from recordings of real devices | PyLabRobot's |
| Hamilton Prep | `pylabrobot.hamilton.prep` (1.0) | **yes**: `PrepSimulationDriver` | PyLabRobot's |
| Opentrons Flex | `pylabrobot.opentrons.Flex` (1.0) | **no** | ours: a simulated robot-server (`opentrons/simulator.py`) under PyLabRobot's Flex |
| Opentrons OT-2 | `pylabrobot.opentrons.OT2` (1.0) | **no** for the 1.0 class (`OpentronsOT2Simulator` exists only for the legacy backend) | ours: the same robot-server, OT-2 flavour |
| Hamilton Nimbus | `pylabrobot.legacy` `NimbusBackend` | **no** robot-specific one | PyLabRobot's generic legacy `LiquidHandlerChatterboxBackend` |
| Hamilton Vantage | `pylabrobot.legacy` `VantageBackend` | **no** robot-specific one | the same generic chatterbox |
| Tecan Freedom EVO | `pylabrobot.legacy` `EVOBackend` | **no** robot-specific one | the same generic chatterbox |

What each simulator checks:

- **STAR, Prep** (PyLabRobot's): the firmware's answers, replayed from a recording, so a command
  the robot would refuse is refused. The strongest of the three kinds.
- **Flex, OT-2** (ours): everything PyLabRobot does above the HTTP transport (its tip and volume
  tracking, its reach and flow-rate checks, the commands a real run sends); the robot-server
  answers every command with success, except a pickup where the rack has no tip. Not the robot's
  own motion planning.
- **Nimbus, Vantage, EVO** (generic chatterbox): only PyLabRobot's legacy front end (tips, volumes,
  channel counts). Nothing robot-specific: no firmware, no deck geometry checks beyond PyLabRobot's
  resource tree.

## Should we build what is missing, or should PyLabRobot have it?

### Flex and OT-2 robot-server: ours now, better upstream

Easy and maintainable for us: one file (~270 lines), sitting on a seam PyLabRobot made public
(`Flex(io=...)`, `OT2(io=...)`), answering a small, stable HTTP API (health, instruments, runs,
commands). A command it does not know is answered with success, so a new PyLabRobot command does
not break it; at worst it is checked less. Both robots share it.

Still, **the better home is PyLabRobot**: it is the natural counterpart of `STARSimulationDriver`,
every PyLabRobot user would get a simulated Flex and OT-2, and PyLabRobot's own tests would keep its
answers in step with the commands PyLabRobot sends. A PR would add it as
`pylabrobot.opentrons.simulator` (or an `io` for `Flex(simulation=True)`), with our tip-sensor and
position behaviour. Keep ours until one is merged, then use theirs.

### Nimbus, Vantage, EVO: don't build one; wait for (or contribute) their 1.0 classes

Not maintainable for us. A useful robot-specific simulator means emulating the robot's firmware
protocol (the Nimbus's TCP introspection protocol, the Vantage's and EVO's firmware strings), for
backends PyLabRobot is replacing: the STAR and Prep show the pattern, a 1.0 class with a
`*SimulationDriver` built from recordings. The generic chatterbox already checks what this package
depends on (tips, volumes, wells). When PyLabRobot ports one of these robots to 1.0, it gets a
module here like `hamilton/star.py`, with PyLabRobot's simulator. If we want them sooner, the
contribution is upstream: a 1.0 class and simulation driver, recorded from a real robot.

### Bugs in PyLabRobot 1.0.0b1 found doing this: small PRs upstream

| What | Effect here | Fix |
| :--- | :--- | :--- |
| No Tecan tip rack can be made: every `DiTi_*` tip has `diameter=None`, and making one raises "Tip diameter is not defined" (PyLabRobot's tests expect it) | an EVO worktable cannot hold disposable tips | measured diameters for the Tecan tips (a data PR; needs the tips measured) |
| `FlexDeck`, `NimbusDeck`, `VantageDeck` and `TecanDeck` cannot be read back from their own `serialize()` (unexpected `size_x` / `model`, the wash station's missing `off_x`) | no `worktable.pylabrobot.json` beside those robots' worktables | each deck's `__init__` (or `deserialize`) to accept what `serialize` writes |
| `NimbusDeck` has no resource called `trash` (its waste positions are `default_long_1`...) | the legacy `discard_tips()` raises "Trash area not found" on a Nimbus; `drop_tips` to a rack works | name the waste, or give the deck a `get_trash_area` |
| The 1.0 `iSWAP` has joint moves only, no "move this plate there" | a STAR moves plates with its CoRe grippers here, not the iSWAP | a resource-level iSWAP move, as the CoRe grippers have |

## Everything else PyLabRobot 1.0 drives

PyLabRobot 1.0 gives several dozen other machines a class of their own (Inheco incubators and
ThermoShakes, BioTek readers and washers, Agilent PlateLoc and VSpin, Azenta, KBiosystems and Thermo
sealers, Mettler Toledo and Sartorius scales, Byonoy and SpectraMax readers, QInstruments BioShake,
HighRes storage, Brooks PreciseFlex, Keyence and Micronic scanners, ...). Of those, **only the LI-COR
Odyssey has a simulator** (`OdysseyChatterbox`). Only three take their transport as an argument
(`OdysseyClassic(io=...)` and the Micronic `SaneScanner` and `TwainScanner`); the rest open their
own serial port or socket, so there is no seam a simulator could use without patching.

Since 1.0.0b3 this package wraps the ones the 0.2 line had (README, *Devices*): the Mettler Toledo
balance, Masterflex pump, VSpin, BioShake, Inheco ThermoShake, Cytation 5, Synergy H1, SpectraMax M5
and 384 Plus, and the Byonoy A96 and L96 through their 1.0 classes, and the rest through
`pylabrobot.legacy`. How each is simulated, and what that checks:

| Device | Simulator | What it checks |
| :--- | :--- | :--- |
| a PyLabRobot 1.0 device class (the eleven above) | ours, `plr_ivoryos/simulators.py`: one per kind of device, standing in for the class at its methods | the step's arguments against PyLabRobot's signature, and the state the main operations change (a tare, a door that must be closed to spin, a target temperature); a reader's readings follow the liquids in each well. **None of PyLabRobot's driver code runs**: not the protocol, not its own checks. Weaker than the Flex's. |
| a legacy front end (scale, pump, centrifuge, heater-shaker, thermocycler, fan) | PyLabRobot's legacy chatterbox for it | PyLabRobot's legacy front end runs as written (a shake for a duration, `wait_for_temperature`, `run_pcr_profile` building its protocol); nothing device-specific |
| a legacy plate reader backend (CLARIOstar, Spark, Infinite, Gemini EM) | ours, as for a 1.0 reader | as for a 1.0 reader |

Simulating each protocol ourselves (as the Flex's robot-server does) is not maintainable for dozens
of devices, so the 1.0 classes are stood in for at the method level. The upstream fix is still one
pattern for all of them: each machine takes its `io` (or a driver) as an argument, as the Flex, OT-2
and Odyssey do, so a chatterbox or a recorded-traffic replay (`pylabrobot.io` already has capture
and validation) can stand in for the device, and its own code runs in simulation.
