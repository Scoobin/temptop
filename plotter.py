"""
Temp Top - Braille Graph Engine
Renders multi-channel temperature curves using Unicode Braille characters (U+2800..U+28FF)
with 10°C guide lines, temperature axis, and btop-styled box frames.
"""

import time
import math
from typing import List, Dict, Tuple, Optional, Any
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

        # 1. Determine raw min/max from displayed temperatures
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
            # Minimum and maximum graphed area strictly relate to currently displayed graph dots:
            # - If dots sit in 25-30, show 25 as lowest line (half height of 10° segment)
            # - Any unused 10° or 5° range where no dots sit is removed
            scale_min = math.floor(lowest_displayed / 5.0) * 5.0
            scale_max = math.ceil(highest_displayed / 5.0) * 5.0
        else:
            scale_min = 20.0
            scale_max = 50.0

        if scale_max <= scale_min:
            scale_max = scale_min + 5.0

        self.temp_min = float(scale_min)
        self.temp_max = float(scale_max)
        temp_span = self.temp_max - self.temp_min
        if temp_span <= 0.001:
            temp_span = 5.0
            self.temp_max = self.temp_min + 5.0

        # Guide lines:
        # 1. scale_min is always the bottom graph line
        # 2. Multiples of 10 strictly between scale_min and scale_max are 10° guide lines
        # 3. scale_max is always the top graph line
        guide_degs: List[int] = [int(self.temp_min)]
        d = int(math.floor(self.temp_min / 10.0) * 10) + 10
        while d < self.temp_max:
            if d > self.temp_min:
                guide_degs.append(d)
            d += 10
        if int(self.temp_max) > int(self.temp_min):
            guide_degs.append(int(self.temp_max))

        guide_rows: Dict[int, int] = {}
        for deg in guide_degs:
            if deg == int(self.temp_max):
                r = 0
            elif deg == int(self.temp_min):
                r = plot_height - 1
            else:
                norm = (deg - self.temp_min) / temp_span
                r = int(round((1.0 - norm) * (plot_height - 1)))
                r = max(1, min(plot_height - 2, r))

            if r not in guide_rows:
                guide_rows[r] = deg
            else:
                for offset in (1, -1, 2, -2):
                    cand = r + offset
                    if 0 <= cand < plot_height and cand not in guide_rows:
                        guide_rows[cand] = deg
                        break

        # Sub-pixel dimensions (2 dots per col, 4 dots per row)
        sub_w = plot_width * 2
        sub_h = plot_height * 4

        # Helper to map temperature to sub-row y
        def temp_to_sub_y(temp: float) -> int:
            norm = (temp - self.temp_min) / temp_span
            norm = max(0.0, min(1.0, norm))
            return int((1.0 - norm) * (sub_h - 1))

        # Collect Bresenham line points for each enabled sensor without vertical distortion
        cell_devs: Dict[Tuple[int, int], List[int]] = {}
        dev_cell_dots: Dict[Tuple[int, int, int], List[Tuple[int, int]]] = {}
        dev_colors: Dict[int, str] = {}

        for dev_idx, dev in enumerate(devices):
            if not dev.enabled or not dev.history:
                continue

            color_code = dev.get_color_code()
            dev_colors[dev_idx] = color_code
            history_pts = list(dev.history)
            if not history_pts:
                continue

            # Compute sub-pixel positions for each historical sample
            pixel_pts: List[Tuple[int, int]] = []
            for t_val, temp_val in history_pts:
                if t_val < start_time:
                    continue
                fraction = (t_val - start_time) / duration_seconds if duration_seconds > 0 else 1.0
                x = int(fraction * (sub_w - 1))
                y = temp_to_sub_y(temp_val)
                pixel_pts.append((x, y))

            # Extend to current time if needed
            if history_pts and history_pts[-1][0] < now:
                latest_x = sub_w - 1
                latest_y = temp_to_sub_y(history_pts[-1][1])
                pixel_pts.append((latest_x, latest_y))
            # If only 1 point is visible, render it as a single dot
            if len(pixel_pts) == 1:
                curr_x, curr_y = pixel_pts[0]
                if 0 <= curr_x < sub_w and 0 <= curr_y < sub_h:
                    r = curr_y // 4
                    c = curr_x // 2
                    cell = (r, c)
                    if cell not in cell_devs:
                        cell_devs[cell] = []
                    if dev_idx not in cell_devs[cell]:
                        cell_devs[cell].append(dev_idx)
                    key = (dev_idx, r, c)
                    if key not in dev_cell_dots:
                        dev_cell_dots[key] = []
                    dev_cell_dots[key].append((curr_x, curr_y))

            # Connect consecutive points with Bresenham lines
            for i in range(len(pixel_pts) - 1):
                x0, y0 = pixel_pts[i]
                x1, y1 = pixel_pts[i + 1]
                dx = abs(x1 - x0)
                dy = abs(y1 - y0)
                sx = 1 if x0 < x1 else -1
                sy = 1 if y0 < y1 else -1
                err = dx - dy
                curr_x, curr_y = x0, y0
                while True:
                    if 0 <= curr_x < sub_w and 0 <= curr_y < sub_h:
                        r = curr_y // 4
                        c = curr_x // 2
                        cell = (r, c)
                        if cell not in cell_devs:
                            cell_devs[cell] = []
                        if dev_idx not in cell_devs[cell]:
                            cell_devs[cell].append(dev_idx)
                        key = (dev_idx, r, c)
                        if key not in dev_cell_dots:
                            dev_cell_dots[key] = []
                        dev_cell_dots[key].append((curr_x, curr_y))

                    if curr_x == x1 and curr_y == y1:
                        break
                    e2 = 2 * err
                    if e2 > -dy:
                        err -= dy
                        curr_x += sx
                    if e2 < dx:
                        err += dx
                        curr_y += sy

        # Cell grid buffers
        cell_mask = [[0 for _ in range(plot_width)] for _ in range(plot_height)]
        cell_color = [["" for _ in range(plot_width)] for _ in range(plot_height)]

        # Render cells: when multiple devices track at the same temperature (occupy same cell),
        # alternate which device's color appears horizontally (2 dots per cell) with no vertical overlap.
        for (r, c), devs_in_cell in cell_devs.items():
            if len(devs_in_cell) == 1:
                active_dev = devs_in_cell[0]
            else:
                active_dev = devs_in_cell[c % len(devs_in_cell)]

            dots = dev_cell_dots.get((active_dev, r, c), [])
            col = dev_colors.get(active_dev, "")
            for (x, y) in dots:
                dx = x % 2
                dy = y % 4
                cell_mask[r][c] |= BRAILLE_DOT_MAP[(dx, dy)]
                cell_color[r][c] = col

        # Assemble formatted rows with guide markers on both left and right sides
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
