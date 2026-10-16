# -*- coding: utf-8 -*-
r"""按「单位编号」重排角色攻略的条目顺序（面板与线上编辑器各一份）。

编号来源：未打包/V1.0/out/journey_kb.json 的 characters（角色 id）与 forms（形态 unit_id），
面板角色详情页里显示的那个「单位编号」就是它。攻略条目里带的 faces/UFS_NKM_UNIT_S_XXX 素材名
与知识库的 face 一一对应，靠它把条目认到具体形态，再按 unit_id 排序。

改的只是「键的顺序」，内容一个字都不动（面板与线上编辑器都按这个顺序显示角色）。

用法:
    python sort_roles_by_unit.py            # 只预览，不写文件
    python sort_roles_by_unit.py --write    # 写回两份数据
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "未打包" / "V1.0" / "out" / "journey_kb.json"
PANEL_SHEETS = ROOT / "未打包" / "V1.0" / "out" / "role_sheets.json"
WEB_PAGES = ROOT / "docs" / "roles" / "role_pages.js"

FACE_RE = re.compile(r"faces/([^/\"']+?)\.(?:webp|png|jpg)", re.I)


def load_kb_index() -> dict:
    """素材名（不含扩展名）→ 单位编号。"""
    kb = json.loads(KB.read_text(encoding="utf-8"))
    idx = {}
    for c in kb.get("characters") or []:
        for f in c.get("forms") or []:
            face = (f.get("face") or "").split("/")[-1]
            if not face:
                continue
            idx.setdefault(Path(face).stem, f.get("unit_id"))
        face = (c.get("face") or "").split("/")[-1]
        if face and c.get("id") is not None:
            idx.setdefault(Path(face).stem, None)
    return idx


def entry_unit(entry: dict, idx: dict):
    """从条目的图片里找出 faces/ 素材，认回单位编号。"""
    files = []
    imgs = entry.get("imgs")
    if isinstance(imgs, dict):
        files += [str(v) for v in imgs.values()]
    elif isinstance(imgs, list):
        files += [str(v) for v in imgs]
    for im in entry.get("images") or []:
        files.append(str(im.get("file") or ""))
    for s in files:
        m = FACE_RE.search(s)
        if m:
            return idx.get(m.group(1))
    return None


def read_pages(path: Path) -> dict:
    t = path.read_text(encoding="utf-8")
    return json.loads(t[t.index("{"):t.rindex("}") + 1])


def sort_dict(d: dict, idx: dict):
    """按单位编号排；认不出编号的排到最后（并在返回里点名）。"""
    scored = [(k, v, entry_unit(v, idx)) for k, v in d.items()]
    known = [(k, v, n) for k, v, n in scored if n is not None]
    unknown = [(k, v, n) for k, v, n in scored if n is None]
    known.sort(key=lambda x: (x[2], x[0]))
    unknown.sort(key=lambda x: x[0])
    out = {}
    for k, v, _ in known + unknown:
        out[k] = v
    return out, [(k, n) for k, _, n in known], [k for k, _, _ in unknown]


def main() -> int:
    write = "--write" in sys.argv
    idx = load_kb_index()
    print("知识库覆盖素材 %d 个（含编号的 %d 个）" % (len(idx), sum(1 for v in idx.values() if v is not None)))

    pages_raw = WEB_PAGES.read_text(encoding="utf-8")
    pages = json.loads(pages_raw[pages_raw.index("{"):pages_raw.rindex("}") + 1])
    sheets = json.loads(PANEL_SHEETS.read_text(encoding="utf-8"))

    for name, d in (("线上编辑器 role_pages.js", pages), ("面板 role_sheets.json", sheets)):
        ordered, known, unknown = sort_dict(d, idx)
        print("\n%s：%d 条（认出编号 %d 条）" % (name, len(d), len(known)))
        print("  排序结果：" + "、".join("%s(%s)" % (k, n) for k, n in known[:8]) + " …")
        if unknown:
            print("  ！认不出编号（排到最后）：" + "、".join(unknown))
        if name.startswith("线上"):
            pages = ordered
        else:
            sheets = ordered

    if not write:
        print("\n（预览，未写文件；加 --write 落盘）")
        return 0
    WEB_PAGES.write_text("window.ROLE_PAGES = "
                         + json.dumps(pages, ensure_ascii=False, separators=(",", ":")) + ";\n",
                         encoding="utf-8", newline="\n")
    PANEL_SHEETS.write_text(json.dumps(sheets, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8", newline="\n")
    print("\n已写回 %s 与 %s" % (WEB_PAGES, PANEL_SHEETS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
