# report_postprocess.py
from __future__ import annotations

import json
import re
from pathlib import Path

import chardet
from bs4 import BeautifulSoup


_MGE_MAPPING_CACHE: dict[str, dict[str, str]] = {}

PATTERN_DESCRIPTIONS = {
    r"(?:А|Б|В1|В2|В3|В4|Г|Д)": "Введите одно из значений: А, Б, В1, В2, В3, В4, Г, Д",
    r"(?:Г1|Г2|Г3|Г4|НГ)": "Введите одно из значений: Г1, Г2, Г3, Г4, НГ",
    r"(?:НН|ПН|ЛО)": "Введите одно из значений: НН, ПН, ЛО",
    r"(?:С0|С1|С2|С3)": "Введите одно из значений: С0, С1, С2, С3",
    r"(?:свая-стойка|висячая)": "Введите одно из значений: свая-стойка, висячая",
    r"(?:I|II|III|IV|V|IIIа|IIIб|IVа)": "Введите одно из значений: I, II, III, IV, V, IIIа, IIIб, IVа",
    r"(?:R|E|RE|REI)\s\d{2,3}": "Введите значение в формате: R 60, E 90, RE 120 или REI 150",
    r"(?:R|E|RE|REI|EI)\s\d{2,3}": "Введите значение в формате: R 60, E 90, RE 120, REI 150 или EI 60",
    r"(НН|ПН|ЛО)": "Введите одно из значений: НН, ПН, ЛО",
    r"^(I|II|III|IV|VIII|IIa|IIIa|IVa)$": "Введите одно из значений: I, II, III, IV, VIII, IIa, IIIa, IVa",
    r"А\d{3}.*": "Введите значение, начинающееся с А и трех цифр, например: А500",
    r"ВН НН .*": "Введите значение, начинающееся с ВН НН",
    r"воздух|аргон|криптон": "Введите одно из значений: воздух, аргон, криптон",
    r"Е|П": "Введите одно из значений: Е, П",
    r"НД .*": "Введите значение, начинающееся с НД",
    r"НД .*|ПЗ .*": "Введите значение, начинающееся с НД или ПЗ",
    r"ПЗ .*": "Введите значение, начинающееся с ПЗ",
    r"СТ .*": "Введите код, начинающийся с СТ",
    r"Ф.*": "Введите значение, начинающееся с Ф",
    r"ЭЛ .*": "Введите код, начинающийся с ЭЛ",
    r"B.*": "Введите значение, начинающееся с B",
    r"F.*": "Введите значение, начинающееся с F",
    r"W\d{1,2}": "Введите значение W и 1–2 цифры",
}


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    result = chardet.detect(raw)
    encoding = result.get("encoding") or "utf-8"
    return raw.decode(encoding, errors="ignore")


def load_mge_mapping(path: str | Path) -> dict[str, str]:
    path = Path(path)

    if not path.exists():
        return {}

    text = read_text_auto(path)
    mapping: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")

        if not line.strip():
            continue

        if line.lstrip().startswith("#"):
            continue

        if line.lstrip().startswith("PropertySet:"):
            continue

        parts = [p.strip() for p in line.split("\t")]

        if len(parts) >= 4 and parts[0] == "":
            old_param = parts[1]
            new_param = parts[3]
        elif len(parts) >= 3:
            old_param = parts[0]
            new_param = parts[2]
        else:
            continue

        if old_param and new_param:
            mapping[old_param] = new_param

    return mapping


def get_mge_mapping(mapping_path: str | Path | None) -> dict[str, str]:
    if not mapping_path:
        return {}

    key = str(Path(mapping_path))

    if key not in _MGE_MAPPING_CACHE:
        _MGE_MAPPING_CACHE[key] = load_mge_mapping(key)

    return _MGE_MAPPING_CACHE[key]


def replace_value_block(value: str) -> str:
    """
    Преобразует:
    {'pattern': '...'}
    {'minLength': 2}
    {'enumeration': [...]}
    в человекочитаемый текст.
    """

    # {'pattern': '...'}
    m = re.search(
        r"\{\s*'pattern'\s*:\s*'(.+?)'\s*\}",
        value,
        flags=re.DOTALL,
    )
    if m:
        pattern = m.group(1)
        description = PATTERN_DESCRIPTIONS.get(pattern)
        return f"Шаблон: {description or pattern}"

    # {'minLength': 2}
    m = re.search(
        r"\{\s*'minLength'\s*:\s*(\d+)\s*\}",
        value,
        flags=re.DOTALL,
    )
    if m:
        return f"Минимальная длина - {m.group(1)}"

    # {'enumeration': ['...', '...']}
    m = re.search(
        r"\{\s*'enumeration'\s*:\s*\[(.*?)\]\s*\}",
        value,
        flags=re.DOTALL,
    )
    if m:
        values = re.findall(r"'([^']+)'", m.group(1))

        if values:
            return "Список: " + ", ".join(values)

        return "Список"

    return value


def translate_summary_text(text: str, mapping: dict[str, str]) -> str:
    text = " ".join(text.split())

    if text.lower().startswith("параметр "):
        text = text[len("Параметр "):].strip()

    parts = text.split(maxsplit=1)

    if parts:
        old_param = parts[0]
        new_param = mapping.get(old_param, old_param)
        text = f"{new_param} {parts[1]}" if len(parts) > 1 else new_param

    match = re.match(
        r"^(?P<param>.+?)\s+data shall be\s+(?P<value>\{.*?\}|provided)\s+and in the dataset\s+(?P<dataset>\S+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if match:
        param = match.group("param")
        value = match.group("value")
        dataset = match.group("dataset")

        if value == "provided":
            value = "заполнено"
        else:
            value = replace_value_block(value)

        return (
            f"Параметр {param} должен соответствовать значению {value} "
            f"и находиться в наборе данных {dataset}"
        )

    result = text

    replacements = [
        (r"\bdata shall be\b", "должен соответствовать значению"),
        (r"\band in the dataset\b", "и находиться в наборе данных"),
        (r"\bin the dataset\b", "в наборе данных"),
        (r"\bshall be\b", "должен быть"),
        (r"\bThe\b", ""),
    ]

    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    result = replace_value_block(result)

    return f"Параметр {result}".strip()


def _unique_tags(values):
    """Use IFC Tag only; never substitute STEP ids, names or GlobalId."""
    tags, seen = [], set()
    missing = 0
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text or text.casefold() in {"none", "null", "n/a", "$", "—", "-"}:
            missing += 1
            continue
        if text not in seen:
            seen.add(text)
            tags.append(text)
    return tags, missing


def _tags_from_requirement(requirement):
    failures = getattr(requirement, "failures", None)
    if failures is None:
        return None
    values = []
    for failure in failures:
        element = failure.get("element") if isinstance(failure, dict) else getattr(failure, "element", None)
        values.append(getattr(element, "Tag", None) if element is not None else None)
    tags, missing = _unique_tags(values)
    return {"tags": tags, "missing": missing, "complete": True}


def _tags_from_tables(details):
    values = []
    complete = True
    for table in details.select("table.fail"):
        headers = [cell.get_text(" ", strip=True).casefold() for cell in table.select("thead th")]
        if "tag" not in headers:
            continue
        column = headers.index("tag")
        body = table.find("tbody") or table
        for row in body.find_all("tr", recursive=False):
            cells = row.find_all("td", recursive=False)
            if any(int(cell.get("colspan", 1)) > 1 for cell in cells):
                complete = False
                continue
            if len(cells) > column:
                values.append(cells[column].get_text(" ", strip=True))
    tags, missing = _unique_tags(values)
    return {"tags": tags, "missing": missing, "complete": complete}


def _add_copy_tag_controls(soup, validation_specs=None):
    specifications = list(getattr(validation_specs, "specifications", []) or [])
    for spec_index, section in enumerate(soup.select("section.specification")):
        spec = specifications[spec_index] if spec_index < len(specifications) else None
        heading = section.find("h2")
        # Check the specification name as well as its position before using model data.
        if spec is not None and (heading is None or re.sub(r"^\d+[.)]\s*", "", heading.get_text(" ", strip=True)) != str(spec.name).strip()):
            spec = None
        rules = list(getattr(spec, "requirements", []) or [])
        results = section.find("div", class_="results")
        requirements = results.find("ol", recursive=False) if results else None
        if requirements is None:
            continue
        for rule_index, item in enumerate(requirements.find_all("li", recursive=False)):
            details = item.find("details", recursive=False)
            if details is None or "fail" not in item.get("class", []):
                continue
            summary = details.find("summary", recursive=False)
            if summary is None:
                continue
            data = _tags_from_requirement(rules[rule_index]) if rule_index < len(rules) else None
            if data is None:
                # Retain complete embedded lists when reprocessing an existing report.
                try:
                    data = json.loads(details.get("data-ifc-failed-tags", "null"))
                except (ValueError, TypeError):
                    data = None
            if not isinstance(data, dict) or not isinstance(data.get("tags"), list):
                data = _tags_from_tables(details)
            details["data-ifc-failed-tags"] = json.dumps(data, ensure_ascii=False)
            classes = list(summary.get("class", []))
            if "ifc-copy-summary" not in classes:
                classes.append("ifc-copy-summary")
            summary["class"] = classes
            label = soup.new_tag("span", attrs={"class": "ifc-copy-label"})
            for child in list(summary.contents):
                label.append(child.extract())
            summary.append(label)
            actions = soup.new_tag("span", attrs={"class": "ifc-copy-actions"})
            button = soup.new_tag("button", attrs={"type": "button", "class": "ifc-copy-tags"})
            count = len(data["tags"])
            button.string = f"Копировать ID ({count})" if count else "Нет Tag для копирования"
            if not data.get("complete"):
                button.string = f"Копировать ID ({count}, видимые)" if count else "Нет Tag для копирования"
            button["title"] = "Скопировать Tag элементов этой проверки через ;, без повторов."
            if not count:
                button["disabled"] = ""
            note = "Часть элементов скрыта" if not data.get("complete") else ""
            if data.get("missing"):
                note += (" · " if note else "") + f"Без Tag: {data['missing']}"
            status = soup.new_tag("span", attrs={"class": "ifc-copy-status", "role": "status", "aria-live": "polite"})
            status.string = note
            status["data-idle-text"] = note
            actions.extend([button, status])
            summary.append(actions)
    if not soup.select(".ifc-copy-tags"):
        return
    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        soup.insert(0, head)
    for identifier in ("ifc-copy-tags-style", "ifc-copy-tags-script"):
        previous = soup.find(id=identifier)
        if previous:
            previous.decompose()
    style = soup.new_tag("style", id="ifc-copy-tags-style")
    style.string = _COPY_TAGS_CSS
    head.append(style)
    script = soup.new_tag("script", id="ifc-copy-tags-script")
    script.string = _COPY_TAGS_JS
    (soup.body or soup).append(script)


_COPY_TAGS_CSS = r'''
.ifc-copy-summary{display:flex;flex-wrap:wrap;align-items:flex-start;gap:10px}
.ifc-copy-label{flex:1 1 280px;min-width:0;overflow-wrap:anywhere}
.ifc-copy-actions{display:flex;flex-direction:column;align-items:flex-start;gap:4px;flex:0 1 auto}
.ifc-copy-tags{font:600 12px Arial,sans-serif;line-height:1.4;padding:8px 11px;border:1px solid #aec3e8;border-radius:7px;background:#fff;color:#194fa6;cursor:pointer;white-space:nowrap}
.ifc-copy-tags:hover{background:#edf4ff;border-color:#608cd1}
.ifc-copy-tags:focus-visible{outline:3px solid #548ade;outline-offset:2px}
.ifc-copy-tags:disabled{color:#707781;border-color:#bbb;background:#eee;cursor:default}
.ifc-copy-status{font:11px Arial,sans-serif;line-height:1.5;color:#4b5563;max-width:260px}
.ifc-copy-fallback{padding:12px;margin:10px 0;background:#fff;border:1px solid #b7c8e3;border-radius:8px;color:#172a43;font:13px Arial,sans-serif}
.ifc-copy-fallback textarea{display:block;width:100%;min-height:80px;margin:8px 0;font:13px Consolas,monospace;color:#172a43}
@media print{.ifc-copy-actions,.ifc-copy-fallback{display:none}}
'''


_COPY_TAGS_JS = r'''
(() => {
 'use strict';
 function legacyCopy(text){
  const previous=document.activeElement,scrollX=window.scrollX,scrollY=window.scrollY;
  const input=document.createElement('textarea');input.value=text;input.readOnly=true;
  input.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:0';
  document.body.append(input);input.focus();input.select();input.setSelectionRange(0,text.length);
  let copied=false;
  try{copied=typeof document.execCommand==='function'&&document.execCommand('copy');}catch(error){}
  input.remove();if(previous&&previous.focus)previous.focus({preventScroll:true});window.scrollTo(scrollX,scrollY);
  return copied;
 }
 function manualCopy(details,text){
  let box=details.querySelector('.ifc-copy-fallback');if(box)box.remove();
  box=document.createElement('div');box.className='ifc-copy-fallback';
  const caption=document.createElement('p');caption.textContent='Браузер не разрешил автоматическое копирование. Список выделен: нажмите Ctrl+C (⌘C на Mac).';
  const input=document.createElement('textarea');input.value=text;input.readOnly=true;input.setAttribute('aria-label','Tag элементов через точку с запятой');
  const close=document.createElement('button');close.type='button';close.className='ifc-copy-tags';close.textContent='Закрыть';close.addEventListener('click',()=>box.remove());
  box.append(caption,input,close);details.append(box);details.open=true;input.focus();input.select();
 }
 document.addEventListener('click',async event=>{
  const button=event.target.closest('button.ifc-copy-tags');
  if(!button||!button.closest('summary')||button.disabled)return;
  event.preventDefault();event.stopPropagation();
  const details=button.closest('details'),status=button.parentElement.querySelector('.ifc-copy-status');
  let data;
  try{data=JSON.parse(details.getAttribute('data-ifc-failed-tags'));}catch(error){status.textContent='Не удалось прочитать список Tag.';return;}
  if(!data||!Array.isArray(data.tags)||!data.tags.length)return;
  const text=data.tags.join(';');let copied=false;
  // Synchronous fallback keeps the user gesture when opening an offline HTML file.
  if(navigator.clipboard&&typeof navigator.clipboard.writeText==='function'&&window.isSecureContext!==false){
   try{await navigator.clipboard.writeText(text);copied=true;}catch(error){}
  }
  if(!copied)copied=legacyCopy(text);
  status.textContent=copied?'Скопировано ID: '+data.tags.length:'Скопируйте список вручную.';
  if(!copied)manualCopy(details,text);
 });
})();
'''


def postprocess_html_report(
    html_path: str | Path,
    output_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
    remove_empty_ifc_classes: bool = False,
    validation_specs=None,
) -> Path:
    html_path = Path(html_path)
    output_path = Path(output_path) if output_path else html_path

    mapping = get_mge_mapping(mapping_path)

    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove only our controls before translating, so a second pass is idempotent.
    for actions in soup.select("summary .ifc-copy-actions"):
        actions.decompose()
    for label in soup.select("summary .ifc-copy-label"):
        label.unwrap()
    for summary in soup.find_all("summary"):
        old_text = summary.get_text(" ", strip=True)
        new_text = translate_summary_text(old_text, mapping)

        if new_text != old_text:
            summary.clear()
            summary.append(new_text)

    _add_copy_tag_controls(soup, validation_specs)
    if remove_empty_ifc_classes:
        for section in soup.select("section.specification.is-skipped"):
            section.decompose()

    output_path.write_text(str(soup), encoding="utf-8")
    return output_path
