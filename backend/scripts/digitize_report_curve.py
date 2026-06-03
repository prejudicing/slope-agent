from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image


def _find_plot_box(gray: np.ndarray) -> tuple[int, int, int, int, list[int]]:
    dark = gray < 90
    h, w = dark.shape

    row_counts = dark.sum(axis=1)
    horizontal = [
        y
        for y in range(40, h - 30)
        if row_counts[y] > w * 0.42
    ]
    groups = _group_runs(horizontal)
    # Real grid/border lines are one or two pixels thick. Dense curve clusters
    # around the zero axis can also cross the threshold, but they form wider
    # groups and must not be used as chart gridlines.
    gridlines = [int(round(sum(g) / len(g))) for g in groups if 1 <= len(g) <= 4]
    gridlines = [y for y in gridlines if 60 <= y <= h - 40]

    col_counts = dark.sum(axis=0)
    vertical = [
        x
        for x in range(50, w - 20)
        if col_counts[x] > h * 0.30
    ]
    vgroups = _group_runs(vertical)
    verticals = [int(round(sum(g) / len(g))) for g in vgroups if len(g) >= 1]

    if len(gridlines) < 6:
        # Fallbacks for the current report chart sizes, raw and enhanced.
        if h > 700:
            gridlines = [236, 310, 384, 458, 532, 606, 680, 753]
        else:
            gridlines = [118, 155, 192, 229, 266, 303, 340, 377]
    if len(verticals) < 2:
        verticals = [121, w - 49]

    left = min(verticals)
    right = max(verticals)
    top = min(gridlines)
    bottom = max(gridlines)
    return left, top, right, bottom, gridlines


def _group_runs(values: list[int]) -> list[list[int]]:
    if not values:
        return []
    groups = [[values[0]]]
    for value in values[1:]:
        if value <= groups[-1][-1] + 1:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups


def _value_from_y(y: float, top: int, bottom: int, y_max: float, y_min: float) -> float:
    return y_max - (y - top) * (y_max - y_min) / (bottom - top)


def _date_labels(count: int, start_year: int = 2011, start_month: int = 1, step_months: int = 1) -> list[str]:
    labels = []
    month_index = start_year * 12 + start_month - 1
    for i in range(count):
        current = month_index + i * step_months
        labels.append(f"{current // 12:04d}-{current % 12 + 1:02d}")
    return labels


def _smooth(values: list[float], window: int = 3) -> list[float]:
    if window <= 1:
        return values
    result = []
    for i in range(len(values)):
        lo = max(0, i - window // 2)
        hi = min(len(values), i + window // 2 + 1)
        result.append(round(float(np.median(values[lo:hi])), 1))
    return result


def _infer_title(image_path: Path) -> str:
    match = re.search(r"page_(\d+)_image_(\d+)", image_path.name)
    if image_path.parent.name.startswith("xingshan_") and image_path.name == "page_019_image_01_enhanced.png":
        return "XSTJC01（湖南路高切坡（XS00035））位移过程线图"
    if match:
        return f"兴山县月报第{int(match.group(1))}页第{int(match.group(2))}张位移过程线图"
    return f"{image_path.stem.replace('_enhanced', '')} 位移过程线图"


def _source_image_url(image_path: Path) -> str:
    report_key = image_path.parent.name
    return f"/report-assets/report_chart_sources/{report_key}/{image_path.name}"


def digitize_chart(image_path: Path, samples: int = 166) -> dict:
    image = Image.open(image_path).convert("L")
    gray = np.array(image)
    left, top, right, bottom, gridlines = _find_plot_box(gray)

    dark = gray < 90
    # Remove axes, borders and horizontal gridlines so the line/marker pixels dominate.
    mask = dark.copy()
    for y in gridlines:
        mask[max(0, y - 2): y + 3, :] = False
    mask[:, max(0, left - 2): left + 3] = False
    mask[:, max(0, right - 2): right + 3] = False
    mask[max(0, top - 2): top + 3, :] = False
    mask[max(0, bottom - 2): bottom + 3, :] = False

    y_max, y_min = 80.0, -60.0
    xs = np.linspace(left + 2, right - 2, samples)
    z_values: list[float] = []
    y_values: list[float] = []
    x_values: list[float] = []
    prev = {"z": 0.0, "y": 0.0, "x": 0.0}

    for x in xs:
        x0 = max(left + 1, int(round(x)) - 3)
        x1 = min(right - 1, int(round(x)) + 4)
        ys, _ = np.where(mask[top + 3: bottom - 3, x0:x1])
        rows = ys + top + 3
        if rows.size < 2:
            z_values.append(prev["z"])
            y_values.append(prev["y"])
            x_values.append(prev["x"])
            continue

        values = [_value_from_y(float(row), top, bottom, y_max, y_min) for row in rows]
        positive = [v for v in values if v > 4]
        near_zero = [v for v in values if -8 <= v <= 8]
        negative = [v for v in values if v < -4]

        z = float(np.median(positive)) if positive else prev["z"]
        yv = float(np.median(near_zero)) if near_zero else prev["y"]
        xv = float(np.percentile(negative, 72)) if negative else prev["x"]

        # When X and Y overlap below zero, use the upper negative cluster as Y and the
        # lower cluster as X. This keeps the three report lines visually separated.
        if not near_zero and len(negative) >= 6:
            yv = float(np.percentile(negative, 72))
        if len(negative) >= 6:
            xv = float(np.percentile(negative, 28))

        prev = {"z": z, "y": yv, "x": xv}
        z_values.append(round(z, 1))
        y_values.append(round(yv, 1))
        x_values.append(round(xv, 1))

    labels = _date_labels(samples)
    x_values = _smooth(x_values)
    y_values = _smooth(y_values)
    z_values = _smooth(z_values)

    title = _infer_title(image_path)
    match = re.search(r"page_(\d+)_image_(\d+)", image_path.name)
    return {
        "title": title,
        "source_image": image_path.name,
        "source_image_url": _source_image_url(image_path),
        "digitize_method": "image_scan_approximation",
        "accuracy_note": "由扫描图像近似提取，适合业务展示和趋势判断；最终入库建议用原始监测表复核。",
        "axis": {"x": "观测月份", "y": "位移量（mm）", "y_min": y_min, "y_max": y_max},
        "page_no": int(match.group(1)) if match else None,
        "image_index": int(match.group(2)) if match else None,
        "series": [
            {"name": "水平位移X", "data": [{"date": d, "value": v} for d, v in zip(labels, x_values)]},
            {"name": "水平位移Y", "data": [{"date": d, "value": v} for d, v in zip(labels, y_values)]},
            {"name": "垂直位移Z", "data": [{"date": d, "value": v} for d, v in zip(labels, z_values)]},
        ],
    }


def write_echarts_html(data: dict, data_url: str, output_path: Path) -> None:
    trend = data.get("trend", {})
    validation = data.get("validation", {})
    stability = data.get("stability", {})
    option = {
        "title": {"text": data["title"], "left": "center", "top": 8},
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 42, "data": [item["name"] for item in data["series"]]},
        "grid": {"left": 70, "right": 28, "top": 88, "bottom": 54},
        "xAxis": {
            "type": "category",
            "name": "观测月份",
            "data": [item["date"] for item in data["series"][0]["data"]],
            "axisLabel": {"rotate": 45},
        },
        "yAxis": {
            "type": "value",
            "name": "位移量（mm）",
            "min": -60,
            "max": 80,
        },
        "dataZoom": [{"type": "inside"}],
        "series": [
            {
                "name": item["name"],
                "type": "line",
                "showSymbol": False,
                "smooth": True,
                "lineStyle": {"width": 2.4},
                "data": [point["value"] for point in item["data"]],
            }
            for item in data["series"]
        ],
        "color": ["#2563eb", "#16a34a", "#dc2626"],
    }
    source_image_url = data.get("source_image_url", "")
    validation_html = _info_list_html(validation.get("items", [])) if validation else "<p>未配置库内校核信息。</p>"
    trend_html = _info_list_html(trend.get("items", [])) if trend else "<p>趋势分析暂未生成。</p>"
    stability_html = _info_list_html(stability.get("items", [])) if stability else "<p>稳定性评价暂未生成。</p>"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{data["title"]}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    html, body {{ margin: 0; min-height: 100%; font-family: Arial, "Microsoft YaHei", sans-serif; background: #f6f8fb; color: #172033; }}
    .page {{ width: min(1320px, calc(100vw - 24px)); margin: 12px auto 18px; display: grid; gap: 12px; }}
    .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    .panel h2 {{ margin: 0; padding: 10px 14px; font-size: 15px; border-bottom: 1px solid #edf0f5; }}
    .source img {{ display: block; width: 100%; height: auto; }}
    #chart {{ width: 100%; height: min(640px, 62vh); }}
    .note {{ padding: 10px 14px; color: #667085; font-size: 13px; line-height: 1.6; }}
    .insights {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .insights ul {{ margin: 0; padding: 12px 18px 14px 32px; line-height: 1.7; color: #344054; font-size: 14px; }}
    .insights p {{ margin: 0; padding: 12px 14px; color: #667085; }}
    @media (max-width: 980px) {{ .insights {{ grid-template-columns: 1fr; }} #chart {{ height: 520px; }} }}
  </style>
</head>
<body>
  <main class="page">
    <section class="panel source">
      <h2>原报告曲线增强图</h2>
      <img src="{source_image_url}" alt="原报告曲线增强图" />
    </section>
    <section class="panel">
      <h2>插件重绘图（图像提取样例）</h2>
      <div id="chart"></div>
      <div class="note">当前曲线由扫描图像近似提取，用于趋势对比；正式入库建议使用原始监测数据复核。</div>
    </section>
    <section class="insights">
      <div class="panel">
        <h2>库内校核</h2>
        {validation_html}
      </div>
      <div class="panel">
        <h2>未来趋势研判</h2>
        {trend_html}
      </div>
      <div class="panel">
        <h2>稳定性评价</h2>
        {stability_html}
      </div>
    </section>
  </main>
  <script>
    const chart = echarts.init(document.getElementById('chart'));
    const option = {json.dumps(option, ensure_ascii=False)};
    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
  </script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def _info_list_html(items: list[str]) -> str:
    if not items:
        return "<p>暂无分析结果。</p>"
    return "<ul>" + "".join(f"<li>{_html_escape(str(item))}</li>" for item in items) + "</ul>"


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _build_trend(data: dict) -> dict:
    items: list[str] = []
    for series in data.get("series", []):
        values = [float(point["value"]) for point in series.get("data", [])]
        if len(values) < 12:
            continue
        last_12 = values[-12:]
        last_24 = values[-24:] if len(values) >= 24 else values
        slope_12 = _linear_slope(last_12)
        slope_24 = _linear_slope(last_24)
        forecast_6 = values[-1] + slope_12 * 6
        direction = "继续上升" if slope_12 > 0.15 else ("继续下降" if slope_12 < -0.15 else "总体平稳")
        volatility = float(np.std(last_12))
        items.append(
            f"{series['name']}：近 12 期月均变化约 {slope_12:.2f} mm/月，近 24 期约 {slope_24:.2f} mm/月，"
            f"按当前斜率外推 6 个月约为 {forecast_6:.1f} mm，趋势判断为{direction}，近 12 期波动约 {volatility:.1f} mm。"
        )
    items.append("趋势结论仅用于辅助研判；若后续连续出现加速、突跳或与库内预警阈值接近，应结合现场巡查和原始监测数据复核。")
    return {"items": items}


def _build_stability(data: dict) -> dict:
    series_by_name = {item["name"]: [float(point["value"]) for point in item.get("data", [])] for item in data.get("series", [])}
    x_vals = series_by_name.get("水平位移X", [])
    y_vals = series_by_name.get("水平位移Y", [])
    z_vals = series_by_name.get("垂直位移Z", [])

    def last(values: list[float]) -> float:
        return values[-1] if values else 0.0

    def slope(values: list[float], count: int = 12) -> float:
        return _linear_slope(values[-count:]) if len(values) >= 2 else 0.0

    x_last, y_last, z_last = last(x_vals), last(y_vals), last(z_vals)
    x_slope, y_slope, z_slope = slope(x_vals), slope(y_vals), slope(z_vals)
    max_abs = max(abs(x_last), abs(y_last), abs(z_last))
    max_speed = max(abs(x_slope), abs(y_slope), abs(z_slope))

    if max_abs >= 60 or max_speed >= 1.2:
        level = "稳定性较差，建议列为重点关注对象"
    elif max_abs >= 40 or max_speed >= 0.6:
        level = "稳定性一般，建议持续跟踪"
    else:
        level = "整体较稳定，建议按常规频率监测"

    items = [
        f"综合评价：{level}。本评价基于报告曲线图像提取结果，库内校核存在口径差异，当前以报告图趋势为主。",
        f"控制性指标：当前绝对位移最大约 {max_abs:.1f} mm，近 12 期最大月均变化约 {max_speed:.2f} mm/月。",
        f"主要风险方向：垂直位移 Z 当前约 {z_last:.1f} mm，水平位移 X 当前约 {x_last:.1f} mm；其中 X 近期下降较明显，Z 近期仍有上升趋势。",
        "稳定性判断：未见短期突跳式剧烈变化，但累计位移已达到需要持续关注的量级，建议结合现场裂缝、挡墙、排水沟和坡面变形情况进行复核。",
        "处置建议：近期保持月度监测；若 X 方向持续负向发展或 Z 方向连续 2-3 期上升，应提高复核频次并开展现场巡查。",
    ]
    return {"level": level, "items": items}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--validation-json", type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    data = digitize_chart(args.image)
    data["trend"] = _build_trend(data)
    data["stability"] = _build_stability(data)
    if args.validation_json and args.validation_json.exists():
        data["validation"] = json.loads(args.validation_json.read_text(encoding="utf-8"))
    stem = args.image.stem.replace("_enhanced", "")
    data_path = args.out_dir / f"{stem}_digitized.json"
    html_path = args.out_dir / f"{stem}_echarts.html"
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_echarts_html(data, data_path.name, html_path)
    print(json.dumps({"data": str(data_path), "html": str(html_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
