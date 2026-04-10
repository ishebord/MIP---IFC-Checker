# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, Tuple, Optional, List

import ifcopenshell
from ifctester import ids as ids_mod

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
            return r, (r.get("code") or "disc")
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


def _requirements_passed_from_html(html_path: Path) -> Optional[str]:
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    total = 0

    if HAVE_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")
            spans = soup.find_all("span", class_="item")

            for span in spans:
                span_text = span.get_text(" ", strip=True).lower()
                if "elements passed" not in span_text:
                    continue

                strong = span.find_all("strong")
                if len(strong) >= 2:
                    b = strong[1].get_text(strip=True)
                    if b.isdigit():
                        total += int(b)

            return str(total)
        except Exception:
            pass

    pattern = re.compile(
        r'Elements\s+passed:\s*<strong>\s*\d+\s*</strong>\s*/\s*<strong>\s*(\d+)\s*</strong>',
        re.IGNORECASE
    )

    matches = pattern.findall(text)
    if matches:
        total = sum(int(x) for x in matches)
        return str(total)

    return None


def _named_block_percent_from_html(html_path: Path, title_part: str) -> Optional[str]:
    """
    Ищет в HTML блок <div class="info">, внутри которого заголовок h2
    содержит title_part, и возвращает процент из блока percent, например '87%'.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    if HAVE_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")
            info_blocks = soup.find_all("div", class_=lambda c: c and "info" in c)

            for block in info_blocks:
                h2 = block.find("h2")
                if not h2:
                    continue

                h2_text = h2.get_text(" ", strip=True)
                if title_part.lower() not in h2_text.lower():
                    continue

                percent_div = block.find("div", class_=lambda c: c and "percent" in c)
                if percent_div:
                    percent_text = percent_div.get_text(" ", strip=True)
                    m = _percent_num_re.search(percent_text)
                    if m:
                        return f"{m.group(1)}%"
            return None
        except Exception:
            pass

    info_iter = re.finditer(
        r'<div[^>]*class="[^"]*\binfo\b[^"]*"[^>]*>',
        text,
        flags=re.IGNORECASE
    )

    for m_info in info_iter:
        start = m_info.start()
        fragment = text[start:start + 5000]

        h2_match = re.search(r'<h2[^>]*>(.*?)</h2>', fragment, flags=re.IGNORECASE | re.DOTALL)
        if not h2_match:
            continue

        h2_text = re.sub(r"<.*?>", "", h2_match.group(1)).strip()
        if title_part.lower() not in h2_text.lower():
            continue

        percent_match = re.search(
            r'<div[^>]*class="[^"]*\bpercent\b[^"]*"[^>]*>\s*(\d{1,3})\s*%\s*</div>',
            fragment,
            flags=re.IGNORECASE | re.DOTALL
        )
        if percent_match:
            return f"{percent_match.group(1)}%"

    return None


# ---------------------------- CLI helper ----------------------------
def _run_ifctester_cli(ids_path: str, ifc_path: str, report: str, out_dir: Path) -> None:
    """
    Запуск ifctester через CLI без -o, с cwd=out_dir (устраняет проблемы путей/кириллицы).
    Создаёт {stem}.html/.json в out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-m", "ifctester", ids_path, ifc_path, "-r", report]
    completed = subprocess.run(
        args,
        cwd=str(out_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ifctester {report} failed (code {completed.returncode}).\n{completed.stdout}")


# ----------------------------- reports ------------------------------
def emit_reports(specs, out_base: Path, ids_path: str, ifc_path: str) -> Tuple[Path, Path, Optional[float]]:
    """
    Генерирует HTML и JSON для переданных specs.
    out_base: базовый путь без расширения (например: .../МССК/<stem>
              или .../Дисциплинарные/<stem>.__КОД)
    Возвращает: (html_path, json_path, percent) — percent берём из HTML Summary.
    """
    out_base = Path(out_base)
    out_dir = out_base.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    target_html = out_base.with_suffix(".html")
    target_json = out_base.with_suffix(".json")

    for p in (target_html, target_json):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    html_ok = False
    json_ok = False
    if HAVE_REPORTER:
        try:
            h = reporter.Html(specs)
            h.report()
            h.to_file(str(target_html))
            html_ok = target_html.exists()
        except Exception:
            html_ok = False

        try:
            j = reporter.Json(specs)
            j.report()
            j.to_file(str(target_json))
            json_ok = target_json.exists()
        except Exception:
            json_ok = False

    if not html_ok:
        try:
            stem = Path(ifc_path).stem
            tmp_html = out_dir / f"{stem}.html"
            if tmp_html.exists():
                tmp_html.unlink()
            _run_ifctester_cli(ids_path, ifc_path, "Html", out_dir)
            if tmp_html.exists():
                tmp_html.replace(target_html)
                html_ok = target_html.exists()
        except Exception:
            html_ok = False

    if not json_ok:
        try:
            stem = Path(ifc_path).stem
            tmp_json = out_dir / f"{stem}.json"
            if tmp_json.exists():
                tmp_json.unlink()
            _run_ifctester_cli(ids_path, ifc_path, "Json", out_dir)
            if tmp_json.exists():
                tmp_json.replace(target_json)
                json_ok = target_json.exists()
        except Exception:
            json_ok = False

    percent = _percent_from_html(target_html) if html_ok else None
    return target_html, target_json, percent