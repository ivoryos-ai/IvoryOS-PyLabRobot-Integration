"""Agilent devices through PyLabRobot 1.0: the VSpin centrifuge and the BioTek Cytation 5 and
Synergy H1 plate readers.

    from plr_ivoryos.agilent import VSpin, Cytation5, SynergyH1
    vspin = VSpin(device_id="FTXXXXXX")         # needs plr-ivoryos[ftdi]
    reader = SynergyH1(simulated=True)          # reads the plates of the liquid handler beside it

The steps are PyLabRobot's own methods. A reader's `plate` and `wells` name labware on a liquid
handler's worktable (device.Reader), written as for a robot's steps: `assay_plate`,
`assay_plate[A1:H12]`.
"""

from typing import Optional

from pylabrobot.agilent.biotek.cytation.cytation5 import Cytation5 as PLRCytation5
from pylabrobot.agilent.biotek.synergy.synergy_h1 import SynergyH1 as PLRSynergyH1
from pylabrobot.agilent.vspin import VSpin as PLRVSpin

from plr_ivoryos import worktable as _worktable
from plr_ivoryos.device import Device, Reader, device_steps
from plr_ivoryos.simulators import SimulatedCentrifuge, SimulatedPlateReader


class VSpin(Device):
    """An Agilent VSpin centrifuge over FTDI (PyLabRobot: agilent.vspin.VSpin). Before its first
    spin, set where bucket 1 is (`set_bucket_1_position_to_current`), as PyLabRobot asks.

    device_id    the FTDI serial number; optional when there is one VSpin
    simulated    a door, a bucket lock and spins that take their time (simulators.SimulatedCentrifuge)
    step_delay_s a pause after each step, simulated only
    """

    def __init__(self, device_id: Optional[str] = None, simulated: bool = False, step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s)
        self._plr = SimulatedCentrifuge(PLRVSpin) if self._simulated else PLRVSpin(name="vspin", device_id=device_id)


class Cytation5(Reader):
    """An Agilent BioTek Cytation 5 imaging reader, used as a plate reader (absorbance, fluorescence,
    luminescence) over FTDI (PyLabRobot: Cytation5).

    device_id    the FTDI serial number; optional when there is one reader
    use_cam      start the camera too (PyLabRobot's imaging, plr-ivoryos does not offer it as steps)
    camera_serial  which camera, with use_cam
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    def __init__(self, device_id: Optional[str] = None, use_cam: bool = False, camera_serial: Optional[str] = None,
                 simulated: bool = False, worktable: Optional[str] = None, plate_type: str = _worktable._PLATE,
                 signal_liquids: str = "dye", step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s, worktable, plate_type, signal_liquids)
        self._plr = SimulatedPlateReader(PLRCytation5, self) if self._simulated else \
            PLRCytation5(name="cytation5", device_id=device_id, use_cam=use_cam, camera_serial=camera_serial)


class SynergyH1(Reader):
    """An Agilent BioTek Synergy H1 plate reader over FTDI (PyLabRobot: SynergyH1).

    device_id    the FTDI serial number; optional when there is one reader
    timeout      seconds to wait for an answer
    simulated, worktable, plate_type, signal_liquids, step_delay_s: see device.Reader
    """

    def __init__(self, device_id: Optional[str] = None, timeout: float = 20, simulated: bool = False,
                 worktable: Optional[str] = None, plate_type: str = _worktable._PLATE, signal_liquids: str = "dye",
                 step_delay_s: float = 0.0):
        super().__init__(simulated, step_delay_s, worktable, plate_type, signal_liquids)
        self._plr = SimulatedPlateReader(PLRSynergyH1, self) if self._simulated else \
            PLRSynergyH1(name="synergy_h1", timeout=timeout, device_id=device_id)


SKIPPED = {
    "VSpin": device_steps(VSpin, PLRVSpin, exclude=("g_to_rpm",)),
    "Cytation5": device_steps(Cytation5, PLRCytation5),
    "SynergyH1": device_steps(SynergyH1, PLRSynergyH1),
}
