# config.py
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Any, Optional

APPDATA_DIR = Path(os.getenv("APPDATA", Path.home()))
CONF_DIR = APPDATA_DIR / "IFC_IDS_Validator"
CONF_PATH = CONF_DIR / "config.json"

RULES_64_PATH = CONF_DIR / "rules_64.json"
RULES_178_PATH = CONF_DIR / "rules_178.json"
RULES_CUSTOM_PATH = CONF_DIR / "rules_custom.json"

DEFAULT_SECTIONS_BY_MODE = {
    "Приказ 178": [
        ["БФ", "Базовый координационный файл"],
        ["АР", "Архитектурные решения"],
        ["КР", "Конструктивные решения"],
        ["КЖ", "Конструктивные решения - Конструкции железобетонные"],
        ["КМ", "Конструктивные решения - Конструкции металлические"],
        ["КД", "Конструктивные решения - Конструкции деревянные"],
        ["МА", "Конструктивные решения - Модель армирования"],
        ["ЭС", "Электроснабжение"],
        ["ЭО", "Электрическое освещение (внутреннее)"],
        ["ЭМ", "Силовое электрооборудование"],
        ["ВВ", "Водоснабжение и водоотведение (внутренние)"],
        ["О", "Отопление"],
        ["ВК", "Вентиляция и кондиционирование"],
        ["ТМ", "Тепломеханическая часть (ИТП)"],
        ["ХС", "Холодоснабжение"],
        ["ДУ", "Противодымная защита"],
        ["ПТ", "Система пожаротушения"],
        ["ПС", "Пожарная сигнализация"],
        ["СС", "Сети связи"],
        ["ГСВ", "Газоснабжение (внутреннее)"],
        ["ТХ", "Технологические решения"],
    ],

    "Приказ 64": [
        ["ПЗУ", "Схема планировочной организации земельного участка"],
        ["ГП", "Генеральный план"],
        ["АР", "Объемно-планировочные и архитектурные решения"],
        ["АС", "Архитектурно-строительные решения"],
        ["АИ", "Интерьеры"],
        ["ИД", "Информационный дизайн"],
        ["КР", "Конструктивные решения"],
        ["КЖ", "Конструкции железобетонные"],
        ["КМ", "Конструкции металлические"],
        ["КМД", "Конструкции металлические деталировочные"],
        ["КД", "Конструкции деревянные"],
        ["КДД", "Конструкции деревянные деталировочные"],
        ["ЭС", "Система электроснабжения"],
        ["ЭО", "Электрическое освещение (внутреннее)"],
        ["ЭМ", "Силовое электрооборудование"],
        ["ЭОМ", "Силовое электрооборудование и освещение"],
        ["ЭП", "Электроснабжение подстанции"],
        ["ВК", "Система водоснабжения"],
        ["ВПТ", "Водяное пожаротушение"],
        ["ВПВ", "Противопожарный водопровод"],
        ["АУВПТ", "Автоматическая установка водяного пожаротушения"],
        ["ОВ", "Отопление, вентиляция"],
        ["ОВК", "Отопление, вентиляция и кондиционирование"],
        ["ВС", "Воздухоснабжение"],
        ["ПВ", "Противодымная защита"],
        ["ПУ", "Пылеудаление"],
        ["ХС", "Холодоснабжение"],
        ["ТС", "Тепловые сети"],
        ["ТМ", "Тепломеханические решения"],
        ["ЦТП", "Центральные тепловые пункты"],
        ["ИТП", "Индивидуальные тепловые пункты"],
        ["СС", "Сети связи"],
        ["РТ", "Радиосвязь"],
        ["ПС", "Пожарная сигнализация"],
        ["ОС", "Охранная сигнализация"],
        ["АК", "Автоматизация комплексная"],
        ["АУПТ", "Автоматическое пожаротушение"],
        ["СБ", "Система безопасности"],
        ["СА", "Система автоматизации"],
        ["СД", "Система диспетчеризации"],
        ["ТХ", "Технологические решения"],
        ["ТК", "Технологические коммуникации"],
        ["ВТ", "Вертикальный транспорт"],
    ],

    # "Настроить" → используем 178
    "Настроить": None,
}

def get_default_sections(mode: str) -> List[List[str]]:
    mode = (mode or "").strip()

    if mode == "Настроить":
        return [row[:] for row in DEFAULT_SECTIONS_BY_MODE["Приказ 178"]]

    return [row[:] for row in DEFAULT_SECTIONS_BY_MODE.get(mode, DEFAULT_SECTIONS_BY_MODE["Приказ 178"])]

def get_rules_path(mode: str) -> Path:
    mode = (mode or "").strip().lower()
    if mode in ("приказ 64", "64", "rules_64"):
        return RULES_64_PATH
    if mode in ("приказ 178", "178", "rules_178"):
        return RULES_178_PATH
    return RULES_CUSTOM_PATH


@dataclass
class DisciplineRule:
    pattern: str
    ids_path: str
    mapping_path: str = ""


@dataclass
class Profile:
    name: str
    last_ifc_dir: str = ""
    ifc_paths: List[str] = field(default_factory=list)
    reports_dir: str = ""
    common_ids_path: str = ""
    disc_rules: List[DisciplineRule] = field(default_factory=list)
    create_summary: bool = True
    rules_mode: str = "Приказ 64"
    section_descriptions: List[List[str]] = field(default_factory=list)    

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Profile":
        return Profile(
            name=d.get("name", "Project"),
            last_ifc_dir=d.get("last_ifc_dir", ""),
            ifc_paths=list(d.get("ifc_paths", [])),
            reports_dir=d.get("reports_dir", ""),
            common_ids_path="",
            disc_rules=[],
            create_summary=bool(d.get("create_summary", True)),
            rules_mode=d.get("rules_mode", "Приказ 64"),
            section_descriptions=[],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_ifc_dir": self.last_ifc_dir,
            "ifc_paths": list(self.ifc_paths),
            "reports_dir": self.reports_dir,
            "create_summary": bool(self.create_summary),
            "rules_mode": self.rules_mode,
        }


def load_rules(mode: str) -> Dict[str, Any]:
    rules_path = get_rules_path(mode)

    try:
        if rules_path.exists():
            raw = json.loads(rules_path.read_text(encoding="utf-8"))

            if isinstance(raw, dict):
                raw_sections = raw.get("section_descriptions", get_default_sections(mode))
                section_descriptions = [
                    [str(row[0]), str(row[1])]
                    for row in raw_sections
                    if isinstance(row, (list, tuple)) and len(row) >= 2
                ]

                if not section_descriptions:
                    section_descriptions = [row[:] for row in get_default_sections(mode)]

                return {
                    "common_ids_path": raw.get("common_ids_path", ""),
                    "disc_rules": [
                        DisciplineRule(**r)
                        for r in raw.get("disc_rules", [])
                        if isinstance(r, dict)
                    ],
                    "section_descriptions": section_descriptions,
                }

            if isinstance(raw, list):
                return {
                    "common_ids_path": "",
                    "disc_rules": [
                        DisciplineRule(**r)
                        for r in raw
                        if isinstance(r, dict)
                    ],
                    "section_descriptions": get_default_sections(mode),
                }
    except Exception:
        pass

    return {
        "common_ids_path": "",
        "disc_rules": [],
        "section_descriptions":  get_default_sections(mode),
    }


def save_rules(
    mode: str,
    common_ids_path: str,
    rules: List[DisciplineRule],
    section_descriptions: List[List[str]] | None = None
) -> None:
    rules_path = get_rules_path(mode)

    try:
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "common_ids_path": common_ids_path or "",
            "disc_rules": [asdict(r) for r in rules],
            "section_descriptions": section_descriptions if section_descriptions is not None else get_default_sections(mode),
        }
        rules_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


@dataclass
class AppConfig:
    profiles: Dict[str, Profile]
    active: str
    match_mode: str = "contains"

    @staticmethod
    def default() -> "AppConfig":
        p = Profile(name="Project 1")
        rules_data = load_rules(p.rules_mode)
        p.common_ids_path = rules_data.get("common_ids_path", "")
        p.disc_rules = [DisciplineRule(**asdict(r)) for r in rules_data.get("disc_rules", [])]
        p.section_descriptions = [row[:] for row in rules_data.get("section_descriptions", get_default_sections(p.rules_mode))]
        return AppConfig(profiles={p.name: p}, active=p.name)

    @staticmethod
    def load() -> "AppConfig":
        try:
            if CONF_PATH.exists():
                raw = json.loads(CONF_PATH.read_text(encoding="utf-8"))
                active = raw.get("active")
                profiles_raw = raw.get("profiles", {})

                profiles = {
                    name: Profile.from_dict({**v, "name": name})
                    for name, v in profiles_raw.items()
                    if isinstance(v, dict)
                }

                if not profiles:
                    return AppConfig.default()

                for p in profiles.values():
                    rules_data = load_rules(p.rules_mode)
                    p.common_ids_path = rules_data.get("common_ids_path", "")
                    p.disc_rules = [DisciplineRule(**asdict(r)) for r in rules_data.get("disc_rules", [])]
                    p.section_descriptions = [row[:] for row in rules_data.get("section_descriptions", get_default_sections(p.rules_mode))]

                if not active or active not in profiles:
                    active = next(iter(profiles))

                return AppConfig(
                    profiles=profiles,
                    active=active,
                    match_mode=raw.get("match_mode", "contains"),
                )
        except Exception:
            pass

        return AppConfig.default()

    def save(self) -> None:
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)

            data = {
                "active": self.active,
                "match_mode": "contains",
                "profiles": {name: p.to_dict() for name, p in self.profiles.items()},
            }

            CONF_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        except Exception:
            pass

    # ---- profile helpers ----
    def get_active(self) -> Profile:
        return self.profiles[self.active]

    def set_active(self, name: str) -> None:
        if name in self.profiles:
            self.active = name

    def create_profile(self, name: str) -> Profile:
        if name in self.profiles:
            i = 2
            base = name
            while f"{base} {i}" in self.profiles:
                i += 1
            name = f"{base} {i}"

        p = Profile(name=name)
        rules_data = load_rules(p.rules_mode)
        p.common_ids_path = rules_data.get("common_ids_path", "")
        p.disc_rules = [
            DisciplineRule(**asdict(r)) for r in rules_data.get("disc_rules", [])
        ]
        p.section_descriptions = [row[:] for row in rules_data.get("section_descriptions", get_default_sections(p.rules_mode))]
        self.profiles[name] = p
        self.active = name
        return p

    def delete_profile(self, name: str) -> bool:
        if name in self.profiles and len(self.profiles) > 1:
            del self.profiles[name]
            if self.active == name:
                self.active = next(iter(self.profiles))
            return True
        return False

    def rename_profile(self, old_name: str, new_name: str) -> str:
        new_name = (new_name or "").strip() or old_name

        if old_name not in self.profiles:
            return old_name

        final = new_name
        i = 2
        while final in self.profiles and final != old_name:
            final = f"{new_name} {i}"
            i += 1

        if final == old_name:
            self.profiles[old_name].name = final
            return final

        prof = self.profiles.pop(old_name)
        prof.name = final
        self.profiles[final] = prof

        if self.active == old_name:
            self.active = final

        return final

    def export_profile(self, name: str, out_path: Path) -> bool:
        if name not in self.profiles:
            return False

        out_path.write_text(
            json.dumps(self.profiles[name].to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return True

    def import_profile(self, path: Path, new_name: Optional[str] = None) -> Profile:
        raw = json.loads(path.read_text(encoding="utf-8"))
        p = Profile.from_dict(raw)

        if new_name:
            p.name = new_name

        final_name = p.name
        i = 2
        while final_name in self.profiles:
            final_name = f"{p.name} {i}"
            i += 1

        p.name = final_name
        rules_data = load_rules(p.rules_mode)
        p.common_ids_path = rules_data.get("common_ids_path", "")
        p.disc_rules = [
            DisciplineRule(**asdict(r)) for r in rules_data.get("disc_rules", [])
        ]
        p.section_descriptions = [row[:] for row in rules_data.get("section_descriptions", get_default_sections(p.rules_mode))]
        self.profiles[p.name] = p
        self.active = p.name
        return p