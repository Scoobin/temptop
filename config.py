"""
Temp Top - Configuration Manager
Handles loading, saving, resetting, and validating user settings in a plain-language TOML file.
"""

import os
import sys
from typing import Dict, Any, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # Fallback handled if needed


# Predefined harmonious color palette (Name -> (Hex, ANSI TrueColor escape))
COLOR_PALETTE: Dict[str, tuple[str, str]] = {
    "cyan": ("#00E5FF", "\033[38;2;0;229;255m"),
    "coral": ("#FF5370", "\033[38;2;255;83;112m"),
    "amber": ("#FFCB6B", "\033[38;2;255;203;107m"),
    "lime": ("#C3E88D", "\033[38;2;195;232;141m"),
    "purple": ("#C792EA", "\033[38;2;199;146;234m"),
    "orange": ("#F78C6C", "\033[38;2;247;140;108m"),
    "sky_blue": ("#82AAFF", "\033[38;2;130;170;255m"),
    "mint": ("#89DDFF", "\033[38;2;137;221;255m"),
    "pink": ("#F07178", "\033[38;2;240;113;120m"),
    "emerald": ("#4DD0E1", "\033[38;2;77;208;225m"),
    "yellow": ("#FFFF80", "\033[38;2;255;255;128m"),
    "magenta": ("#FF79C6", "\033[38;2;255;121;198m"),
    "green": ("#50FA7B", "\033[38;2;80;250;123m"),
    "blue": ("#61AFEF", "\033[38;2;97;175;239m"),
    "red": ("#E06C75", "\033[38;2;224;108;117m"),
    "white": ("#EEEEEE", "\033[38;2;238;238;238m"),
}

COLOR_NAMES = list(COLOR_PALETTE.keys())
RESET_COLOR = "\033[0m"


def resolve_color(color_spec: str) -> str:
    """
    Resolve color specification (palette name, hex #RRGGBB, or ANSI code)
    into an ANSI escape code.
    """
    if not color_spec:
        return COLOR_PALETTE["cyan"][1]

    cs = color_spec.strip().lower()
    if cs in COLOR_PALETTE:
        return COLOR_PALETTE[cs][1]

    # Hex color #RRGGBB
    if cs.startswith("#") and len(cs) == 7:
        try:
            r = int(cs[1:3], 16)
            g = int(cs[3:5], 16)
            b = int(cs[5:7], 16)
            return f"\033[38;2;{r};{g};{b}m"
        except ValueError:
            pass

    # 256-color numeric index
    if cs.isdigit():
        idx = int(cs)
        if 0 <= idx <= 255:
            return f"\033[38;5;{idx}m"

    return COLOR_PALETTE["cyan"][1]


DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/temptop")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.py")

DEFAULT_GENERAL_SETTINGS = {
    "update_frequency_ms": 2000,       # Sample rate (default: 2000ms, min: 100ms)
    "plot_time_seconds": 300,          # Graph window length (default: 300s = 5m)
    "sound_alarm_enabled": True,       # Audible beep when alarm triggers
    "alarm_beep_interval_seconds": 10, # Beep once per 10s while threshold is exceeded
}


class Config:
    def __init__(self, config_path: Optional[str] = None):
        if config_path:
            self.config_path = os.path.abspath(os.path.expanduser(config_path))
        else:
            # Check for current default or existing legacy configuration
            candidate_paths = [
                DEFAULT_CONFIG_PATH,
                os.path.join(DEFAULT_CONFIG_DIR, "config.toml"),
                os.path.expanduser("~/.config/temp-top/config.py"),
                os.path.expanduser("~/.config/temp-top/config.toml"),
            ]
            chosen = DEFAULT_CONFIG_PATH
            for p in candidate_paths:
                if os.path.isfile(p):
                    chosen = p
                    break
            self.config_path = os.path.abspath(chosen)
        self.general = dict(DEFAULT_GENERAL_SETTINGS)
        # devices dict: device_id -> dict of properties
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.load()

    def get_update_frequency_ms(self) -> int:
        return int(self.general.get("update_frequency_ms", 2000))

    def set_update_frequency_ms(self, val: int):
        self.general["update_frequency_ms"] = max(100, val)

    def get_plot_time_seconds(self) -> int:
        return int(self.general.get("plot_time_seconds", 300))

    def set_plot_time_seconds(self, val: int):
        self.general["plot_time_seconds"] = max(10, val)

    def load(self):
        """Load configuration from TOML file if it exists."""
        if not os.path.isfile(self.config_path):
            return

        try:
            with open(self.config_path, "rb") as f:
                data = tomllib.load(f)
            
            if "general" in data and isinstance(data["general"], dict):
                for k, v in data["general"].items():
                    if k in self.general:
                        self.general[k] = v

            if "devices" in data and isinstance(data["devices"], dict):
                for dev_id, dev_conf in data["devices"].items():
                    if isinstance(dev_conf, dict):
                        self.devices[dev_id] = {
                            "default_name": dev_conf.get("default_name", dev_id),
                            "display_name": dev_conf.get("display_name", dev_conf.get("default_name", dev_id)),
                            "enabled": bool(dev_conf.get("enabled", True)),
                            "color": str(dev_conf.get("color", "cyan")),
                            "alarm_enabled": bool(dev_conf.get("alarm_enabled", False)),
                            "alarm_threshold": float(dev_conf.get("alarm_threshold", 85.0)),
                        }
        except Exception as e:
            # If load fails, log warning and preserve defaults
            sys.stderr.write(f"Warning: Failed to load config from {self.config_path}: {e}\n")

    def save(self):
        """Save configuration to plain-language TOML with comments."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            content = self.generate_toml_content()
            # Write atomically using a temporary file
            tmp_path = self.config_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, self.config_path)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to save config to {self.config_path}: {e}\n")

    def reset_to_defaults(self):
        """Reset all general settings and device options back to defaults."""
        self.general = dict(DEFAULT_GENERAL_SETTINGS)
        # Reset device overrides: restore default names, enable all, disable alarms
        for dev_id, dev_conf in self.devices.items():
            dev_conf["display_name"] = dev_conf.get("default_name", dev_id)
            dev_conf["enabled"] = True
            dev_conf["alarm_enabled"] = False
            dev_conf["alarm_threshold"] = 85.0
        self.save()

    def generate_toml_content(self) -> str:
        """Generate human-readable, annotated TOML config string."""
        lines = [
            "# ==============================================================================",
            "#                           TEMP TOP CONFIGURATION FILE",
            "#                   Inspired by Psensor & btop hardware monitors",
            "# ==============================================================================",
            "# You can edit this file manually with any text editor or configure settings",
            "# in real-time within the Temp Top terminal application.",
            "#",
            "# Available color names:",
            f"#   {', '.join(COLOR_NAMES)}",
            "# (You may also use hex format like \"#00E5FF\" or 0-255 ANSI numbers)",
            "# ==============================================================================",
            "",
            "[general]",
            "# Sensor sampling update frequency in milliseconds (default: 2000 ms, min: 100 ms)",
            f"update_frequency_ms = {self.general.get('update_frequency_ms', 2000)}",
            "",
            "# Total graphed plot time in seconds (default: 300 seconds = 5 minutes)",
            f"plot_time_seconds = {self.general.get('plot_time_seconds', 300)}",
            "",
            "# Terminal sound / bell alarm enabled",
            f"sound_alarm_enabled = {'true' if self.general.get('sound_alarm_enabled', True) else 'false'}",
            "",
            "# Beep cooldown interval in seconds (default: 10 seconds between alarm beeps)",
            f"alarm_beep_interval_seconds = {self.general.get('alarm_beep_interval_seconds', 10)}",
            "",
            "# ==============================================================================",
            "# HARDWARE TEMPERATURE DEVICES",
            "# ------------------------------------------------------------------------------",
            "# All devices containing temperature sensors are listed below.",
            "#",
            "# Fields for each device:",
            "#   default_name    : Original hardware name detected by lm-sensors (reference)",
            "#   display_name    : Custom user-chosen name (editable; return to default anytime)",
            "#   enabled         : true to plot on graph, false to hide",
            "#   color           : Color of the graph curve and sensor key badge",
            "#   alarm_enabled   : true to sound alarm when threshold is reached (default: false)",
            "#   alarm_threshold : Threshold temperature in °C for alarm (default: 85.0)",
            "# ==============================================================================",
            "",
        ]

        for dev_id, dev_conf in sorted(self.devices.items()):
            lines.append(f'[devices."{dev_id}"]')
            default_name = dev_conf.get("default_name", dev_id)
            display_name = dev_conf.get("display_name", default_name)
            enabled = bool(dev_conf.get("enabled", True))
            color = str(dev_conf.get("color", "cyan"))
            alarm_enabled = bool(dev_conf.get("alarm_enabled", False))
            alarm_threshold = float(dev_conf.get("alarm_threshold", 85.0))

            lines.append(f'default_name = "{default_name}"')
            lines.append(f'display_name = "{display_name}"')
            lines.append(f'enabled = {"true" if enabled else "false"}')
            lines.append(f'color = "{color}"')
            lines.append(f'alarm_enabled = {"true" if alarm_enabled else "false"}')
            lines.append(f"alarm_threshold = {alarm_threshold:.1f}")
            lines.append("")

        return "\n".join(lines)
