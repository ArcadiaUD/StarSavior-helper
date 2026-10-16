# -*- coding: utf-8 -*-
r"""给强度榜编辑器的头像库（LIB）补上单位编号并按编号排序。

LIB 是 docs/editor.html 里的一个常量：`[{c: 角色, f: 形态, s: 素材路径}, …]`。
素材名（faces/UFS_NKM_UNIT_S_XXX）与 journey_kb.json 的单位一一对应，靠它取到 unit_id。
只动这个常量：加 `no` 字段 + 按编号重排，格位、渲染、几何一律不碰（LIB 只喂头像库抽屉）。

用法:
    python sort_lib_by_unit.py            # 预览
    python sort_lib_by_unit.py --write    # 写回 docs/editor.html
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "docs" / "editor.html"
KB = ROOT / "未打包" / "V1.0" / "out" / "journey_kb.json"


def load_kb_index() -> dict:
    kb = json.loads(KB.read_text(encoding="utf-8"))
    idx = {}
    for c in kb.get("characters") or []:
        for f in c.get("forms") or []:
            face = (f.get("face") or "").split("/")[-1]
            if face:
                idx.setdefault(Path(face).stem, f.get("unit_id"))
    return idx


def main() -> int:
    write = "--write" in sys.argv
    idx = load_kb_index()
    html = EDITOR.read_text(encoding="utf-8")
    m = re.search(r"const LIB = (\[.*?\]);", html, re.S)
    if not m:
        print("没找到 LIB 常量"); return 1
    lib = json.loads(m.group(1))

    known, unknown = [], []
    for it in lib:
        stem = Path((it.get("s") or "").split("/")[-1]).stem
        no = idx.get(stem)
        it = dict(it)
        if no is not None:
            it["no"] = no
            known.append(it)
        else:
            unknown.append(it)
    known.sort(key=lambda x: (x["no"], x.get("c") or "", x.get("f") or ""))
    unknown.sort(key=lambda x: (x.get("c") or "", x.get("f") or ""))
    out = known + unknown

    print("LIB 共 %d 条｜认出编号 %d 条｜认不出 %d 条" % (len(lib), len(known), len(unknown)))
    print("排序后前 8 条：" + "、".join("%s·%s(%s)" % (x.get("c"), x.get("f") or "原型", x.get("no"))
                                        for x in out[:8]))
    if unknown:
        print("！认不出编号的：" + "、".join("%s·%s" % (x.get("c"), x.get("f")) for x in unknown))

    if not write:
        print("（预览，未写文件；加 --write 落盘）")
        return 0
    # 换行风格跟原文件保持一致
    nl = "\r\n" if "\r\n" in html else "\n"
    body = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    new_html = html[:m.start()] + "const LIB = " + body + ";" + html[m.end():]
    EDITOR.write_text(new_html, encoding="utf-8", newline=nl)
    print("已写回 %s（%d 条）" % (EDITOR, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
