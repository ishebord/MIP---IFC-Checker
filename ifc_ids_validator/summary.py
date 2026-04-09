# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from collections import Counter

SUMMARY_FILENAME = "__Сводный_ИДС_отчет.html"


def summary_path(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / SUMMARY_FILENAME


def _rel(from_dir: Path, to_path: Path | None) -> str:
    if not to_path:
        return ""
    try:
        return str(to_path.relative_to(from_dir))
    except Exception:
        try:
            return str(to_path.resolve().relative_to(from_dir.resolve()))
        except Exception:
            return to_path.name


def _pct(v):
    return "—" if v is None else f"{v:.0f}%"


def _norm(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _majority_value(items: List[Dict[str, Any]], key: str) -> str:
    values = [_norm(it.get(key)) for it in items]
    values = [v for v in values if v]
    if not values:
        return ""
    cnt = Counter(values)
    value, amount = cnt.most_common(1)[0]

    if amount < 2:
        return ""
    return value


def _cell_html(value: str, majority: str) -> str:
    value = value or "—"

    if not majority:
        return f"<td>{value}</td>"

    if value == "—":
        return "<td class='error-cell'>—</td>"

    if value != majority:
        return f"<td class='error-cell'>{value}</td>"

    return f"<td>{value}</td>"


def _pct_badge(value: str) -> str:
    if not value or value == "—":
        return "<td class='badge-red'>—</td>"

    v = value.replace("%", "").strip()

    try:
        num = float(v)
    except Exception:
        return f"<td class='badge-red'>{value}</td>"

    if num == 100:
        return f"<td><span class='badge badge-green'>{value}</span></td>"
    else:
        return f"<td><span class='badge badge-red'>{value}</span></td>"


def _build_description_lookup(section_descriptions: List[List[str]] | None) -> List[tuple[str, str]]:
    result: List[tuple[str, str]] = []

    if not section_descriptions:
        return result

    for row in section_descriptions:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue

        code = str(row[0]).strip()
        desc = str(row[1]).strip()

        if not code:
            continue

        result.append((code.upper(), desc))

    # Сначала ищем более длинные коды, чтобы "ЭОМ" не перебивалось "ЭО"
    result.sort(key=lambda x: len(x[0]), reverse=True)
    return result


def _model_description(model_name: str, section_descriptions: List[List[str]] | None) -> str:
    model_upper = _norm(model_name).upper()
    if not model_upper:
        return "—"

    lookup = _build_description_lookup(section_descriptions)
    if not lookup:
        return "—"

    normalized = model_upper.replace(".", "_").replace("-", "_").replace(" ", "_")

    for code, desc in lookup:
        patterns = (
            f"_{code}_",
            f"{code}_",
            f"_{code}",
        )

        if normalized == code:
            return desc

        if any(p in normalized for p in patterns):
            return desc

        # Дополнительная проверка для случаев без явных разделителей
        if code in model_upper:
            return desc

    return "—"


def write_summary(
    outfile: Path,
    items: List[Dict[str, Any]],
    project_name: str = "",
    section_descriptions: List[List[str]] | None = None,
):
    """Перезаписывает сводный отчёт. Ссылки делаем относительно outfile.parent."""
    base = outfile.parent
    title = "Сводный IDS отчёт"
    if project_name:
        title = f"Сводный IDS отчёт по проекту {project_name}"

    maj_site = _majority_value(items, "site_name")
    maj_x = _majority_value(items, "x")
    maj_y = _majority_value(items, "y")
    maj_z = _majority_value(items, "z")
    maj_lat = _majority_value(items, "lat")
    maj_lon = _majority_value(items, "lon")

    rows = []
    for it in items:
        model = it.get("model", "")
        description = _model_description(model, section_descriptions)
        qty = it.get("qty") or "—"

        site_name = it.get("site_name") or "—"
        common_html = it.get("common")
        common_pct = it.get("common_pct")
        disc_html = it.get("disc")
        disc_pct = it.get("disc_pct")
        disc_code = it.get("disc_code") or ""
        site_building_pct = it.get("site_building_pct") or "—"
        building_pct = it.get("building_pct") or "—"
        storey_pct = it.get("storey_pct") or "—"

        x = it.get("x") or "—"
        y = it.get("y") or "—"
        z = it.get("z") or "—"
        lat = it.get("lat") or "—"
        lon = it.get("lon") or "—"

        c_href = _rel(base, common_html)
        d_href = _rel(base, disc_html)

        c_cell = f'<a class="link" href="{c_href}">{_pct(common_pct)}</a>' if c_href else "—"
        d_label = f"Дисциплина ({disc_code}) — {_pct(disc_pct)}" if d_href else "—"
        d_cell = f'<a class="link" href="{d_href}">{d_label}</a>' if d_href else "—"

        rows.append(
            f"<tr>"
            f"<td class='model-name'>{model}</td>"
            f"<td>{description}</td>"
            f"<td>{qty}</td>"
            f"<td style='text-align:center'>{c_cell}</td>"
            f"<td>{d_cell}</td>"
            f"{_cell_html(site_name, maj_site)}"
            f"{_cell_html(x, maj_x)}"
            f"{_cell_html(y, maj_y)}"
            f"{_cell_html(z, maj_z)}"
            f"{_cell_html(lat, maj_lat)}"
            f"{_cell_html(lon, maj_lon)}"
            f"{_pct_badge(site_building_pct)}"
            f"{_pct_badge(building_pct)}"
            f"{_pct_badge(storey_pct)}"
            f"</tr>"
        )

    html = f"""<!doctype html>
        <html lang="ru">
        <head>
        <meta charset="utf-8">
        <title>{title}</title>

        <style>
        :root {{
            --bg: #f5f7fb;
            --card: #ffffff;
            --text: #1f2937;
            --muted: #6b7280;
            --border: #e5e7eb;
            --accent: #3b82f6;
            --green: #10b981;
            --red: #ef4444;
        }}

        body {{
            margin: 0;
            background: var(--bg);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial;
            color: var(--text);
        }}

        .container {{
            max-width: 1600px;
            margin: 40px auto;
            padding: 0 20px;
        }}

        .card {{
            background: var(--card);
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            padding: 24px;
        }}

        h1 {{
            margin: 0 0 10px;
            font-size: 26px;
        }}

        .meta {{
            color: var(--muted);
            font-size: 13px;
            margin-bottom: 20px;
        }}

        .table-wrap {{
            overflow-x: auto;
        }}

        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            overflow: hidden;
            border-radius: 12px;
            min-width: 1450px;
        }}

        thead {{
            background: #f9fafb;
        }}

        th {{
            text-align: left;
            font-size: 13px;
            font-weight: 600;
            padding: 12px;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
        }}

        td {{
            padding: 12px;
            border-bottom: 1px solid var(--border);
            font-size: 14px;
            vertical-align: middle;
        }}

        tr:hover td {{
            background: #f9fbff;
        }}

        .center {{
            text-align: center;
        }}

        .badge {{
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
            display: inline-block;
        }}

        .badge-green {{
            background: rgba(16,185,129,0.1);
            color: var(--green);
        }}

        .badge-red {{
            background: rgba(239,68,68,0.1);
            color: var(--red);
        }}

        .link {{
            text-decoration: none;
            font-weight: 600;
            color: var(--accent);
        }}

        .link:hover {{
            text-decoration: underline;
        }}

        .error-cell {{
            background: #ffe4e6 !important;
            color: #991b1b;
            font-weight: 600;
            border-radius: 6px;
        }}

        .model-name {{
            font-weight: 600;
        }}

        .footer {{
            margin-top: 20px;
            font-size: 12px;
            color: var(--muted);
            text-align: right;
        }}
        </style>
        </head>

        <body>
        <div class="container">
        <div class="card">

        <h1>{title}</h1>
        <div class="meta">Создан: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>

        <div class="table-wrap">
        <table>
        <thead>
        <tr>
        <th>Модель</th>
        <th>Описание</th>
        <th>Кол-во</th>
        <th class="center">МССК</th>
        <th>Дисциплина</th>
        <th>Площадка</th>
        <th>Global X</th>
        <th>Global Y</th>
        <th>Global Z</th>
        <th>RefLatitude</th>
        <th>RefLongitude</th>
        <th>Участок застройки</th>
        <th>Здание (сооружение)</th>
        <th>Этаж (уровень)</th>
        </tr>
        </thead>

        <tbody>
        {''.join(rows)}
        </tbody>
        </table>
        </div>

        <div class="footer">
        IFC → IDS Validator
        </div>

        </div>
        </div>
        </body>
        </html>
        """
    outfile.write_text(html, encoding="utf-8")