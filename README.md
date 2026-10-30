# Temp Top 🌡️

> A Linux terminal hardware temperature monitor and Braille grapher inspired by **Psensor** and **btop**.

```
╭─ temptop ───────────────────────────────────┤ Rate: 2000ms [+/-] ├─┤ Time: 5m [</>] ├─╮
│ 65°C┤┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│
│ 60°C┤┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄⣀⣀⣀⣀⠤⠤⠤⠔⠒⠒⠒⠉⠉⠉┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│
│ 50°C┤┄┄┄┄⢀⣀⣀⣀⠤⠤⠤⠔⠒⠒⠊⠉⠉⠉┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│
│ 40°C┤⠒⠊⠉⠉⠁┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│
│ 35°C┤┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│
├─ 09:35:16 ────────────────────────────────────────────────────────── 09:40:16 [5m] ─┤
│ [1] [✓] ● CPU (Tctl)       60.0° M:64°  [3] [✓] ● GPU (RTX 3060)     52.0° M:55°   │
│ [2] [✓] ● NVMe (Overall)   41.0° M:44°  [4] [✓] ● Motherboard        64.0° M:66°   │
│                                                                                    │
╰─ [1-9] Toggle  [+/-] Rate  [</>] Time  [M] Sensors  [D] Reset  [Q] Quit ───────────╯
```

---

## Features

- **Braille Multi-Curve Plotting**: Renders smooth, continuous curves using Unicode Braille characters (`U+2800` through `U+28FF`) with sub-pixel Bresenham line interpolation.
- **Hardware Integration & Zero-Overhead Polling**:
  - **Linux sysfs & lm-sensors**: Auto-detects all CPUs, motherboards, WiFi, and NVMe drives via direct `/sys/class/hwmon` acceleration with sub-millisecond reads.
  - **Nvidia GPU Support**: Direct NVML library bindings via standard library `ctypes` (`libnvidia-ml.so`) with fallback to `nvidia-smi`. Fully synchronized with the user-selected update frequency.
- **Dynamic Temperature Range & Half-Height 5° Segments**:
  - Graph Y-axis strictly bounds to currently displayed graph dots, automatically removing unused 10° ranges at the top and bottom.
  - Renders a clean half-height 5° segment at the bottom (e.g. 25°C, 35°C) and/or top (e.g. 65°C, 75°C, 85°C) whenever dots sit within those ranges.
- **Configurable Time Horizons**:
  - 10 selectable plot durations: **30s, 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m, and 60m**.
- **Accurate Time Range Tracking**:
  - Bottom-left shows the exact timestamp when the oldest visible data point was sampled.
  - Bottom-right shows the latest timestamp and active window duration (e.g. `[20m]`).
- **Interactive Sensor Key & Controls**:
  - Hotkeys `1` through `9` toggle sensor curves immediately.
  - **Color Accents**: Current temperature rendered in **bright orange**, session maximum recorded heat (`M:XX°`) in **darker red**.
  - **Disabled Sensor Filtering**: Sensors that are disabled are excluded from the main key on subsequent runs, reclaiming vertical rows for the graph.
  - **Dynamic Column Packing**: Automatically packs more devices per line when names are shortened by the user.
  - **Clean Spacing**: One blank separator row between sensor devices and bottom navigation controls.
- **Full-Featured Device Manager (`M` or `Enter`)**:
  - Seamless navigation with `Up`/`Down`, `k`/`j`, `PageUp`/`PageDown`, and `Home`/`End`.
  - Live graph display freezes cleanly while modals are open; upon exiting, graph refreshes with all background data gathered while in the menu.
  - Rename sensors, toggle visibility, adjust alarm thresholds, and cycle colors.
- **Audible & Visual Alarms**:
  - Optional terminal bell (`\a`) and alert header banner when any sensor exceeds its threshold.
- **Configuration File**:
  - Stored at `~/.config/temptop/config.py` with automatic migration support.

---

## Installation & Quick Start

### Direct Execution
Temp Top is self-contained with no external Python library dependencies:

```bash
# Run directly from the temptop directory
python temptop.py

# Or via the executable symlink
./temptop

# Or run globally via PATH (~/.local/bin)
temptop
```

### Nix Flake

Run directly without installing:

```bash
nix run github:Scoobin/temptop
```

Install into your profile:

```bash
nix profile install github:Scoobin/temptop
```

Or add to a NixOS/home-manager configuration:

```nix
# flake.nix inputs
inputs.temptop.url = "github:Scoobin/temptop";

# Then in your packages list
inputs.temptop.packages.${system}.default
```

For local development with all dependencies available:

```bash
nix develop
```

---

### CLI Options

```
temptop [options]

Options:
  -c, --config PATH     Path to custom configuration file
  -r, --rate MS         Initial sensor sample frequency in ms (default: 2000)
  -t, --time SECONDS    Initial total graphed plot time in seconds (default: 300)
  -l, --list-sensors    List detected temperature sensors and exit
  -v, --version         Show application version
  -h, --help            Show help message
```

---

## Keyboard Controls

| Key | Action |
|-----|--------|
| `1` – `9` | **Toggle Sensor**: Immediately show/hide sensors 1 through 9 |
| `+` / `-` | **Sample Frequency**: Increase / decrease sample interval by 250ms (down to 100ms) |
| `>` / `<` (or `w` / `W`) | **Plot Duration**: Cycle plot time window (30s, 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m, 60m) |
| `M` or `Enter` | **Device Manager**: Open interactive menu to rename sensors, toggle alarms, edit thresholds, and change colors |
| `P` | **Pause / Resume**: Freeze live graph plotting for inspection |
| `S` | **Save Settings**: Force save current settings to configuration file |
| `D` or `Ctrl+R` | **Reset Defaults**: Prompt to reset all settings, names, colors, and alarms to factory defaults |
| `H` or `?` | **Help**: View keyboard shortcut overlay |
| `Q` or `Esc` | **Quit**: Exit application cleanly (current settings are auto-saved) |

---

## Device Manager Modal (`M` or `Enter`)

When inside the Device Manager:
- `Up` / `Down` (`k` / `j`): Select sensor
- `PageUp` / `PageDown`: Jump by 5 sensors
- `Home` / `End`: Jump to first / last sensor
- `Space`: Toggle visibility on graph
- `R`: Rename sensor (opens interactive text entry prompt)
- `Backspace`: Revert sensor name back to default hardware name
- `A`: Toggle threshold alarm on/off
- `+` / `-` (`Right` / `Left`): Adjust alarm threshold temperature (±1°C)
- `C`: Cycle line color through the 16-color palette
- `Enter` / `Esc` / `M` / `Q`: Close manager and return to graph

---

## Configuration File (`~/.config/temptop/config.py`)

Temp Top automatically creates and updates its configuration file:

```toml
# ==============================================================================
#                           TEMP TOP CONFIGURATION FILE
#                  
# ==============================================================================

[general]
# Sensor sampling update frequency in milliseconds (default: 2000 ms, min: 100 ms)
update_frequency_ms = 2000

# Total graphed plot time in seconds (e.g. 300 for 5m, 1200 for 20m)
plot_time_seconds = 300

# Terminal sound / bell alarm enabled
sound_alarm_enabled = true

# Beep cooldown interval in seconds (default: 10 seconds between alarm beeps)
alarm_beep_interval_seconds = 10

# ==============================================================================
# HARDWARE TEMPERATURE DEVICES
# ==============================================================================

[devices."k10temp-pci-00c3.Tctl"]
default_name = "k10temp-pci-00c3 Tctl (PCI adapter)"
display_name = "CPU"
enabled = true
color = "cyan"
alarm_enabled = false
alarm_threshold = 85.0

[devices."nvidia.0"]
default_name = "NVIDIA GeForce RTX 3060 Laptop GPU"
display_name = "GPU (RTX 3060)"
enabled = true
color = "green"
alarm_enabled = false
alarm_threshold = 80.0
```
