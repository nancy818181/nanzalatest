"""3D bar charts without extra libraries (2.9.50).

A chart is computed once as plain geometry (polygons and texts, y going down like a screen) and then drawn on a
Tkinter canvas or as a ReportLab drawing for the PDF. Series are placed one behind the other (depth), categories
along the floor, so a projection by year / scenario / month reads as a real 3D chart.
"""
from __future__ import annotations

import math

PALETTE = ["#1f5f99", "#d39b1f", "#2e8b57", "#b23a48", "#6a4c93", "#11847f", "#c46210", "#4d5d6c"]
INK = "#071B2E"; GRID = "#c9d3dd"; WALL = "#f4f7fa"; FLOOR = "#e6ecf2"


def shade(color, factor):
    color = color.lstrip("#"); r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    if factor >= 1: r, g, b = (int(c + (255 - c) * (factor - 1)) for c in (r, g, b))
    else: r, g, b = (int(c * factor) for c in (r, g, b))
    return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in (r, g, b))


def compact(value):
    value = float(value or 0); sign = "-" if value < 0 else ""; value = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= limit:
            text = f"{value / limit:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return f"{sign}{value:,.0f}"


def nice_ticks(low, high, count=5):
    if high <= low: high = low + 1
    raw = (high - low) / count; power = 10 ** math.floor(math.log10(raw)); step = power
    for multiple in (1, 2, 2.5, 5, 10):
        if multiple * power >= raw: step = multiple * power; break
    start = math.floor(low / step) * step; ticks = []; value = start
    while value <= high + step * 0.001:
        ticks.append(round(value, 10)); value += step
    if ticks[-1] < high: ticks.append(ticks[-1] + step)
    return ticks


def bar3d(series, categories, values, title="", width=900, height=430, angle=35, depth=0.55):
    """series: names placed in depth (front first); categories: along the floor; values[s][c] numbers.
    Returns {"width","height","polygons":[(points, fill, outline)],"texts":[(x, y, text, anchor, size, color, bold)]}."""
    series = list(series); categories = list(categories)
    matrix = [[float(v or 0) for v in (list(row) + [0] * len(categories))[:len(categories)]] for row in values][:len(series)]
    while len(matrix) < len(series): matrix.append([0.0] * len(categories))
    polygons = []; texts = []
    if not series or not categories:
        texts.append((width / 2, height / 2, "No data", "center", 11, INK, True))
        return {"width": width, "height": height, "polygons": polygons, "texts": texts}
    flat = [v for row in matrix for v in row]
    ticks = nice_ticks(min(0.0, min(flat)), max(0.0, max(flat)))
    vmin, vmax = ticks[0], ticks[-1]
    left, right, top, bottom = 78, 30, 46 + 16 * ((len(series) + 3) // 4), 56
    rad = math.radians(angle)
    columns = len(categories); rows = len(series)
    plot_w = width - left - right
    slot = plot_w / (columns + rows * depth * math.cos(rad) * 0.8 + 0.2)
    row_step = slot * depth * 0.8                     # depth taken by one series
    dx_row, dy_row = row_step * math.cos(rad), row_step * math.sin(rad)
    total_dx, total_dy = dx_row * rows, dy_row * rows
    plot_h = height - top - bottom - total_dy
    scale = plot_h / (vmax - vmin)
    base_y = height - bottom                          # front edge of the floor at vmin
    y_of = lambda v: base_y - (v - vmin) * scale
    front_w = slot * columns
    # back wall and floor with grid lines
    back = lambda x, y: (x + total_dx, y - total_dy)
    wall = [back(left, y_of(vmin)), back(left + front_w, y_of(vmin)), back(left + front_w, y_of(vmax)), back(left, y_of(vmax))]
    polygons.append((wall, WALL, GRID))
    side = [(left, y_of(vmin)), back(left, y_of(vmin)), back(left, y_of(vmax)), (left, y_of(vmax))]
    polygons.append((side, WALL, GRID))
    zero = y_of(0.0)
    floor = [(left, zero), (left + front_w, zero), back(left + front_w, zero), back(left, zero)]
    polygons.append((floor, FLOOR, GRID))
    for tick in ticks:
        y = y_of(tick)
        polygons.append(([(left, y), back(left, y), back(left + front_w, y)], None, GRID))
        texts.append((left - 6, y, compact(tick), "e", 8, INK, False))
    # bars: back series first, and left to right, so nearer bars cover farther ones
    bar_w = slot * 0.4; bar_d = row_step * 0.7
    bdx, bdy = bar_d * math.cos(rad), bar_d * math.sin(rad)
    # smaller series in front so the taller ones behind stay visible; each series keeps its own colour
    order = sorted(range(rows), key=lambda index: (sum(abs(v) for v in matrix[index]), index))
    for position in reversed(range(rows)):
        r = order[position]
        color = PALETTE[r % len(PALETTE)]
        ox = dx_row * position + (dx_row - bdx) / 2; oy = dy_row * position + (dy_row - bdy) / 2
        for c in range(columns):
            value = matrix[r][c]
            x0 = left + slot * c + slot * 0.08 + ox; x1 = x0 + bar_w
            y_top = y_of(max(value, 0.0)) - oy; y_bottom = y_of(min(value, 0.0)) - oy
            if abs(y_bottom - y_top) < 0.6: y_top = y_bottom - 0.6
            front = [(x0, y_bottom), (x1, y_bottom), (x1, y_top), (x0, y_top)]
            side_face = [(x1, y_bottom), (x1 + bdx, y_bottom - bdy), (x1 + bdx, y_top - bdy), (x1, y_top)]
            top_face = [(x0, y_top), (x1, y_top), (x1 + bdx, y_top - bdy), (x0 + bdx, y_top - bdy)]
            fill = color if value >= 0 else shade(color, 1.35)
            polygons += [(side_face, shade(fill, 0.68), shade(fill, 0.5)), (front, fill, shade(fill, 0.55)), (top_face, shade(fill, 1.25), shade(fill, 0.55))]
            if value and (position == 0 or rows <= 4):
                texts.append(((x0 + x1) / 2 + bdx / 2, (y_top - bdy - 8) if value >= 0 else (y_bottom + 8), compact(value), "center", 7, INK, False))
    for c, name in enumerate(categories):
        texts.append((left + slot * c + slot / 2, base_y + 14, str(name), "center", 8, INK, True))
    if title: texts.append((width / 2, 16, title, "center", 12, INK, True))
    x = left; y = 36
    for r, name in enumerate(series):
        color = PALETTE[r % len(PALETTE)]
        polygons.append(([(x, y - 5), (x + 12, y - 5), (x + 12, y + 5), (x, y + 5)], color, shade(color, 0.6)))
        texts.append((x + 17, y, str(name), "w", 8, INK, False))
        x += max(110, 9 * len(str(name)) + 40)
        if x > width - 150: x = left; y += 16
    return {"width": width, "height": height, "polygons": polygons, "texts": texts}


# ---------------------------------------------------------------- drawing
def draw_on_canvas(canvas, chart, offset_x=0, offset_y=0):
    canvas.delete("all")
    for points, fill, outline in chart["polygons"]:
        flat = [coordinate for x, y in points for coordinate in (x + offset_x, y + offset_y)]
        if fill is None: canvas.create_line(*flat, fill=outline)
        else: canvas.create_polygon(*flat, fill=fill, outline=outline or "")
    anchors = {"center": "center", "e": "e", "w": "w"}
    for x, y, text, anchor, size, color, bold in chart["texts"]:
        canvas.create_text(x + offset_x, y + offset_y, text=text, anchor=anchors.get(anchor, "center"), fill=color,
                           font=("Segoe UI", size, "bold" if bold else "normal"))


def reportlab_drawing(chart, max_width=None):
    """A ReportLab Drawing of the chart, scaled down to max_width points when needed."""
    from reportlab.graphics.shapes import Drawing, Group, PolyLine, Polygon, String
    from reportlab.lib import colors
    width, height = chart["width"], chart["height"]
    factor = min(1.0, (max_width or width) / width)
    drawing = Drawing(width * factor, height * factor); group = Group()
    flip = lambda points: [value for x, y in points for value in (x, height - y)]
    for points, fill, outline in chart["polygons"]:
        if fill is None:
            group.add(PolyLine(flip(points), strokeColor=colors.HexColor(outline), strokeWidth=0.4))
        else:
            group.add(Polygon(flip(points), fillColor=colors.HexColor(fill), strokeColor=colors.HexColor(outline) if outline else None, strokeWidth=0.4))
    for x, y, text, anchor, size, color, bold in chart["texts"]:
        mode = {"center": "middle", "e": "end", "w": "start"}.get(anchor, "middle")
        group.add(String(x, height - y - size * 0.35, str(text), fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size,
                         fillColor=colors.HexColor(color), textAnchor=mode))
    group.transform = (factor, 0, 0, factor, 0, 0); drawing.add(group)
    return drawing


def chart_from_spec(spec, width=900, height=430):
    return bar3d(spec.get("series") or [], spec.get("categories") or [], spec.get("values") or [], spec.get("title", ""), width, height,
                 spec.get("angle", 35), spec.get("depth", 0.55))
