"""
Temp Top - Sensor Monitor Engine
Discovers and monitors hardware temperatures using lm-sensors and sysfs hwmon.
Maintains history, session statistics, thresholds, and alarm state.
"""

import os
import glob
import json
import time
import subprocess
import threading
import ctypes
from collections import deque
from typing import Dict, List, Optional, Tuple, Any

from config import Config, COLOR_NAMES, resolve_color


class SensorDevice:
    """Represents a single hardware temperature sensor channel."""
    def __init__(
        self,
        device_id: str,
        default_name: str,
        display_name: Optional[str] = None,
        color: str = "cyan",
        enabled: bool = True,
        alarm_enabled: bool = False,
        alarm_threshold: float = 85.0,
        sysfs_path: Optional[str] = None,
    ):
        self.device_id = device_id
        self.default_name = default_name
        self.display_name = display_name or default_name
        self.color = color
        self.enabled = enabled
        self.alarm_enabled = alarm_enabled
        self.alarm_threshold = alarm_threshold
        self.sysfs_path = sysfs_path

        self.current_temp: Optional[float] = None
        self.session_max_temp: Optional[float] = None
        self.session_min_temp: Optional[float] = None

        # Store up to 3600s (1 hr) of history at 100ms resolution -> max 36,000 pts
        # (deque with maxlen keeps memory strictly bounded)
        self.history: deque[Tuple[float, float]] = deque(maxlen=40000)

    def record_reading(self, temp: float, timestamp: float):
        """Record a new temperature reading."""
        self.current_temp = temp
        if self.session_max_temp is None or temp > self.session_max_temp:
            self.session_max_temp = temp
        if self.session_min_temp is None or temp < self.session_min_temp:
            self.session_min_temp = temp
        self.history.append((timestamp, temp))

    def reset_stats(self):
        """Reset session min/max statistics."""
        self.session_max_temp = self.current_temp
        self.session_min_temp = self.current_temp

    def is_alarming(self) -> bool:
        """Check if this sensor currently violates its alarm threshold."""
        return (
            self.enabled
            and self.alarm_enabled
            and self.current_temp is not None
            and self.current_temp >= self.alarm_threshold
        )

    def get_color_code(self) -> str:
        """Return the ANSI color escape sequence."""
        return resolve_color(self.color)


class NvidiaMonitor:
    """
    Monitors Nvidia GPU temperatures using NVML (via ctypes libnvidia-ml.so)
    with automatic fallback to nvidia-smi if NVML library is unavailable.
    """
    def __init__(self):
        self.nvml_loaded = False
        self.nvml_lib = None
        self.nvml_devices: List[Tuple[int, Any, str]] = []  # (index, handle, name)
        self.has_nvidia_smi = False
        self._init_nvml()
        if not self.nvml_loaded:
            self._check_nvidia_smi()

    def _init_nvml(self):
        try:
            self.nvml_lib = ctypes.CDLL("libnvidia-ml.so")
            if self.nvml_lib.nvmlInit_v2() == 0:
                count = ctypes.c_uint()
                if self.nvml_lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) == 0:
                    for i in range(count.value):
                        handle = ctypes.c_void_p()
                        if self.nvml_lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(handle)) == 0:
                            name_buf = ctypes.create_string_buffer(96)
                            self.nvml_lib.nvmlDeviceGetName(handle, name_buf, 96)
                            name = name_buf.value.decode("utf-8", errors="replace").strip()
                            self.nvml_devices.append((i, handle, name))
                    if self.nvml_devices:
                        self.nvml_loaded = True
        except Exception:
            self.nvml_loaded = False

    def _check_nvidia_smi(self):
        try:
            res = subprocess.run(["which", "nvidia-smi"], capture_output=True, text=True, timeout=1)
            self.has_nvidia_smi = (res.returncode == 0)
        except Exception:
            self.has_nvidia_smi = False

    def get_detected_devices(self) -> List[Tuple[str, str, Optional[float]]]:
        """Returns list of (device_id, device_name, initial_temp)."""
        results = []
        if self.nvml_loaded:
            for idx, handle, name in self.nvml_devices:
                temp = ctypes.c_uint()
                t_val = None
                if self.nvml_lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) == 0:
                    t_val = float(temp.value)
                results.append((f"nvidia.{idx}", name, t_val))
            return results

        if self.has_nvidia_smi:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,name,temperature.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0:
                    for line in res.stdout.strip().splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 3:
                            idx = parts[0]
                            name = parts[1]
                            temp_val = float(parts[2])
                            results.append((f"nvidia.{idx}", name, temp_val))
            except Exception:
                pass
        return results

    def read_temperatures(self) -> Dict[str, float]:
        """Read current temperature for all Nvidia devices."""
        readings = {}
        if self.nvml_loaded:
            for idx, handle, _ in self.nvml_devices:
                temp = ctypes.c_uint()
                if self.nvml_lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) == 0:
                    readings[f"nvidia.{idx}"] = float(temp.value)
            return readings

        if self.has_nvidia_smi:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,temperature.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=1.5
                )
                if res.returncode == 0:
                    for line in res.stdout.strip().splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 2:
                            idx = parts[0]
                            readings[f"nvidia.{idx}"] = float(parts[1])
            except Exception:
                pass
        return readings

    def close(self):
        if self.nvml_loaded and self.nvml_lib:
            try:
                self.nvml_lib.nvmlShutdown()
            except Exception:
                pass
            self.nvml_loaded = False


class SensorManager:
    """Discovers sensors via lm-sensors and manages real-time polling and alarms."""
    def __init__(self, config: Config):
        self.config = config
        self.devices: Dict[str, SensorDevice] = {}
        self.lock = threading.Lock()
        self.running = False
        self.paused = False
        self.worker_thread: Optional[threading.Thread] = None

        # Alarm state
        self.last_beep_time: float = 0.0
        self.is_alarm_active: bool = False
        self.alarming_devices: List[SensorDevice] = []

        # Nvidia GPU monitor (NVML with fallback to nvidia-smi)
        self.nvidia_monitor = NvidiaMonitor()

        # Discover sensors initially
        self.discover_sensors()

    def _friendly_display_name(self, chip: str, feat: str) -> str:
        """Generate a clean, friendly initial display name for common hardware sensors."""
        chip_lower = chip.lower()
        feat_clean = feat.replace("Composite", "Overall").replace("_", " ")

        if "k10temp" in chip_lower or "coretemp" in chip_lower or "zenpower" in chip_lower:
            return f"CPU ({feat})"
        elif "amdgpu" in chip_lower or "nouveau" in chip_lower or "nvidia" in chip_lower:
            return f"GPU ({feat})"
        elif "nvme" in chip_lower:
            # Extract PCI bus or index if present
            parts = chip.split("-")
            bus = parts[-1] if len(parts) > 1 else "1"
            return f"NVMe [{bus}] ({feat_clean})"
        elif "iwlwifi" in chip_lower or "wifi" in chip_lower or "wlan" in chip_lower:
            return f"WiFi ({feat})"
        elif "acpitz" in chip_lower or "thermal_zone" in chip_lower:
            return f"Motherboard ({feat})"
        elif "asus" in chip_lower or "thinkpad" in chip_lower or "dell" in chip_lower:
            return f"Laptop Sensor ({feat})"
        return f"{chip} {feat}"

    def discover_sensors(self):
        """Discover all hardware temperature sensors using lm-sensors (sensors -j) and sysfs."""
        discovered: Dict[str, Dict[str, Any]] = {}

        # 1. Try lm-sensors json output
        try:
            res = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                for chip_name, features in data.items():
                    adapter = features.get("Adapter", "")
                    for feat_name, subfeats in features.items():
                        if feat_name == "Adapter" or not isinstance(subfeats, dict):
                            continue
                        for sub_name, val in subfeats.items():
                            if "temp" in sub_name and sub_name.endswith("_input"):
                                dev_id = f"{chip_name}.{feat_name}"
                                def_name = f"{chip_name} {feat_name}"
                                if adapter and adapter != "Unknown":
                                    def_name += f" ({adapter})"
                                
                                friendly = self._friendly_display_name(chip_name, feat_name)
                                
                                # Check for device-reported crit/max threshold to use as good default
                                crit_val = subfeats.get(sub_name.replace("_input", "_crit"))
                                max_val = subfeats.get(sub_name.replace("_input", "_max"))
                                default_threshold = 85.0
                                if crit_val is not None and 30.0 < float(crit_val) < 130.0:
                                    default_threshold = float(crit_val)
                                elif max_val is not None and 30.0 < float(max_val) < 130.0:
                                    default_threshold = float(max_val)

                                discovered[dev_id] = {
                                    "default_name": def_name,
                                    "friendly_name": friendly,
                                    "initial_temp": float(val),
                                    "suggested_threshold": default_threshold,
                                    "chip": chip_name,
                                    "feature": feat_name,
                                    "subfeat": sub_name,
                                }
        except Exception:
            pass

        # 2. Map sysfs hwmon paths for sub-millisecond polling
        sysfs_mapping = self._map_sysfs_hwmon()

        # If lm-sensors returned nothing, fallback directly to sysfs hwmon
        if not discovered:
            for dev_id, info in sysfs_mapping.items():
                discovered[dev_id] = {
                    "default_name": info["label"],
                    "initial_temp": info["temp"],
                    "suggested_threshold": 85.0,
                    "sysfs_path": info["path"],
                }

        # 3. Add Nvidia GPU devices (NVML / nvidia-smi)
        nv_devices = self.nvidia_monitor.get_detected_devices()
        for dev_id, name, init_temp in nv_devices:
            short_name = name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "").strip()
            friendly = f"GPU ({short_name})" if short_name else "GPU (Nvidia)"
            discovered[dev_id] = {
                "default_name": f"Nvidia {name}",
                "friendly_name": friendly,
                "initial_temp": init_temp if init_temp is not None else 45.0,
                "suggested_threshold": 85.0,
            }

        # 4. Populate or update self.devices syncing with config
        with self.lock:
            color_idx = 0
            for dev_id, info in discovered.items():
                conf = self.config.devices.get(dev_id, {})
                default_name = conf.get("default_name", info["default_name"])
                friendly = info.get("friendly_name", default_name)
                display_name = conf.get("display_name", friendly)
                enabled = conf.get("enabled", True)
                
                # Pick next harmonious color if not in config
                if "color" in conf:
                    color = conf["color"]
                else:
                    color = COLOR_NAMES[color_idx % len(COLOR_NAMES)]
                    color_idx += 1

                alarm_enabled = conf.get("alarm_enabled", False)
                alarm_threshold = conf.get("alarm_threshold", info.get("suggested_threshold", 85.0))
                
                sysfs_path = info.get("sysfs_path")
                if not sysfs_path and dev_id in sysfs_mapping:
                    sysfs_path = sysfs_mapping[dev_id]["path"]

                device = SensorDevice(
                    device_id=dev_id,
                    default_name=default_name,
                    display_name=display_name,
                    color=color,
                    enabled=enabled,
                    alarm_enabled=alarm_enabled,
                    alarm_threshold=alarm_threshold,
                    sysfs_path=sysfs_path,
                )

                if "initial_temp" in info:
                    device.record_reading(info["initial_temp"], time.time())

                self.devices[dev_id] = device

                # Sync back into config to ensure persistence
                self.config.devices[dev_id] = {
                    "default_name": default_name,
                    "display_name": display_name,
                    "enabled": enabled,
                    "color": color,
                    "alarm_enabled": alarm_enabled,
                    "alarm_threshold": alarm_threshold,
                }

        # Save config if new devices were added
        self.config.save()

        # Apply saved display order from config if available
        self._apply_saved_order()

    def _map_sysfs_hwmon(self) -> Dict[str, Dict[str, Any]]:
        """Map sysfs /sys/class/hwmon files for fast polling."""
        mapping: Dict[str, Dict[str, Any]] = {}
        try:
            for hwmon_dir in glob.glob("/sys/class/hwmon/hwmon*"):
                name_file = os.path.join(hwmon_dir, "name")
                chip_name = "unknown"
                if os.path.exists(name_file):
                    try:
                        with open(name_file, "r") as f:
                            chip_name = f.read().strip()
                    except Exception:
                        pass

                for temp_file in glob.glob(os.path.join(hwmon_dir, "temp*_input")):
                    base = temp_file[:-6]
                    label_file = base + "_label"
                    label = ""
                    if os.path.exists(label_file):
                        try:
                            with open(label_file, "r") as f:
                                label = f.read().strip()
                        except Exception:
                            pass
                    if not label:
                        label = os.path.basename(base)

                    try:
                        with open(temp_file, "r") as f:
                            raw_val = float(f.read().strip())
                            temp_val = raw_val / 1000.0 if raw_val > 500 else raw_val
                    except Exception:
                        continue

                    # Construct matching keys
                    dev_id_candidate = f"{chip_name}.{label}"
                    mapping[dev_id_candidate] = {
                        "path": temp_file,
                        "label": f"{chip_name} {label}",
                        "temp": temp_val,
                    }
        except Exception:
            pass
        return mapping

    def read_temperatures(self) -> Dict[str, float]:
        """Read latest temperatures from sensors."""
        readings: Dict[str, float] = {}

        # 1. First try reading direct sysfs paths (ultra fast, < 1ms)
        all_sysfs_found = True
        for dev_id, dev in self.devices.items():
            if dev.sysfs_path and os.path.exists(dev.sysfs_path):
                try:
                    with open(dev.sysfs_path, "r") as f:
                        raw = float(f.read().strip())
                        val = raw / 1000.0 if raw > 500 else raw
                        readings[dev_id] = val
                except Exception:
                    all_sysfs_found = False
            else:
                all_sysfs_found = False

        if all_sysfs_found and len(readings) == len(self.devices):
            return readings

        # 2. Fallback to `sensors -j`
        try:
            res = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                for chip_name, features in data.items():
                    for feat_name, subfeats in features.items():
                        if feat_name == "Adapter" or not isinstance(subfeats, dict):
                            continue
                        for sub_name, val in subfeats.items():
                            if "temp" in sub_name and sub_name.endswith("_input"):
                                dev_id = f"{chip_name}.{feat_name}"
                                readings[dev_id] = float(val)
        except Exception:
            pass

        # 3. Read temperatures from Nvidia devices if present
        if self.nvidia_monitor.nvml_loaded or self.nvidia_monitor.has_nvidia_smi:
            try:
                nv_readings = self.nvidia_monitor.read_temperatures()
                readings.update(nv_readings)
            except Exception:
                pass

        return readings

    def poll_once(self):
        """Perform a single sample poll and update history and alarms.
        Always records data even when paused, so unpausing shows the latest readings."""
        now = time.time()
        readings = self.read_temperatures()

        with self.lock:
            for dev_id, temp in readings.items():
                if dev_id in self.devices:
                    self.devices[dev_id].record_reading(temp, now)

            # Check alarms (even when paused, alarms should still work)
            self._update_alarms(now)

    def _update_alarms(self, now: float):
        """Check all sensors for threshold exceedance and trigger alarm beeper if active."""
        alarming: List[SensorDevice] = []
        for dev in self.devices.values():
            if dev.is_alarming():
                alarming.append(dev)

        self.alarming_devices = alarming
        self.is_alarm_active = len(alarming) > 0

        # Beep once per 10 seconds if any device hits threshold
        if self.is_alarm_active:
            interval = self.config.general.get("alarm_beep_interval_seconds", 10)
            if now - self.last_beep_time >= interval:
                self.last_beep_time = now
                if self.config.general.get("sound_alarm_enabled", True):
                    self._sound_alarm_beep()
        else:
            # Alarm automatically ceases when temps drop below threshold
            pass

    def _sound_alarm_beep(self):
        """Emit terminal bell / audio beep."""
        try:
            # Universal ASCII bell
            import sys
            sys.stdout.write("\a")
            sys.stdout.flush()

            # Also attempt system beep/paplay if available non-blocking
            if os.path.exists("/usr/share/sounds/freedesktop/stereo/bell.oga"):
                subprocess.Popen(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    def start_background_polling(self):
        """Start background monitoring thread."""
        if self.running:
            return
        self.running = True

        def _worker():
            while self.running:
                interval_ms = self.config.get_update_frequency_ms()
                self.poll_once()
                # Sleep in small slices so frequency changes are immediately responsive
                sleep_target = interval_ms / 1000.0
                slice_time = 0.05
                slept = 0.0
                while self.running and slept < sleep_target:
                    time.sleep(min(slice_time, sleep_target - slept))
                    slept += slice_time

        self.worker_thread = threading.Thread(target=_worker, daemon=True)
        self.worker_thread.start()

    def stop_background_polling(self):
        """Stop background monitoring thread."""
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
        self.nvidia_monitor.close()

    def toggle_sensor(self, dev_id: str) -> bool:
        """Toggle sensor enabled state in real time."""
        with self.lock:
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                dev.enabled = not dev.enabled
                self.config.devices[dev_id]["enabled"] = dev.enabled
                self.config.save()
                return dev.enabled
        return False

    def rename_sensor(self, dev_id: str, new_name: str):
        """Rename sensor, preserving the original default name."""
        with self.lock:
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                dev.display_name = new_name.strip() if new_name.strip() else dev.default_name
                self.config.devices[dev_id]["display_name"] = dev.display_name
                self.config.save()

    def reset_sensor_name(self, dev_id: str):
        """Reset sensor name back to default hardware name."""
        with self.lock:
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                dev.display_name = dev.default_name
                self.config.devices[dev_id]["display_name"] = dev.default_name
                self.config.save()

    def set_sensor_color(self, dev_id: str, color: str):
        """Set sensor color."""
        with self.lock:
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                dev.color = color
                self.config.devices[dev_id]["color"] = color
                self.config.save()

    def toggle_alarm(self, dev_id: str) -> bool:
        """Toggle alarm on/off for a sensor."""
        with self.lock:
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                dev.alarm_enabled = not dev.alarm_enabled
                self.config.devices[dev_id]["alarm_enabled"] = dev.alarm_enabled
                self.config.save()
                return dev.alarm_enabled
        return False

    def set_alarm_threshold(self, dev_id: str, threshold: float):
        """Set alarm threshold temperature."""
        with self.lock:
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                dev.alarm_threshold = max(20.0, min(120.0, threshold))
                self.config.devices[dev_id]["alarm_threshold"] = dev.alarm_threshold
                self.config.save()

    def reset_all_defaults(self):
        """Reset all sensors to default names, enabled=True, alarms=False, and reset config."""
        with self.lock:
            color_idx = 0
            for dev_id, dev in self.devices.items():
                dev.display_name = dev.default_name
                dev.enabled = True
                dev.alarm_enabled = False
                dev.alarm_threshold = 85.0
                dev.color = COLOR_NAMES[color_idx % len(COLOR_NAMES)]
                color_idx += 1
            self.config.reset_to_defaults()
            # Re-discover to restore default order (config.device_order cleared by reset_to_defaults)
            self._reorder_by_discovery()

    def move_sensor(self, dev_id: str, direction: int) -> bool:
        """Move a sensor up (direction=-1) or down (direction=+1) in the display order.
        Returns True if the move was performed."""
        with self.lock:
            keys = list(self.devices.keys())
            if dev_id not in keys:
                return False
            idx = keys.index(dev_id)
            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(keys):
                return False
            # Swap in the ordered dict by rebuilding it
            keys[idx], keys[new_idx] = keys[new_idx], keys[idx]
            new_devices: Dict[str, SensorDevice] = {}
            for k in keys:
                new_devices[k] = self.devices[k]
            self.devices = new_devices
            # Also reorder config.devices to persist the order
            new_cfg_devices: Dict[str, Any] = {}
            for k in keys:
                if k in self.config.devices:
                    new_cfg_devices[k] = self.config.devices[k]
            self.config.devices = new_cfg_devices
            # Persist display order
            self.config.device_order = list(keys)
            self.config.save()
            return True

    def _apply_saved_order(self):
        """Reorder self.devices dict to match the saved device_order from config."""
        saved_order = self.config.device_order
        if not saved_order:
            return
        with self.lock:
            current_keys = set(self.devices.keys())
            # Build new order: saved order first (only keys that exist), then any new devices
            ordered_keys = [k for k in saved_order if k in current_keys]
            remaining = [k for k in self.devices.keys() if k not in set(ordered_keys)]
            ordered_keys.extend(remaining)
            new_devices: Dict[str, SensorDevice] = {}
            for k in ordered_keys:
                new_devices[k] = self.devices[k]
            self.devices = new_devices
            # Also reorder config.devices
            new_cfg_devices: Dict[str, Any] = {}
            for k in ordered_keys:
                if k in self.config.devices:
                    new_cfg_devices[k] = self.config.devices[k]
            self.config.devices = new_cfg_devices

    def _reorder_by_discovery(self):
        """Restore devices to sorted/discovery order (alphabetical by device_id)."""
        sorted_keys = sorted(self.devices.keys())
        new_devices: Dict[str, SensorDevice] = {}
        for k in sorted_keys:
            new_devices[k] = self.devices[k]
        self.devices = new_devices
        new_cfg_devices: Dict[str, Any] = {}
        for k in sorted_keys:
            if k in self.config.devices:
                new_cfg_devices[k] = self.config.devices[k]
        self.config.devices = new_cfg_devices
