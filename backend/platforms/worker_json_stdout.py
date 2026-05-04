"""
Одна строка JSON на stdout для subprocess-воркеров Playwright.
На Windows print() использует cp1251/cp1252 и падает на эмодзи в текстах постов.
"""
import json
import sys


def write_json_line(payload: dict) -> None:
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    data = line.encode("utf-8", errors="replace")
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        sys.stdout.write(line)
        sys.stdout.flush()
