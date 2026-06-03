from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
CHART_DIR = BACKEND_DIR / "generated" / "report_charts"
CHART_URL_PREFIX = "http://127.0.0.1:8000/report-assets/report_charts"

COLORS = {
    "X": "#2563eb",
    "Y": "#dc2626",
    "H": "#16a34a",
}


def extract_displacement_values(text_value: str) -> list[dict[str, Any]]:
    """Extract displacement rows from report page text.

    Typical OCR/text extraction fragments look like:
    X -43.1～244.1 244.1 JC17 白沙河高切坡（XS0044）
    Y -166.5～61.1 -166.5 JC15 白沙河高切坡（XS0044）
    H -10.0～8.8 -10.0 JC19 白沙河高切坡（XS0044）
    """
    text_value = " ".join(str(text_value or "").replace("\r", "\n").split())
    pattern = re.compile(
        r"\b([XYH])\s+"
        r"[-+]?\d+(?:\.\d+)?\s*[～~-]\s*[-+]?\d+(?:\.\d+)?\s+"
        r"([-+]?\d+(?:\.\d+)?)\s+"
        r"((?:JC|KZ)\d+(?:-\d+)?)\s+"
        r"(.{2,60}?)(?:（([A-Z]{1,5}\d{3,6}|420\d{10,})[*]?）|$)",
        re.IGNORECASE,
    )
    values: list[dict[str, Any]] = []
    for match in pattern.finditer(text_value):
        direction = match.group(1).upper()
        point = match.group(3).upper()
        slope_name = re.sub(r"\s+", "", match.group(4)).strip("，,;；。 ")
        values.append({
            "direction": direction,
            "value": float(match.group(2)),
            "point": point,
            "slope_name": slope_name[:40],
            "slope_code": match.group(5) or "",
        })
    return values[:18]


def generate_displacement_chart(row: dict[str, Any]) -> str:
    values = extract_displacement_values(str(row.get("text_excerpt") or ""))
    if not values:
        return ""

    source = "|".join(
        str(row.get(key, ""))
        for key in ("file_name", "page_no", "county", "report_year", "report_month")
    )
    chart_id = hashlib.sha1((source + repr(values)).encode("utf-8")).hexdigest()[:20]
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    chart_path = CHART_DIR / f"{chart_id}.svg"
    if not chart_path.exists():
        chart_path.write_text(_build_svg(row, values), encoding="utf-8")
    return f"{CHART_URL_PREFIX}/{chart_path.name}"


def _build_svg(row: dict[str, Any], values: list[dict[str, Any]]) -> str:
    width = 980
    height = 520
    left = 78
    right = 36
    top = 74
    bottom = 112
    plot_w = width - left - right
    plot_h = height - top - bottom

    max_abs = max(abs(item["value"]) for item in values) or 1
    axis_max = max(10, round(max_abs * 1.25 + 0.5))
    labels = [f"{item['point']}\\n{item['direction']}" for item in values]

    def x_at(index: int) -> float:
        if len(values) == 1:
            return left + plot_w / 2
        return left + plot_w * index / (len(values) - 1)

    def y_at(value: float) -> float:
        return top + (axis_max - value) / (axis_max * 2) * plot_h

    zero_y = y_at(0)
    grid = []
    for tick in (-axis_max, -axis_max / 2, 0, axis_max / 2, axis_max):
        y = y_at(tick)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5e7eb" stroke-width="1"/>'
            f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" font-size="12" fill="#64748b">{tick:.0f}</text>'
        )

    polylines = []
    points_svg = []
    for direction, color in COLORS.items():
        indexed = [(index, item) for index, item in enumerate(values) if item["direction"] == direction]
        if not indexed:
            continue
        coords = " ".join(f"{x_at(index):.1f},{y_at(item['value']):.1f}" for index, item in indexed)
        polylines.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for index, item in indexed:
            x = x_at(index)
            y = y_at(item["value"])
            label = html.escape(f"{item['point']} {item['value']:.1f}mm")
            points_svg.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}" stroke="#fff" stroke-width="2"/>'
                f'<text x="{x:.1f}" y="{y-10:.1f}" text-anchor="middle" font-size="12" fill="#0f172a">{label}</text>'
            )

    x_labels = []
    for index, label in enumerate(labels):
        x = x_at(index)
        line1, line2 = label.split("\\n")
        x_labels.append(
            f'<text x="{x:.1f}" y="{height-bottom+34}" text-anchor="middle" font-size="11" fill="#475569">'
            f'<tspan x="{x:.1f}" dy="0">{html.escape(line1)}</tspan>'
            f'<tspan x="{x:.1f}" dy="14">{html.escape(line2)}</tspan>'
            "</text>"
        )

    legend_x = width - right - 230
    legend = []
    for offset, (direction, color) in enumerate(COLORS.items()):
        x = legend_x + offset * 76
        legend.append(
            f'<circle cx="{x}" cy="36" r="5" fill="{color}"/>'
            f'<text x="{x+10}" y="40" font-size="13" fill="#334155">{direction}方向</text>'
        )

    title = html.escape(
        f"{row.get('county', '')}{row.get('report_year', '')}年{row.get('report_month', '')}月 位移变化高清重绘"
    )
    subtitle = html.escape(f"{row.get('file_name', '')} 第{row.get('page_no', '')}页")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{left}" y="34" font-size="22" font-weight="700" fill="#0f172a">{title}</text>
  <text x="{left}" y="58" font-size="13" fill="#64748b">{subtitle}</text>
  {''.join(legend)}
  <rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>
  {''.join(grid)}
  <line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="#334155" stroke-width="1.5"/>
  {''.join(polylines)}
  {''.join(points_svg)}
  {''.join(x_labels)}
  <text x="26" y="{top + plot_h/2}" transform="rotate(-90 26 {top + plot_h/2})" text-anchor="middle" font-size="13" fill="#475569">位移值 mm</text>
  <text x="{left}" y="{height-28}" font-size="12" fill="#64748b">说明：本图由报告页文字识别的位移特征表重绘，颜色用于区分 X/Y/H 方向。</text>
</svg>
"""
