# plr-ivoryos

**The native PyLabRobot experience, powered by IvoryOS.**

`plr-ivoryos` provides IvoryOS-compatible versions of standard [PyLabRobot](https://github.com/PyLabRobot/pylabrobot) classes. It allows you to build, simulate, and execute complex lab automation workflows using a visual interface, with **no manual wrapper code** required.

---

## 🚀 Quick Start (Simulation)

Develop and test your workflows with zero hardware. `plr-ivoryos` provides a built-in "headless" simulation mode that requires no configuration.

```python
from plr_ivoryos import LiquidHandler, Scale

# Start with a default simulated deck and balance
lh = LiquidHandler(simulated=True)
scale = Scale(simulated=True)

if __name__ == "__main__":
    import ivoryos
    ivoryos.run(__name__)
```

---

## ✨ Key Features

### 1. Native PLR Naming
Classes in `plr-ivoryos` use the exact same names as the original PyLabRobot classes (`LiquidHandler`, `Scale`, `Pump`, etc.). This makes the integration intuitive for PLR users while ensuring full compatibility with the IvoryOS ecosystem.

### 2. Smart Simulation Mode
Setting `simulated=True` on any device wrapper automatically selects a suitable mock backend. For the `LiquidHandler`, it also sets up a default Hamilton STARLet deck, allowing you to see interactive plate and well dropdowns in the IvoryOS UI immediately.

### 3. Dynamic Enum Introspection
`plr-ivoryos` inspects your hardware deck at runtime to generate dynamic Python Enums. 
- **Plate Selection**: Dropdowns are automatically populated with the specific plates on your deck.
- **Well Selection**: Intelligent `A1..H12` dropdowns for all aspiration and dispense commands.

---

## 🛠 Advanced Usage

### Custom Backends
You can pass any standard PyLabRobot backend to the wrappers. This is how you connect to real hardware or specialized simulators.

```python
from plr_ivoryos import Scale
from pylabrobot.scales.mettler_toledo import MettlerToledoWXS205SDU

# Connect to a real Mettler Toledo balance
scale = Scale(backend=MettlerToledoWXS205SDU(port="COM3"))
```

### Visual Simulator
To use PyLabRobot's 3D browser-based simulator, simply pass the `SimulatorBackend`:

```python
from plr_ivoryos import LiquidHandler
from pylabrobot.liquid_handling.backends import SimulatorBackend

lh = LiquidHandler(
    backend=SimulatorBackend(open_browser=True),
    deck_json="my_layout.json"
)
```

---

## 📋 Supported Devices

| Device Type | Class Name | Simulation Shortcut | Common Backends |
| :--- | :--- | :---: | :--- |
| **Liquid Handler** | `LiquidHandler` | `simulated=True` | Hamilton STAR, OT-2, Tecan EVO |
| **Balance** | `Scale` | `simulated=True` | Mettler Toledo |
| **Pumps** | `Pump` | `simulated=True` | Cole-Parmer Masterflex |
| **Heater/Shaker** | `HeaterShaker` | `simulated=True` | Inheco ThermoShake |
| **Centrifuge** | `Centrifuge` | `simulated=True` | VSpin |
| **Plate Reader** | `PlateReader` | `simulated=True` | CLARIOstar, Cytation5 |
| **Fans** | `Fan` | `simulated=True` | Hamilton HEPA |
| **Thermocycler** | `Thermocycler` | `simulated=True` | Any PLR-supported TC |

---

## ⚙️ Installation

```bash
pip install plr-ivoryos
```

Or from source:
```bash
pip install .
```

Or using the requirements file:
```bash
pip install -r requirements.txt
```

---

## 🏗 How it Works

### Async Bridge
PyLabRobot is built on `asyncio`. `plr-ivoryos` manages a dedicated background thread running a persistent event loop. All commands are safely bridged from the IvoryOS script-runner thread to the PLR loop, ensuring your UI stays responsive during long hardware operations.

### Runtime Registry
Runtime-generated Enums are registered in `plr_ivoryos._runtime_enums`. IvoryOS introspects these at startup to build the interactive forms and dropdowns seen in the Control Panel.

---

## License
MIT
