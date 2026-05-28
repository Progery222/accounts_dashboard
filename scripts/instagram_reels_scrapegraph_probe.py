#!/usr/bin/env python3
"""
УСТАРЕВШИЙ пробник. Используйте scripts/scrapegraph_social_probe.py
(html_mode + embedded JSON, формат как у dashboard).

Пробный одноразовый скрипт: Instagram Reels через ScrapeGraphAI (open-source).

Не интегрирован в Django refresh. Instagram часто требует логин / ловит антибот —
результат может быть пустым или неточным; сравните с вашим platforms/instagram.

Установка (отдельный venv, чтобы не тянуть LangChain в backend Poetry):

  py -3.13 -m venv .venv-scrapegraph
  .venv-scrapegraph\\Scripts\\activate
  pip install scrapegraphai python-dotenv
  playwright install chromium

Переменные окружения:
  OPENAI_API_KEY   — для модели openai/gpt-4o-mini (по умолчанию)
  или запуск с --llm-provider ollama и локальным Ollama

Примеры:
  python scripts/instagram_reels_scrapegraph_probe.py
  python scripts/instagram_reels_scrapegraph_probe.py --no-headless
  python scripts/instagram_reels_scrapegraph_probe.py --url https://www.instagram.com/thecapitolverdict/reels/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_URL = "https://www.instagram.com/thecapitolverdict/reels/"


def _output_schema_model():
    from pydantic import BaseModel, Field

    class ReelPost(BaseModel):
        post_url: str = Field(description="Full or relative Instagram reel URL")
        view_count: int = Field(
            description="Play/view count as integer (convert 1.2M → 1200000); 0 if hidden"
        )
        like_count: int = Field(description="Like count; 0 if not shown")

    class InstagramReelsExtract(BaseModel):
        username: str = Field(default="", description="Handle without @")
        follower_count: int = Field(
            description="Subscribers/followers; 0 if not visible on page"
        )
        post_count: int = Field(
            description="Total reels/posts count if shown, else count of visible grid items"
        )
        posts: list[ReelPost] = Field(
            default_factory=list,
            description="Each visible reel on the reels tab",
        )
        notes: str = Field(
            default="",
            description="Login wall, captcha, or why data is missing",
        )

    return InstagramReelsExtract

EXTRACT_PROMPT = """
You scrape an Instagram profile REELS tab (grid of short videos).

Extract ONLY what is visibly present on the loaded page:
1) follower_count — subscribers / followers for the account
2) post_count — how many reels/posts are shown or the total count if displayed
3) posts — for EACH visible reel on the page:
   - post_url (full or relative Instagram reel URL)
   - view_count (plays/views; integer, no K/M suffix in output — convert 1.2M to 1200000)
   - like_count (integer; 0 if not shown)

Do not invent numbers. If the page shows login, checkpoint, or "Log in to continue",
set follower_count and post_count to 0, posts to [], and explain in notes.
Return valid JSON matching the schema.
""".strip()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parent.parent
    for name in (".env", "backend/.env", "backend/config/.env"):
        p = root / name
        if p.is_file():
            load_dotenv(p)


def _build_graph_config(*, headless: bool, llm_provider: str, model: str) -> dict:
    if llm_provider == "openai":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            print(
                "Нужен OPENAI_API_KEY (или --llm-provider ollama).\n"
                "Пример: $env:OPENAI_API_KEY='sk-...'",
                file=sys.stderr,
            )
            sys.exit(1)
        llm = {
            "api_key": api_key,
            "model": model or "openai/gpt-4o-mini",
        }
    else:
        llm = {
            "model": model or "ollama/llama3.2",
            "model_tokens": 8192,
            "format": "json",
        }

    return {
        "llm": llm,
        "verbose": True,
        "headless": headless,
        "loader_kwargs": {
            "timeout": 120000,
        },
    }


def run_scrape(*, url: str, headless: bool, llm_provider: str, model: str) -> dict:
    from scrapegraphai.graphs import SmartScraperGraph

    graph = SmartScraperGraph(
        prompt=EXTRACT_PROMPT,
        source=url,
        config=_build_graph_config(
            headless=headless,
            llm_provider=llm_provider,
            model=model,
        ),
        schema=_output_schema_model(),
    )
    raw = graph.run()
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw_text": raw}
    return {"raw": raw}


def _summarize(data: dict) -> None:
    posts = data.get("posts") or []
    if not isinstance(posts, list):
        posts = []
    print("\n--- Сводка ---")
    print(f"Подписчики:     {data.get('follower_count', '—')}")
    print(f"Постов (reels): {data.get('post_count', len(posts))}")
    print(f"В списке posts: {len(posts)}")
    notes = (data.get("notes") or "").strip()
    if notes:
        print(f"Заметки:        {notes}")
    for i, p in enumerate(posts[:30], 1):
        if not isinstance(p, dict):
            continue
        print(
            f"  {i}. views={p.get('view_count', 0)} likes={p.get('like_count', 0)} "
            f"url={p.get('post_url', '')}"
        )
    if len(posts) > 30:
        print(f"  … и ещё {len(posts) - 30}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Instagram Reels probe via ScrapeGraphAI")
    parser.add_argument("--url", default=DEFAULT_URL, help="Страница reels")
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Показать окно Chromium (лучше для капчи/логина)",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("openai", "ollama"),
        default="openai",
    )
    parser.add_argument("--model", default="", help="Переопределить модель LLM")
    parser.add_argument(
        "--out",
        default="",
        help="Сохранить JSON в файл (например instagram_scrapegraph_result.json)",
    )
    args = parser.parse_args()

    _load_dotenv()
    os.environ.setdefault("SCRAPEGRAPHAI_TELEMETRY_ENABLED", "false")

    url = args.url.strip()
    headless = not args.no_headless

    print(f"URL: {url}")
    print(f"headless={headless} llm={args.llm_provider}")
    print("Запуск SmartScraperGraph (может занять 1–3 мин.)…\n")

    try:
        data = run_scrape(
            url=url,
            headless=headless,
            llm_provider=args.llm_provider,
            model=args.model.strip(),
        )
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)
    _summarize(data)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\nСохранено: {out_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
