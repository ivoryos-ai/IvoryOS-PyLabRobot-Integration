"""
plr_ivoryos.simple
===================
Thin, synchronous IvoryOS wrappers for PLR devices that have primitive-only
arguments (Scale, Pump, HeaterShaker, Centrifuge, PlateReader, Fan,
Thermocycler, TemperatureController, Sealer, Peeler, Tilter, BarcodeScanner).

These classes have no resource-model problem — every PLR method on these
devices accepts plain Python scalars (float, int, str).  The only thing the
wrapper needs to do is:

  1. Call setup() once at construction time on the shared async loop.
  2. Proxy every useful public method through run_async().

All PLR docstrings are preserved so IvoryOS can display them in the UI.

Simulator backends
------------------
SimulatedScaleBackend  — in-memory scale; no hardware needed.
Use it to develop and test Scale-based workflows inside IvoryOS immediately.
SimulatedSealerBackend, SimulatedPeelerBackend, SimulatedBarcodeScannerBackend — the same for
devices PyLabRobot 0.2.2 has no simulator for. The others use PyLabRobot's own chatterbox.
"""

from __future__ import annotations

import logging
from typing import List, Literal, Optional, Union

from plr_ivoryos.async_bridge import run_async

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SimulatedScaleBackend — test PLRScale without any physical hardware
# ---------------------------------------------------------------------------

class SimulatedScaleBackend:
    """
    A fully in-memory PLR ScaleBackend for development and testing.

    Returns a configurable simulated weight and logs every operation.
    No serial port, USB cable, or physical balance required.

    Usage
    -----
        from plr4ivoryos.simple import SimulatedScaleBackend
        from plr4ivoryos import PLRScale

        scale = PLRScale(
            backend=SimulatedScaleBackend(initial_weight=12.5),
            name="sim_balance",
        )

    The simulated weight increments slightly on each read to mimic a real
    balance settling, making it useful for testing loop/wait logic too.
    """

    def __init__(self, initial_weight: float = 10.0, noise: float = 0.05):
        self._weight = initial_weight
        self._noise = noise
        self._tare_offset = 0.0
        self._is_set_up = False

    # PLR ScaleBackend protocol ------------------------------------------------

    async def setup(self, **kwargs) -> None:
        self._is_set_up = True
        _log.info("[SimulatedScale] setup() — connected (simulated)")

    async def stop(self, **kwargs) -> None:
        self._is_set_up = False
        _log.info("[SimulatedScale] stop() — disconnected (simulated)")

    async def zero(self, **kwargs) -> None:
        """Reset zero calibration point."""
        self._tare_offset = self._weight
        _log.info("[SimulatedScale] zero() — tare offset set to %.4f g", self._tare_offset)

    async def tare(self, **kwargs) -> None:
        """Tare the scale."""
        self._tare_offset = self._weight
        _log.info("[SimulatedScale] tare() — weight zeroed")

    async def get_weight(self, **kwargs) -> float:
        """Return simulated weight in grams (with tiny noise each read)."""
        import random
        self._weight += random.uniform(-self._noise, self._noise)
        reading = max(0.0, self._weight - self._tare_offset)
        _log.info("[SimulatedScale] read_weight() → %.4f g", reading)
        return reading

    async def read_weight(self, **kwargs) -> float:
        """PyLabRobot 0.2.2 renamed the backend's get_weight to read_weight."""
        return await self.get_weight(**kwargs)

    # Helper: set a new simulated weight (useful in test scripts) -------------

    def set_weight(self, weight: float) -> None:
        """Programmatically set the simulated weight (for testing)."""
        self._weight = weight
        _log.info("[SimulatedScale] set_weight(%.4f g)", weight)



# ---------------------------------------------------------------------------
# SimulatedPumpBackend
# ---------------------------------------------------------------------------

class SimulatedPumpBackend:
    """A simulated PLR PumpBackend."""
    def __init__(self):
        self._is_running = False

    async def setup(self, **kwargs) -> None:
        _log.info("[SimulatedPump] setup()")

    async def stop(self, **kwargs) -> None:
        _log.info("[SimulatedPump] stop()")

    def run_continuously(self, speed: float):
        self._is_running = True
        _log.info("[SimulatedPump] run_continuously(speed=%.2f)", speed)

    def run_for_duration(self, speed: float, duration: float):
        _log.info("[SimulatedPump] run_for_duration(speed=%.2f, duration=%.2f)", speed, duration)

    def pump_volume(self, speed: float, volume: float):
        _log.info("[SimulatedPump] pump_volume(speed=%.2f, volume=%.2f)", speed, volume)

    def halt(self):
        self._is_running = False
        _log.info("[SimulatedPump] halt()")


# ---------------------------------------------------------------------------
# SimulatedHeaterShakerBackend
# ---------------------------------------------------------------------------

class SimulatedHeaterShakerBackend:
    """A simulated PLR HeaterShakerBackend."""
    def __init__(self):
        self.supports_locking = False
    async def setup(self, **kwargs) -> None: _log.info("[SimulatedHS] setup()")
    async def stop(self, **kwargs) -> None: _log.info("[SimulatedHS] stop()")
    async def set_temperature(self, temp: float): _log.info("[SimulatedHS] set_temperature(%.2f)", temp)
    async def get_current_temperature(self) -> float: return 25.0
    async def deactivate(self): _log.info("[SimulatedHS] deactivate()")
    async def start_shaking(self, speed: float): _log.info("[SimulatedHS] shake(%.2f)", speed)
    async def stop_shaking(self): _log.info("[SimulatedHS] stop_shaking()")


# ---------------------------------------------------------------------------
# SimulatedGenericBackend — for devices that just need to log setup/stop
# ---------------------------------------------------------------------------

class SimulatedGenericBackend:
    """A generic simulated PLR backend that logs all async calls."""
    def __init__(self, name="Generic"):
        self._name = name
    async def setup(self, **kwargs) -> None: _log.info("[%s] setup()", self._name)
    async def stop(self, **kwargs) -> None: _log.info("[%s] stop()", self._name)
    def __getattr__(self, item):
        if item.startswith("_"): raise AttributeError(item)
        async def _mock_call(*args, **kwargs):
            _log.info("[%s] %s(%s, %s)", self._name, item, args, kwargs)
            if item.lower().startswith("read_"):
                data = [[0.1 for _ in range(12)] for _ in range(8)]
                measurement = {
                    "time": 0.0,
                    "temperature": 25.0,
                    "data": data,
                }
                if item == "read_absorbance":
                    measurement["wavelength"] = kwargs.get("wavelength")
                elif item == "read_fluorescence":
                    measurement["ex_wavelength"] = kwargs.get("excitation_wavelength")
                    measurement["em_wavelength"] = kwargs.get("emission_wavelength")
                return [measurement]
            if "get" in item.lower():
                return 0.0
            return None
        return _mock_call


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------

class Scale:
    """
    IvoryOS wrapper for a PyLabRobot Scale.

    Parameters
    ----------
    backend : ScaleBackend
        e.g. MettlerToledoWXS205SDU(port="COM3")
    name : str
        Resource name (required by PLR Scale).
    simulated : bool
        If True, use the SimulatedScaleBackend.
    size_x, size_y, size_z : float
        Physical dimensions in mm (pass 0 if unknown).
    """

    def __init__(self, backend=None, name: str = "scale", simulated: bool = False,
                 size_x: float = 0, size_y: float = 0, size_z: float = 0):
        if simulated:
            backend = SimulatedScaleBackend()
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.scales import Scale as _Scale
        self._scale = _Scale(
            backend=backend, name=name,
            size_x=size_x, size_y=size_y, size_z=size_z,
        )
        run_async(self._scale.setup())

    def zero(self):
        """Calibrate the scale's zero point to the current load."""
        run_async(self._scale.zero())

    def tare(self):
        """Tare the scale — reset displayed weight to zero."""
        run_async(self._scale.tare())

    def read_weight(self) -> float:
        """Read the current weight in grams."""
        # read_weight since PyLabRobot 0.2.2; get_weight before (now deprecated, and it calls the
        # backend's read_weight, which older backends do not have).
        reader = getattr(self._scale, "read_weight", None) or self._scale.get_weight
        return run_async(reader())

    def shutdown(self):
        """Disconnect from the scale hardware."""
        run_async(self._scale.stop())


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------

class Pump:
    """
    IvoryOS wrapper for a PyLabRobot Pump.

    Parameters
    ----------
    backend : PumpBackend
        e.g. Masterflex() or ColeParmerPump()
    simulated : bool
        If True, use a simulated pump backend.
    """

    def __init__(self, backend=None, simulated: bool = False):
        if simulated:
            backend = SimulatedPumpBackend()
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.pumps import Pump as _Pump
        self._pump = _Pump(backend=backend)
        run_async(self._pump.setup())

    def run_continuously(self, speed: float = 100.0):
        """Start the pump at the given speed (rpm or device units). Run until halted."""
        run_async(self._pump.run_continuously(speed=speed))

    def run_for_duration(self, speed: float = 100.0, duration: float = 30.0):
        """Run the pump at *speed* for *duration* seconds, then stop."""
        run_async(self._pump.run_for_duration(speed=speed, duration=duration))

    def pump_volume(self, speed: float = 100.0, volume: float = 10.0):
        """Pump a specific *volume* (mL) at *speed*. Requires calibration."""
        run_async(self._pump.pump_volume(speed=speed, volume=volume))

    def halt(self):
        """Immediately stop the pump."""
        run_async(self._pump.halt())

    def shutdown(self):
        """Disconnect from the pump hardware."""
        run_async(self._pump.stop())


# ---------------------------------------------------------------------------
# HeaterShaker
# ---------------------------------------------------------------------------

class HeaterShaker:
    """
    IvoryOS wrapper for a PyLabRobot HeaterShaker.

    Parameters
    ----------
    backend : HeaterShakerBackend
        e.g. InhecoThermoShakeBackend()
    name : str
        Resource name.
    simulated : bool
        If True, use a simulated heater-shaker backend.
    size_x, size_y, size_z : float
        Physical dimensions in mm.
    child_location : Coordinate, optional
        Location of the child resource slot (default: origin).
    """

    def __init__(self, backend=None, name: str = "heater_shaker", simulated: bool = False,
                 size_x: float = 0, size_y: float = 0, size_z: float = 0,
                 child_location=None):
        if simulated:
            backend = SimulatedHeaterShakerBackend()
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.heating_shaking import HeaterShaker as _HeaterShaker
        from pylabrobot.resources.coordinate import Coordinate
        self._hs = _HeaterShaker(
            backend=backend, name=name,
            size_x=size_x, size_y=size_y, size_z=size_z,
            child_location=child_location or Coordinate.zero(),
        )
        run_async(self._hs.setup())

    def set_temperature(self, temperature: float = 37.0):
        """Set the target temperature in °C."""
        run_async(self._hs.set_temperature(temperature))

    def deactivate_temperature(self):
        """Turn off the heater / stop temperature control."""
        run_async(self._hs.deactivate())

    def shake(self, speed: float = 300.0):
        """Start shaking at *speed* (rpm). Runs until stopped."""
        run_async(self._hs.shake(speed=speed))

    def stop_shaking(self):
        """Stop shaking."""
        run_async(self._hs.stop_shaking())

    def shutdown(self):
        """Stop heating/shaking and disconnect."""
        run_async(self._hs.stop())


# ---------------------------------------------------------------------------
# Centrifuge
# ---------------------------------------------------------------------------

class Centrifuge:
    """
    IvoryOS wrapper for a PyLabRobot Centrifuge.

    Parameters
    ----------
    backend : CentrifugeBackend
        e.g. VSpin(bucket_1_position=0)
    name : str
        Resource name.
    simulated : bool
    size_x, size_y, size_z : float
        Physical dimensions in mm.
    """

    def __init__(self, backend=None, name: str = "centrifuge", simulated: bool = False,
                 size_x: float = 0, size_y: float = 0, size_z: float = 0):
        if simulated:
            backend = SimulatedGenericBackend(name="Centrifuge")
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.centrifuge import Centrifuge as _Centrifuge
        self._cf = _Centrifuge(
            backend=backend, name=name,
            size_x=size_x, size_y=size_y, size_z=size_z,
        )
        run_async(self._cf.setup())

    def spin(self, g: float = 400.0, duration: float = 60.0):
        """Start a spin cycle at *g* × gravity for *duration* seconds."""
        run_async(self._cf.start_spin_cycle(g=g, duration=duration))

    def shutdown(self):
        """Disconnect from the centrifuge."""
        run_async(self._cf.stop())


# ---------------------------------------------------------------------------
# PlateReader
# ---------------------------------------------------------------------------

class PlateReader:
    """
    IvoryOS wrapper for a PyLabRobot PlateReader.

    Parameters
    ----------
    backend : PlateReaderBackend
        e.g. CLARIOstarBackend() or Cytation5Backend()
    name : str
        Resource name.
    simulated : bool
    size_x, size_y, size_z : float
        Physical dimensions in mm.
    """

    def __init__(self, backend=None, name: str = "plate_reader", simulated: bool = False,
                 size_x: float = 1, size_y: float = 1, size_z: float = 1):
        if simulated:
            backend = SimulatedGenericBackend(name="PlateReader")
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.plate_reading import PlateReader as _PlateReader
        self._pr = _PlateReader(
            backend=backend, name=name,
            size_x=size_x, size_y=size_y, size_z=size_z,
        )
        run_async(self._pr.setup())

    def read_luminescence(self, focal_height: float = 10.0) -> list:
        """Read a luminescence plate measurement."""
        return run_async(self._pr.read_luminescence(focal_height=focal_height))

    def read_absorbance(self, wavelength: float = 450.0) -> list:
        """Read absorbance at *wavelength* nm."""
        return run_async(self._pr.read_absorbance(wavelength=wavelength))

    def read_fluorescence(self,
                          excitation_wavelength: float = 485.0,
                          emission_wavelength: float = 535.0,
                          focal_height: float = 10.0) -> list:
        """Read fluorescence intensity."""
        return run_async(self._pr.read_fluorescence(
            excitation_wavelength=excitation_wavelength,
            emission_wavelength=emission_wavelength,
            focal_height=focal_height,
        ))

    def shutdown(self):
        """Disconnect from the plate reader."""
        run_async(self._pr.stop())


# ---------------------------------------------------------------------------
# Fan
# ---------------------------------------------------------------------------

class Fan:
    """
    IvoryOS wrapper for a PyLabRobot Fan.

    Parameters
    ----------
    backend : FanBackend
        e.g. HamiltonHepaFanBackend()
    name : str
        Resource name.
    simulated : bool
    """

    def __init__(self, backend=None, name: str = "fan", simulated: bool = False):
        if simulated:
            backend = SimulatedGenericBackend(name="Fan")
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.only_fans import Fan as _Fan
        self._fan = _Fan(backend=backend)
        run_async(self._fan.setup())

    def turn_on(self, intensity: float = 100.0, duration: float = None):
        """Turn the fan on at *intensity* % for *duration* seconds."""
        run_async(self._fan.turn_on(intensity=intensity, duration=duration))

    def turn_off(self):
        """Turn the fan off immediately."""
        run_async(self._fan.turn_off())

    def shutdown(self):
        """Disconnect from the fan."""
        run_async(self._fan.stop())


# ---------------------------------------------------------------------------
# Thermocycler
# ---------------------------------------------------------------------------

class Thermocycler:
    """
    IvoryOS wrapper for a PyLabRobot Thermocycler.

    Parameters
    ----------
    backend : ThermocyclerBackend
    name : str
    simulated : bool
    size_x, size_y, size_z : float
    child_location : Coordinate, optional
    """

    def __init__(self, backend=None, name: str = "thermocycler", simulated: bool = False,
                 size_x: float = 0, size_y: float = 0, size_z: float = 0,
                 child_location=None):
        if simulated:
            backend = SimulatedGenericBackend(name="Thermocycler")
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.thermocycling import Thermocycler as _Thermocycler
        from pylabrobot.resources.coordinate import Coordinate
        self._tc = _Thermocycler(
            backend=backend, name=name,
            size_x=size_x, size_y=size_y, size_z=size_z,
            child_location=child_location or Coordinate.zero(),
        )
        run_async(self._tc.setup())

    def run_pcr_profile(
        self,
        denaturation_temp: float = 98.0,
        denaturation_time: float = 10.0,
        annealing_temp: float = 55.0,
        annealing_time: float = 30.0,
        extension_temp: float = 72.0,
        extension_time: float = 60.0,
        num_cycles: int = 30,
        lid_temperature: float = 105.0,
        pre_denaturation_temp: float = 95.0,
        pre_denaturation_time: float = 180.0,
        final_extension_temp: float = 72.0,
        final_extension_time: float = 300.0,
        storage_temp: float = 4.0,
    ):
        """Run a standard PCR protocol."""
        run_async(self._tc.run_pcr_profile(
            denaturation_temp=denaturation_temp,
            denaturation_time=denaturation_time,
            annealing_temp=annealing_temp,
            annealing_time=annealing_time,
            extension_temp=extension_temp,
            extension_time=extension_time,
            num_cycles=num_cycles,
            block_max_volume=25.0,
            lid_temperature=lid_temperature,
            pre_denaturation_temp=pre_denaturation_temp,
            pre_denaturation_time=pre_denaturation_time,
            final_extension_temp=final_extension_temp,
            final_extension_time=final_extension_time,
            storage_temp=storage_temp,
            storage_time=600.0,
        ))

    def set_temperature(self, temperature: float = 37.0):
        """Set the block temperature in °C."""
        run_async(self._tc.set_block_temperature(temperature))

    def shutdown(self):
        """Disconnect from the thermocycler."""
        run_async(self._tc.stop())


# ---------------------------------------------------------------------------
# Simulators for devices PyLabRobot 0.2.2 has none for
# ---------------------------------------------------------------------------

class SimulatedSealerBackend:
    """A simulated PLR SealerBackend: remembers its temperature and logs each seal."""
    def __init__(self, temperature: float = 25.0):
        self._temperature = temperature
    async def setup(self, **kwargs) -> None: _log.info("[SimulatedSealer] setup()")
    async def stop(self, **kwargs) -> None: _log.info("[SimulatedSealer] stop()")
    async def seal(self, temperature: int, duration: float):
        self._temperature = float(temperature)
        _log.info("[SimulatedSealer] seal(temperature=%s, duration=%s)", temperature, duration)
    async def open(self): _log.info("[SimulatedSealer] open()")
    async def close(self): _log.info("[SimulatedSealer] close()")
    async def set_temperature(self, temperature: float): self._temperature = float(temperature)
    async def get_temperature(self) -> float: return self._temperature


class SimulatedPeelerBackend:
    """A simulated PLR PeelerBackend."""
    async def setup(self, **kwargs) -> None: _log.info("[SimulatedPeeler] setup()")
    async def stop(self, **kwargs) -> None: _log.info("[SimulatedPeeler] stop()")
    async def peel(self, **kwargs): _log.info("[SimulatedPeeler] peel(%s)", kwargs)
    async def restart(self, **kwargs): _log.info("[SimulatedPeeler] restart()")


class SimulatedBarcodeScannerBackend:
    """A simulated PLR BarcodeScannerBackend. Hands out `codes` in turn, then SIM-0001, SIM-0002..."""
    def __init__(self, codes: Optional[List[str]] = None):
        self._codes = list(codes or [])
        self._count = 0
    async def setup(self, **kwargs) -> None: _log.info("[SimulatedBarcodeScanner] setup()")
    async def stop(self, **kwargs) -> None: _log.info("[SimulatedBarcodeScanner] stop()")
    async def scan_barcode(self):
        from pylabrobot.resources.barcode import Barcode
        self._count += 1
        data = self._codes.pop(0) if self._codes else f"SIM-{self._count:04d}"
        return Barcode(data=data, symbology="Code128", position_on_resource="front")


# ---------------------------------------------------------------------------
# TemperatureController
# ---------------------------------------------------------------------------

class TemperatureController:
    """
    IvoryOS wrapper for a PyLabRobot TemperatureController: a block that heats or cools a plate.

    Parameters
    ----------
    backend : TemperatureControllerBackend
        e.g. InhecoCPACBackend(index=1, control_box=InhecoTECControlBox(...)), or
        OpentronsTemperatureModuleUSBBackend(port="/dev/ttyACM0")
    name : str
        Resource name.
    simulated : bool
        If True, use PyLabRobot's TemperatureControllerChatterboxBackend.
    """

    def __init__(self, backend=None, name: str = "temperature_controller", simulated: bool = False,
                 size_x: float = 0, size_y: float = 0, size_z: float = 0, child_location=None):
        if simulated:
            from pylabrobot.temperature_controlling import TemperatureControllerChatterboxBackend
            backend = TemperatureControllerChatterboxBackend(dummy_temperature=25.0)
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.temperature_controlling import TemperatureController as _TemperatureController
        from pylabrobot.resources.coordinate import Coordinate
        self._tc = _TemperatureController(
            backend=backend, name=name,
            size_x=size_x, size_y=size_y, size_z=size_z,
            child_location=child_location or Coordinate.zero(),
        )
        run_async(self._tc.setup())

    def set_temperature(self, temperature: float = 37.0, passive: bool = False) -> None:
        """Set the target temperature in °C. With *passive*, a block that cannot cool lets a lower
        temperature be reached by switching its heater off instead of refusing."""
        run_async(self._tc.set_temperature(temperature, passive=passive))

    def get_temperature(self) -> float:
        """Read the current block temperature in °C."""
        return run_async(self._tc.get_temperature())

    def wait_for_temperature(self, timeout: float = 300.0, tolerance: float = 0.5) -> None:
        """Wait until the block is within *tolerance* °C of its target, for at most *timeout* s."""
        run_async(self._tc.wait_for_temperature(timeout=timeout, tolerance=tolerance))

    def deactivate(self) -> None:
        """Stop temperature control."""
        run_async(self._tc.deactivate())

    def shutdown(self) -> None:
        """Stop temperature control and disconnect."""
        run_async(self._tc.stop())


# ---------------------------------------------------------------------------
# Sealer
# ---------------------------------------------------------------------------

class Sealer:
    """
    IvoryOS wrapper for a PyLabRobot plate Sealer (heat sealing a foil onto a plate).

    Parameters
    ----------
    backend : SealerBackend
        e.g. A4SBackend(port="COM5") (Azenta a4S)
    simulated : bool
        If True, use SimulatedSealerBackend.
    """

    def __init__(self, backend=None, simulated: bool = False):
        if simulated:
            backend = SimulatedSealerBackend()
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.sealing import Sealer as _Sealer
        self._sealer = _Sealer(backend=backend)
        run_async(self._sealer.setup())

    def seal(self, temperature: int, duration: float) -> None:
        """Seal the plate in the sealer at *temperature* °C, pressing for *duration* seconds."""
        run_async(self._sealer.seal(temperature=temperature, duration=duration))

    def open(self) -> None:
        """Move the shuttle out, to put a plate on or take it off."""
        run_async(self._sealer.open())

    def close(self) -> None:
        """Move the shuttle in."""
        run_async(self._sealer.close())

    def set_temperature(self, temperature: float) -> None:
        """Heat the sealing plate to *temperature* °C ahead of sealing."""
        run_async(self._sealer.set_temperature(temperature))

    def get_temperature(self) -> float:
        """Read the sealing plate's temperature in °C."""
        return run_async(self._sealer.get_temperature())

    def shutdown(self) -> None:
        """Disconnect from the sealer."""
        run_async(self._sealer.stop())


# ---------------------------------------------------------------------------
# Peeler
# ---------------------------------------------------------------------------

class Peeler:
    """
    IvoryOS wrapper for a PyLabRobot plate Peeler (taking a seal off a plate).

    Parameters
    ----------
    backend : PeelerBackend
        e.g. XPeelBackend(port="COM6") (Azenta XPeel)
    simulated : bool
        If True, use SimulatedPeelerBackend.
    """

    def __init__(self, backend=None, simulated: bool = False):
        if simulated:
            backend = SimulatedPeelerBackend()
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.peeling.peeler import Peeler as _Peeler
        self._peeler = _Peeler(backend=backend)
        run_async(self._peeler.setup())

    def peel(self, begin_location: Literal[-2, 0, 2, 4] = 0, fast: bool = False, adhere_time: float = 2.5) -> None:
        """Peel the seal off the plate in the peeler. *begin_location* is where the peel starts,
        in mm from the default; *adhere_time* how long the tape is pressed on (s)."""
        run_async(self._peeler.peel(begin_location=begin_location, fast=fast, adhere_time=adhere_time))

    def restart(self) -> None:
        """Restart the peeler, e.g. after an error."""
        run_async(self._peeler.restart())

    def shutdown(self) -> None:
        """Disconnect from the peeler."""
        run_async(self._peeler.stop())


# ---------------------------------------------------------------------------
# Tilter
# ---------------------------------------------------------------------------

class Tilter:
    """
    IvoryOS wrapper for a PyLabRobot tilt module: tilts a plate so a liquid handler can reach the
    last of each well.

    Parameters
    ----------
    com_port : str
        The Hamilton tilt module's serial port.
    name : str
        Resource name.
    simulated : bool
        If True, a Hamilton tilt module on PyLabRobot's TilterChatterboxBackend.
    backend : TilterBackend, optional
        Another backend, on the Hamilton tilt module's geometry.
    """

    def __init__(self, com_port: Optional[str] = None, name: str = "tilter", simulated: bool = False, backend=None):
        if simulated:
            from pylabrobot.tilting.chatterbox import TilterChatterboxBackend
            backend = TilterChatterboxBackend()
        if backend is None and not com_port:
            raise ValueError("Provide 'com_port', a 'backend', or 'simulated=True'.")
        if backend is None:
            from pylabrobot.tilting import HamiltonTiltModule
            self._tilter = HamiltonTiltModule(name=name, com_port=com_port)
        else:
            # The Hamilton module's geometry (as HamiltonTiltModule), built here because that class
            # opens its own serial backend, which a simulator has no port for.
            from pylabrobot.resources.coordinate import Coordinate
            from pylabrobot.tilting import Tilter as _Tilter
            self._tilter = _Tilter(
                name=name, size_x=132, size_y=92.57, size_z=85.81, backend=backend,
                hinge_coordinate=Coordinate(6.18, 0, 72.85), child_location=Coordinate(1.0, 3.0, 83.55),
                category="tilter", model="HamiltonTiltModule",
            )
        run_async(self._tilter.setup())

    def set_angle(self, absolute_angle: float) -> None:
        """Tilt to *absolute_angle* degrees (0 is flat)."""
        run_async(self._tilter.set_angle(absolute_angle))

    def tilt(self, relative_angle: float) -> None:
        """Tilt by *relative_angle* degrees from where it is."""
        run_async(self._tilter.tilt(relative_angle))

    def shutdown(self) -> None:
        """Disconnect from the tilt module."""
        run_async(self._tilter.stop())


# ---------------------------------------------------------------------------
# BarcodeScanner
# ---------------------------------------------------------------------------

class BarcodeScanner:
    """
    IvoryOS wrapper for a PyLabRobot BarcodeScanner.

    Parameters
    ----------
    backend : BarcodeScannerBackend
        e.g. KeyenceBarcodeScannerBackend(port="COM7")
    simulated : bool
        If True, use SimulatedBarcodeScannerBackend.
    """

    def __init__(self, backend=None, simulated: bool = False):
        if simulated:
            backend = SimulatedBarcodeScannerBackend()
        if backend is None:
            raise ValueError("Provide either 'backend' or 'simulated=True'.")
        from pylabrobot.barcode_scanners import BarcodeScanner as _BarcodeScanner
        self._scanner = _BarcodeScanner(backend=backend)
        run_async(self._scanner.setup())

    def scan(self) -> str:
        """Read the barcode in front of the scanner and return its text."""
        return run_async(self._scanner.scan()).data

    def shutdown(self) -> None:
        """Disconnect from the scanner."""
        run_async(self._scanner.stop())
