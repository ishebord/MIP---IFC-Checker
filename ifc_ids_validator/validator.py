# validator.py
from __future__ import annotations
import json
import sys
import subprocess
import re
import os
import multiprocessing
import queue
import time
import threading
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional, List

import ifcopenshell
from ifctester import ids as ids_mod

from ifc_ids_validator.report_postprocess import postprocess_html_report

# reporter может отсутствовать на некоторых сборках
try:
    from ifctester import reporter
    HAVE_REPORTER = True
except Exception:
    HAVE_REPORTER = False

# опционально используем bs4, если установлена (pip install beautifulsoup4)
try:
    from bs4 import BeautifulSoup  # type: ignore
    HAVE_BS4 = True
except Exception:
    HAVE_BS4 = False

MATCH_CONTAINS = "contains"   # единственный режим — «Содержит»


# ----------------------------- matching -----------------------------
def match_rule(filename: str, rules: List[Dict], mode: str = MATCH_CONTAINS) -> Tuple[Optional[Dict], Optional[str]]:
    """Подстрочный match без регистра."""
    name = (filename or "").lower()
    for r in rules or []:
        patt = (r.get("pattern") or "").lower()
        if patt and patt in name:
            return r, None
    return None, None


# ------------------------------- IO --------------------------------
def open_ids(path: str):
    return ids_mod.open(path, validate=True)


def open_ifc(path: str):
    return ifcopenshell.open(path)


def _fmt_num(v) -> Optional[str]:
    if v is None:
        return None
    try:
        f = float(v)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return f"{f:.6f}".rstrip("0").rstrip(".")
    except Exception:
        return str(v)


def _format_dms(values) -> Optional[str]:
    """
    IFC хранит широту/долготу как список:
    [degrees, minutes, seconds, millionths_of_second]
    """
    try:
        vals = list(values)
    except Exception:
        return None

    if not vals:
        return None

    try:
        deg = vals[0] if len(vals) > 0 else 0
        minute = vals[1] if len(vals) > 1 else 0
        second = vals[2] if len(vals) > 2 else 0
        frac = vals[3] if len(vals) > 3 else 0

        sec_total = float(second)
        if frac:
            sec_total += float(frac) / 1_000_000.0

        return f"{deg}° {minute}' {sec_total:.3f}\""
    except Exception:
        try:
            return ".".join(map(str, vals))
        except Exception:
            return None


def _get_map_conversion(model):
    """
    Возвращает первый IfcMapConversion, если он есть.
    """
    try:
        conversions = model.by_type("IfcMapConversion")
        if conversions:
            return conversions[0]
    except Exception:
        pass
    return None

def get_ifc_elements_count(model) -> str:
    """
    Возвращает количество физических элементов в IFC-модели.
    Считаем IfcElement — стены, перекрытия, двери, окна, инженерные элементы и т.п.
    """
    try:
        return str(len(model.by_type("IfcElement")))
    except Exception:
        return "—"
    
def get_ifc_storey_names(model) -> list[str]:
    """
    Возвращает список уровней IfcBuildingStorey.

    Для каждого уровня выводятся:
    - Name;
    - LongName;
    - Elevation — отметка уровня.

    Пример:
    1_этаж_основной / Первый этаж — отметка: +0.000
    """

    result: list[str] = []

    try:
        storeys = model.by_type("IfcBuildingStorey")
    except Exception:
        return result

    for storey in storeys:
        try:
            name_value = getattr(storey, "Name", None)
            long_name_value = getattr(storey, "LongName", None)
            elevation_value = getattr(storey, "Elevation", None)

            name = str(name_value).strip() if name_value else ""
            long_name = str(long_name_value).strip() if long_name_value else ""

            # Формируем основное название уровня
            if name and long_name and name != long_name:
                level_title = f"{name} / {long_name}"
            elif name:
                level_title = name
            elif long_name:
                level_title = long_name
            else:
                level_title = "Уровень без имени"

            # Формируем отметку уровня
            if elevation_value is not None:
                try:
                    elevation_number = float(elevation_value)
                    elevation_text = f"{elevation_number:+.3f}"
                except (TypeError, ValueError):
                    elevation_text = str(elevation_value).strip() or "не задана"
            else:
                elevation_text = "не задана"

            result.append(
                f"{level_title} — отметка: {elevation_text}"
            )

        except Exception:
            continue

    return result

def get_ifc_site_data(model) -> Dict[str, Optional[str]]:
    """
    Возвращает данные площадки:
    - site_name
    - x, y, z
    - lat, lon

    Global X/Y/Z:
    1. в первую очередь IfcMapConversion (Eastings/Northings/OrthogonalHeight)
    2. если его нет — из IfcSite.ObjectPlacement.RelativePlacement.Location
    """
    result = {
        "site_name": None,
        "x": None,
        "y": None,
        "z": None,
        "lat": None,
        "lon": None,
    }

    # ---- IfcMapConversion ----
    map_conv = _get_map_conversion(model)
    if map_conv is not None:
        try:
            result["x"] = _fmt_num(getattr(map_conv, "Eastings", None))
        except Exception:
            pass
        try:
            result["y"] = _fmt_num(getattr(map_conv, "Northings", None))
        except Exception:
            pass
        try:
            result["z"] = _fmt_num(getattr(map_conv, "OrthogonalHeight", None))
        except Exception:
            pass

    # ---- IfcSite ----
    try:
        sites = model.by_type("IfcSite")
    except Exception:
        sites = []

    if not sites:
        return result

    site = sites[0]

    # ---- имя ----
    try:
        long_name = getattr(site, "LongName", None)
        if long_name:
            result["site_name"] = str(long_name).strip()
        else:
            name = getattr(site, "Name", None)
            if name:
                result["site_name"] = str(name).strip()
    except Exception:
        pass

    # ---- координаты из placement, если MapConversion не дал значений ----
    if result["x"] is None or result["y"] is None or result["z"] is None:
        try:
            placement = site.ObjectPlacement
            if placement and placement.RelativePlacement and placement.RelativePlacement.Location:
                coords = getattr(placement.RelativePlacement.Location, "Coordinates", None)
                if coords:
                    if result["x"] is None and len(coords) > 0:
                        result["x"] = _fmt_num(coords[0])
                    if result["y"] is None and len(coords) > 1:
                        result["y"] = _fmt_num(coords[1])
                    if result["z"] is None and len(coords) > 2:
                        result["z"] = _fmt_num(coords[2])
        except Exception:
            pass

    # ---- география ----
    try:
        ref_lat = getattr(site, "RefLatitude", None)
        if ref_lat:
            result["lat"] = _format_dms(ref_lat)
    except Exception:
        pass

    try:
        ref_lon = getattr(site, "RefLongitude", None)
        if ref_lon:
            result["lon"] = _format_dms(ref_lon)
    except Exception:
        pass

    return result


# ---------------------- percent from HTML (Summary) -----------------
_percent_num_re = re.compile(r'(\d{1,3})\s*%')
_percent_style_re = re.compile(r'width\s*:\s*(\d{1,3})\s*%')
_requirements_re = re.compile(
    r'Requirements\s+passed\s*:\s*<strong>\s*(\d+)\s*</strong>\s*/\s*<strong>\s*(\d+)\s*</strong>',
    flags=re.IGNORECASE | re.DOTALL
)

def _percent_from_html(html_path: Path) -> Optional[float]:
    """
    Извлекает процент из блока Summary отчёта IfcTester.
    Возвращает число [0..100] или None.
    Работает без зависимостей (regex); если есть bs4 — используем её для надёжности.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    if HAVE_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")
            h2 = soup.find(lambda tag: tag.name in ("h2", "h3") and tag.get_text(strip=True).lower() == "summary")
            container = h2.find_next("div") if h2 else soup
            percent_div = container.find("div", class_=lambda c: c and "percent" in c) if container else None
            if percent_div:
                m = _percent_num_re.search(percent_div.get_text(" ", strip=True))
                if m:
                    return float(m.group(1))
                style = percent_div.get("style", "")
                m2 = _percent_style_re.search(style)
                if m2:
                    return float(m2.group(1))
        except Exception:
            pass

    idx = text.lower().find("summary")
    sniff = text[idx: idx + 5000] if idx != -1 else text

    m = re.search(
        r'<div[^>]*class="[^"]*\bpercent\b[^"]*"[^>]*>(.*?)</div>',
        sniff,
        flags=re.IGNORECASE | re.DOTALL
    )
    if m:
        inner = m.group(1)
        mnum = _percent_num_re.search(inner)
        if mnum:
            return float(mnum.group(1))
        mstyle = _percent_style_re.search(m.group(0))
        if mstyle:
            return float(mstyle.group(1))

    m_all = re.search(
        r'<div[^>]*class="[^"]*\bpercent\b[^"]*"[^>]*>(.*?)</div>',
        text,
        flags=re.IGNORECASE | re.DOTALL
    )
    if m_all:
        inner = m_all.group(1)
        mnum = _percent_num_re.search(inner)
        if mnum:
            return float(mnum.group(1))
        mstyle = _percent_style_re.search(m_all.group(0))
        if mstyle:
            return float(mstyle.group(1))

    return None

def _ifc_class_percent_from_html(html_path: Path, ifc_class: str) -> Optional[str]:
    """
    Ищет в HTML блок спецификации, где в Applicability есть:
    All IfcBuilding data / All IfcSite data / All IfcBuildingStorey data

    Возвращает процент из этого блока, например '100%'.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    target = f"All {ifc_class} data".lower()

    if HAVE_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")

            sections = soup.find_all("section", class_=lambda c: c and "specification" in c)

            for section in sections:
                section_text = section.get_text(" ", strip=True).lower()

                if target not in section_text:
                    continue

                percent_div = section.find("div", class_=lambda c: c and "percent" in c)
                if percent_div:
                    percent_text = percent_div.get_text(" ", strip=True)
                    m = _percent_num_re.search(percent_text)
                    if m:
                        return f"{m.group(1)}%"

            return None
        except Exception:
            pass

    # fallback без BeautifulSoup
    section_iter = re.finditer(
        r'<section[^>]*class="[^"]*\bspecification\b[^"]*"[^>]*>',
        text,
        flags=re.IGNORECASE
    )

    starts = [m.start() for m in section_iter]
    starts.append(len(text))

    for i in range(len(starts) - 1):
        fragment = text[starts[i]:starts[i + 1]]

        plain = re.sub(r"<.*?>", " ", fragment)
        plain = re.sub(r"\s+", " ", plain).strip().lower()

        if target not in plain:
            continue

        percent_match = re.search(
            r'<div[^>]*class="[^"]*\bpercent\b[^"]*"[^>]*>\s*(\d{1,3})\s*%\s*</div>',
            fragment,
            flags=re.IGNORECASE | re.DOTALL
        )

        if percent_match:
            return f"{percent_match.group(1)}%"

    return None


def ifc_class_percentages_from_html(html_path: Path):
    """Read and parse a report once for all three spatial IFC metrics."""
    classes = {"site_building_pct": "IfcSite", "building_pct": "IfcBuilding", "storey_pct": "IfcBuildingStorey"}
    values = {key: None for key in classes}
    try:
        text = Path(html_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return values
    if HAVE_BS4:
        soup = BeautifulSoup(text, "html.parser")
        for section in soup.select("section.specification"):
            plain = section.get_text(" ", strip=True).lower()
            percent = section.select_one("div.percent")
            match = _percent_num_re.search(percent.get_text(" ", strip=True)) if percent else None
            if match:
                for key, name in classes.items():
                    if values[key] is None and f"all {name} data".lower() in plain:
                        values[key] = f"{match.group(1)}%"
        return values
    # The application already needs bs4 for postprocessing; retain legacy fallback.
    return {key: _ifc_class_percent_from_html(html_path, name) for key, name in classes.items()}


# ---------------------------- CLI helper ----------------------------
def _run_ifctester_cli(ids_path: str, ifc_path: str, report: str, out_dir: Path, output_path=None) -> None:
    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "CLI-запуск ifctester отключён в exe-сборке. "
            "Используется только встроенный reporter ifctester."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    args = [sys.executable, "-m", "ifctester", ids_path, ifc_path, "-r", report]
    if output_path is not None:
        args.extend(["-o", str(Path(output_path).resolve())])

    completed = subprocess.run(
        args,
        cwd=str(out_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8"
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"ifctester {report} failed (code {completed.returncode}).\n{completed.stdout}"
        )


# ----------------------------- reports ------------------------------
def emit_reports(
    specs,
    out_base: Path,
    ids_path: str,
    ifc_path: str,
    mapping_path: str | None = None,
    remove_empty_ifc_classes: bool = False,
) -> Tuple[Path, Optional[float]]:
    """
    Генерирует HTML-отчёт для переданных specs.
    out_base: базовый путь без расширения.
    mapping_path: путь к txt-файлу сопоставления параметров.
    """
    out_base = Path(out_base)
    out_dir = out_base.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    target_html = out_base.with_name(out_base.name + ".html")

    try:
        if target_html.exists():
            target_html.unlink()
    except Exception:
        pass

    html_ok = False

    if HAVE_REPORTER:
        try:
            h = reporter.Html(specs)
            h.report()
            h.to_file(str(target_html))
            html_ok = target_html.exists()
        except Exception:
            html_ok = False

    if not html_ok:
        try:
            _run_ifctester_cli(ids_path, ifc_path, "Html", out_dir, output_path=target_html)
            html_ok = target_html.exists()
        except Exception:
            html_ok = False

    if html_ok and target_html.exists():
        try:
            postprocess_html_report(
                target_html,
                mapping_path=mapping_path,
                remove_empty_ifc_classes=remove_empty_ifc_classes,
                validation_specs=specs,
            )
        except Exception as e:
            print(f"[POSTPROCESS ERROR] {target_html}: {e}")

    percent = _percent_from_html(target_html) if html_ok else None
    if not html_ok or not target_html.exists():
        raise RuntimeError(f"Не удалось создать HTML-отчёт: {target_html}")
    return target_html, percent


# ------------------------ parallel model checks ---------------------
_WORKER_EVENTS = None
_WORKER_STOP = None
_IDS_TEMPLATES = {}


def available_cpu_count():
    count = getattr(os, "process_cpu_count", os.cpu_count)()
    return max(1, count or 1)


def model_worker_count(requested, total):
    count = available_cpu_count() if not requested else max(1, int(requested))
    # ProcessPoolExecutor has a documented Windows limit of 61 processes.
    if os.name == "nt":
        count = min(count, 61)
    return max(1, min(count, max(1, total)))


def initialize_model_worker(events, stop):
    global _WORKER_EVENTS, _WORKER_STOP
    _WORKER_EVENTS, _WORKER_STOP = events, stop
    _IDS_TEMPLATES.clear()


def _fresh_ids(path):
    source = Path(path)
    stamp = source.stat()
    key = (str(source.resolve()), stamp.st_mtime_ns, stamp.st_size)
    template = _IDS_TEMPLATES.get(key)
    if template is None:
        template = open_ids(path)
        _IDS_TEMPLATES[key] = template
    # Validated specs hold model entities; only cache unvalidated templates.
    return deepcopy(template)


def check_model_task(task, stop=None, notify=None):
    """One IFC model and its own IDS objects, entirely outside Tkinter."""
    stop = stop if stop is not None else _WORKER_STOP
    def stopped():
        return stop is not None and stop.is_set()
    def send(kind, value):
        event = (task["index"], kind, value)
        if notify is not None:
            notify(event)
        elif _WORKER_EVENTS is not None:
            _WORKER_EVENTS.put(event)
    if stopped():
        return None
    started = time.perf_counter()
    path = Path(task["ifc_path"])
    name = path.name
    root = Path(task["reports_dir"])
    use_discipline = task["discipline_enabled"]
    item = {
        "model": name, "common_ids": task["common_ids"],
        "common_ids_fingerprint": task.get("common_signature", ""),
        "disc_ids": "", "common_status": "error",
        "disc_status": "not_run" if use_discipline else "disabled",
        "revit_name": task.get("revit_name", ""), "site_name": None,
        "x": None, "y": None, "z": None, "lat": None, "lon": None,
        "site_building_pct": None, "building_pct": None, "storey_pct": None,
        "qty": None, "dir_root": root, "common": None, "common_pct": None,
        "disc": None, "disc_pct": None, "disc_code": None, "storey_names": [],
    }
    try:
        send("status", f"Открытие IFC: {name}")
        model = open_ifc(str(path))
        if stopped():
            return None
        item.update(get_ifc_site_data(model))
        item["qty"] = get_ifc_elements_count(model)
        item["storey_names"] = get_ifc_storey_names(model)
        if stopped():
            return None
        passes = [("common", task["common_ids"], "Общие", None)]
        rule = task.get("discipline_rule")
        if use_discipline and rule:
            item["disc_ids"] = rule["ids_path"]
            item["disc_ids_fingerprint"] = task.get("discipline_signature", "")
            passes.append(("disc", rule["ids_path"], "Дисциплинарные", rule.get("mapping_path")))
        for key, ids_path, subdir, mapping in passes:
            if stopped():
                break
            label = "Общая IDS" if key == "common" else "Дисциплина"
            item[key+"_status"] = "error"
            try:
                send("status", f"{label}: {name}")
                specs = _fresh_ids(ids_path)
                specs.validate(model)
                # Complete the report of a finished validation even after Stop.
                html, percent = emit_reports(specs, root / subdir / path.stem,
                    ids_path, str(path), mapping_path=mapping,
                    remove_empty_ifc_classes=task.get("remove_empty_ifc_classes", False))
                item[key], item[key+"_pct"] = html, percent
                item[key+"_status"] = "result" if percent is not None else "no_result"
                if key == "disc":
                    item["disc_code"] = ""
                metrics = ifc_class_percentages_from_html(html)
                for metric, value in metrics.items():
                    if key == "common" or value is not None:
                        item[metric] = value
                send("log", f"✅ {label}: {html}")
                send("report", str(html))
            except Exception as error:
                send("log", f"❌ Ошибка {label}: {name}: {error}")
        if use_discipline and not rule and not stopped():
            item["disc_status"] = "no_rule"
            send("log", f"🟡 Правило дисциплины не найдено — выполнена только общая проверка: {name}")
    except Exception as error:
        send("log", f"❌ Ошибка обработки IFC: {name}: {error}")
    item["checked_at"] = datetime.now().astimezone().isoformat(timespec="microseconds")
    item["elapsed_seconds"] = round(time.perf_counter()-started, 3)
    item["worker_pid"] = os.getpid()
    return item


def run_model_batch(tasks, requested_workers, stop, on_event, on_result):
    """Rolling submission; only the coordinator handles shared state and events."""
    tasks = list(tasks)
    if not tasks:
        return []
    outputs = set()
    for task in tasks:
        key = (str(Path(task["reports_dir"]).resolve()).casefold(), Path(task["ifc_path"]).stem.casefold())
        if key in outputs:
            raise ValueError(f"Совпадают имена отчётов IFC: {task['ifc_path']}")
        outputs.add(key)
    workers = model_worker_count(requested_workers, len(tasks))
    items = {}
    def accept(task, item):
        if item is not None:
            items[task["index"]] = item
            on_result(task["index"], item)
    if workers == 1:
        _IDS_TEMPLATES.clear()
        for task in tasks:
            if stop.is_set():
                break
            accept(task, check_model_task(task, stop=stop, notify=on_event))
        _IDS_TEMPLATES.clear()
        return [items[index] for index in sorted(items)]
    context = multiprocessing.get_context("spawn")
    events, shared_stop = context.Queue(), context.Event()
    executor = None
    aborted = False
    def drain():
        while True:
            try:
                on_event(events.get_nowait())
            except queue.Empty:
                return
    try:
        executor = ProcessPoolExecutor(max_workers=workers, mp_context=context,
            initializer=initialize_model_worker, initargs=(events, shared_stop))
        pending = {}
        iterator = iter(tasks)
        def submit_next():
            if stop.is_set() or aborted:
                shared_stop.set()
                return
            task = next(iterator, None)
            if task is not None:
                pending[executor.submit(check_model_task, task)] = task
        for _ in range(workers):
            submit_next()
        while pending:
            if stop.is_set() or aborted:
                shared_stop.set()
                for future in pending:
                    future.cancel()
            done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            drain()
            for future in done:
                task = pending.pop(future)
                if not future.cancelled():
                    try:
                        item = future.result()
                    except Exception as error:
                        on_event((task["index"], "log", f"❌ Исполнитель завершился с ошибкой: {task['ifc_path']}: {error}"))
                        # Retain other completed results; stop further submissions.
                        aborted = True
                        shared_stop.set()
                        item = None
                    accept(task, item)
                submit_next()
        return [items[index] for index in sorted(items)]
    finally:
        shared_stop.set()
        if executor is not None:
            # Keep draining IPC while workers flush their queue and shut down.
            # Otherwise a full pipe can deadlock shutdown on large batches.
            shutdown_done = threading.Event()
            shutdown_errors = []
            def shutdown_pool():
                try:
                    executor.shutdown(wait=True, cancel_futures=True)
                except Exception as error:
                    shutdown_errors.append(error)
                finally:
                    shutdown_done.set()
            threading.Thread(target=shutdown_pool, daemon=True).start()
            while not shutdown_done.wait(0.05):
                drain()
        drain()
        events.close()
        events.join_thread()
        if executor is not None and shutdown_errors:
            raise shutdown_errors[0]
