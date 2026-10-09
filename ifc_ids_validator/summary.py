# summary.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from collections import Counter
from html import escape
from html.parser import HTMLParser
import json
import os
import re
import tempfile
import unicodedata
import math
import hashlib
from uuid import uuid4
from urllib.parse import quote

SUMMARY_FILENAME = "__Сводный_ИДС_отчет.html"


def summary_path(out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / SUMMARY_FILENAME


def _rel(from_dir: Path, to_path: Path | None) -> str:
    if not to_path:
        return ""
    target = Path(to_path).resolve()
    try:
        relative = os.path.relpath(target, Path(from_dir).resolve())
        return quote(Path(relative).as_posix(), safe="/")
    except ValueError:
        return target.as_uri()


def _model_key(name: str) -> str:
    # Windows file names compare without case; retain the full IFC filename.
    return unicodedata.normalize("NFC", str(name).replace("\\", "/").rsplit("/", 1)[-1]).casefold()


class _SavedSummaryParser(HTMLParser):
    """Read embedded dashboard state or migrate this application's old HTML table."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.payload = []
        self.in_payload = False
        self.in_body = False
        self.in_title = False
        self.title = []
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "ifc-dashboard-state":
            self.in_payload = True
        elif tag == "title":
            self.in_title = True
        elif tag == "tbody":
            self.in_body = True
        elif tag == "tr" and self.in_body:
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"text": [], "href": ""}
        elif tag == "a" and self.cell is not None:
            self.cell["href"] = attrs.get("href", "")
        elif tag == "br" and self.cell is not None:
            self.cell["text"].append("\n")

    def handle_data(self, data):
        if self.in_payload:
            self.payload.append(data)
        elif self.in_title:
            self.title.append(data)
        elif self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False
        elif tag == "title":
            self.in_title = False
        elif tag == "td" and self.cell is not None:
            self.cell["text"] = "".join(self.cell["text"]).strip()
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "tbody":
            self.in_body = False


def _read_saved_items(path: Path, project_name: str = "", history: bool = False):
    parser = _SavedSummaryParser()
    parser.feed(path.read_text(encoding="utf-8-sig"))
    if parser.payload:
        state = json.loads("".join(parser.payload))
        if state.get("version") != 1 or not isinstance(state.get("items"), list):
            raise ValueError(f"Неподдерживаемые данные сводного отчёта: {path.name}")
        if history and state.get("project_name", "") != project_name:
            return []
        return state["items"]
    expected_title = "Сводный IDS отчёт" + (f" по проекту {project_name}" if project_name else "")
    if "".join(parser.title).strip() != expected_title:
        if history:
            return []
        raise ValueError(f"Файл {path.name} не является сводным отчётом этого проекта.")
    result = []
    for cells in parser.rows:
        if len(cells) < 16:
            raise ValueError(f"Не удалось прочитать строку старой сводки: {path.name}")
        texts = [cell["text"] for cell in cells]
        row = dict(zip(("model", "revit_name", "description", "qty"), texts[:4]))
        for index, prefix in ((4, "common"), (5, "disc")):
            row[prefix + "_href"] = cells[index]["href"].replace("\\", "/")
            value = texts[index].replace("%", "").replace(",", ".").strip()
            row[prefix + "_pct"] = float(value) if value not in ("", "—") else None
        for index, key in enumerate(("site_name", "x", "y", "z", "lat", "lon",
                                     "site_building_pct", "building_pct", "storey_pct"), 6):
            row[key] = None if texts[index] == "—" else texts[index]
        row["storey_names"] = texts[15].splitlines() if texts[15] != "—" else []
        row["updated_at"] = "—"
        result.append(row)
    return result


def _merge_dashboard_items(outfile, incoming, project_name, section_descriptions):
    merged = {}
    previous = _read_saved_items(outfile, project_name) if outfile.exists() else []
    is_dashboard = outfile.exists() and 'id="ifc-dashboard-state"' in outfile.read_text(encoding="utf-8-sig")
    if not is_dashboard:
        # One-time migration of timestamped summaries generated by the previous build.
        base = Path(SUMMARY_FILENAME)
        pattern = re.compile(re.escape(base.stem) + r"_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_\d+)?\.html$")
        files = [path for path in outfile.parent.glob(base.stem + "_*.html") if pattern.fullmatch(path.name)]
        def history_order(path):
            stem = path.stem[len(base.stem) + 1:]
            parts = stem.split("_")
            return (parts[0], parts[1], int(parts[2]) if len(parts) > 2 else 1)
        for path in sorted(files, key=history_order):
            previous.extend(_read_saved_items(path, project_name, history=True))
    for row in previous:
        if not isinstance(row, dict) or not row.get("model"):
            raise ValueError("Повреждена запись модели в сводном отчёте; исходный файл сохранён.")
        merged[_model_key(row["model"])] = row
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in incoming:
        if not item.get("model"):
            raise ValueError("Не задано имя IFC-модели для обновления сводного отчёта.")
        row = {key: value for key, value in item.items() if key not in ("common", "disc", "dir_root")}
        row["common_href"] = _rel(outfile.parent, item.get("common"))
        row["disc_href"] = _rel(outfile.parent, item.get("disc"))
        row["description"] = _model_description(item["model"], section_descriptions)
        row["updated_at"] = updated_at
        merged[_model_key(item["model"])] = row
    return sorted(merged.values(), key=lambda row: _model_key(row["model"]))


def _atomic_write(outfile: Path, text: str):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=outfile.parent,
                                         prefix=".ids_dashboard_", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, outfile)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


HISTORY_FILENAME = "__История_проверок.json"
_HISTORY_METRICS = ("common_pct", "disc_pct", "site_building_pct", "building_pct", "storey_pct")


def _history_percent(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace("%", "").replace(",", "."))
        return number if math.isfinite(number) and 0 <= number <= 100 else None
    except (ValueError, TypeError):
        return None


def load_check_history(out_dir: Path):
    path = Path(out_dir) / HISTORY_FILENAME
    if not path.exists():
        return {"version": 1, "project_name": "", "records": []}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("version") != 1 or not isinstance(data.get("records"), list):
        raise ValueError(f"Неизвестный формат истории: {path.name}. Файл не изменён.")
    for record in data["records"]:
        if not isinstance(record, dict) or not record.get("model") or not record.get("checked_at"):
            raise ValueError(f"Повреждена запись истории: {path.name}. Файл не изменён.")
        datetime.fromisoformat(record["checked_at"])
        if not isinstance(record.get("values"), dict):
            raise ValueError(f"Повреждены проценты в истории: {path.name}.")
    return data


def ids_fingerprint(path):
    if not path:
        return ""
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return ""


def record_check_history(out_dir: Path, items, project_name="", run_id=None, checked_at=None):
    """Append actual checks; never invent samples for unchanged summary rows."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / HISTORY_FILENAME
    history = load_check_history(out_dir)
    history["project_name"] = project_name
    # Carry forward the last known dated result, when upgrading an existing report.
    if not path.exists() and (out_dir / SUMMARY_FILENAME).exists():
        for item in _read_saved_items(out_dir / SUMMARY_FILENAME, project_name):
            try:
                date = datetime.fromisoformat(item.get("updated_at", ""))
                date = date.astimezone()
            except (ValueError, TypeError):
                continue
            history["records"].append({
                "run_id": "imported-last-result", "model": item["model"],
                "checked_at": date.isoformat(), "source": "previous_summary",
                "values": {key: _history_percent(item.get(key)) for key in _HISTORY_METRICS},
                "common_ids": "", "disc_ids": "", "common_status": "imported", "disc_status": "imported",
            })
    run_id = run_id or uuid4().hex
    checked_at = checked_at or datetime.now().astimezone().isoformat(timespec="microseconds")
    datetime.fromisoformat(checked_at)
    # Retrying the same run is idempotent; distinct runs in one second are retained.
    existing = {(r.get("run_id"), _model_key(r["model"])) for r in history["records"]}
    for item in items:
        name = item.get("model")
        if not name:
            raise ValueError("В истории проверки отсутствует имя IFC-модели.")
        identity = (run_id, _model_key(name))
        if identity in existing:
            continue
        stamp = item.get("checked_at") or checked_at
        datetime.fromisoformat(stamp)
        history["records"].append({
            "run_id": run_id, "model": name, "checked_at": stamp, "source": "check",
            "values": {key: _history_percent(item.get(key)) for key in _HISTORY_METRICS},
            "common_ids": str(item.get("common_ids") or ""),
            "disc_ids": str(item.get("disc_ids") or ""),
            "common_ids_fingerprint": str(item.get("common_ids_fingerprint") or ""),
            "disc_ids_fingerprint": str(item.get("disc_ids_fingerprint") or ""),
            "common_status": str(item.get("common_status") or ("result" if item.get("common_pct") is not None else "no_result")),
            "disc_status": str(item.get("disc_status") or ("result" if item.get("disc_pct") is not None else "no_result")),
        })
        existing.add(identity)
    history["updated_at"] = datetime.now().astimezone().isoformat()
    _atomic_write(path, json.dumps(history, ensure_ascii=False, indent=2, allow_nan=False))
    return history


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
    return f"<td{class_attr}>{escape(str(value))}</td>"


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
    record_history: bool = True,
):
    outfile = Path(outfile)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    incoming = items
    items = _merge_dashboard_items(outfile, incoming, project_name, section_descriptions)
    history = record_check_history(outfile.parent, incoming, project_name) if record_history else load_check_history(outfile.parent)
    history_payload = json.dumps(history, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    payload = json.dumps({"version": 1, "project_name": project_name, "items": items},
                         ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
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
        revit_name = it.get("revit_name") or "—"
        description = it.get("description") or _model_description(model, section_descriptions)
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

        storey_names = it.get("storey_names") or []
        if isinstance(storey_names, list) and storey_names:
            storey_names_html = "<br>".join(escape(str(x)) for x in storey_names)
        else:
            storey_names_html = "—"

        c_href = escape(it.get("common_href") or "", quote=True)
        d_href = escape(it.get("disc_href") or "", quote=True)

        c_cell = f'<a class="link" href="{c_href}">{_pct(common_pct)}</a>' if c_href else "—"
        d_label = _pct(disc_pct) if d_href else "—"
        d_cell = f'<a class="link" href="{d_href}">{d_label}</a>' if d_href else "—"

        rows.append(
            f"<tr>"
            f"<td class='model-name'>{escape(str(model))}</td>"
            f"<td>{escape(str(revit_name))}</td>"
            f"<td>{escape(str(description))}</td>"
            f"<td>{escape(str(qty))}</td>"
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
            f"<td class='group-storeys'>{storey_names_html}</td>"
            f"<td>{escape(str(it.get('updated_at') or '—'))}</td>"
            f"</tr>"
        )

    html = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>

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

<h1>{escape(title)}</h1>
<div class="meta">Обновлён: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>

<div class="column-controls">
    <label><input type="checkbox" data-group="coords"> Координаты (X/Y/Z)</label>
    <label><input type="checkbox" data-group="geo"> География (Lat/Lon)</label>
    <label><input type="checkbox" checked data-group="ifc"> IFC структура</label>
    <label><input type="checkbox" data-group="storeys"> Уровни</label>
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
<th class="sortable" data-type="text" data-col="0">Модель ▲</th>
<th>Наименование Revit</th>
<th>Описание</th>
<th class="sortable" data-type="number" data-col="3">Кол-во элементов</th>
<th class="sortable center" data-type="percent" data-col="4">Общая IDS</th>
<th class="sortable" data-type="percent" data-col="5">Дисциплина</th>
<th>Площадка</th>
<th class="group-coords">Global X</th>
<th class="group-coords">Global Y</th>
<th class="group-coords">Global Z</th>
<th class="group-geo">RefLatitude</th>
<th class="group-geo">RefLongitude</th>
<th class="group-ifc">IfcSite – Участок застройки</th>
<th class="group-ifc">IfcBuilding - Здание (сооружение)</th>
<th class="group-ifc">IfcBuildingStorey - Этаж (уровень)</th>
<th class="group-storeys">Список уровней</th>
<th>Проверено</th>
</tr>
</thead>

<tbody>
{''.join(rows)}
</tbody>
</table>
</div>

{_HISTORY_HTML}

<div class="footer">
IFC → IDS Validator
</div>

</div>
</div>

<script id="ifc-check-history" type="application/json">{history_payload}</script>
<style>{_HISTORY_CSS}</style>
<script>{_HISTORY_JS}</script>
<script id="ifc-dashboard-state" type="application/json">{payload}</script>
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

    _atomic_write(outfile, html)


_HISTORY_HTML = r'''
<section id="history-panel" aria-labelledby="history-heading">
  <div class="hist-heading"><div><span class="hist-eyebrow">ИСТОРИЯ ПРОВЕРОК</span><h2 id="history-heading">Как меняется качество моделей</h2><p>Процент выполнения требований IDS по каждой проверке. Без усреднения разных моделей.</p></div><a href="__История_проверок.json" download class="hist-button">История JSON ↓</a></div>
  <div class="hist-controls">
    <label>Вид проверки<select id="hist-metric"><option value="common_pct">Общая IDS</option><option value="disc_pct">Дисциплинарная IDS</option><option value="site_building_pct">IfcSite — участок</option><option value="building_pct">IfcBuilding — здание</option><option value="storey_pct">IfcBuildingStorey — уровни</option></select></label>
    <label>Период<select id="hist-period"><option value="all">Вся история</option><option value="7">7 дней до последней проверки</option><option value="30">30 дней до последней проверки</option><option value="90">90 дней до последней проверки</option><option value="custom">Выбрать даты</option></select></label>
    <label>С даты<input id="hist-from" type="date" aria-label="Начало периода" disabled></label>
    <label>По дату<input id="hist-to" type="date" aria-label="Конец периода" disabled></label>
    <button id="hist-csv" type="button" class="hist-button">Выгрузить CSV ↓</button>
  </div>
  <div class="hist-layout">
    <aside class="hist-models"><div class="hist-model-title">Модели <span id="hist-selected-count"></span></div><input id="hist-search" type="search" placeholder="Поиск по имени IFC" aria-label="Поиск модели"><p>Количество моделей не ограничено</p><button id="hist-all" type="button" class="hist-text-button">Выбрать все</button> · <button id="hist-clear" type="button" class="hist-text-button">Снять выбор</button><div id="hist-model-list"></div></aside>
    <div class="hist-main"><div id="hist-caption" class="hist-caption" aria-live="polite"></div><div id="hist-plot" class="hist-plot"></div><div id="hist-inspect" class="hist-inspect" aria-live="polite">Наведите на точку или выберите её клавишей Tab, чтобы увидеть результат.</div><div id="hist-cards" class="hist-cards"></div></div>
  </div>
  <p id="hist-line-status" class="hist-note" aria-live="polite"></p>
  <p class="hist-note">Шкала всегда 0–100%. Сплошная линия — одинаковые IDS. Пунктир — IDS изменена или её версия неизвестна; такой переход не означает улучшение или ухудшение модели при одинаковых требованиях. Нет результата — разрыв, а не 0%. Одна проверка отображается точкой. Время показано в часовом поясе браузера.</p>
  <details class="hist-details"><summary>Все значения выбранных моделей</summary><div class="hist-table-wrap"><table class="hist-table"><thead><tr><th>Дата и время</th><th>Модель IFC</th><th>Результат</th><th>Состояние</th><th>IDS</th></tr></thead><tbody id="hist-values"></tbody></table></div><div class="hist-pagination"><button id="hist-prev" type="button" class="hist-button">← Назад</button><span id="hist-page"></span><button id="hist-next" type="button" class="hist-button">Далее →</button></div></details>
</section>
'''


_HISTORY_CSS = r'''
#history-panel{margin-top:36px;border-top:1px solid #dfe6f0;padding-top:30px;color:#172a43}#history-panel *{box-sizing:border-box}.hist-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.hist-eyebrow{font-size:11px;letter-spacing:.15em;font-weight:750;color:#3268e8}.hist-heading h2{font-size:25px;margin:8px 0;letter-spacing:-.025em}.hist-heading p,.hist-note{font-size:13px;color:#64748b;line-height:1.6}.hist-heading p{margin:0}.hist-controls{display:flex;align-items:end;flex-wrap:wrap;gap:12px;margin:24px 0}.hist-controls label{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:650;color:#526176}.hist-controls select,.hist-controls input,#hist-search{padding:10px 12px;border:1px solid #dbe3ef;border-radius:8px;font:inherit;background:white;color:#172a43;min-height:40px}.hist-controls select{min-width:195px}.hist-controls input{width:150px}.hist-controls input:disabled{background:#f5f7fb;color:#94a3b8}.hist-button{border:1px solid #dbe3ef;border-radius:8px;background:#fff;padding:10px 14px;color:#2453a6;font:600 12px system-ui,sans-serif;cursor:pointer;text-decoration:none;white-space:nowrap;min-height:40px}.hist-button:hover{background:#eef4ff}.hist-button:disabled{color:#a5adbb;cursor:default;background:#f8fafc}#history-panel :focus-visible{outline:3px solid #93b4ff;outline-offset:3px}.hist-layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:24px}.hist-models{background:#f7f9fc;border:1px solid #e3eaf3;border-radius:12px;padding:16px}.hist-model-title{font-size:14px;font-weight:700;display:flex;justify-content:space-between}.hist-models p{font-size:11px;color:#64748b;margin:8px 0}.hist-models input[type=search]{width:100%;margin-top:14px;font-size:12px}.hist-text-button{border:0;background:none;padding:4px 0;color:#3268e8;cursor:pointer;font-size:12px}.hist-model-list-item{display:flex;align-items:flex-start;gap:8px;padding:9px 0;font-size:12px;line-height:1.5;cursor:pointer;overflow-wrap:anywhere}.hist-model-list-item input{margin-top:3px;accent-color:#3268e8}.hist-swatch{width:9px;height:9px;min-width:9px;margin-top:5px;border-radius:50%}#hist-model-list{max-height:325px;overflow:auto;margin-top:6px}.hist-main{min-width:0}.hist-caption{font-size:13px;font-weight:650;min-height:24px}.hist-plot{overflow:auto;border:1px solid #e2e8f0;border-radius:12px;background:#fff;min-height:335px}.hist-plot svg{display:block;min-width:620px;width:100%;height:335px}.hist-plot .hist-empty{padding:90px 25px;text-align:center;color:#64748b;font-size:14px}.hist-inspect{min-height:52px;padding:10px 2px;font-size:12px;color:#526176;line-height:1.6;white-space:pre-line;overflow-wrap:anywhere}.hist-cards{display:flex;flex-wrap:wrap;gap:10px}.hist-card{padding:12px;border:1px solid #e2e8f0;border-radius:10px;flex:1 1 170px;min-width:0}.hist-card-name{font-size:12px;font-weight:650;overflow-wrap:anywhere;min-height:32px}.hist-card-value{font-size:23px;font-weight:750;margin:8px 0}.hist-card-detail{font-size:11px;color:#64748b;line-height:1.6}.hist-note{margin:18px 0}.hist-details{border:1px solid #e2e8f0;border-radius:10px;padding:14px}.hist-details summary{font-size:13px;font-weight:650;cursor:pointer}.hist-table-wrap{overflow:auto;margin-top:12px}.hist-table{width:100%;border-collapse:collapse}.hist-table td,.hist-table th{font-size:12px;padding:10px;white-space:normal}.hist-table th:first-child,.hist-table td:first-child{white-space:nowrap}.hist-table td{overflow-wrap:anywhere}.hist-pagination{display:flex;align-items:center;justify-content:space-between;font-size:12px;margin-top:12px}.hist-point{cursor:pointer}.hist-point:hover,.hist-point:focus{stroke:#172a43;stroke-width:3}@media(max-width:1000px){.hist-layout{grid-template-columns:1fr}.hist-models{max-height:250px}.hist-models #hist-model-list{max-height:110px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.hist-heading{align-items:flex-start}.hist-heading h2{font-size:22px}}@media print{.hist-controls,.hist-models,.hist-inspect,.hist-pagination,.hist-button{display:none}.hist-layout{display:block}.hist-details{display:none}.hist-plot svg{height:300px}}
'''


_HISTORY_JS = r'''
document.addEventListener('DOMContentLoaded', () => {
 'use strict';
 const state = JSON.parse(document.getElementById('ifc-check-history').textContent);
 const byId = id => document.getElementById(id);
 const metric = byId('hist-metric'), period = byId('hist-period'), start = byId('hist-from'), end = byId('hist-to');
 const records = state.records.map((r,index) => ({...r,index,t:Date.parse(r.checked_at),key:r.model.normalize('NFC').replaceAll('\\','/').split('/').pop().toLowerCase()})).filter(r => Number.isFinite(r.t)).sort((a,b) => a.t-b.t || a.index-b.index);
 const names = new Map(); records.forEach(r=>names.set(r.key,r.model));
 const keys = [...names.keys()].sort((a,b)=>names.get(a).localeCompare(names.get(b),'ru'));
 const selected = new Set(keys.slice(0,3));
 const colors = ['#2563eb','#d97706','#059669','#9333ea','#db2777'];
 const modelColors = new Map(keys.map((key,index)=>[key,index<colors.length?colors[index]:`hsl(${(210+(index-colors.length)*137.508)%360}, 68%, 40%)`]));
 const colorFor = key => modelColors.get(key);
 let filtered=[], page=0;
 const number = n => n===null || n===undefined ? '—' : new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n)+'%';
 const date = t => new Date(t).toLocaleString('ru-RU',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
 const value = r => {const v=r.values[metric.value];return typeof v==='number' && Number.isFinite(v) && v>=0 && v<=100 ? v : null;};
 const ids = r => metric.value==='common_pct' ? r.common_ids : metric.value==='disc_pct' ? r.disc_ids : [r.common_ids,r.disc_ids].filter(Boolean).join(' + ');
 function idsRelation(a,b){
  const families=metric.value==='common_pct'?['common']:metric.value==='disc_pct'?['disc']:['common','disc'];
  let unknown=false;
  for(const family of families){
   const ah=a[family+'_ids_fingerprint'],bh=b[family+'_ids_fingerprint'];
   const ap=a[family+'_ids'],bp=b[family+'_ids'];
   if(ah&&bh){if(ah!==bh)return 'changed';}
   else if(ap&&bp&&ap!==bp)return 'changed';
   else if(family==='disc'&&a.disc_status==='disabled'&&b.disc_status==='disabled')continue;
   else unknown=true;
  }
  return unknown?'unknown':'same';
 }
 const relationText = relation => relation==='changed'?'IDS изменена — результаты получены по разным требованиям':'Версия IDS неизвестна — сопоставимость результатов не подтверждена';
 const status = r => r.source==='previous_summary' ? 'Из прежней сводки' : ({result:'Результат получен',error:'Ошибка проверки',disabled:'Отключено',no_rule:'Нет правила',not_run:'Не выполнено',no_result:'Нет результата',imported:'Из прежней сводки'}[(metric.value==='common_pct'?r.common_status:metric.value==='disc_pct'?r.disc_status:'')] || (value(r)===null?'Нет результата':'Результат получен'));
 function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
 function modelList(){
  const box=byId('hist-model-list');box.replaceChildren();
  const search=byId('hist-search').value.toLowerCase();
  keys.filter(k=>names.get(k).toLowerCase().includes(search)).forEach(k=>{
   const label=element('label',undefined,'hist-model-list-item'),check=document.createElement('input');check.type='checkbox';check.checked=selected.has(k);check.setAttribute('aria-label',names.get(k));
   check.addEventListener('change',()=>{if(check.checked)selected.add(k);else selected.delete(k);page=0;render();});
   const swatch=element('span',undefined,'hist-swatch');swatch.style.background=selected.has(k)?colorFor(k):'#cbd5e1';
   label.append(check,swatch,element('span',names.get(k)));box.append(label);
  });
  if(!box.children.length)box.append(element('p','Модели не найдены.'));
  byId('hist-selected-count').textContent=selected.size+' / '+keys.length;
 }
 function filter(){
  let lo=-Infinity,hi=Infinity;
  if(period.value==='custom'){
   if(start.value)lo=new Date(start.value+'T00:00:00').getTime();
   if(end.value)hi=new Date(end.value+'T23:59:59.999').getTime();
  }else if(period.value!=='all'){
   hi=records.length?records[records.length-1].t:Date.now();lo=hi-Number(period.value)*86400000;
  }
  filtered=records.filter(r=>selected.has(r.key)&&r.t>=lo&&r.t<=hi);
 }
 function svgNode(tag,attrs={},text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));if(text!==undefined)e.textContent=text;return e;}
 function inspect(r){byId('hist-inspect').textContent=names.get(r.key)+' · '+date(r.t)+' · '+metric.options[metric.selectedIndex].text+': '+number(value(r))+'\n'+status(r)+(ids(r)?' · IDS: '+ids(r):'');}
 function chart(){
  const box=byId('hist-plot');box.replaceChildren();
  const lineStatus=byId('hist-line-status');lineStatus.textContent='';
  let transitions=0,singletons=0;
  const valid=filtered.filter(r=>value(r)!==null);
  if(!valid.length){box.append(element('div',!records.length?'История появится после первой проверки.':!selected.size?'Выберите модели слева.':'За выбранный период нет числовых результатов этой проверки.','hist-empty'));return;}
  const w=Math.max(620,box.clientWidth),h=335,L=55,R=24,T=25,B=55;
  const min=filtered[0].t,max=filtered[filtered.length-1].t;
  const lo=min===max?min-1800000:min,hi=min===max?max+1800000:max;
  const x=t=>L+(t-lo)/(hi-lo)*(w-L-R), y=v=>T+(100-v)/100*(h-T-B);
  const svg=svgNode('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':metric.options[metric.selectedIndex].text+' — изменение процентов во времени'});
  for(let v=0;v<=100;v+=20){svg.append(svgNode('line',{x1:L,y1:y(v),x2:w-R,y2:y(v),stroke:v===100?'#b8ddcb':'#e7edf5','stroke-dasharray':v===100?'5 4':'0'}));svg.append(svgNode('text',{x:L-10,y:y(v)+4,'text-anchor':'end',fill:'#708097','font-size':11},v+'%'));}
  const count=w<850?3:5;
  for(let i=0;i<count;i++){const t=lo+(hi-lo)*i/(count-1);const d=new Date(t);svg.append(svgNode('text',{x:x(t),y:h-29,'text-anchor':i===0?'start':i===count-1?'end':'middle',fill:'#708097','font-size':11},d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})));svg.append(svgNode('text',{x:x(t),y:h-13,'text-anchor':i===0?'start':i===count-1?'end':'middle',fill:'#708097','font-size':10},hi-lo<172800000?d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):String(d.getFullYear())));}
  [...selected].forEach(key=>{
   const rr=filtered.filter(r=>r.key===key);let segment=[],previous=null;
   function flush(){if(segment.length>1)svg.append(svgNode('polyline',{points:segment.join(' '),fill:'none',stroke:colorFor(key),'stroke-width':2.5,'stroke-linejoin':'round',class:'hist-series'}));segment=[];}
   if(rr.filter(r=>value(r)!==null).length===1)singletons++;
   rr.forEach(r=>{
    if(value(r)===null){flush();previous=null;return;}
    if(previous){
     const relation=idsRelation(previous,r);
     if(relation!=='same'){
      flush();transitions++;
      const label=names.get(key)+' · '+date(previous.t)+' → '+date(r.t)+' · '+relationText(relation);
      const link=svgNode('line',{x1:x(previous.t),y1:y(value(previous)),x2:x(r.t),y2:y(value(r)),stroke:colorFor(key),'stroke-width':2.5,'stroke-dasharray':'7 5',class:'hist-transition','data-relation':relation,tabindex:0,'aria-label':label});
      link.append(svgNode('title',{},label));
      const show=()=>{byId('hist-inspect').textContent=label;};
      link.addEventListener('mouseenter',show);link.addEventListener('focus',show);link.addEventListener('click',show);svg.append(link);
     }
    }
    segment.push(`${x(r.t)},${y(value(r))}`);previous=r;
   });flush();
   rr.filter(r=>value(r)!==null).forEach(r=>{const circle=svgNode('circle',{cx:x(r.t),cy:y(value(r)),r:4.5,fill:colorFor(key),stroke:'white','stroke-width':1.5,tabindex:0,class:'hist-point','aria-label':`${r.model}, ${date(r.t)}, ${number(value(r))}`});circle.append(svgNode('title',{},`${r.model}\n${date(r.t)}\n${number(value(r))}\n${ids(r) || 'IDS не сохранена'}`));circle.addEventListener('mouseenter',()=>inspect(r));circle.addEventListener('focus',()=>inspect(r));circle.addEventListener('click',()=>inspect(r));svg.append(circle);});
  });box.append(svg);
  lineStatus.textContent=[transitions?'Пунктирных переходов: '+transitions+'. Наведите на пунктир или выберите его клавишей Tab, чтобы узнать причину.':'',singletons?'У моделей с одной проверкой пока отображается только точка.':''].filter(Boolean).join(' ');
 }
 function cards(){const box=byId('hist-cards');box.replaceChildren();[...selected].forEach(key=>{
  const rr=filtered.filter(r=>r.key===key),last=rr.at(-1),first=rr.find(r=>value(r)!==null);
  const card=element('div',undefined,'hist-card');card.style.borderTop='3px solid '+colorFor(key);card.append(element('div',names.get(key),'hist-card-name'),element('div',last?number(value(last)):'—','hist-card-value'));
  let detail=last?'Последняя проверка: '+date(last.t):'Нет проверок в этом периоде';
  const relations=rr.slice(1).map((r,index)=>idsRelation(rr[index],r));
  if(first&&last&&value(last)!==null&&first!==last&&relations.every(r=>r==='same')){
   const delta=value(last)-value(first);detail+=' · '+(delta>0?'+':'')+new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(delta)+' п.п. к первой проверке периода';
  }else if(relations.includes('changed'))detail+=' · IDS изменена';
  else if(relations.includes('unknown'))detail+=' · Версия IDS неизвестна';
  card.append(element('div',detail,'hist-card-detail'));box.append(card);
 });}
 function table(){const rows=[...filtered].reverse(),pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages-1);const body=byId('hist-values');body.replaceChildren();rows.slice(page*50,(page+1)*50).forEach(r=>{const tr=element('tr');[date(r.t),r.model,number(value(r)),status(r),ids(r)||'—'].forEach(v=>tr.append(element('td',v)));body.append(tr);});byId('hist-page').textContent=`Страница ${page+1} / ${pages} · Записей: ${rows.length}`;byId('hist-prev').disabled=page===0;byId('hist-next').disabled=page===pages-1;}
 function render(){filter();modelList();byId('hist-caption').textContent=metric.options[metric.selectedIndex].text+' · '+filtered.length+' записей · '+selected.size+' моделей';byId('hist-inspect').textContent='Наведите на точку или выберите её клавишей Tab, чтобы увидеть результат.';chart();cards();table();}
 function csv(){const safe=v=>'"'+String(v??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';const rows=[['Дата ISO','Модель IFC','Проверка','Процент','Состояние','IDS'],...filtered.map(r=>[r.checked_at,r.model,metric.options[metric.selectedIndex].text,value(r),status(r),ids(r)])];const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(safe).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='IFC_История_проверок.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
 metric.addEventListener('change',()=>{page=0;render();});period.addEventListener('change',()=>{const custom=period.value==='custom';start.disabled=end.disabled=!custom;page=0;render();});[start,end].forEach(e=>e.addEventListener('change',()=>{page=0;render();}));byId('hist-search').addEventListener('input',modelList);byId('hist-all').addEventListener('click',()=>{keys.forEach(k=>selected.add(k));page=0;render();});byId('hist-clear').addEventListener('click',()=>{selected.clear();page=0;render();});byId('hist-csv').addEventListener('click',csv);byId('hist-prev').addEventListener('click',()=>{page--;table();});byId('hist-next').addEventListener('click',()=>{page++;table();});
 let width=0;new ResizeObserver(entries=>{const next=Math.round(entries[0].contentRect.width);if(next!==width){width=next;chart();}}).observe(byId('hist-plot'));
 render();
});
'''
