# -*- coding: utf-8 -*-
"""用编辑器的渲染结果覆盖榜单数据里的位置。

为什么需要它：榜单数据（board.json）原本是构建脚本**从 PSB 原稿重算**出来的，
而编辑器用的是已经处理好的内联基线 + 存档位移。两套算法只要有一处不一致，
版面就会错位（删格没扣、层列表漏项、下移重复……）。这里改成直接取编辑器的渲染结果，
位置一定与编辑器一模一样。

做法：
 1. 起本地 http 服务，headless Chrome 打开 docs/editor.html（它会自动载入线上存档）；
 2. 抓渲染后的 DOM：格位（div.slot）与图层（div.lb / div.bg）的最终 left/top/宽/高；
 3. 按格位 id / 图层 seq 覆盖 docs/board.json 里对应条目的 box。

用法: python patch_positions.py [--write]
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

ROOT = Path(__file__).resolve().parent.parent      # 本机与 CI 都能跑：以脚本位置推仓库根
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


CHROME = find_chrome()
PORT = 8971


class Probe(HTMLParser):
    """抓 .slot（格位）与 .lb/.bg（图层）的位置。"""

    def __init__(self):
        super().__init__()
        self.cur = None
        self.slots = {}     # id -> (left, top, w, h)
        self.layers = {}    # seq -> (left, top, w, h)
        self.stage = None   # 画布尺寸 (w, h)

    @staticmethod
    def _box(style):
        def n(pat):
            m = re.search(pat, style or "")
            return int(m.group(1)) if m else None
        return (n(r"left:\s*(-?\d+)px"), n(r"top:\s*(-?\d+)px"),
                n(r"width:\s*(\d+)px"), n(r"height:\s*(\d+)px"))

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        d = dict(attrs)
        if d.get("id") == "stage":                 # 画布本体：尺寸就是榜单的画布大小
            b = self._box(d.get("style"))
            if b[2] and b[3]:
                self.stage = (b[2], b[3])
        cls = (d.get("class") or "").split()
        if "slot" in cls and d.get("data-slot"):
            self.cur = ("slot", d["data-slot"])
            self.slots[d["data-slot"]] = self._box(d.get("style"))
        elif ("lb" in cls or "bg" in cls) and d.get("data-seq"):
            self.cur = ("layer", d["data-seq"])
            self.layers[d["data-seq"]] = self._box(d.get("style"))
        else:
            self.cur = None


def wait_port(port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def main():
    write = "--write" in sys.argv
    tmp = tempfile.mkdtemp(prefix="psb-pos-")
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT)],
                              cwd=DOCS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_port(PORT):
        server.kill()
        raise SystemExit("本地服务没起来")
    dom = os.path.join(tmp, "dom.html")
    try:
        with io.open(dom, "w", encoding="utf-8", errors="replace") as f:
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--user-data-dir=" + os.path.join(tmp, "prof"),
                            "--virtual-time-budget=20000", "--dump-dom",
                            "http://127.0.0.1:%d/editor.html" % PORT],
                           stdout=f, stderr=subprocess.DEVNULL, timeout=180)
    finally:
        server.kill()

    p = Probe()
    p.feed(io.open(dom, encoding="utf-8", errors="replace").read())
    print("抓到：格位 %d 个，图层 %d 个" % (len(p.slots), len(p.layers)))

    board = json.loads(BOARD.read_text(encoding="utf-8"))
    hit, dropped = 0, []
    for it in board["items"]:                    # 顺序不能动：它决定渲染层级（后画的盖前面的）
        seq = it.get("seq")
        if it.get("cell"):
            sid = str(seq - 900000 if seq >= 900000 else seq)   # 新格在编辑器里就是原 id
            box = p.slots.get(sid) or p.slots.get(str(seq))
        else:
            box = p.layers.get(str(seq))
        if box and None not in box:
            it["box"] = [box[0], box[1], box[2], box[3]]
            hit += 1
        else:
            dropped.append(it)       # 编辑器里没抓到位置的：先原样留着，别误删说明文字
    if p.stage:
        board["w"], board["h"] = p.stage[0], p.stage[1]
    print("覆盖成功 %d 条，编辑器里没抓到的 %d 条（保持原样）" % (hit, len(dropped)))
    for d in dropped:
        print("   未抓到：seq=%-8s %s %s" % (d.get("seq"), d.get("t"), d.get("name")))
    print("画布：%sx%s" % (board["w"], board["h"]))
    if not write:
        print("（试算，未写文件；加 --write 落盘）")
        return
    BOARD.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    BOARD_DATA.write_text("window.BOARD_DATA = " + json.dumps(board, ensure_ascii=False,
                          separators=(",", ":")) + ";\n", encoding="utf-8")
    print("已写回", BOARD, "与", BOARD_DATA.name)


if __name__ == "__main__":
    main()
