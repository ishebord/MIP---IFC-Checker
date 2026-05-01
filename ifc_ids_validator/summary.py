# summary.py
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


def _cell_html(value: str, majority: str, css_class: str = "") -> str:
    value = value or "—"
    cls = css_class

    if majority:
        if value == "—" or value != majority:
            cls = (cls + " error-cell").strip()

    class_attr = f" class='{cls}'" if cls else ""
    return f"<td{class_attr}>{value}</td>"


def _pct_badge(value: str, css_class: str = "") -> str:
    if not value or value == "—":
        class_attr = f" class='{css_class}'" if css_class else ""
        return f"<td{class_attr}>—</td>"

    v = value.replace("%", "").strip()

    try:
        num = float(v)
    except Exception:
        cls = (css_class + " badge-red").strip()
        return f"<td class='{cls}'>{value}</td>"

    badge_class = "badge-green" if num == 100 else "badge-red"
    class_attr = f" class='{css_class}'" if css_class else ""

    return f"<td{class_attr}><span class='badge {badge_class}'>{value}</span></td>"


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

        if code in model_upper:
            return desc

    return "—"


def write_summary(
    outfile: Path,
    items: List[Dict[str, Any]],
    project_name: str = "",
    section_descriptions: List[List[str]] | None = None,
):
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
        d_label = _pct(disc_pct) if d_href else "—"
        d_cell = f'<a class="link" href="{d_href}">{d_label}</a>' if d_href else "—"

        rows.append(
            f"<tr>"
            f"<td class='model-name'>{model}</td>"
            f"<td>{description}</td>"
            f"<td>{qty}</td>"
            f"<td style='text-align:center'>{c_cell}</td>"
            f"<td>{d_cell}</td>"
            f"{_cell_html(site_name, maj_site)}"
            f"{_cell_html(x, maj_x, 'group-coords')}"
            f"{_cell_html(y, maj_y, 'group-coords')}"
            f"{_cell_html(z, maj_z, 'group-coords')}"
            f"{_cell_html(lat, maj_lat, 'group-geo')}"
            f"{_cell_html(lon, maj_lon, 'group-geo')}"
            f"{_pct_badge(site_building_pct, 'group-ifc')}"
            f"{_pct_badge(building_pct, 'group-ifc')}"
            f"{_pct_badge(storey_pct, 'group-ifc')}"
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
    max-width: 2200px;
    margin: 40px auto;
    padding: 0 12px;
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
    margin-bottom: 16px;
}}

.column-controls {{
    margin-bottom: 14px;
    padding: 10px 12px;
    background: #f9fafb;
    border: 1px solid var(--border);
    border-radius: 10px;
    font-size: 14px;
}}

.column-controls label {{
    margin-right: 18px;
    cursor: pointer;
    user-select: none;
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
    white-space: normal;
}}

td {{
    padding: 12px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
    vertical-align: middle;
    word-break: break-word;
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

.sortable {{
    cursor: pointer;
    user-select: none;
}}

.sortable:hover {{
    background: #eef4ff;
}}
</style>
</head>

<body>
<div class="container">
<div class="card">

<h1>{title}</h1>
<div class="meta">Создан: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>

<div class="column-controls">
    <label><input type="checkbox" data-group="coords"> Координаты (X/Y/Z)</label>
    <label><input type="checkbox" data-group="geo"> География (Lat/Lon)</label>
    <label><input type="checkbox" checked data-group="ifc"> IFC структура</label>
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
<th class="sortable" data-type="text" data-col="0">Модель ▲</th>
<th>Описание</th>
<th class="sortable" data-type="number" data-col="2">Кол-во элементов</th>
<th class="sortable center" data-type="percent" data-col="3">МССК</th>
<th class="sortable" data-type="percent" data-col="4">Дисциплина</th>
<th>Площадка</th>
<th class="group-coords">Global X</th>
<th class="group-coords">Global Y</th>
<th class="group-coords">Global Z</th>
<th class="group-geo">RefLatitude</th>
<th class="group-geo">RefLongitude</th>
<th class="group-ifc">IfcSite – Участок застройки</th>
<th class="group-ifc">IfcBuilding - Здание (сооружение)</th>
<th class="group-ifc">IfcBuildingStorey - Этаж (уровень)</th>
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

<script>
document.addEventListener("DOMContentLoaded", function () {{
    const table = document.querySelector("table");
    const tbody = table.querySelector("tbody");
    const headers = table.querySelectorAll("th.sortable");

    let currentSort = {{
        col: 0,
        direction: "asc"
    }};

    function cleanText(value) {{
        return (value || "")
            .replace("▲", "")
            .replace("▼", "")
            .replace("%", "")
            .replace("—", "")
            .trim();
    }}

    function getCellValue(row, col, type) {{
        const cell = row.children[col];
        if (!cell) return "";

        const raw = cleanText(cell.innerText);

        if (type === "number" || type === "percent") {{
            const num = parseFloat(raw.replace(",", "."));
            return isNaN(num) ? -1 : num;
        }}

        return raw.toLowerCase();
    }}

    function sortTable(col, type, direction) {{
        const rows = Array.from(tbody.querySelectorAll("tr"));

        rows.sort((a, b) => {{
            const av = getCellValue(a, col, type);
            const bv = getCellValue(b, col, type);

            if (typeof av === "number" && typeof bv === "number") {{
                return direction === "asc" ? av - bv : bv - av;
            }}

            return direction === "asc"
                ? String(av).localeCompare(String(bv), "ru")
                : String(bv).localeCompare(String(av), "ru");
        }});

        rows.forEach(row => tbody.appendChild(row));

        headers.forEach(h => {{
            h.textContent = h.textContent.replace(" ▲", "").replace(" ▼", "");
        }});

        const active = Array.from(headers).find(h => Number(h.dataset.col) === col);

        if (active) {{
            active.textContent += direction === "asc" ? " ▲" : " ▼";
        }}

        currentSort.col = col;
        currentSort.direction = direction;
    }}

    headers.forEach(header => {{
        header.addEventListener("click", function () {{
            const col = Number(this.dataset.col);
            const type = this.dataset.type;

            let direction = "asc";

            if (currentSort.col === col) {{
                direction = currentSort.direction === "asc" ? "desc" : "asc";
            }}

            sortTable(col, type, direction);
        }});
    }});

    document.querySelectorAll("input[type=checkbox][data-group]").forEach(cb => {{
        cb.addEventListener("change", function () {{
            const group = this.dataset.group;
            const visible = this.checked;

            document.querySelectorAll(".group-" + group).forEach(el => {{
                el.style.display = visible ? "" : "none";
            }});
        }});
    }});

    // применяем начальную видимость колонок
    document.querySelectorAll("input[type=checkbox][data-group]").forEach(cb => {{
        const group = cb.dataset.group;
        const visible = cb.checked;

        document.querySelectorAll(".group-" + group).forEach(el => {{
            el.style.display = visible ? "" : "none";
        }});
    }});

    sortTable(0, "text", "asc");
}});
</script>

</body>
</html>
"""

    outfile.write_text(html, encoding="utf-8")