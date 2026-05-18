"""
Эвристики для колонок «Предполагаемый …» в CSV экспорта подписчиков.

Это не факты и не аналитика по IP: только текст ника, имени и био.
Значения выводятся коротко (без «возможно», «вероятно» и пояснений в скобках);
при слабом сигнале по-прежнему «Нет данных». По типичным индийским именам
в латинице — Индия / хинди, если в тексте нет явного Пакистана, Бангладеша и т.п.
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

# Токены из латиницы (ник / имя): совпадение целиком — сигнал к Южной Азии / Индии.
_INDIAN_NAME_TOKENS: frozenset[str] = frozenset(
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
        "iyengar",
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
        "omprakash",
        "prakash",
        "priyanka",
        "deepak",
        "vikram",
        "rajesh",
        "ramesh",
        "suresh",
        "mahesh",
        "ganesh",
        "naresh",
        "yogesh",
        "bhavesh",
        "hitesh",
        "pritesh",
        "sandesh",
        "mahendra",
        "ravindra",
        "narendra",
        "surendra",
        "satendra",
        "jitendra",
        "dharmendra",
        "rajendra",
        "lakshman",
        "lakshmanan",
        "venkatesh",
        "venkat",
        "subramanian",
        "murugan",
        "karthikeyan",
        "narayan",
        "narayana",
        "chandran",
        "krishnan",
        "swaminathan",
        "meenakshi",
        "deepika",
        "aishwarya",
        "anushka",
        "kavitha",
        "kavita",
        "swathi",
        "swati",
        "pooja",
        "puja",
        "neha",
        "kunal",
        "rohan",
        "sohan",
        "varun",
        "tarun",
        "arjun",
        "nikhil",
        "manish",
        "ritesh",
        "jitesh",
        "dinesh",
        "harish",
        "girish",
        "satish",
        "lokesh",
        "pravesh",
        "nandini",
        "kiran",
        "anil",
        "sunil",
        "anupam",
        "amitabh",
        "amit",
        "sachin",
        "vishal",
        "rohit",
        "mohit",
        "sumit",
        "namit",
        "udit",
        "aditya",
        "abhishek",
        "shreya",
        "shruti",
        "tanvi",
        "ishita",
        "divya",
        "sneha",
        "aarti",
        "arti",
        "sunita",
        "anita",
        "geeta",
        "gita",
        "seema",
        "reena",
        "rina",
        "veena",
        "heena",
        "sheena",
        "sanjay",
        "ajay",
        "vijay",
        "ranjeet",
        "ranjit",
        "surjeet",
        "baljeet",
        "gurpreet",
        "harpreet",
        "manpreet",
        "jaspreet",
        "navpreet",
    }
)

# Подстроки в нижнем регистре (для «склееных» ников без разделителей). Не короче 4 символов.
_INDIAN_NAME_SUBSTRINGS: tuple[str, ...] = (
    "omprakash",
    "prakash",
    "lakshman",
    "krishnan",
    "venkatesh",
    "subraman",
    "swaminath",
    "narayan",
    "chandrasekhar",
    "meenakshi",
    "priyanka",
    "aishwarya",
    "murugan",
    "karthikeyan",
    "jitendra",
    "dharmendra",
    "rajendra",
    "surendra",
    "narendra",
    "ravindra",
    "mahendra",
    "satendra",
)

# Если это есть в нике/имени/био — не угадываем Индию по имени (явный другой регион).
_INDIAN_GUESS_BLOCKERS: tuple[str, ...] = (
    "пакистан",
    "pakistan",
    "pakistani",
    "karachi",
    "lahore",
    "islamabad",
    "rawalpindi",
    "peshawar",
    "faisalabad",
    "quetta",
    "multan",
    "sialkot",
    "gujranwala",
    "бангладеш",
    "bangladesh",
    "bangladeshi",
    "dhaka",
    "chittagong",
    "шри-ланк",
    "sri lanka",
    "colombo",
    "kandy",
    "nepal",
    "kathmandu",
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


def _latin_letter_count(blob: str) -> int:
    return sum(1 for c in blob if "a" <= c.lower() <= "z")


def _latin_alpha_tokens(low: str) -> set[str]:
    tokens = re.split(r"[^a-zа-яё0-9]+", low)
    out: set[str] = set()
    for t in tokens:
        if len(t) < 3 or t.isdigit():
            continue
        if not any(c.isalpha() for c in t):
            continue
        out.add(t)
    return out


def _indian_name_hint(low: str) -> bool:
    """Индия по имени/нику, если нет явного Пакистана и т.д. в тексте."""
    if any(b in low for b in _INDIAN_GUESS_BLOCKERS):
        return False
    if any(s in low for s in _INDIAN_NAME_SUBSTRINGS):
        return True
    if _latin_alpha_tokens(low) & _INDIAN_NAME_TOKENS:
        return True
    return False


def _presumed_language(blob: str) -> str:
    if not blob or not any(c.isalpha() for c in blob):
        return ND
    low = blob.lower()
    # Скрипты Unicode
    arabic = sum(1 for c in blob if "\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f")
    cyrillic = sum(1 for c in blob if "\u0400" <= c <= "\u04ff")
    deva = sum(1 for c in blob if "\u0900" <= c <= "\u097f")
    letters = sum(1 for c in blob if c.isalpha())
    if letters == 0:
        return ND
    if arabic >= max(5, letters // 4):
        return "Арабский"
    if cyrillic >= max(4, letters // 3):
        return "Русский"
    if deva >= 3:
        return "Хинди"
    hebrew = sum(1 for c in blob if "\u0590" <= c <= "\u05ff")
    if hebrew >= 3:
        return "Иврит"
    cjk = sum(1 for c in blob if "\u4e00" <= c <= "\u9fff")
    if cjk >= 3:
        return "Восточная Азия"

    # Преимущественно латиница
    latin_letters = _latin_letter_count(blob)
    if latin_letters >= 4 and _indian_name_hint(low):
        return "Хинди"
    if latin_letters < 4:
        return ND
    padded = f" {low} "
    if any(h in padded for h in _EN_HINTS):
        return "Английский"
    if any(h in padded for h in _RU_HINTS):
        return "Русский"
    return ND


def _presumed_country(blob: str) -> str:
    if not blob:
        return ND
    low = blob.lower()
    for needle, label in _COUNTRY_BY_SUBSTRING:
        if needle in low:
            return label

    # Флаги в виде региональных индикаторов (упрощённо: ищем известные пары)
    if "🇮🇳" in blob:
        return "Индия"
    if "🇷🇺" in blob:
        return "Россия"
    if "🇺🇸" in blob:
        return "США"
    if "🇦🇪" in blob:
        return "ОАЭ"

    if _indian_name_hint(low):
        return "Индия"

    if any(f in low for f in _ARABIC_NAME_FRAGMENTS):
        return "Ближний Восток и Северная Африка"

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
            return f"{a} лет"
    m = re.search(r"\b(?:born|рожд\.?|рождения|birth)\s*[:\s]*((?:19|20)\d{2})\b", low, re.I)
    if m:
        y = int(m.group(1))
        cy = date.today().year
        if 1940 <= y <= cy - 10:
            return f"{cy - y} лет"
    m = re.search(r"\b(?:age|возраст)\s*[:\s]*(\d{1,2})\b", low, re.I)
    if m:
        a = int(m.group(1))
        if 13 <= a <= 80:
            return f"{a} лет"
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
    hit(
        "зодиак / астрология (по био)",
        r"\baries\b",
        r"\btaurus\b",
        r"\bgemini\b",
        r"\bcancer\b",
        r"\bleo\b",
        r"\bvirgo\b",
        r"\blibra\b",
        r"\bscorpio\b",
        r"\bsagittarius\b",
        r"\bcapricorn\b",
        r"\baquarius\b",
        r"\bpisces\b",
        r"\bastro\b",
        r"\bhoroscope\b",
        r"овен|телец|близнецы|рак|лев|дева|весы|скорпион|стрелец|козерог|водолей|рыбы",
        r"зодиак",
        r"астролог",
    )

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
