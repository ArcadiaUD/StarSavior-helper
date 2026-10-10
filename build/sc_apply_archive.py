# -*- coding: utf-8 -*-
r"""把编辑器的支援卡存档并进榜单数据（云端重建用，不需要图像库）。

用法:
    python sc_apply_archive.py                    # 用默认路径
    python sc_apply_archive.py 基线.json 存档.json 输出.json

输入:
    基线：docs/sc/sc_board.json（格位与卡库的骨架，随仓库维护）
    存档：docs/sc_psb_slots.json（编辑器保存的那份）
输出:
    docs/sc/sc_board.json（就地更新：哪一格挂了哪张卡、坐标、文字改动、新增的格）

说明：卡框与卡面素材不在这里处理——它们随包下发、由面板自己引用，这一步只改数据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "docs" / "sc" / "sc_board.json"
ARCHIVE = ROOT / "docs" / "sc_psb_slots.json"
OUT = ROOT / "docs" / "sc" / "sc_board.json"


def apply_archive(data: dict, arc: dict, log=print) -> tuple[int, int, int]:
    cards = {c["id"] for c in data.get("cards", [])}
    by_id = {s["id"]: s for s in data["slots"]}
    n_card = n_new = n_item = 0

    for s0 in arc.get("slots", []):
        s = by_id.get(s0.get("id"))
        if not s:
            continue
        cid = s0.get("卡")
        if cid is not None and cid not in cards:
            log(f"  ！存档里挂的卡不在卡库里，跳过：{s0.get('id')} → {cid}")
            continue
        if s.get("卡") != cid or bool(s.get("空", True)) != bool(s0.get("空", True)):
            s["卡"] = cid
            s["空"] = True if cid is None else bool(s0.get("空"))
            n_card += 1
        for k in ("box", "win"):
            if isinstance(s0.get(k), list) and len(s0[k]) == 4:
                s[k] = s0[k]
        if s0.get("frame"):
            s["frame"] = s0["frame"]

    known = {s["id"] for s in data["slots"]}
    for s0 in arc.get("slots", []):
        if s0.get("id") in known or not s0.get("box"):
            continue
        box = s0["box"]
        data["slots"].append({
            "id": s0["id"], "group": s0.get("group") or "", "name": s0.get("name") or s0["id"],
            "box": box, "win": s0.get("win") or [box[0] + 10, box[1] + 13, 304, 299],
            "frame": s0.get("frame") or "", "卡": s0.get("卡"),
            "空": bool(s0.get("空", True))})
        n_new += 1

    items = {it.get("name"): it for it in data["items"] if it.get("name")}
    for it0 in arc.get("items", []):
        it = items.get(it0.get("name"))
        if not it:
            continue
        if isinstance(it0.get("box"), list) and len(it0["box"]) == 4 and it["box"] != it0["box"]:
            it["box"] = it0["box"]
            n_item += 1
        for k in ("text", "color", "fs", "lh", "bold", "hidden"):
            if k in it0 and it.get(k) != it0[k]:
                it[k] = it0[k]
                n_item += 1
    if arc.get("h"):
        data["h"] = arc["h"]
    data["bases"] = {"layers": "layers/", "frames": "frames/", "cards": "cards/"}
    return n_card, n_new, n_item


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE
    arc_p = Path(sys.argv[2]) if len(sys.argv) > 2 else ARCHIVE
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else OUT

    data = json.loads(base.read_text(encoding="utf-8"))
    if not arc_p.is_file():
        print(f"没有编辑存档（{arc_p}），按基线输出")
    else:
        arc = json.loads(arc_p.read_text(encoding="utf-8"))
        n_card, n_new, n_item = apply_archive(data, arc)
        print(f"并入存档：挂卡改动 {n_card} 格、新增格 {n_new} 个、图层改动 {n_item} 处")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    filled = [s for s in data["slots"] if s.get("卡") and not s.get("空")]
    print(f"写出 {out}：格位 {len(data['slots'])} 个（挂了卡 {len(filled)} 个）／图层 {len(data['items'])} 个")


if __name__ == "__main__":
    main()
