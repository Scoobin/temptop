"""
Temp Top - Braille Graph Engine
Renders multi-channel temperature curves using Unicode Braille characters (U+2800..U+28FF)
with 10°C guide lines, temperature axis, and btop-styled box frames.
"""

import time
import math
from typing import List, Dict, Tuple, Optional
from config import resolve_color, RESET_COLOR

# Unicode Braille bitmask mappings:
# A Braille character cell is 2 columns (x in 0..1) by 4 rows (y in 0..3)
BRAILLE_DOT_MAP: Dict[Tuple[int, int], int] = {
    (0, 0): 0x01,  # Dot 1
    (0, 1): 0x02,  # Dot 2
    (0, 2): 0x04,  # Dot 3
    (0, 3): 0x40,  # Dot 7
    (1, 0): 0x08,  # Dot 4
    (1, 1): 0x10,  # Dot 5
    (1, 2): 0x20,  # Dot 6
    (1, 3): 0x80,  # Dot 8
}

BRAILLE_BASE = 0x2800

# Guide line color: sleek dark grey
GUIDE_COLOR = "\033[38;2;75;80;92m"       # Subtle slate grey for 10°C guide lines
GUIDE_CHAR = "┄"                          # Clean dotted dashed horizontal guide
AXIS_COLOR = "\033[38;2;140;145;160m"     # Dim silver for axis text
LABEL_COLOR = "\033[38;2;180;190;210m"    # Crisp light blue-grey for numbers
BORDER_COLOR = "\033[38;2;90;105;130m"    # btop steel blue border
TIME_COLOR = "\033[38;2;160;175;195m"


class BraillePlotter:
    def __init__(
        self,
        temp_min: float = 20.0,
        temp_max: float = 50.0,
    ):
        self.temp_min = temp_min
        self.temp_max = temp_max

    def render_graph(
        self,
        plot_width: int,
        plot_height: int,
        duration_seconds: float,
        devices: List[Any],  # List[SensorDevice]
        current_time: Optional[float] = None,
    ) -> Tuple[List[str], str, str]:
        """
        Render graph lines within (plot_width x plot_height) character cells.
        Returns:
            (rendered_rows, oldest_time_str, latest_time_str)
        """
        now = current_time or time.time()
        start_time = now - duration_seconds

        oldest_time_str = time.strftime("%H:%M:%S", time.localtime(start_time))
        latest_time_str = time.strftime("%H:%M:%S", time.localtime(now))

        if plot_width < 10 or plot_height < 4:
            return [" " * plot_width] * plot_height, oldest_time_str, latest_time_str

        # Dynamically adjust temperature range:
        # Only extend the graph range to 2 degrees above the highest currently
        # shown graph line and 2 degrees below the lowest currently shown graph line.
        displayed_temps: List[float] = []
        for dev in devices:
            if not dev.enabled:
                continue
            visible_readings = [temp for t, temp in dev.history if t >= start_time]
            if visible_readings:
                displayed_temps.extend(visible_readings)
            elif dev.current_temp is not None:
                displayed_temps.append(dev.current_temp)

        if displayed_temps:
            highest_displayed = max(displayed_temps)
            lowest_displayed = min(displayed_temps)
            self.temp_max = highest_displayed + 2.0
            self.temp_min = lowest_displayed - 2.0
        else:
            self.temp_min = 20.0
            self.temp_max = 50.0

        temp_span = self.temp_max - self.temp_min
        if temp_span <= 0.001:
            temp_span = 4.0
            self.temp_max = self.temp_min + 4.0

        # Sub-pixel dimensions (2 dots per col, 4 dots per row)
        sub_w = plot_width * 2
        sub_h = plot_height * 4

        # Cell grid buffers
        # cell_mask[r][c] = integer bitmask of dots
        cell_mask = [[0 for _ in range(plot_width)] for _ in range(plot_height)]
        # cell_color[r][c] = ANSI color sequence for the cell
        cell_color = [["" for _ in range(plot_width)] for _ in range(plot_height)]

        # Determine which character rows correspond to 10°C intervals
        # Markers (e.g. 40, 50, 60) within existing current graph line temperatures
        guide_rows: Dict[int, int] = {}  # char_row -> temperature
        start_deg = int(math.ceil(self.temp_min / 10.0)) * 10
        end_deg = int(math.floor(self.temp_max / 10.0)) * 10
        for temp_deg in range(start_deg, end_deg + 1, 10):
            norm = (temp_deg - self.temp_min) / temp_span
            r = round((1.0 - norm) * (plot_height - 1))
            if 0 <= r < plot_height and r not in guide_rows:
                guide_rows[r] = temp_deg

        # Helper to map temperature to sub-row y
        def temp_to_sub_y(temp: float) -> int:
            norm = (temp - self.temp_min) / temp_span
            norm = max(0.0, min(1.0, norm))
            return int((1.0 - norm) * (sub_h - 1))

        # Helper to set a sub-pixel dot
        def set_dot(x: int, y: int, color_code: str):
            if 0 <= x < sub_w and 0 <= y < sub_h:
                c = x // 2
                r = y // 4
                dx = x % 2
                dy = y % 4
                cell_mask[r][c] |= BRAILLE_DOT_MAP[(dx, dy)]
                cell_color[r][c] = color_code

        # Helper to draw a continuous line segment between two sub-pixels
        def draw_line(x0: int, y0: int, x1: int, y1: int, color_code: str):
            dx = abs(x1 - x0)
            dy = abs(y1 - y0)
            sx = 1 if x0 < x1 else -1
            sy = 1 if y0 < y1 else -1
            err = dx - dy
            curr_x, curr_y = x0, y0
            while True:
                set_dot(curr_x, curr_y, color_code)
                if curr_x == x1 and curr_y == y1:
                    break
                e2 = 2 * err
                if e2 > -dy:
                    err -= dy
                    curr_x += sx
                if e2 < dx:
                    err += dx
                    curr_y += sy

        # Plot curves for each enabled sensor
        for dev in devices:
            if not dev.enabled or not dev.history:
                continue

            color_code = dev.get_color_code()
            # Extract readings within [start_time, now]
            history_pts = list(dev.history)
            if not history_pts:
                continue

            # Compute sub-pixel positions for each historical sample
            pixel_pts: List[Tuple[int, int]] = []
            for t_val, temp_val in history_pts:
                if t_val < start_time:
                    continue
                # Map time to sub-x
                if duration_seconds > 0:
                    fraction = (t_val - start_time) / duration_seconds
                else:
                    fraction = 1.0
                x = int(fraction * (sub_w - 1))
                y = temp_to_sub_y(temp_val)
                pixel_pts.append((x, y))

            # If there is only one reading or history is recent, extend to current time
            if history_pts and history_pts[-1][0] < now:
                latest_x = sub_w - 1
                latest_y = temp_to_sub_y(history_pts[-1][1])
                pixel_pts.append((latest_x, latest_y))

            # Connect consecutive points with Bresenham lines
            for i in range(len(pixel_pts) - 1):
                x0, y0 = pixel_pts[i]
                x1, y1 = pixel_pts[i + 1]
                draw_line(x0, y0, x1, y1, color_code)

        # Assemble formatted rows with 10°C markers on both left and right sides
        rows: List[str] = []
        for r in range(plot_height):
            # Left and right axis labels
            if r in guide_rows:
                deg = guide_rows[r]
                axis_left = f"{LABEL_COLOR}{deg:3d}°C{AXIS_COLOR}┤{RESET_COLOR}"
                axis_right = f"{AXIS_COLOR}├{RESET_COLOR}{LABEL_COLOR}{deg:3d}°C{RESET_COLOR}"
            else:
                axis_left = f"     {AXIS_COLOR}│{RESET_COLOR}"
                axis_right = f"{AXIS_COLOR}│{RESET_COLOR}     "

            # Graph plot characters
            line_parts = [axis_left]
            current_active_color = ""

            for c in range(plot_width):
                mask = cell_mask[r][c]
                if mask != 0:
                    color = cell_color[r][c]
                    if color != current_active_color:
                        line_parts.append(color)
                        current_active_color = color
                    line_parts.append(chr(BRAILLE_BASE + mask))
                elif r in guide_rows:
                    if current_active_color != GUIDE_COLOR:
                        line_parts.append(GUIDE_COLOR)
                        current_active_color = GUIDE_COLOR
                    line_parts.append(GUIDE_CHAR)
                else:
                    if current_active_color != "":
                        line_parts.append(RESET_COLOR)
                        current_active_color = ""
                    line_parts.append(" ")

            if current_active_color != "":
                line_parts.append(RESET_COLOR)

            line_parts.append(axis_right)
            rows.append("".join(line_parts))

        return rows, oldest_time_str, latest_time_str
