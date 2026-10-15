# -*- coding: utf-8 -*-
r"""发布前校验：面板随包那份榜数据是不是最新的。

为什么单列一道：面板对使用者是「读随包为主」——国内直连 raw.githubusercontent 与
GitHub Pages 多半不通，在线取数失败就回落随包那份；程序包与数据包又都是从
`未打包/V1.0/assets/tier` 打包的。随包一旦落后于 docs（2026-10-16 支援卡那份长期是
空榜就是这么来的），别人装完看到的就是旧榜/空榜，而本机因为能连线上，怎么试都是对的。

用法:
    python check_panel_assets.py          # 一致退出 0，不一致退出 1
    python check_panel_assets.py -v       # 顺带打印每份的行数/条目数

打包前跑一次：publish_data.py 与 assemble_v25.py 已经接上，不一致直接中止发布。
本机没有 `未打包` 目录时（云端 CI、别人的 clone）跳过并退出 0。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PANEL = ROOT / "未打包" / "V1.0" / "assets" / "tier"

# 随包那份 ← 应当与谁一致（左边若是渲染器，源在仓库里，不是 docs 的产物）
PAIRS = (
    (PANEL / "board" / "board.json", DOCS / "board.json", "python build/export_from_editor.py --write"),
    (PANEL / "board" / "board_data.js", DOCS / "board_data.js", "python build/export_from_editor.py --write"),
    (PANEL / "board" / "board.js", ROOT / "build" / "board.js", "python build/export_from_editor.py --write"),
    (PANEL / "sc" / "sc_board.json", DOCS / "sc" / "sc_board.json", "python build/export_sc_board.py"),
    (PANEL / "sc" / "sc_board.js", DOCS / "sc_board.js", "python build/export_sc_board.py"),
)


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def summarize(path: Path) -> str:
    """给个人眼看的规模：角色榜看条目数，支援卡看格位数，渲染器看行数。"""
    if not path.is_file():
        return ""
    if path.suffix == ".js":
        return "%d 行" % len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if "items" in d:
        cells = [i for i in d.get("items") or [] if i.get("cell")]
        return "%d 条目（格位 %d）" % (len(d["items"]), len(cells))
    return "%d 格位" % len(d.get("slots") or [])


def main() -> int:
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    if not PANEL.is_dir():
        print("本机没有 %s，跳过（云端或没有面板目录时正常）" % PANEL)
        return 0

    bad = []
    for panel_file, source_file, fix in PAIRS:
        rel = panel_file.relative_to(PANEL)
        if not panel_file.is_file():
            bad.append(("%s" % rel, "缺失", fix))
            continue
        if not source_file.is_file():
            bad.append(("%s" % rel, "对照文件不存在：%s" % source_file, fix))
            continue
        a, b = digest(panel_file), digest(source_file)
        if verbose or a != b:
            print("  %-22s 随包 %s ｜ 源 %s ｜ %s %s"
                  % (rel, a, b, summarize(panel_file), summarize(source_file)))
        if a != b:
            bad.append(("%s" % rel, "与源不一致", fix))

    if bad:
        print("FAIL 面板随包那份榜数据不是最新的（使用者看的就是这一份）：")
        for name, why, fix in bad:
            print("  - %-22s %s" % (name, why))
        for fix in sorted({b[2] for b in bad}):
            print("  修：%s" % fix)
        return 1
    print("PASS 面板随包与线上/源一致（%d 份）" % len(PAIRS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
