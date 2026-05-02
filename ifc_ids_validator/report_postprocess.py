# report_postprocess.py
from __future__ import annotations

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
    r"ВН НН .*": "Введите значение, начинающееся с ВН НН, например: ВН НН жилое здание",
    r"воздух|аргон|криптон": "Введите одно из значений: воздух, аргон, криптон",
    r"Е|П": "Введите одно из значений: Е, П",
    r"НД .*": "Введите значение, начинающееся с НД, например: НД 01",
    r"НД .*|ПЗ .*": "Введите значение, начинающееся с НД или ПЗ",
    r"ПЗ .*": "Введите значение, начинающееся с ПЗ, например: ПЗ 01",
    r"СТ .*": "Введите код, начинающийся с СТ, например: СТ 00 10",
    r"Ф.*": "Введите значение, начинающееся с Ф, например: Ф100",
    r"ЭЛ .*": "Введите код, начинающийся с ЭЛ, например: ЭЛ 30 10 40",
    r"B.*": "Введите значение, начинающееся с B, например: B25",
    r"F.*": "Введите значение, начинающееся с F, например: F100",
    r"W\d{1,2}": "Введите значение W и 1–2 цифры, например: W6 или W12",
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

def replace_pattern_block(value: str) -> str:
    """
    Преобразует {'pattern': '...'} в человекочитаемый текст
    """
    match = re.search(r"\{\s*'pattern'\s*:\s*'(.+?)'\s*\}", value)

    if not match:
        return value

    pattern = match.group(1)

    description = PATTERN_DESCRIPTIONS.get(pattern)

    if description:
        return f"Шаблон: {description}"
    else:
        return f"Шаблон: {pattern}"

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
        flags=re.IGNORECASE,
    )

    if match:
        param = match.group("param")
        value = match.group("value")

        # 🔥 обработка pattern
        if "pattern" in value:
            value = replace_pattern_block(value)
        elif value == "provided":
            value = "заполнено"
            
        dataset = match.group("dataset")

        if value == "provided":
            value = "заполнено"

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

    return f"Параметр {result}".strip()


def postprocess_html_report(
    html_path: str | Path,
    output_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
) -> Path:
    html_path = Path(html_path)
    output_path = Path(output_path) if output_path else html_path

    mapping = get_mge_mapping(mapping_path)

    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    for summary in soup.find_all("summary"):
        old_text = summary.get_text(" ", strip=True)
        new_text = translate_summary_text(old_text, mapping)

        if new_text != old_text:
            summary.clear()
            summary.append(new_text)

    output_path.write_text(str(soup), encoding="utf-8")
    return output_path