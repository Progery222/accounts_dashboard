#!/usr/bin/env python3
"""
Импорт иерархии (tab-indented .txt) на доску Miro через REST API v2.

Перед запуском:
  1. https://miro.com/app/settings/user-profile/apps → Create new app
  2. Permissions: boards:read, boards:write
  3. Install app and get OAuth token (или PAT с теми же scope)
  4. ID доски — из URL: https://miro.com/app/board/uXjV.../  → uXjV...

Запуск:
  set MIRO_ACCESS_TOKEN=...
  set MIRO_BOARD_ID=uXjV...
  py scripts/miro_import_mindmap.py

  py scripts/miro_import_mindmap.py --dry-run
  py scripts/miro_import_mindmap.py --file docs/miro-analytics-mindmap.txt
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API_BASE = "https://api.miro.com/v2"
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "docs" / "miro-analytics-mindmap.txt"

# Расстояния между узлами на доске (пиксели)
H_SPACING = 440
V_SPACING = 130

# Цвета веток первого уровня (Miro fillColor)
BRANCH_COLORS = [
    "light_yellow",
    "light_green",
    "light_blue",
    "light_pink",
    "cyan",
    "violet",
    "orange",
]
ROOT_COLOR = "green"
DEFAULT_COLOR = "light_yellow"

REQUEST_PAUSE_SEC = 0.25


@dataclass
class Node:
    text: str
    depth: int = 0
    children: list[Node] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    miro_id: str | None = None
    color: str = DEFAULT_COLOR


class MiroClient:
    def __init__(self, token: str, board_id: str) -> None:
        self.token = token
        self.board_id = board_id

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{API_BASE}/boards/{self.board_id}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Miro API {method} {path} → HTTP {exc.code}: {detail}") from exc

    def verify_board(self) -> str:
        data = self._request("GET", "")
        return data.get("name", self.board_id)

    def create_sticky(self, node: Node) -> str:
        content = html.escape(node.text)
        payload = {
            "data": {
                "content": content,
                "shape": "rectangle" if len(node.text) > 28 else "square",
            },
            "style": {
                "fillColor": node.color,
                "textAlign": "center",
                "textAlignVertical": "middle",
            },
            "position": {
                "x": node.x,
                "y": node.y,
                "origin": "center",
            },
        }
        data = self._request("POST", "/sticky_notes", payload)
        item_id = data["id"]
        time.sleep(REQUEST_PAUSE_SEC)
        return item_id

    def create_connector(self, start_id: str, end_id: str) -> None:
        payload = {
            "startItem": {"id": start_id},
            "endItem": {"id": end_id},
            "shape": "elbowed",
            "style": {
                "strokeColor": "#1a1a1a",
                "strokeWidth": "2.0",
            },
        }
        self._request("POST", "/connectors", payload)
        time.sleep(REQUEST_PAUSE_SEC)


def parse_tab_outline(path: Path) -> Node:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"Файл пустой: {path}")

    entries: list[tuple[int, str]] = []
    for line in lines:
        stripped = line.lstrip("\t")
        depth = len(line) - len(stripped)
        entries.append((depth, stripped.strip()))

    root = Node(text=entries[0][1], depth=0)
    stack: list[tuple[int, Node]] = [(0, root)]
    for depth, text in entries[1:]:
        node = Node(text=text, depth=depth)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if not stack:
            raise ValueError(f"Некорректная вложенность у строки: {text!r}")
        stack[-1][1].children.append(node)
        stack.append((depth, node))
    return root


def layout_tree(node: Node, depth: int = 0, y_cursor: float = 0.0) -> float:
    """Горизонтальное дерево: x по глубине, y по листьям."""
    if not node.children:
        node.x = depth * H_SPACING
        node.y = y_cursor
        return y_cursor + V_SPACING

    y = y_cursor
    for child in node.children:
        y = layout_tree(child, depth + 1, y)

    first_y = node.children[0].y
    last_y = node.children[-1].y
    node.x = depth * H_SPACING
    node.y = (first_y + last_y) / 2
    return y


def assign_colors(node: Node, branch_color: str | None = None) -> None:
    if node.depth == 0:
        node.color = ROOT_COLOR
        for i, child in enumerate(node.children):
            color = BRANCH_COLORS[i % len(BRANCH_COLORS)]
            assign_colors(child, color)
        return

    node.color = branch_color or DEFAULT_COLOR
    for child in node.children:
        assign_colors(child, branch_color)


def iter_nodes(node: Node):
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def create_on_board(client: MiroClient, root: Node) -> int:
    count = 0
    for node in iter_nodes(root):
        node.miro_id = client.create_sticky(node)
        count += 1
        print(f"  [{count}] {node.text[:60]}{'…' if len(node.text) > 60 else ''}")

    for node in iter_nodes(root):
        if not node.miro_id:
            continue
        for child in node.children:
            if child.miro_id:
                client.create_connector(node.miro_id, child.miro_id)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт mind map на доску Miro")
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_FILE,
        help=f"Tab-indented файл (по умолчанию {DEFAULT_FILE})",
    )
    parser.add_argument("--token", default=os.environ.get("MIRO_ACCESS_TOKEN", ""))
    parser.add_argument("--board-id", default=os.environ.get("MIRO_BOARD_ID", ""))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать план, без запросов к API",
    )
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"Файл не найден: {args.file}", file=sys.stderr)
        return 1

    root = parse_tab_outline(args.file)
    layout_tree(root)
    assign_colors(root)

    nodes = list(iter_nodes(root))
    print(f"Узлов: {len(nodes)}")
    print(f"Связей: {len(nodes) - 1}")

    if args.dry_run:
        print("\n--- dry-run: координаты ---")
        for node in nodes:
            print(f"  d={node.depth} ({node.x:.0f},{node.y:.0f}) [{node.color}] {node.text}")
        return 0

    if not args.token or not args.board_id:
        print(
            "Нужны MIRO_ACCESS_TOKEN и MIRO_BOARD_ID (env или --token / --board-id).",
            file=sys.stderr,
        )
        return 1

    client = MiroClient(args.token.strip(), args.board_id.strip())
    print("Проверка доски…")
    board_name = client.verify_board()
    print(f"Доска: {board_name!r}")
    print("Создание стикеров и связей…")

    try:
        created = create_on_board(client, root)
    except RuntimeError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print(f"\nГотово: {created} стикеров на доске {args.board_id}")
    print("Откройте доску в Miro и при необходимости сдвините вид (Fit to screen).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
