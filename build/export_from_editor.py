# -*- coding: utf-8 -*-
"""按编辑器的渲染结果导出榜单数据（不再从 PSB 原稿重算）。

为什么这么做：原先榜单数据由 build_psb_full.py 从 PSB 原稿（psb_full.png + layers.json）
重新计算版面与文字，而编辑器用的是内联基线 + 存档改动。两套来源必然对不上——
文字/版本号还是原稿的（10 月 2 号那版）、图层集合也不一样（多出原稿残留的文字层）。
这个脚本改成：打开编辑器，把**渲染后的 DOM 原样读出来**，位置/尺寸/图片/文字/字号/颜色
全部以编辑器为准，PSB 原稿完全不参与。

用法：
    python export_from_editor.py [--write] [--port 8979]

输出（--write 时）：docs/board.json、docs/board_data.js
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BOARD = DOCS / "board.json"
BOARD_DATA = DOCS / "board_data.js"


def find_chrome():
    for c in (os.environ.get("CHROME_BIN"),
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("google-chrome"), shutil.which("chrome"),
              shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and Path(c).exists():
            return c
    raise SystemExit("找不到 Chrome/Chromium，可用 CHROME_BIN 指定")


def px(style, prop):
    m = re.search(prop + r":\s*(-?\d+(?:\.\d+)?)px", style or "")
    return float(m.group(1)) if m else None


def color_of(style):
    m = re.search(r"color:\s*(rgb\([^)]*\)|#[0-9a-fA-F]{3,8})", style or "")
    return m.group(1) if m else None


class Probe(HTMLParser):
    """把 #stage 里渲染出来的元素读成条目。

    - div.slot  → 格位（cell）：位置/底色/头像图/稀有度环
    - div.lb    → 文字图层；div.bg → 图片图层；div.nt → 新建文字
    """

    def __init__(self):
        super().__init__()
        self.stage = None
        self.items = []
        self.depth = []          # 元素栈

    def _text_style(self, style):
        return {
            "fs": px(style, "font-size"),
            "lh": px(style, "line-height"),
            "color": color_of(style),
            "bold": "bold" in (style or "") or "font-weight: 7" in (style or ""),
        }

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        st = d.get("style") or ""
        cls = (d.get("class") or "").split()

        if d.get("id") == "stage":
            w, h = px(st, "width"), px(st, "height")
            if w and h:
                self.stage = (round(w), round(h))
            self.depth.append(("stage", None))
            return

        item = None
        if tag == "div" and "slot" in cls and d.get("data-slot"):
            item = {"t": "img", "cell": True, "seq": int(d["data-slot"]),
                    "box": [round(px(st, "left") or 0), round(px(st, "top") or 0),
                            round(px(st, "width") or 0), round(px(st, "height") or 0)],
                    "blank": "blank" in cls, "ph": "ph" in cls,
                    "bg": (re.search(r"background:\s*([^;]+)", st) or [None, ""])[1].strip() or None,
                    "file": None, "ring": None}
        elif tag == "div" and ("lb" in cls or "bg" in cls) and d.get("data-seq"):
            item = {"t": "text" if "lb" in cls else "img", "cell": False,
                    "seq": int(d["data-seq"]), "wall": "wall" in cls,
                    "box": [round(px(st, "left") or 0), round(px(st, "top") or 0),
                            round(px(st, "width") or 0), round(px(st, "height") or 0)],
                    "file": None, "text": ""}
            item.update(self._text_style(st))
        elif tag == "div" and "sltext" in cls and d.get("data-slot-text"):
            # 格位下方的说明栏（编辑器里是真文字，可改内容/字号/颜色）
            if "hint" in cls:                      # 空占位，没内容就不输出
                self.depth.append(("hint", None))
                return
            item = {"t": "text", "cell": False, "abs": True,
                    "seq": None, "slotid": int(d["data-slot-text"]),
                    "box": [round(px(st, "left") or 0), round(px(st, "top") or 0),
                            round(px(st, "width") or 0),
                            round(px(st, "min-height") or px(st, "height") or 0)],
                    "file": None, "text": ""}
            item.update(self._text_style(st))
        elif tag == "div" and "nt" in cls and d.get("data-key"):
            item = {"t": "text", "cell": False, "abs": True, "nkey": d["data-key"],
                    "seq": None,
                    "box": [round(px(st, "left") or 0), round(px(st, "top") or 0),
                            round(px(st, "width") or 0), round(px(st, "height") or 0)],
                    "file": None, "text": ""}
            item.update(self._text_style(st))

        if item is not None:
            self.items.append(item)
            self.depth.append((item["t"], item))
            return

        # 子元素：头像图 / 稀有度环
        if tag == "img" and self.depth and isinstance(self.depth[-1][1], dict):
            it = self.depth[-1][1]
            if it.get("file") is None:
                it["file"] = d.get("src")
        elif tag == "i" and self.depth and isinstance(self.depth[-1][1], dict):
            it = self.depth[-1][1]
            if "ring" in cls and it.get("cell"):
                it["ring"] = {"w": px(st, "border-width"), "color": color_of(st)}
        self.depth.append((tag, None))

    def handle_endtag(self, tag):
        if self.depth:
            self.depth.pop()

    def handle_data(self, data):
        if self.depth and isinstance(self.depth[-1][1], dict):
            it = self.depth[-1][1]
            if it.get("t") == "text" and not it.get("cell"):
                it["text"] += data


def build_items(probe):
    """把探针输出整理成榜单条目（丢掉空壳、清掉临时键）。"""
    out = []
    for raw in probe.items:
        it = {k: v for k, v in raw.items() if v not in (None, "", False) or k in ("cell",)}
        if it.get("cell"):
            it.pop("text", None)
            it["cell"] = True
            if it.get("file"):          # 头像：渲染器认 face/src，不认 file
                it["face"] = it.pop("file")
            it["big"] = False
            it["grow"] = False
            rg = it.get("ring") or {}
            it["ring"] = round(rg.get("w") or 6)
            it["bg"] = it.get("bg") or "#2b3038"
            it.pop("blank", None)
            it.pop("ph", None)
        else:
            if not it.get("text"):
                it.pop("text", None)
            it.pop("cell", None)
        it.pop("wall", None)
        it.pop("nkey", None)
        out.append(it)
    return out


def main():
    args = sys.argv[1:]
    write = "--write" in args
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8979

    tmp = tempfile.mkdtemp(prefix="psb-export-")
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port)],
                              cwd=DOCS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 15
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.3)
    dom = os.path.join(tmp, "dom.html")
    try:
        with io.open(dom, "w", encoding="utf-8", errors="replace") as f:
            subprocess.run([find_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--user-data-dir=" + os.path.join(tmp, "prof"),
                            "--virtual-time-budget=25000", "--dump-dom",
                            "http://127.0.0.1:%d/editor.html" % port],
                           stdout=f, stderr=subprocess.DEVNULL, timeout=240)
    finally:
        server.kill()

    probe = Probe()
    probe.feed(io.open(dom, encoding="utf-8", errors="replace").read())
    items = build_items(probe)
    cells = [i for i in items if i.get("cell")]
    print("抓到：画布 %s ／ 条目 %d（格位 %d，图层 %d）"
          % (probe.stage, len(items), len(cells), len(items) - len(cells)))

    # #stage 的宽高写在 CSS 里，DOM 抓不到，就从渲染出来的元素算：
    # 画布高 = 最底那个元素的底边（黑底是撑到画布底的），宽取最右。
    if probe.stage:
        w, h = probe.stage
    else:
        w = max(i["box"][0] + i["box"][2] for i in items)
        h = max(i["box"][1] + i["box"][3] for i in items)

    old = json.loads(BOARD.read_text(encoding="utf-8")) if BOARD.is_file() else {}

    # 身份信息（角色/形态/分组/名字）不靠 DOM：按 id 从上一版数据里对齐过来，
    # 渲染器要靠它决定稀有度边框色与格子的名字。新格在数据里的 seq 是 900000+id。
    old_by = {}
    for o in old.get("items") or []:
        for k in (o.get("seq"), (o.get("seq") or 0) - 900000):
            if k is not None:
                old_by.setdefault(k, o)
    for it in items:
        o = old_by.get(it.get("seq"))
        if not o:
            continue
        for k in ("name", "group", "char", "form"):
            if o.get(k):
                it[k] = o[k]

    board = {
        "w": old.get("w") or w, "h": h,
        "bases": old.get("bases") or {"layers": "layers/", "faces": "faces/"},
        "grades": old.get("grades") or {},
        "items": items,
    }
    if not write:
        print("（试算，未写文件；加 --write 落盘）")
        return
    BOARD.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    BOARD_DATA.write_text("window.BOARD_DATA = " + json.dumps(board, ensure_ascii=False,
                          separators=(",", ":")) + ";\n", encoding="utf-8")
    print("已写回 docs/board.json 与 docs/board_data.js")


if __name__ == "__main__":
    main()
