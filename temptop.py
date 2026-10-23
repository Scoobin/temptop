#!/usr/bin/env python3
"""
Temp Top - Hardware Temperature Monitor and Braille Grapher
Inspired by Psensor and btop.

Usage:
  temptop [options]

Options:
  -c, --config PATH     Path to custom configuration file
  -r, --rate MS         Initial sensor sample frequency in ms (default: 2000)
  -t, --time SECONDS    Initial total graphed plot time in seconds (default: 300)
  -l, --list-sensors    List detected temperature sensors and exit
  -v, --version         Show application version
  -h, --help            Show this help message
"""

import sys
import os
import argparse

# Add current directory to sys.path so modules resolve cleanly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, DEFAULT_CONFIG_PATH
from sensors import SensorManager
from ui import TempTopApp

__version__ = "1.0.0"


def list_sensors(config_path: str = None):
    """Detect and print all temperature sensors detected via lm-sensors."""
    cfg = Config(config_path)
    mgr = SensorManager(cfg)
    print(f"\n=== Temp Top - Detected Hardware Temperature Sensors ({len(mgr.devices)}) ===")
    print("-" * 75)
    print(f"{'ID':<30} | {'Current':<8} | {'Display Name'}")
    print("-" * 75)
    for dev_id, dev in sorted(mgr.devices.items()):
        temp_str = f"{dev.current_temp:.1f}°C" if dev.current_temp is not None else "N/A"
        print(f"{dev_id:<30} | {temp_str:<8} | {dev.display_name}")
    print("-" * 75)
    print(f"Configuration file: {cfg.config_path}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Temp Top - Hardware Temperature Monitor and Braille Grapher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Keybindings inside Temp Top:
  1 - 9         Toggle individual sensors on/off the graph
  + / -         Increase / decrease sample frequency (250ms steps, down to 100ms)
  > / < (w/W)   Increase / decrease graphed plot time window (30s to 60m)
  M / Enter     Open Device Manager (rename sensors, toggle alarms, change colors)
  P             Pause / resume graph plotting
  S             Save configuration immediately
  D / Ctrl+R    Reset all settings, colors, and device names to factory defaults
  H / ?         Help screen
  Q / Esc       Quit
        """,
    )
    parser.add_argument("-c", "--config", help="Path to config file", default=None)
    parser.add_argument("-r", "--rate", type=int, help="Initial update rate in ms (min: 100)")
    parser.add_argument("-t", "--time", type=int, help="Initial plot window in seconds (e.g. 300 for 5m)")
    parser.add_argument("-l", "--list-sensors", action="store_true", help="List detected sensors and exit")
    parser.add_argument("-v", "--version", action="version", version=f"Temp Top v{__version__}")

    args = parser.parse_args()

    if args.list_sensors:
        list_sensors(args.config)
        return 0

    app = TempTopApp(args.config)

    if args.rate:
        app.config.set_update_frequency_ms(args.rate)
    if args.time:
        app.config.set_plot_time_seconds(args.time)

    try:
        app.run()
    except Exception as e:
        sys.stderr.write(f"\nError running Temp Top: {e}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
