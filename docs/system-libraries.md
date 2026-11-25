# What a device needs outside Python

`pip install "plr-ivoryos[...]"` (and the IvoryOS desktop app, which installs a Hub driver the same
way) installs Python packages only. Some of PyLabRobot's connection libraries are Python wrappers
around a library of the operating system, which no pip package carries: **for those devices, the
library has to be installed separately, with the system's package manager or from the library's own
project, before the device can connect.** The desktop app cannot do it for you.

A **simulated** device needs none of this: it never opens a connection.

Checked on 2026-11-24 with plr-ivoryos 1.0.0b3 and PyLabRobot 1.0.0b1 on macOS (every extra
installed in a clean environment, each library loaded); the Linux and Windows steps are from
PyLabRobot's installation guide, the libraries' own projects and common practice, not run here.

| Extra | Python packages it installs | Also needs, outside Python | Devices |
| :--- | :--- | :--- | :--- |
| `serial` | pyserial | nothing | Mettler Toledo balance, Masterflex pump, BioShake, SpectraMax M5, 384 Plus and Gemini EM, a Flex over its USB-B port |
| `usb` | pyusb, libusb-package (which carries libusb) | **Windows:** a libusbK driver for the device, set with Zadig ([below](#windows-usb-driver-zadig)) | Hamilton STAR, Vantage, Tecan EVO, Tecan Spark and Infinite 200 PRO, Hamilton Heater Shaker |
| `ftdi` | pylibftdi, pyusb | **the libftdi library** (with libusb) | BioTek Cytation 5 and Synergy H1, Agilent VSpin, BMG CLARIOstar, Hamilton HEPA fan |
| `hid` | hid | **the hidapi library** | Byonoy Absorbance 96 and Luminescence 96, Inheco ThermoShake |
| `opentrons` | opentrons-http-api-client, httpx, zeroconf | nothing (it talks to the OT-2 over the network) | Opentrons Thermocycler through its OT-2 |

Every extra resolves, from wheels alone, beside `ivoryos-edge` on macOS, Linux and Windows with
Python 3.10, 3.12 and 3.14, and extras combine (`plr-ivoryos[usb,hid]==1.0.0b3`).

## hidapi (the `hid` extra)

| System | Install |
| :--- | :--- |
| macOS | `brew install hidapi` ([Homebrew](https://brew.sh)) |
| Debian, Ubuntu | `sudo apt install libhidapi-hidraw0` |
| Windows | `hidapi.dll` from the [hidapi releases](https://github.com/libusb/hidapi/releases) (the `x64` folder of `hidapi-win.zip`), in a folder on `PATH` |

Without it, the first step fails with PyLabRobot's message **"hid is not installed. Install with:
pip install pylabrobot[hid]"**, even though the `hid` package *is* installed: the part that matters
is what follows, "Unable to load any of the following libraries: libhidapi-hidraw.so ...
libhidapi.dylib hidapi.dll ...". Installing `pylabrobot[hid]` again does not help; installing
hidapi does.

## libftdi (the `ftdi` extra)

| System | Install |
| :--- | :--- |
| macOS | `brew install libftdi` (brings libusb with it) |
| Debian, Ubuntu | `sudo apt install libftdi1-2` |
| Windows | libftdi has no official Windows build, and PyLabRobot does not document one. Not checked here. |

PyLabRobot's own pages say to install "the platform's libftdi runtime" (its Synergy page) without
the commands. Without it, the first step fails with "libftdi library not found" or
`usb.core.NoBackendError: No backend available`. To find a device's FTDI serial number (the
`device_id` argument), PyLabRobot suggests `python -m pylibftdi.examples.list_devices`.

## Windows: USB driver (Zadig)

From PyLabRobot's installation guide, for a Hamilton or Tecan robot over USB: install
[Zadig](https://zadig.akeo.ie), connect the robot with no vendor software running, choose Options,
List All Devices, select "ML Star" (a STAR or STARlet) or "TECU" (a Tecan), choose **libusbK**, and
Replace Driver. The vendor's own software (VENUS) needs its driver back to drive the robot again;
PyLabRobot's guide says how. Other USB devices on Windows are likely to need the same; it is not
documented by PyLabRobot.

On macOS, PyLabRobot's guide also suggests `brew install libusb` for USB devices; the `usb` extra
carries libusb (libusb-package), which is what PyLabRobot 1.0.0b1 uses, so it was not needed here.

## Linux: permission to open the device

A device under `/dev` usually needs your user to be allowed to open it: the `dialout` group for a
serial port, a udev rule for a USB, FTDI or HID device. Without it, the step fails with a
permission error, and works with `sudo`.

## The Opentrons Thermocycler over USB

`OpentronsThermocycler(usb=True)` uses PyLabRobot's USB backend, which needs Opentrons' own
`opentrons` package (`pip install opentrons`): a large package of Opentrons' robot software that pins
its own dependencies (numpy 1.26). It is not an extra here. Through its OT-2 (`opentrons_id`, the
`opentrons` extra) it needs nothing more.

## When it shows

Not when the deck starts: a device is made without opening its connection, so the deck starts and
the device is listed. The first step (or `setup`) opens the connection, and that is where a missing
library is reported, as that step's error.
