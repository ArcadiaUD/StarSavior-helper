# -*- coding: utf-8 -*-
r"""以编辑器的支援卡存档为准，生成支援卡榜的三份数据。

为什么这么做：原先 build/sc_apply_archive.py 把存档「按 name 合并」进基线
docs/sc/sc_board.json —— 只覆盖 box / 挂的卡 / 文字这些字段，删掉的格位、新增的图层
都进不去；基线一旦与编辑器不是同一版，面板就永远对不上。
这个脚本改成：**存档就是唯一真相**。编辑器「存到仓库」推上来的 docs/sc_psb_slots.json
本身就是完整快照（画布、格位、图层），这里原样搬进产物，坐标一个都不重算；
卡库只从现有数据里取并集（卡库随时会更新，不在这里删卡）。

用法:
    python export_sc_board.py            # 生成三份数据
    python export_sc_board.py --check    # 只校验，不写文件

输入:
    docs/sc_psb_slots.json（编辑器保存的完整版面）
    卡库：docs/sc_board_data.js 与 docs/sc/sc_board.json 的 cards 并集

输出:
    docs/sc_board_data.js       编辑器与网页首页用（素材在 docs 根下的 sc_layers/ 等）
    docs/sc/sc_board.json       线上与面板用（素材在各自目录下的 layers/ frames/ cards/）
    docs/sc/sc_board_data.js    同上一份，包成 window.SC_BOARD_DATA
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "sc_psb_slots.json"
EDITOR_JS = DOCS / "sc_board_data.js"
SITE = DOCS / "sc" / "sc_board.json"
SITE_JS = DOCS / "sc" / "sc_board_data.js"

EDITOR_BASES = {"layers": "sc_layers/", "cards": "sc_cards/", "frames": "sc_frames/"}
SITE_BASES = {"layers": "layers/", "cards": "cards/", "frames": "frames/"}


def read_board(path: Path) -> dict:
    """读一份榜单数据：.json 直接读，.js 是 window.XXX = {...}; 的包装。"""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        text = text[text.index("{"):text.rindex("}") + 1]
    return json.loads(text)


def write_js(path: Path, board: dict) -> None:
    path.write_text("window.SC_BOARD_DATA = " + json.dumps(board, ensure_ascii=False) + ";\n",
                    encoding="utf-8", newline="\n")


def load_cards() -> dict:
    """卡库取现有数据的并集，靠前的来源优先（新的卡面信息在编辑器那份里）。"""
    cards: dict = {}
    for p in (EDITOR_JS, SITE):
        if not p.is_file():
            continue
        for c in read_board(p).get("cards") or []:
            if c.get("id"):
                cards.setdefault(c["id"], c)
    return cards


def validate(board: dict, cards: dict) -> list:
    errs = []
    if not isinstance(board.get("w"), int) or not isinstance(board.get("h"), int):
        errs.append("画布尺寸不合法：" + str((board.get("w"), board.get("h"))))
    if not board.get("slots"):
        errs.append("格位为空，存档可疑")
    for s in board.get("slots") or []:
        for k in ("box", "win"):
            v = s.get(k)
            if not (isinstance(v, list) and len(v) == 4 and all(isinstance(n, (int, float)) for n in v)):
                errs.append(f"格位 {s.get('id')} 的 {k} 不是 4 个数：{v}")
        cid = s.get("卡")
        if cid is not None and cid not in cards:
            errs.append(f"格位 {s.get('id')} 挂了不在卡库里的卡：{cid}")
    for it in board.get("items") or []:
        v = it.get("box")
        if not (isinstance(v, list) and len(v) == 4):
            errs.append(f"图层 {it.get('name')} 的 box 不是 4 个数：{v}")
        if it.get("t") == "img" and not it.get("file"):
            errs.append(f"图片图层 {it.get('name')} 没有 file")
    return errs


def main() -> int:
    check_only = "--check" in sys.argv
    board = read_board(ARCHIVE)
    cards = load_cards()
    errs = validate(board, cards)

    filled = [s for s in board.get("slots") or [] if s.get("卡") and not s.get("空")]
    print(f"存档：画布 {board.get('w')}x{board.get('h')}／格位 {len(board.get('slots') or [])}"
          f"（挂了卡 {len(filled)}）／图层 {len(board.get('items') or [])}／卡库 {len(cards)}")
    if errs:
        for e in errs:
            print("  FAIL " + e)
        print("校验不通过，一个字段都不写")
        return 1
    if check_only:
        print("PASS 校验通过（未写文件）")
        return 0

    card_list = [cards[k] for k in sorted(cards)]
    print(f"卡库 {len(cards)} 张，其中被挂上的 {len({s['卡'] for s in filled})} 张")

    editor = dict(board, bases=EDITOR_BASES, cards=card_list)
    site = dict(board, bases=SITE_BASES, cards=card_list)

    write_js(EDITOR_JS, editor)
    SITE.parent.mkdir(parents=True, exist_ok=True)
    SITE.write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_js(SITE_JS, site)
    print(f"已写 {EDITOR_JS.name}、{SITE.parent.name}/{SITE.name}、{SITE.parent.name}/{SITE_JS.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
