"""
Эвристики для колонок «Предполагаемый …» в CSV экспорта подписчиков.

Это не факты и не аналитика по IP: только текст ника, имени и био.
При слабых сигналах везде возвращается «Нет данных».
"""

from __future__ import annotations

import re
from datetime import date

ND = "Нет данных"

CSV_PRESUMED_HEADERS: tuple[str, str, str, str, str] = (
    "Предполагаемый язык",
    "Предполагаемая страна",
    "Предполагаемый возраст",
    "Предполагаемая профессия / род занятий",
    "Предполагаемая сводка",
)

# (подстрока в нижнем регистре, подпись страны)
_COUNTRY_BY_SUBSTRING: tuple[tuple[str, str], ...] = (
    ("индия", "Индия"),
    ("india", "Индия"),
    ("indian", "Индия"),
    ("mumbai", "Индия"),
    ("delhi", "Индия"),
    ("bangalore", "Индия"),
    ("bengaluru", "Индия"),
    ("hyderabad", "Индия"),
    ("chennai", "Индия"),
    ("kolkata", "Индия"),
    ("россия", "Россия"),
    ("russia", "Россия"),
    ("moscow", "Россия"),
    ("москва", "Россия"),
    ("saint petersburg", "Россия"),
    ("спб", "Россия"),
    ("питер", "Россия"),
    ("украина", "Украина"),
    ("ukraine", "Украина"),
    ("kyiv", "Украина"),
    ("kiev", "Украина"),
    ("харьков", "Украина"),
    ("одесса", "Украина"),
    ("казахстан", "Казахстан"),
    ("kazakhstan", "Казахстан"),
    ("алматы", "Казахстан"),
    ("астана", "Казахстан"),
    ("беларус", "Беларусь"),
    ("belarus", "Беларусь"),
    ("minsk", "Беларусь"),
    ("минск", "Беларусь"),
    ("usa", "США"),
    ("u.s.a", "США"),
    ("america", "США"),
    ("united states", "США"),
    ("new york", "США"),
    ("los angeles", "США"),
    ("california", "США"),
    ("texas", "США"),
    ("london", "Великобритания"),
    ("uk ", "Великобритания"),
    ("england", "Великобритания"),
    ("germany", "Германия"),
    ("berlin", "Германия"),
    ("france", "Франция"),
    ("paris", "Франция"),
    ("итали", "Италия"),
    ("italy", "Италия"),
    ("roma", "Италия"),
    ("испани", "Испания"),
    ("spain", "Испания"),
    ("madrid", "Испания"),
    ("barcelona", "Испания"),
    ("турци", "Турция"),
    ("turkey", "Турция"),
    ("istanbul", "Турция"),
    ("оаэ", "ОАЭ"),
    ("uae", "ОАЭ"),
    ("emirates", "ОАЭ"),
    ("dubai", "ОАЭ"),
    ("абу-даби", "ОАЭ"),
    ("египет", "Египет"),
    ("egypt", "Египет"),
    ("cairo", "Египет"),
    ("кairo", "Египет"),
    ("сауд", "Саудовская Аравия"),
    ("saudi", "Саудовская Аравия"),
    ("израил", "Израиль"),
    ("israel", "Израиль"),
    ("tel aviv", "Израиль"),
    ("иран", "Иран"),
    ("iran", "Иран"),
    ("пакистан", "Пакистан"),
    ("pakistan", "Пакистан"),
    ("karachi", "Пакистан"),
    ("бангладеш", "Бангладеш"),
    ("bangladesh", "Бангладеш"),
    ("китай", "Китай"),
    ("china", "Китай"),
    ("beijing", "Китай"),
    ("shanghai", "Китай"),
    ("япони", "Япония"),
    ("japan", "Япония"),
    ("tokyo", "Япония"),
    ("коре", "Корея"),
    ("korea", "Корея"),
    ("seoul", "Корея"),
    ("филиппин", "Филиппины"),
    ("philippines", "Филиппины"),
    ("manila", "Филиппины"),
    ("индонези", "Индонезия"),
    ("indonesia", "Индонезия"),
    ("jakarta", "Индонезия"),
    ("бразил", "Бразилия"),
    ("brazil", "Бразилия"),
    ("são paulo", "Бразилия"),
    ("mexico", "Мексика"),
    ("мексик", "Мексика"),
)

# Частые окончания/фрагменты в латинице — только как слабый сигнал к региону (не этнос).
_INDIAN_NAME_FRAGMENTS: frozenset[str] = frozenset(
    {
        "kumar",
        "singh",
        "sharma",
        "patel",
        "reddy",
        "verma",
        "gupta",
        "nair",
        "prasad",
        "yadav",
        "iyer",
        "mehta",
        "bose",
        "gandhi",
        "sati",
        "devi",
        "krishna",
        "raman",
        "lakshmi",
        "priya",
        "rahul",
        "ananya",
        "mahatma",
    }
)

_ARABIC_NAME_FRAGMENTS: frozenset[str] = frozenset(
    {
        "ahmed",
        "mohammed",
        "muhammad",
        "ibrahim",
        "abdul",
        "khalid",
        "fatima",
        "hassan",
        "omar",
    }
)

_EN_HINTS = (" the ", " and ", " with ", " from ", " for ", " my ", " love ", " life ", " check ", " link ")
_RU_HINTS = (" что ", " как ", " это ", " для ", " меня ", " привет ", " спасибо ", " только ", " если ")


def _blob(username: str, display_name: str, bio: str) -> str:
    return f"{username or ''}\n{display_name or ''}\n{bio or ''}".strip()


def _presumed_language(blob: str) -> str:
    if not blob or not any(c.isalpha() for c in blob):
        return ND
    low = blob.lower()
    # Скрипты Unicode
    n = len(blob)
    arabic = sum(1 for c in blob if "\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f")
    cyrillic = sum(1 for c in blob if "\u0400" <= c <= "\u04ff")
    deva = sum(1 for c in blob if "\u0900" <= c <= "\u097f")
    letters = sum(1 for c in blob if c.isalpha())
    if letters == 0:
        return ND
    if arabic >= max(5, letters // 4):
        return "Арабский (по алфавиту био/ника)"
    if cyrillic >= max(4, letters // 3):
        return "Русский или родственный кириллический (по алфавиту)"
    if deva >= 3:
        return "Хинди или другой язык Индии (деванагари, по алфавиту)"
    hebrew = sum(1 for c in blob if "\u0590" <= c <= "\u05ff")
    if hebrew >= 3:
        return "Иврит (по алфавиту)"
    cjk = sum(1 for c in blob if "\u4e00" <= c <= "\u9fff")
    if cjk >= 3:
        return "Китайский, японский или корейский (по иероглифам, точнее: нет данных)"

    # Преимущественно латиница
    latin_letters = sum(1 for c in blob if "a" <= c.lower() <= "z")
    if latin_letters < 4:
        return ND
    padded = f" {low} "
    if any(h in padded for h in _EN_HINTS):
        return "Английский (предположительно, по частым словам)"
    if any(h in padded for h in _RU_HINTS):
        return "Русский (предположительно, по частым словам)"
    return ND


def _presumed_country(blob: str) -> str:
    if not blob:
        return ND
    low = blob.lower()
    for needle, label in _COUNTRY_BY_SUBSTRING:
        if needle in low:
            return f"{label} (по явному упоминанию в тексте)"

    # Флаги в виде региональных индикаторов (упрощённо: ищем известные пары)
    if "🇮🇳" in blob:
        return "Индия (по эмодзи флага)"
    if "🇷🇺" in blob:
        return "Россия (по эмодзи флага)"
    if "🇺🇸" in blob:
        return "США (по эмодзи флага)"
    if "🇦🇪" in blob:
        return "ОАЭ (по эмодзи флага)"

    tokens = re.split(r"[^a-zа-яё0-9]+", low)
    tokens = {t for t in tokens if len(t) >= 3}
    if tokens & _INDIAN_NAME_FRAGMENTS:
        return "Возможно Индия (по типичным фрагментам имени/ника, неточно)"
    if any(f in low for f in _ARABIC_NAME_FRAGMENTS):
        return "Возможно страна Ближнего Востока или Северной Африки (по имени, неточно)"

    return ND


def _presumed_age(blob: str) -> str:
    if not blob:
        return ND
    low = blob.lower()
    m = re.search(
        r"\b(\d{1,2})\s*(?:years?\s*old|y\.?o\.?|лет|года?|г\.)\b",
        low,
        re.I,
    )
    if m:
        a = int(m.group(1))
        if 13 <= a <= 80:
            return f"около {a} лет (по явной фразе в тексте)"
    m = re.search(r"\b(?:born|рожд\.?|рождения|birth)\s*[:\s]*((?:19|20)\d{2})\b", low, re.I)
    if m:
        y = int(m.group(1))
        cy = date.today().year
        if 1940 <= y <= cy - 10:
            return f"около {cy - y} лет (по году рождения в тексте)"
    m = re.search(r"\b(?:age|возраст)\s*[:\s]*(\d{1,2})\b", low, re.I)
    if m:
        a = int(m.group(1))
        if 13 <= a <= 80:
            return f"около {a} лет (по полю «возраст» в тексте)"
    return ND


def _presumed_occupation(blob: str) -> str:
    if not blob:
        return ND
    low = blob.lower()
    hits: list[str] = []

    def hit(label: str, *patterns: str) -> None:
        for p in patterns:
            if re.search(p, low, re.I):
                hits.append(label)
                return

    hit("блогер / контент-мейкер", r"\bblogger\b", r"\binfluencer\b", r"инфлюенсер", r"блогер", r"content creator")
    hit("модель", r"\bmodel\b", r"\bмодель\b")
    hit("медицина", r"\bdoctor\b", r"\bdr\.?\b", r"\bmd\b", r"врач", r"medic", r"surgeon", r"стоматолог")
    hit("юриспруденция", r"\blawyer\b", r"юрист", r"адвокат", r"attorney")
    hit("образование / наука", r"\bteacher\b", r"учитель", r"препод", r"\bprofessor\b", r"профессор", r"scientist", r"студент", r"\bstudent\b")
    hit("предпринимательство", r"\bceo\b", r"\bfounder\b", r"предприниматель", r"основатель", r"стартап", r"\bentrepreneur\b")
    hit("маркетинг / SMM", r"\bseo\b", r"\bmarketing\b", r"маркетинг", r"smm", r"реклам")
    hit("спорт / фитнес", r"\bcoach\b", r"тренер", r"fitness", r"фитнес", r"athlete", r"спорт")
    hit("творчество", r"\bartist\b", r"художник", r"музыкант", r"musician", r"photographer", r"фотограф", r"designer", r"дизайнер")
    hit("IT", r"\bdeveloper\b", r"\bengineer\b", r"программист", r"разработчик", r"\bdev\b", r"кодер")

    if not hits:
        return ND
    return ", ".join(dict.fromkeys(hits))  # уникальные по порядку


def presumed_csv_fields(
    *,
    username: str,
    display_name: str,
    bio: str,
    platform: str,
) -> dict[str, str]:
    """Ключи — первые четыре из CSV_PRESUMED_HEADERS; сводка считается отдельно."""
    _ = platform
    blob = _blob(username, display_name, bio)
    lang = _presumed_language(blob)
    country = _presumed_country(blob)
    age = _presumed_age(blob)
    occ = _presumed_occupation(blob)
    parts = [x for x in (lang, country, age, occ) if x != ND]
    summary = ", ".join(parts) if parts else ND
    return {
        CSV_PRESUMED_HEADERS[0]: lang,
        CSV_PRESUMED_HEADERS[1]: country,
        CSV_PRESUMED_HEADERS[2]: age,
        CSV_PRESUMED_HEADERS[3]: occ,
        CSV_PRESUMED_HEADERS[4]: summary,
    }


def presumed_csv_column_values(
    *,
    username: str,
    display_name: str,
    bio: str,
    platform: str,
) -> list[str]:
    d = presumed_csv_fields(
        username=username,
        display_name=display_name,
        bio=bio,
        platform=platform,
    )
    return [d[h] for h in CSV_PRESUMED_HEADERS]
