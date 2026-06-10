from __future__ import annotations

import base64
import math
from html import escape
from typing import Any


PALETTE = ["#2f6fed", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b", "#22c55e", "#ef4444", "#0ea5e9"]
SUPPORTED_CHART_TYPES = {"kpi", "bar", "horizontal_bar", "line", "pie", "donut", "none", None}


def build_rendered_chart(chart_spec: Any, execution: dict[str, Any]) -> dict[str, Any]:
    """Use the LLM-selected chart spec and backend execution rows to render an SVG chart."""

    spec = chart_spec if isinstance(chart_spec, dict) else {}
    rows = [row for row in execution.get("rows", []) if isinstance(row, dict)]
    columns = [str(column) for column in (execution.get("columns") or _columns_from_rows(rows))]
    chart_type = _clean_chart_type(spec.get("chart_type"))
    if chart_type is None:
        chart_type = _infer_chart_type(rows, columns, spec)
    if chart_type in {None, "none"}:
        return {
            "chart_type": None,
            "title": str(spec.get("title") or "结果表"),
            "data": rows[:24],
            "reason": str(spec.get("reason") or "LLM decided this result is better shown as text/table."),
            "image_data_uri": "",
            "image_format": "",
            "render_engine": "",
        }

    x_column = _usable_column(spec.get("x"), columns)
    y_column = _usable_column(spec.get("y"), columns)
    if not x_column or not y_column:
        inferred_x, inferred_y = _infer_xy(rows, columns)
        x_column = x_column or inferred_x
        y_column = y_column or inferred_y
    if chart_type == "line" and (
        _looks_like_time_column(str(y_column or ""))
        or not _column_is_numeric(rows, y_column)
        or (not _looks_like_time_column(str(x_column or "")) and any(_looks_like_time_column(column) for column in columns))
    ):
        inferred_x, inferred_y = _infer_xy(rows, columns)
        x_column = inferred_x or x_column
        y_column = inferred_y or y_column
    preferred_y = _preferred_metric_column_from_text(spec, rows, columns)
    if preferred_y and _column_is_numeric(rows, preferred_y):
        y_column = preferred_y
    if chart_type in {"bar", "horizontal_bar", "pie", "donut"} and _column_is_numeric(rows, x_column) and _column_is_numeric(rows, y_column):
        x_column = next((column for column in columns if column != y_column and not _column_is_numeric(rows, column)), x_column)
    if chart_type in {"bar", "horizontal_bar", "line", "pie", "donut"} and _column_is_numeric(rows, x_column) and not _column_is_numeric(rows, y_column):
        x_column, y_column = y_column, x_column
    title = str(spec.get("title") or _default_title(chart_type, x_column, y_column))
    chart = {
        "chart_type": chart_type,
        "title": title,
        "x": x_column,
        "y": y_column,
        "data": rows[:24],
        "reason": str(spec.get("reason") or "LLM selected this chart type from the question and data context."),
        "encoding": {"x": x_column, "y": y_column},
        "series": spec.get("series") if isinstance(spec.get("series"), list) else [],
        "confidence": spec.get("confidence", 0),
        "selection_reason": str(spec.get("selection_reason") or ""),
        "fallback_reason": "",
        "image_data_uri": "",
        "image_format": "",
        "render_engine": "",
    }
    svg = _render_svg(chart)
    if svg:
        chart["image_data_uri"] = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
        chart["image_format"] = "svg"
        chart["render_engine"] = "python_svg"
    else:
        chart["fallback_reason"] = "chart_data_not_renderable"
    return chart


def _render_svg(chart: dict[str, Any]) -> str:
    chart_type = chart.get("chart_type")
    if chart_type == "kpi":
        return _kpi_chart(chart)
    values = _chart_values(chart)
    if len(values) <= 0:
        return ""
    if chart_type == "line" and len(values) > 1:
        return _line_chart(values[:24], chart)
    if chart_type in {"pie", "donut"} and len(values) > 1:
        return _pie_chart(values[:8], chart, donut=chart_type == "donut")
    if len(values) > 1:
        return _bar_chart(values[:14], chart, horizontal=chart_type == "horizontal_bar" or len(values) > 8)
    return _kpi_chart(chart)


def _kpi_chart(chart: dict[str, Any]) -> str:
    rows = chart.get("data") or []
    row = rows[0] if rows and isinstance(rows[0], dict) else {}
    y_column = chart.get("y")
    value = _to_float(row.get(y_column)) if y_column else None
    if value is None:
        value = next((_to_float(item) for item in row.values() if _to_float(item) is not None), None)
    label = str(row.get(chart.get("x") or "") or row.get("metric") or chart.get("title") or "核心结果")
    width = 920
    height = 260
    value_text = _format_number(value) if value is not None else escape(str(row or ""))
    body = f"""
<rect x="34" y="82" width="852" height="132" rx="22" fill="#f7f9fc" stroke="#e3e7ef"/>
<text x="64" y="128" class="axis-label">{escape(_short_label(label, 42))}</text>
<text x="64" y="184" class="kpi-value">{escape(value_text)}</text>
"""
    return _wrap_svg(width, height, str(chart.get("title") or "核心结果"), body)


def _bar_chart(values: list[dict[str, Any]], chart: dict[str, Any], *, horizontal: bool) -> str:
    width = 920
    height = max(420, 146 + len(values) * 34) if horizontal else 460
    max_value = max((abs(item["value"]) for item in values), default=1) or 1
    body: list[str] = []
    if horizontal:
        left = 186
        right = 126
        top = 78
        row_height = 34
        plot_width = width - left - right
        body.append(_grid_lines(left, top - 16, plot_width, len(values) * row_height, horizontal=True))
        for index, item in enumerate(values):
            y = top + index * row_height
            bar_width = max(3, abs(item["value"]) / max_value * plot_width)
            color = PALETTE[index % len(PALETTE)]
            body.append(f'<text x="{left - 12}" y="{y + 17}" class="axis-label" text-anchor="end">{escape(_short_label(item["label"], 20))}</text>')
            body.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="22" rx="7" fill="{color}"/>')
            body.append(f'<text x="{min(left + bar_width + 10, width - 96):.1f}" y="{y + 16}" class="value-label">{escape(_format_number(item["value"]))}</text>')
    else:
        left = 70
        right = 34
        top = 76
        bottom = 86
        plot_width = width - left - right
        plot_height = height - top - bottom
        body.append(_grid_lines(left, top, plot_width, plot_height))
        gap = 14
        bar_width = max(22, (plot_width - gap * (len(values) - 1)) / max(len(values), 1))
        for index, item in enumerate(values):
            bar_height = abs(item["value"]) / max_value * plot_height
            x = left + index * (bar_width + gap)
            y = top + plot_height - bar_height
            color = PALETTE[index % len(PALETTE)]
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" rx="8" fill="{color}"/>')
            body.append(f'<text x="{x + bar_width / 2:.1f}" y="{y - 10:.1f}" class="value-label" text-anchor="middle">{escape(_format_number(item["value"]))}</text>')
            body.append(f'<text x="{x + bar_width / 2:.1f}" y="{height - 42}" class="axis-label" text-anchor="middle">{escape(_short_label(item["label"], 8))}</text>')
    return _wrap_svg(width, height, str(chart.get("title") or "数据对比"), "".join(body))


def _line_chart(values: list[dict[str, Any]], chart: dict[str, Any]) -> str:
    width = 920
    height = 450
    left = 72
    right = 36
    top = 76
    bottom = 80
    plot_width = width - left - right
    plot_height = height - top - bottom
    min_value = min(item["value"] for item in values)
    max_value = max(item["value"] for item in values)
    span = max(max_value - min_value, 1)
    points = []
    for index, item in enumerate(values):
        x = left + index / max(len(values) - 1, 1) * plot_width
        y = top + plot_height - (item["value"] - min_value) / span * plot_height
        points.append((x, y, item))
    body = [_grid_lines(left, top, plot_width, plot_height)]
    body.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)}" fill="none" stroke="#2f6fed" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
    for index, (x, y, item) in enumerate(points):
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ffffff" stroke="#2f6fed" stroke-width="3"/>')
        if index in {0, len(points) - 1}:
            body.append(f'<text x="{x:.1f}" y="{y - 14:.1f}" class="value-label" text-anchor="middle">{escape(_format_number(item["value"]))}</text>')
    step = max(1, math.ceil(len(points) / 6))
    for index, (x, _, item) in enumerate(points):
        if index % step == 0 or index == len(points) - 1:
            body.append(f'<text x="{x:.1f}" y="{height - 38}" class="axis-label" text-anchor="middle">{escape(_short_label(item["label"], 8))}</text>')
    return _wrap_svg(width, height, str(chart.get("title") or "趋势图"), "".join(body))


def _pie_chart(values: list[dict[str, Any]], chart: dict[str, Any], *, donut: bool) -> str:
    width = 920
    height = 430
    total = sum(max(item["value"], 0) for item in values) or 1
    cx = 255
    cy = 235
    radius = 122
    start = -90.0
    body: list[str] = []
    for index, item in enumerate(values):
        pct = max(item["value"], 0) / total
        end = start + pct * 360
        body.append(_sector_path(cx, cy, radius, start, end, PALETTE[index % len(PALETTE)]))
        legend_y = 120 + index * 30
        body.append(f'<rect x="510" y="{legend_y - 13}" width="14" height="14" rx="4" fill="{PALETTE[index % len(PALETTE)]}"/>')
        body.append(f'<text x="534" y="{legend_y}" class="axis-label">{escape(_short_label(item["label"], 20))}  {pct * 100:.1f}%</text>')
        start = end
    if donut:
        body.append(f'<circle cx="{cx}" cy="{cy}" r="58" fill="#ffffff"/>')
    return _wrap_svg(width, height, str(chart.get("title") or "构成图"), "".join(body))


def _chart_values(chart: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in (chart.get("data") or []) if isinstance(row, dict)]
    x_column = chart.get("x")
    y_column = chart.get("y")
    values: list[dict[str, Any]] = []
    for row in rows:
        label = str(row.get(str(x_column), "")).strip() if x_column else ""
        value = _to_float(row.get(str(y_column))) if y_column else None
        if not label:
            label = str(row.get("metric") or row.get("name") or row.get("label") or "").strip()
        if value is None:
            value = next((_to_float(item) for key, item in row.items() if key != x_column and _to_float(item) is not None), None)
        if label and value is not None and math.isfinite(value):
            values.append({"label": label, "value": value})
    return values


def _infer_chart_type(rows: list[dict[str, Any]], columns: list[str], spec: dict[str, Any]) -> str | None:
    if not rows:
        return None
    operation = str(spec.get("selection_reason") or spec.get("reason") or "").lower()
    numeric_columns = _numeric_columns(rows, columns)
    if len(rows) == 1:
        return "kpi"
    if any(_looks_like_time_column(column) for column in columns) or "trend" in operation or "趋势" in operation:
        return "line"
    if numeric_columns:
        return "horizontal_bar" if len(rows) > 8 else "bar"
    return None


def _infer_xy(rows: list[dict[str, Any]], columns: list[str]) -> tuple[str | None, str | None]:
    numeric_columns = _numeric_columns(rows, columns)
    y_column = next((column for column in numeric_columns if not _looks_like_time_column(column)), None)
    y_column = y_column or (numeric_columns[0] if numeric_columns else None)
    categorical_columns = [column for column in columns if column != y_column]
    x_column = next((column for column in categorical_columns if _looks_like_time_column(column)), None)
    x_column = x_column or (categorical_columns[0] if categorical_columns else None)
    if x_column == y_column:
        x_column = None
    return x_column, y_column


def _numeric_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    output: list[str] = []
    for column in columns:
        numeric_count = sum(1 for row in rows[:20] if _to_float(row.get(column)) is not None)
        if numeric_count and numeric_count >= max(1, min(len(rows[:20]), 3) // 2):
            output.append(column)
    return output


def _column_is_numeric(rows: list[dict[str, Any]], column: str | None) -> bool:
    if not column:
        return False
    return any(_to_float(row.get(column)) is not None for row in rows[:20])


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    return [str(column) for column in rows[0].keys()] if rows else []


def _clean_chart_type(value: Any) -> str | None:
    chart_type = str(value or "").strip().lower()
    if not chart_type:
        return None
    return chart_type if chart_type in SUPPORTED_CHART_TYPES else None


def _usable_column(value: Any, columns: list[str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    lookup = {column.lower(): column for column in columns}
    return lookup.get(text.lower())


def _preferred_metric_column_from_text(spec: dict[str, Any], rows: list[dict[str, Any]], columns: list[str]) -> str | None:
    text = " ".join(str(spec.get(key) or "") for key in ("title", "reason", "selection_reason")).lower()
    if not text:
        return None
    numeric_columns = _numeric_columns(rows, columns)
    for column in numeric_columns:
        if column and column.lower() in text:
            return column
    if any(token in text for token in ("完成率", "变化率", "环比", "同比", "rate", "ratio", "percent", "%")):
        return next((column for column in numeric_columns if any(token in column.lower() for token in ("率", "rate", "ratio", "percent", "pct"))), None)
    return None


def _looks_like_time_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("date", "time", "month", "year", "week", "period", "日期", "月份", "年月", "时间"))


def _default_title(chart_type: str, x_column: str | None, y_column: str | None) -> str:
    if chart_type == "line":
        return f"{y_column or '指标'}趋势"
    if chart_type in {"pie", "donut"}:
        return f"{y_column or '指标'}构成"
    if chart_type == "kpi":
        return "核心结果"
    return f"{y_column or '指标'}对比"


def _grid_lines(left: int, top: int, plot_width: int, plot_height: int, *, horizontal: bool = False) -> str:
    lines: list[str] = []
    if horizontal:
        for step in range(5):
            x = left + plot_width * step / 4
            lines.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" class="grid-line"/>')
    else:
        for step in range(5):
            y = top + plot_height * step / 4
            lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" class="grid-line"/>')
    return "".join(lines)


def _wrap_svg(width: int, height: int, title: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
<style>
text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }}
.chart-title {{ fill: #111827; font-size: 24px; font-weight: 700; }}
.axis-label {{ fill: #4b5563; font-size: 14px; }}
.value-label {{ fill: #111827; font-size: 13px; font-weight: 650; }}
.kpi-value {{ fill: #111827; font-size: 44px; font-weight: 760; }}
.grid-line {{ stroke: #e5e7eb; stroke-width: 1; }}
</style>
<rect x="0" y="0" width="{width}" height="{height}" rx="24" fill="#ffffff"/>
<text x="34" y="43" class="chart-title">{escape(title)}</text>
{body}
</svg>"""


def _sector_path(cx: int, cy: int, radius: int, start_deg: float, end_deg: float, color: str) -> str:
    start = math.radians(start_deg)
    end = math.radians(end_deg)
    x1 = cx + radius * math.cos(start)
    y1 = cy + radius * math.sin(start)
    x2 = cx + radius * math.cos(end)
    y2 = cy + radius * math.sin(end)
    large_arc = 1 if end_deg - start_deg > 180 else 0
    return f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z" fill="{color}"/>'


def _to_float(value: Any) -> float | None:
    try:
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if text.endswith("%"):
                return float(text[:-1]) / 100
            return float(text)
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value) >= 1000:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _short_label(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(limit - 1, 1)] + "..."
