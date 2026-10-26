"""
Temp Top - Terminal User Interface & Application Controller
Implements btop-style Unicode borders, Braille graphs, real-time sensor toggling,
device management modal, interactive rename prompt, defaults reset, and alarm beeper.
"""

import os
import sys
import tty
import time
import signal
import termios
import select
import shutil
import re
import unicodedata
from typing import Optional, List, Dict, Tuple, Any

from config import Config, COLOR_NAMES, COLOR_PALETTE, resolve_color, RESET_COLOR
from sensors import SensorManager, SensorDevice
from plotter import BraillePlotter

# ANSI regex for visible width calculation
ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

def char_width(c: str) -> int:
    """Return the terminal cell column width of a single character."""
    if unicodedata.combining(c) or c == '\ufe0f':
        return 0
    if c == '\u26a0':  # Warning symbol ⚠️
        return 2
    if unicodedata.east_asian_width(c) in ('W', 'F'):
        return 2
    return 1

def visible_len(s: str) -> int:
    """Calculate the visible terminal column width of an ANSI-colored string."""
    plain = ANSI_REGEX.sub("", s)
    return sum(char_width(c) for c in plain)

def pad_visible(s: str, target_width: int, align: str = "left") -> str:
    """Pad string to exact visible width taking ANSI codes and wide characters into account."""
    vlen = visible_len(s)
    pad = max(0, target_width - vlen)
    if align == "right":
        return (" " * pad) + s
    elif align == "center":
        left_pad = pad // 2
        right_pad = pad - left_pad
        return (" " * left_pad) + s + (" " * right_pad)
    return s + (" " * pad)

def truncate_visible(s: str, max_width: int) -> str:
    """Truncate a plain or ANSI string to max_width visible terminal columns."""
    if visible_len(s) <= max_width:
        return s
    plain = ANSI_REGEX.sub("", s)
    cur_w = 0
    truncated = []
    ellipsis_w = char_width("…")
    limit = max(0, max_width - ellipsis_w)
    for c in plain:
        w = char_width(c)
        if cur_w + w > limit:
            break
        truncated.append(c)
        cur_w += w
    return "".join(truncated) + "…"


# UI Colors
C_BORDER = "\033[38;2;85;105;135m"      # Steel blue btop border
C_TITLE = "\033[1;38;2;0;229;255m"      # Bright cyan title
C_SECTION = "\033[1;38;2;170;190;220m"  # Section headers
C_TEXT = "\033[38;2;220;225;235m"       # Normal crisp text
C_DIM = "\033[38;2;120;130;145m"        # Dim grey
C_HIGHLIGHT = "\033[1;38;2;255;203;107m"# Amber highlight
C_KEY = "\033[1;38;2;130;170;255m"      # Key shortcut highlight
C_ALARM_WARN = "\033[1;38;2;255;83;112m"# Bright red/coral alarm
C_MODAL_BG = "\033[48;2;25;30;40m"      # Modal background
C_MODAL_SEL = "\033[48;2;50;65;90m"     # Modal selected row
C_MODAL_BORDER = "\033[38;2;130;170;255m"
C_CURR_TEMP = "\033[1;38;2;255;140;0m"   # Bright orange for current temperature
C_MAX_TEMP = "\033[38;2;205;40;40m"     # Red slightly darker than bright red for Max temp


class TerminalManager:
    """Handles raw terminal mode, cursor visibility, screen buffer, and input."""
    def __init__(self):
        self.old_settings = None
        self.is_raw = False

    def enter(self):
        if sys.stdin.isatty():
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
            self.is_raw = True
        # Alternate screen buffer, hide cursor, clear
        sys.stdout.write("\033[?1049h\033[?25l\033[2J")
        sys.stdout.flush()

    def exit(self):
        # Show cursor, restore main screen buffer
        sys.stdout.write("\033[?25h\033[?1049l\033[0m")
        sys.stdout.flush()
        if self.is_raw and self.old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass
            self.is_raw = False

    def get_key(self, timeout: float = 0.05) -> Optional[str]:
        """Read a single keypress or escape sequence non-blockingly.

        Uses os.read() on the raw file descriptor to avoid Python's internal
        stdio buffering, which can cause multi-byte escape sequences (e.g.
        arrow keys: \\x1b[A) to be split across reads when select() is used
        to check for remaining bytes.
        """
        if not sys.stdin.isatty():
            time.sleep(timeout)
            return None

        fd = sys.stdin.fileno()
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            return None

        try:
            # Read all available bytes at once (up to 32) to capture full
            # escape sequences in a single read, avoiding buffering splits.
            raw = os.read(fd, 32)
        except Exception:
            return None

        if not raw:
            return None

        # Parse the first key/sequence from the raw bytes
        return self._parse_raw_key(raw)

    def _parse_raw_key(self, raw: bytes) -> Optional[str]:
        """Parse raw bytes into a single key name string."""
        if not raw:
            return None

        if raw[0:1] != b'\x1b':
            # Not an escape sequence — return the character
            ch = raw[0:1]
            if ch == b'\r' or ch == b'\n':
                return "\n"
            try:
                return ch.decode('utf-8', errors='ignore') or None
            except Exception:
                return None

        # Escape byte — check what follows
        if len(raw) == 1:
            return "ESC"

        # CSI sequence: \x1b[ ...
        if raw[1:2] == b'[':
            if len(raw) < 3:
                return "ESC"

            # Handle Linux console format: \x1b[[A
            if raw[2:3] == b'[' and len(raw) >= 4:
                c = raw[3:4]
                if c == b'A': return "UP"
                if c == b'B': return "DOWN"
                if c == b'C': return "RIGHT"
                if c == b'D': return "LEFT"
                return "ESC"

            # Standard CSI: collect parameter bytes then final byte
            i = 2
            while i < len(raw) and (0x30 <= raw[i] <= 0x3F):  # digits, ;, etc.
                i += 1

            if i >= len(raw):
                return "ESC"

            final = raw[i:i+1]
            params = raw[2:i].decode('ascii', errors='ignore')

            if final == b'A': return "UP"
            if final == b'B': return "DOWN"
            if final == b'C': return "RIGHT"
            if final == b'D': return "LEFT"
            if final == b'H': return "HOME"
            if final == b'F': return "END"
            if final == b'~':
                if params.startswith('5'): return "PAGE_UP"
                if params.startswith('6'): return "PAGE_DOWN"
                if params in ('1', '7'):   return "HOME"
                if params in ('4', '8'):   return "END"
                if params == '3':          return "DELETE"
                if params == '2':          return "INSERT"
                return f"FN_{params}"
            return "ESC"

        # SS3 sequence: \x1bO ...
        if raw[1:2] == b'O':
            if len(raw) < 3:
                return "ESC"
            c = raw[2:3]
            if c == b'A': return "UP"
            if c == b'B': return "DOWN"
            if c == b'C': return "RIGHT"
            if c == b'D': return "LEFT"
            if c == b'H': return "HOME"
            if c == b'F': return "END"
            return "ESC"

        # VT52 cursor keys: \x1bA, \x1bB, etc.
        c = raw[1:2]
        if c == b'A': return "UP"
        if c == b'B': return "DOWN"
        if c == b'C': return "RIGHT"
        if c == b'D': return "LEFT"

        return "ESC"


class TempTopApp:
    def __init__(self, config_path: Optional[str] = None):
        self.config = Config(config_path)
        self.sensor_mgr = SensorManager(self.config)
        self.plotter = BraillePlotter()
        self.term = TerminalManager()

        # Window state
        self.cols, self.lines = shutil.get_terminal_size((80, 24))
        self.running = False
        self.needs_full_redraw = True

        # UI Modes: "NORMAL", "DEVICE_MANAGER", "RENAME_PROMPT", "CONFIRM_RESET", "HELP"
        self.ui_mode = "NORMAL"

        # Device manager state
        self.selected_dev_index = 0
        self.rename_buffer = ""

        # Available time durations for quick switching: [30s, 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m, 60m]
        self.plot_durations = [30, 60, 120, 180, 300, 600, 900, 1200, 1800, 3600]

        # Pause state: when paused, freeze the graph at this timestamp
        self.pause_time: Optional[float] = None

        # Setup SIGWINCH handler
        signal.signal(signal.SIGWINCH, self._handle_resize)

    def _handle_resize(self, signum=None, frame=None):
        """Handle terminal window resize."""
        self.cols, self.lines = shutil.get_terminal_size((80, 24))
        self.needs_full_redraw = True

    def run(self):
        """Main application lifecycle loop."""
        self.term.enter()
        self.running = True
        self.sensor_mgr.start_background_polling()

        last_render_time = 0.0

        try:
            while self.running:
                # 1. Process keyboard input non-blockingly
                user_interacted = self._process_input()

                # 2. Render frame: refresh rate is no higher than the set graph update rate
                now = time.time()
                update_interval_sec = self.config.get_update_frequency_ms() / 1000.0
                time_to_refresh = (now - last_render_time) >= update_interval_sec

                if self.ui_mode == "NORMAL":
                    if not self.sensor_mgr.paused:
                        if user_interacted or self.needs_full_redraw or time_to_refresh:
                            self._render()
                            self.needs_full_redraw = False
                            last_render_time = now
                    elif self.needs_full_redraw:
                        # When paused, only redraw if explicitly requested (e.g. just paused/unpaused)
                        self._render()
                        self.needs_full_redraw = False
                else:
                    # When in modal (e.g. Device Manager): graph MUST NOT update.
                    # Only redraw menu when user interacts or window resizes.
                    if user_interacted or self.needs_full_redraw:
                        self._render()
                        self.needs_full_redraw = False

                # Small sleep to prevent busy looping while polling keys
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            self.sensor_mgr.stop_background_polling()
            self.config.save()
            self.term.exit()

    def _process_input(self) -> bool:
        """Process non-blocking key presses. Returns True if a key was handled."""
        key = self.term.get_key(timeout=0.03)
        if not key:
            return False

        if self.ui_mode == "NORMAL":
            self._handle_normal_key(key)
        elif self.ui_mode == "DEVICE_MANAGER":
            self._handle_device_manager_key(key)
        elif self.ui_mode == "RENAME_PROMPT":
            self._handle_rename_key(key)
        elif self.ui_mode == "CONFIRM_RESET":
            self._handle_confirm_reset_key(key)
        elif self.ui_mode == "HELP":
            self._handle_help_key(key)
        return True

    def _handle_normal_key(self, key: str):
        key_devs = [d for d in self.sensor_mgr.devices.values() if d.enabled]

        if key in ("q", "Q"):
            self.running = False

        # Quick sensor toggles via keys 1-9 for visible sensors in key
        elif key in "123456789":
            idx = int(key) - 1
            if 0 <= idx < len(key_devs):
                dev = key_devs[idx]
                self.sensor_mgr.toggle_sensor(dev.device_id)
                self.needs_full_redraw = True

        # Sampling frequency adjustment: + / - or ] / [
        elif key in ("+", "="):
            # Increase interval by 250ms
            curr = self.config.get_update_frequency_ms()
            self.config.set_update_frequency_ms(curr + 250)
            self.config.save()
        elif key in ("-", "_"):
            # Decrease interval by 250ms down to 100ms
            curr = self.config.get_update_frequency_ms()
            new_val = max(100, curr - 250)
            self.config.set_update_frequency_ms(new_val)
            self.config.save()

        # Plot time adjustment: > / < or } / { or w / W
        elif key in (">", ".", "w"):
            # Increase window duration
            curr = self.config.get_plot_time_seconds()
            for d in self.plot_durations:
                if d > curr:
                    self.config.set_plot_time_seconds(d)
                    self.config.save()
                    break
        elif key in ("<", ",", "W"):
            # Decrease window duration
            curr = self.config.get_plot_time_seconds()
            for d in reversed(self.plot_durations):
                if d < curr:
                    self.config.set_plot_time_seconds(d)
                    self.config.save()
                    break

        # Pause / Resume
        elif key in ("p", "P"):
            self.sensor_mgr.paused = not self.sensor_mgr.paused
            if self.sensor_mgr.paused:
                # Record the moment of pausing to freeze graph display
                self.pause_time = time.time()
            else:
                # Unpausing: clear the frozen timestamp so graph resumes live
                self.pause_time = None
                self.needs_full_redraw = True

        # Open Device Manager modal
        elif key in ("m", "M", "\n", "\r"):
            self.ui_mode = "DEVICE_MANAGER"

        # Help modal
        elif key in ("h", "H", "?"):
            self.ui_mode = "HELP"

        # Save settings now
        elif key in ("s", "S"):
            self.config.save()

        # Reset defaults: Ctrl+R (\x12) or 'D' (Shift+d)
        elif key in ("\x12", "D"):
            self.ui_mode = "CONFIRM_RESET"

    def _handle_device_manager_key(self, key: str):
        seen_ids = set()
        dev_list = []
        for d in self.sensor_mgr.devices.values():
            if d.device_id not in seen_ids:
                seen_ids.add(d.device_id)
                dev_list.append(d)

        if not dev_list:
            if key in ("ESC", "q", "m", "\n", "\r"):
                self.ui_mode = "NORMAL"
                self.needs_full_redraw = True
            return

        self.selected_dev_index = max(0, min(len(dev_list) - 1, self.selected_dev_index))
        curr_dev = dev_list[self.selected_dev_index]

        if key in ("ESC", "q", "m", "\n", "\r"):
            self.ui_mode = "NORMAL"
            self.needs_full_redraw = True
        elif key in ("UP", "k", "K"):
            self.selected_dev_index = (self.selected_dev_index - 1) % len(dev_list)
        elif key in ("DOWN", "j", "J"):
            self.selected_dev_index = (self.selected_dev_index + 1) % len(dev_list)
        elif key == "PAGE_UP":
            self.selected_dev_index = max(0, self.selected_dev_index - 5)
        elif key == "PAGE_DOWN":
            self.selected_dev_index = min(len(dev_list) - 1, self.selected_dev_index + 5)
        elif key == "HOME":
            self.selected_dev_index = 0
        elif key == "END":
            self.selected_dev_index = len(dev_list) - 1
        elif key == " ":
            # Toggle visibility
            self.sensor_mgr.toggle_sensor(curr_dev.device_id)
        elif key in ("r", "e"):
            # Rename prompt
            self.rename_buffer = curr_dev.display_name
            self.ui_mode = "RENAME_PROMPT"
        elif key in ("R",):
            # Reset single device name to default (capital R only)
            self.sensor_mgr.reset_sensor_name(curr_dev.device_id)
        elif key in ("\x7f", "\x08"):
            # Backspace also resets single device name to default
            self.sensor_mgr.reset_sensor_name(curr_dev.device_id)
        elif key in ("a", "A"):
            # Toggle alarm on/off
            self.sensor_mgr.toggle_alarm(curr_dev.device_id)
        elif key in ("+", "=", "RIGHT", "]"):
            # Increase alarm threshold by 1°C
            self.sensor_mgr.set_alarm_threshold(curr_dev.device_id, curr_dev.alarm_threshold + 1.0)
        elif key in ("-", "_", "LEFT", "["):
            # Decrease alarm threshold by 1°C
            self.sensor_mgr.set_alarm_threshold(curr_dev.device_id, curr_dev.alarm_threshold - 1.0)
        elif key in ("c", "C"):
            # Cycle color
            try:
                curr_idx = COLOR_NAMES.index(curr_dev.color)
            except ValueError:
                curr_idx = 0
            new_color = COLOR_NAMES[(curr_idx + 1) % len(COLOR_NAMES)]
            self.sensor_mgr.set_sensor_color(curr_dev.device_id, new_color)
        elif key == "w":
            # Move sensor up in display order
            if self.sensor_mgr.move_sensor(curr_dev.device_id, -1):
                self.selected_dev_index = max(0, self.selected_dev_index - 1)
        elif key == "s":
            # Move sensor down in display order
            if self.sensor_mgr.move_sensor(curr_dev.device_id, +1):
                self.selected_dev_index = min(len(dev_list) - 1, self.selected_dev_index + 1)
        elif key in ("\x12", "D"):
            # Reset all defaults
            self.ui_mode = "CONFIRM_RESET"

    def _handle_rename_key(self, key: str):
        seen_ids = set()
        dev_list = []
        for d in self.sensor_mgr.devices.values():
            if d.device_id not in seen_ids:
                seen_ids.add(d.device_id)
                dev_list.append(d)

        if not dev_list:
            self.ui_mode = "NORMAL"
            self.needs_full_redraw = True
            return
        curr_dev = dev_list[self.selected_dev_index]

        if key in ("\n", "\r"):
            # Accept new name
            if self.rename_buffer.strip():
                self.sensor_mgr.rename_sensor(curr_dev.device_id, self.rename_buffer.strip())
            self.ui_mode = "DEVICE_MANAGER"
        elif key == "ESC":
            # Cancel
            self.ui_mode = "DEVICE_MANAGER"
        elif key in ("\x7f", "\x08"):
            # Backspace
            self.rename_buffer = self.rename_buffer[:-1]
        elif len(key) == 1 and 32 <= ord(key) <= 126:
            # Printable character
            if len(self.rename_buffer) < 40:
                self.rename_buffer += key

    def _handle_confirm_reset_key(self, key: str):
        if key in ("y", "Y"):
            self.sensor_mgr.reset_all_defaults()
            self.ui_mode = "NORMAL"
            self.needs_full_redraw = True
        elif key in ("n", "N", "ESC", "q"):
            self.ui_mode = "NORMAL"
            self.needs_full_redraw = True

    def _handle_help_key(self, key: str):
        if key in ("ESC", "q", "h", "?", "\n", "\r", " "):
            self.ui_mode = "NORMAL"
            self.needs_full_redraw = True
            self.ui_mode = "NORMAL"

    def _render(self):
        """Render the complete screen buffer and flush."""
        cols = self.cols
        lines = self.lines

        if cols < 40 or lines < 12:
            msg = "Terminal window too small! Please enlarge."
            sys.stdout.write(f"\033[H\033[2J{msg}")
            sys.stdout.flush()
            return

        frame: List[str] = []

        # 1. Header Line
        frame.append(self._render_header(cols))

        # Determine layout heights:
        # Title bar: 1 line
        # Sensor Key Guide at bottom: lines depending on sensor count and terminal height
        dev_list = list(self.sensor_mgr.devices.values())
        # Deduplicate sensors by device_id
        seen_ids = set()
        unique_devs: List[SensorDevice] = []
        for dev in dev_list:
            if dev.device_id not in seen_ids:
                seen_ids.add(dev.device_id)
                unique_devs.append(dev)

        # For the sensor key, only show enabled sensors (saves vertical space)
        key_devs = [dev for dev in unique_devs if dev.enabled]
        key_lines_needed = self._calculate_sensor_key_height(key_devs, cols)
        # Overhead: 1 header + 1 divider + key_lines_needed + 1 blank line + 1 footer
        overhead = 4 + key_lines_needed
        graph_box_height = max(4, lines - overhead)
        plot_height = graph_box_height
        # Subtract 2 for borders (│...│), 6 for left axis, 6 for right axis = 14
        plot_width = max(10, cols - 14)

        # 2. Render Graph Plot Rows
        duration = self.config.get_plot_time_seconds()
        # When paused, freeze the graph at the pause timestamp
        if self.sensor_mgr.paused and self.pause_time is not None:
            now = self.pause_time
        else:
            now = time.time()
        plot_rows, oldest_str, latest_str = self.plotter.render_graph(
            plot_width=plot_width,
            plot_height=plot_height,
            duration_seconds=duration,
            devices=unique_devs,
            current_time=now,
        )

        for row in plot_rows:
            frame.append(f"{C_BORDER}│{RESET_COLOR}{row}{C_BORDER}│{RESET_COLOR}")

        # 3. Divider Row with Bottom Time Labels
        frame.append(self._render_time_divider(cols, oldest_str, latest_str, duration))

        # 4. Sensor Key Guide Area (only displays enabled sensors)
        sensor_key_rows = self._render_sensor_key(cols, key_lines_needed, key_devs)
        for skr in sensor_key_rows:
            frame.append(f"{C_BORDER}│{RESET_COLOR}{skr}{C_BORDER}│{RESET_COLOR}")

        # Blank line between the sensor device list and the bottom line controls to declutter the UI
        frame.append(f"{C_BORDER}│{RESET_COLOR}{' ' * (cols - 2)}{C_BORDER}│{RESET_COLOR}")

        # 5. Footer Line
        frame.append(self._render_footer(cols))

        # Overlay Modals if active
        if self.ui_mode == "DEVICE_MANAGER":
            self._apply_modal(frame, self._create_device_manager_modal(cols, lines))
        elif self.ui_mode == "RENAME_PROMPT":
            self._apply_modal(frame, self._create_rename_modal(cols, lines))
        elif self.ui_mode == "CONFIRM_RESET":
            self._apply_modal(frame, self._create_confirm_reset_modal(cols, lines))
        elif self.ui_mode == "HELP":
            self._apply_modal(frame, self._create_help_modal(cols, lines))

        # Write whole screen buffer in one shot
        output = "\033[H" + "\n".join(frame[:lines])
        sys.stdout.write(output)
        sys.stdout.flush()

    def _render_header(self, cols: int) -> str:
        """Render top btop-style title bar with exact visible width == cols."""
        rate_ms = self.config.get_update_frequency_ms()
        window_sec = self.config.get_plot_time_seconds()
        window_fmt = self._format_duration(window_sec)

        # Check for alarm alert
        if self.sensor_mgr.is_alarm_active and self.sensor_mgr.alarming_devices:
            first_alarm = self.sensor_mgr.alarming_devices[0]
            alarm_str = f" ⚠️  ALARM: {first_alarm.display_name} @ {first_alarm.current_temp:.1f}°C (>{first_alarm.alarm_threshold:.1f}°C) "
            title_section = f"{C_ALARM_WARN}╭─ [TEMP TOP] ─{alarm_str}"
        elif self.sensor_mgr.paused:
            title_section = f"{C_BORDER}╭─ {C_TITLE}Temp Top{C_BORDER} ─┤ {C_HIGHLIGHT}PAUSED{C_BORDER} ├"
        else:
            title_section = f"{C_BORDER}╭─ {C_TITLE}Temp Top{C_BORDER} ─"

        if cols >= 80:
            ctrl_section = f"┤ Rate: {C_TEXT}{rate_ms}ms{C_DIM} [+/-]{C_BORDER} ├─┤ Time: {C_TEXT}{window_fmt}{C_DIM} [</>]{C_BORDER} ├─╮{RESET_COLOR}"
        else:
            ctrl_section = f"┤ {C_TEXT}{rate_ms}ms{C_BORDER} ├─┤ {C_TEXT}{window_fmt}{C_BORDER} ├─╮{RESET_COLOR}"
        
        vis_title = visible_len(title_section)
        vis_ctrl = visible_len(ctrl_section)

        if vis_title + vis_ctrl < cols:
            middle_dashes = "─" * (cols - vis_title - vis_ctrl)
            return f"{title_section}{middle_dashes}{ctrl_section}"
        else:
            # Fallback if narrow
            left_part = f"{title_section}"
            dashes = max(1, cols - visible_len(left_part) - 1)
            return f"{left_part}{'─' * dashes}╮{RESET_COLOR}"

    def _render_time_divider(self, cols: int, oldest_str: str, latest_str: str, duration_sec: int) -> str:
        """
        Render bottom divider row of the graph containing:
        - Bottom-left: time when oldest visible data was updated
        - Bottom-right: time of latest visible data (current time)
        - Far-right end: length of time currently being measured
        Exact visible width == cols.
        """
        dur_str = f"[{self._format_duration(duration_sec)}]"
        left_str = f" {oldest_str} "
        right_str = f" {latest_str} {dur_str} "

        inner_w = cols - 2
        dashes_needed = inner_w - (visible_len(left_str) + visible_len(right_str))
        if dashes_needed < 0:
            left_str = f" {oldest_str} "
            right_str = f" {latest_str} "
            dashes_needed = max(0, inner_w - (visible_len(left_str) + visible_len(right_str)))

        middle_dashes = "─" * dashes_needed
        return f"{C_BORDER}├{RESET_COLOR}{C_TEXT}{left_str}{C_BORDER}{middle_dashes}{C_TEXT}{right_str}{C_BORDER}┤{RESET_COLOR}"

    def _calculate_sensor_key_height(self, dev_list: List[SensorDevice], cols: int) -> int:
        """Calculate how many lines the sensor key table needs."""
        if not dev_list:
            return 1
        cols_per_row = self._get_key_columns_count(dev_list, cols)
        data_rows = (len(dev_list) + cols_per_row - 1) // cols_per_row
        return max(1, min(8, data_rows))

    def _get_key_columns_count(self, dev_list: List[SensorDevice], cols: int) -> int:
        """
        Determine number of sensor columns based on screen width and device name lengths.
        When names are shortened by the user, packs more devices per line if they fit.
        """
        if not dev_list:
            return 1
        inner_w = cols - 2

        # Try to fit the maximum number of columns (up to 8 or number of devices)
        max_k = min(len(dev_list), max(1, inner_w // 20), 8)
        for k in range(max_k, 1, -1):
            col_width = inner_w // k
            all_fit = True
            for dev in dev_list:
                # Fixed overhead: [N]=3 + spaces=3 + bullet=1 + alarm_icon=3 + temp=6 + max=5 + spacing=3 = 24
                fixed_w = 24
                needed = fixed_w + visible_len(dev.display_name)
                if needed > col_width:
                    all_fit = False
                    break
            if all_fit:
                return k

        # Fallback based on column width
        if cols >= 150:
            return min(len(dev_list), 4)
        elif cols >= 110:
            return min(len(dev_list), 3)
        elif cols >= 70:
            return min(len(dev_list), 2)
        return 1

    def _render_sensor_key(self, cols: int, max_rows: int, dev_list: List[SensorDevice]) -> List[str]:
        """Render multi-column sensor key with current and max temp, colors, and alarms."""
        inner_w = cols - 2
        num_columns = self._get_key_columns_count(dev_list, cols)
        col_width = inner_w // num_columns

        # Remove duplicates while preserving order
        seen_ids = set()
        unique_devs: List[SensorDevice] = []
        for dev in dev_list:
            if dev.device_id not in seen_ids:
                seen_ids.add(dev.device_id)
                unique_devs.append(dev)

        # Build badges for each sensor
        badges: List[str] = []
        for i, dev in enumerate(unique_devs):
            hotkey = f"{i+1}" if i < 9 else " "
            color_code = dev.get_color_code()

            # Status bullet (no checkbox — disabled sensors are already hidden)
            if dev.enabled:
                bullet = f"{color_code}●{RESET_COLOR}"
            else:
                bullet = f"{C_DIM}○{RESET_COLOR}"

            # Temperature values: current temp in bright orange, session max temp in dark red
            temp_str = f"{dev.current_temp:4.1f}°" if dev.current_temp is not None else " N/A "
            max_str = f"M:{dev.session_max_temp:2.0f}°" if dev.session_max_temp is not None else "M:--"

            # Alarm indicator: dark grey icon only (no temp number), between name and current temp
            C_ALARM_ICON = "\033[38;2;100;105;115m"  # Dark grey
            if dev.alarm_enabled:
                if dev.is_alarming():
                    alarm_icon = f" {C_ALARM_WARN}🔔{RESET_COLOR}"
                else:
                    alarm_icon = f" {C_ALARM_ICON}🔔{RESET_COLOR}"
            else:
                alarm_icon = "   "  # 3 chars to match the icon width (space + 2-wide emoji)

            hk_badge = f"{C_KEY}[{hotkey}]{RESET_COLOR}" if hotkey != " " else "   "

            # Fixed overhead: " [N] ● <name> <alarm_icon> <temp> <max>"
            # [N]=3 + spaces=3 + bullet=1 + alarm_icon=3 + temp=6 + max=5 + spacing=3 = 24
            fixed_overhead = 24
            name_budget = max(4, col_width - fixed_overhead)
            disp_name = truncate_visible(dev.display_name, name_budget)
            disp_padded = pad_visible(disp_name, name_budget)

            badge = f" {hk_badge} {bullet} {C_TEXT}{disp_padded}{RESET_COLOR}{alarm_icon} {C_CURR_TEMP}{temp_str:>6}{RESET_COLOR} {C_MAX_TEMP}{max_str:>5}{RESET_COLOR}"
            badge = pad_visible(truncate_visible(badge, col_width), col_width)
            badges.append(badge)

        # Distribute into rows in column-major order (down then across):
        rows: List[str] = []
        for r in range(max_rows):
            row_items: List[str] = []
            for c in range(num_columns):
                idx = c * max_rows + r
                if idx < len(badges):
                    row_items.append(badges[idx])
                else:
                    row_items.append(" " * col_width)
            row_str = "".join(row_items)
            rows.append(pad_visible(truncate_visible(row_str, inner_w), inner_w))

        return rows

    def _render_footer(self, cols: int) -> str:
        """Render bottom status line with keyboard shortcuts tailored to width. Exact visible width == cols."""
        if cols >= 115:
            shortcuts = (
                f" {C_KEY}[1-9]{C_TEXT} Toggle  "
                f"{C_KEY}[+/-]{C_TEXT} Rate  "
                f"{C_KEY}[</>]{C_TEXT} Time  "
                f"{C_KEY}[M/Enter]{C_TEXT} Sensors  "
                f"{C_KEY}[P]{C_TEXT} Pause  "
                f"{C_KEY}[D/Ctrl+R]{C_TEXT} Defaults  "
                f"{C_KEY}[H]{C_TEXT} Help  "
                f"{C_KEY}[Q]{C_TEXT} Quit {RESET_COLOR}"
            )
        elif cols >= 76:
            shortcuts = (
                f" {C_KEY}[1-9]{C_TEXT} Toggle  "
                f"{C_KEY}[+/-]{C_TEXT} Rate  "
                f"{C_KEY}[</>]{C_TEXT} Time  "
                f"{C_KEY}[M]{C_TEXT} Sensors  "
                f"{C_KEY}[D]{C_TEXT} Reset  "
                f"{C_KEY}[Q]{C_TEXT} Quit {RESET_COLOR}"
            )
        else:
            shortcuts = (
                f" {C_KEY}[1-9]{C_TEXT} Toggle  "
                f"{C_KEY}[M]{C_TEXT} Manage  "
                f"{C_KEY}[D]{C_TEXT} Reset  "
                f"{C_KEY}[Q]{C_TEXT} Quit {RESET_COLOR}"
            )

        vis_sc = visible_len(shortcuts)
        if vis_sc + 2 <= cols:
            left_dash = "─"
            right_dash = "─" * max(0, (cols - 2) - 1 - vis_sc)
            return f"{C_BORDER}╰{left_dash}{RESET_COLOR}{shortcuts}{C_BORDER}{right_dash}╯{RESET_COLOR}"
        else:
            truncated = truncate_visible(shortcuts, max(0, cols - 4))
            vis_tr = visible_len(truncated)
            right_dash = "─" * max(0, cols - 3 - vis_tr)
            return f"{C_BORDER}╰─{RESET_COLOR}{truncated}{C_BORDER}{right_dash}╯{RESET_COLOR}"

    def _format_duration(self, seconds: int) -> str:
        """Format duration cleanly (e.g. 5m 00s or 30s)."""
        if seconds < 60:
            return f"{seconds}s"
        m = seconds // 60
        s = seconds % 60
        if s == 0:
            return f"{m}m"
        return f"{m}m {s:02d}s"

    # =========================================================================
    # MODAL DIALOGS
    # =========================================================================
    def _modal_top_border(self, title: str, target_width: int, border_color: str, title_color: str) -> str:
        lead = f"╭─ {title} ─"
        dashes = max(0, target_width - visible_len(lead) - 1)
        return f"{border_color}╭─ {title_color}{title}{border_color} ─{'─' * dashes}╮{RESET_COLOR}"

    def _create_device_manager_modal(self, cols: int, lines: int) -> List[str]:
        """Create interactive Device Manager modal dialog."""
        seen_ids = set()
        dev_list = []
        for d in self.sensor_mgr.devices.values():
            if d.device_id not in seen_ids:
                seen_ids.add(d.device_id)
                dev_list.append(d)

        modal_w = min(74, cols - 4)
        inner_w = modal_w - 2
        modal_h = min(len(dev_list) + 9, lines - 4)

        modal_lines: List[str] = []
        # Header
        modal_lines.append(self._modal_top_border("Device Manager & Sensor Settings", modal_w, C_MODAL_BORDER, C_TITLE))
        modal_lines.append(f"{C_MODAL_BORDER}│{RESET_COLOR}{C_DIM}{pad_visible(truncate_visible('  Navigate: [↑/↓]  Toggle: [Space]  Rename: [E]  Alarm: [A]', inner_w), inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}")
        modal_lines.append(f"{C_MODAL_BORDER}│{RESET_COLOR}{C_DIM}{pad_visible(truncate_visible('  Threshold: [+/-]  Color: [C]  Order: [W/S]  Reset Name: [R/Bksp]', inner_w), inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}")
        modal_lines.append(f"{C_MODAL_BORDER}│{RESET_COLOR}{C_DIM}{pad_visible(truncate_visible('  Reset ALL: [D/Ctrl+R]  Exit: [Esc/M]', inner_w), inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}")
        modal_lines.append(f"{C_MODAL_BORDER}├{'─' * inner_w}┤{RESET_COLOR}")

        # List rows
        list_height = max(3, modal_h - 7)
        start_idx = max(0, min(self.selected_dev_index - list_height // 2, max(0, len(dev_list) - list_height)))
        visible_devs = dev_list[start_idx : start_idx + list_height]

        for i, dev in enumerate(visible_devs):
            real_idx = start_idx + i
            is_sel = (real_idx == self.selected_dev_index)
            prefix = f"{C_HIGHLIGHT}►{RESET_COLOR} " if is_sel else "  "

            chk = "[✓] " if dev.enabled else "[ ] "
            color_code = dev.get_color_code()
            bullet = f"{color_code}■{RESET_COLOR} "

            alarm_info = f"Alarm:{'ON' if dev.alarm_enabled else 'OFF'} ({dev.alarm_threshold:.0f}°C)"
            color_info = truncate_visible(dev.color, 8)
            color_padded = pad_visible(color_info, 8)

            fixed_overhead = 2 + 4 + 2 + 3 + 8 + 3 + len(alarm_info)
            name_budget = max(4, inner_w - fixed_overhead)
            disp_name = truncate_visible(dev.display_name, name_budget)
            disp_padded = pad_visible(disp_name, name_budget)

            row_content = f"{prefix}{chk}{bullet}{disp_padded} │ {color_padded} │ {alarm_info}"
            row_content = truncate_visible(row_content, inner_w)
            bg = C_MODAL_SEL if is_sel else ""
            line_str = f"{C_MODAL_BORDER}│{RESET_COLOR}{bg}{pad_visible(row_content, inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}"
            modal_lines.append(line_str)

        # Fill remaining rows if any
        while len(modal_lines) < modal_h - 1:
            modal_lines.append(f"{C_MODAL_BORDER}│{RESET_COLOR}{' ' * inner_w}{C_MODAL_BORDER}│{RESET_COLOR}")

        modal_lines.append(f"{C_MODAL_BORDER}╰{'─' * inner_w}╯{RESET_COLOR}")
        return modal_lines

    def _create_rename_modal(self, cols: int, lines: int) -> List[str]:
        """Create prompt modal to rename a sensor."""
        modal_w = min(62, cols - 4)
        inner_w = modal_w - 2
        modal_lines: List[str] = [
            self._modal_top_border("Rename Sensor", modal_w, C_MODAL_BORDER, C_TITLE),
            f"{C_MODAL_BORDER}│{RESET_COLOR}{' ' * inner_w}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible('  Enter custom display name for device:', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_HIGHLIGHT}> {self.rename_buffer}█{RESET_COLOR}', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{' ' * inner_w}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{C_DIM}{pad_visible(truncate_visible('  [Enter] Confirm   [Esc] Cancel', inner_w), inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}╰{'─' * inner_w}╯{RESET_COLOR}",
        ]
        return modal_lines

    def _create_confirm_reset_modal(self, cols: int, lines: int) -> List[str]:
        """Create confirmation modal to reset all settings to defaults."""
        modal_w = min(60, cols - 4)
        inner_w = modal_w - 2
        modal_lines: List[str] = [
            self._modal_top_border("Reset All Settings to Defaults", modal_w, C_ALARM_WARN, C_ALARM_WARN),
            f"{C_ALARM_WARN}│{RESET_COLOR}{' ' * inner_w}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}│{RESET_COLOR}{pad_visible(truncate_visible('  Are you sure you want to reset all settings?', inner_w), inner_w)}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}│{RESET_COLOR}{pad_visible(truncate_visible('  This restores default names, colors, alarms,', inner_w), inner_w)}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}│{RESET_COLOR}{pad_visible(truncate_visible('  and sampling rate (2000ms).', inner_w), inner_w)}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}│{RESET_COLOR}{' ' * inner_w}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}│{RESET_COLOR}{C_HIGHLIGHT}{pad_visible(truncate_visible('  Press [Y] to confirm  |  [N] to cancel', inner_w), inner_w)}{RESET_COLOR}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}│{RESET_COLOR}{' ' * inner_w}{C_ALARM_WARN}│{RESET_COLOR}",
            f"{C_ALARM_WARN}╰{'─' * inner_w}╯{RESET_COLOR}",
        ]
        return modal_lines

    def _create_help_modal(self, cols: int, lines: int) -> List[str]:
        """Create Help modal displaying keys and features."""
        modal_w = min(72, cols - 4)
        inner_w = modal_w - 2
        cfg_msg = f"Config file: {self.config.config_path}"
        modal_lines: List[str] = [
            self._modal_top_border("Temp Top Help & Keyboard Shortcuts", modal_w, C_MODAL_BORDER, C_TITLE),
            f"{C_MODAL_BORDER}│{RESET_COLOR}{' ' * inner_w}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}1 - 9{RESET_COLOR}       : Toggle sensor visibility on graph in real time', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}+ / -{RESET_COLOR}       : Increase/decrease sample rate by 250ms (down to 100ms)', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}> / <{RESET_COLOR}       : Increase/decrease plot time window (30s..60m)', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}M / Enter{RESET_COLOR}   : Open Device Manager (rename, alarms, colors)', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}P{RESET_COLOR}           : Pause or resume live graph updates', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}S{RESET_COLOR}           : Save configuration file immediately', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}D / Ctrl+R{RESET_COLOR}  : Reset ALL settings and names to factory defaults', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{pad_visible(truncate_visible(f'  {C_KEY}Q / Esc{RESET_COLOR}     : Quit application', inner_w), inner_w)}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{' ' * inner_w}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{C_DIM}{pad_visible(truncate_visible('  ' + cfg_msg, inner_w), inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}│{RESET_COLOR}{C_DIM}{pad_visible(truncate_visible('  Press any key to close this help window', inner_w), inner_w)}{RESET_COLOR}{C_MODAL_BORDER}│{RESET_COLOR}",
            f"{C_MODAL_BORDER}╰{'─' * inner_w}╯{RESET_COLOR}",
        ]
        return modal_lines

    def _apply_modal(self, frame: List[str], modal_lines: List[str]):
        """Superimpose modal dialog centered on top of the frame."""
        modal_h = len(modal_lines)
        if not modal_h:
            return

        modal_w = visible_len(modal_lines[0])
        start_y = max(1, (len(frame) - modal_h) // 2)
        start_x = max(1, (self.cols - modal_w) // 2)

        for i, m_line in enumerate(modal_lines):
            target_y = start_y + i
            if target_y >= len(frame):
                break
            left_len = max(0, start_x - 1)
            right_len = max(0, self.cols - (start_x + modal_w) - 1)
            left_spaces = " " * left_len
            right_spaces = " " * right_len
            frame[target_y] = f"{C_BORDER}│{RESET_COLOR}{left_spaces}{m_line}{right_spaces}{C_BORDER}│{RESET_COLOR}"
