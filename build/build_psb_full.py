# -*- coding: utf-8 -*-
r"""用 PSB 的全部可见图层还原整版实验网页：一把图层都搬上去（含背景、logo、Q 版表情、特别感谢、底边、持立牌图）。

用法:
    python build_psb_full.py
输出:
    E:/AI/TempFiles/psb_web/index.html   （素材复制到 psb_web/layers、psb_web/faces）
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import cv2
import numpy as np

from build_psb_slots import (headroom_shift, group_dy,   # 与编辑器共用同一份规则
                             attr_grid_normalize, GROW_NAMES, ATTR_PAD, DROP_TEXT,
                             ATTR_ORDER, PLACEHOLDER_TIERS, PLACEHOLDER_TAG_SEQ,
                             PLACEHOLDER_SLOT_ID, clean_name, face_src, attach_slot_texts,
                             ring_width, role_grades, slot_bg, text_color, text_colors)

# 本机跑与仓库里跑（GitHub Actions）根目录不同，用环境变量切换，之后的逻辑完全一致
TMP = Path(os.environ.get("PSB_TMP") or r"E:/AI/TempFiles")
PANEL = Path(os.environ.get("PSB_PANEL") or r"E:/AI/WORK/StarSavior-helper/未打包/V1.0")
WEB = TMP / "psb_web"
LAYERS = TMP / "psb_layers"
FULL = TMP / "psb_full.png"

# 图层名 → 面板角色（形态名可选）。名字取自作者图层，身份一律「按头像的姓名」定：
# 拿该格的原稿裁片（psb_web/layers/<组>__<图层名>.png）跟头像库**全部 56 张脸逐张比**，
# 取最高分那个姓名，不只看同一个角色的各形态——只看同角色会漏掉整格标错。
# 度量见 mat_score.py（先按 alpha 裁齐实心外接框、铺中性底再比），核算脚本 mat_all.py。
LAYER_MAP = {
    "泳装微笑": ("微笑", "阳光猫娘"), "克拉丽莎": ("克拉丽莎", None), "瑟莱丝": ("瑟莱丝", None),
    "gn": ("亚瑟菈", "星光华尔兹"), "mudun": ("艾黛", None), "阿莫拉": ("阿莫拉", None), "M教授": ("M教授", None),
    "tuxia": ("夏尔", "莫纳斯提尔之心"), "hdj": ("缇莉雅", None), "hka": ("卡蜜", "永恒誓约"),
    "aimili": ("埃米莉", None), "卡": ("卡奈莉亚", None), "格温": ("克温", None),
    "sla": ("赛拉", None), "hali": ("哈莉", None), "wikiSS克莉丝特头像": ("克莉丝特", None),
    "luge": ("卢格", None), "zanna": ("安娜", None), "泳装露娜": ("露娜", "白珍珠"),
    "miulier": ("缪莉尔", None), "laixi": ("莱希", None), "cuisita": ("薇丝塔", None),
    "fl": ("芙蕾", None), "qila": ("绮拉", None), "slf": ("瑟乐芬", None),
    "zbeila": ("贝拉", None), "lsf": ("希尔德", None), "凌": ("凌", None), "ptla": ("佩特拉", None),
    "nna": ("露娜", None), "ailisha": ("艾莉莎", None), "ldy": ("莉迪亚", None), "yiz": ("罗莎莉亚", None),
    "zmaerxi": ("玛尔希", None), "skl": ("丝卡蕾", "小暴君"), "zsikalei": ("丝卡蕾", None),
    "hf": ("艾芬黛尔", "花绽祝福"), "xe": ("夏尔", None), "miulier2": (None, None),
    "yasela": ("亚瑟菈", None), "lili": ("莉莉", None), "tfl": ("芙蕾", "贵族公主"),
    "laidai": ("艾芬黛尔", None), "霏": ("霏", None), "kler": ("克莱儿", "无瑕蓝玫瑰"),
    "zkelaier": ("克莱儿", None), "tnji": ("塔妮娅", None), "amj": ("奥米嘉", None),
    "dna": ("达娜", None), "lmn": ("刘米娜", None), "wx": ("微笑", None), "best": ("贝尔·莉丝", None),
    "crs": ("崔瑞丝", None), "lbt": ("萝贝塔", None), "nalu": ("娜鲁", None),
    "klls": ("克拉丽莎", None),
}

BIG = {"背景", "图层 1", "底边"}          # 整图底与页脚，可用开关隐藏
SKIP_TAG = {"矩形 1", "光标"}             # 不算角色格的杂项


def build_face_index():
    """角色名 → 形态名 → 面板脸图（复制进网页目录），供「换成面板形象」对照。
    空形态名那一项是原型自己的脸，格位没写形态时用它；形态名统一去掉零宽字符。"""
    codex = json.loads((PANEL / "out" / "codex.json").read_text(encoding="utf-8"))
    out_dir = WEB / "faces"
    out_dir.mkdir(parents=True, exist_ok=True)
    idx, copied = {}, {}
    for c in codex["roster"]:
        forms = {}
        stem, src = face_src(c)
        if stem:
            forms[""] = f"faces/{stem}.webp"
            copied[stem] = src
        for f in (c.get("forms") or []):
            stem, src = face_src(f)
            if stem:
                forms.setdefault(clean_name(f["title"]), f"faces/{stem}.webp")
                copied[stem] = src
        idx[c["name"]] = forms
    for stem, src in copied.items():
        dst = out_dir / f"{stem}.webp"
        if not dst.exists():
            shutil.copy2(src, dst)
    return idx


def main() -> None:
    doc = json.loads((LAYERS / "layers.json").read_text(encoding="utf-8"))
    raw, (W, H) = doc["items"], doc["size"]
    full = cv2.imdecode(np.fromfile(FULL, dtype=np.uint8), cv2.IMREAD_COLOR)
    faces = build_face_index()
    grades = role_grades()
    tc = text_colors()

    dst_dir = WEB / "layers"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for it in raw:
        if it["kind"] != "img":
            continue
        dst = dst_dir / it["file"]
        if not dst.exists():
            shutil.copy2(LAYERS / it["file"], dst)

    def face_of(char, form=None):
        """角色（可带形态）→ 面板头像；与编辑器里的查表规则保持一致：
        形态名归一化后查；查不到就用原型自己的脸，不再随手取某个形态的脸。"""
        if not char or char not in faces:
            return None
        forms = faces[char]
        key = clean_name(form) if form else ""
        return forms.get(key) or forms.get("")

    items, pending = [], []
    shift = headroom_shift(raw)
    dy = group_dy(shift)
    for it in raw:
        name, grp = it["name"], it.get("group")
        d = dy(name, grp)
        if it["kind"] == "text":
            txt = (it.get("text") or "").replace("\r", "\n").strip()
            if not txt or txt in DROP_TEXT:
                continue
            bx = it["bbox"]                       # 文字层 bbox 是 (x1,y1,x2,y2)
            box = [bx[0], bx[1], bx[2] - bx[0], bx[3] - bx[1]]
            items.append({"t": "text", "name": name, "group": grp, "text": txt,
                          "lines": max(1, txt.count("\n") + 1),
                          "box": [box[0], box[1] + d, box[2], box[3]],
                          "color": tc.get(tuple(bx)) or text_color(full, box), "seq": it["seq"]})
            continue
        who = LAYER_MAP.get(name, (None, None)) if name not in BIG else (None, None)
        face = face_of(who[0], who[1])
        is_cell = bool(grp) and name not in SKIP_TAG
        if is_cell and who[0] is None:
            pending.append(f"{grp}/{name}")
        items.append({"t": "img", "name": name, "group": grp,
                      "box": [it["x"], it["y"] + d, it["w"], it["h"]], "seq": it["seq"],
                      "file": it["file"], "char": who[0], "form": who[1], "face": face,
                      "cell": is_cell, "big": name in BIG, "grow": name in GROW_NAMES,
                      "bg": slot_bg(LAYERS / it["file"]) if is_cell else "",
                      "ring": (max(ring_width(LAYERS / it["file"]) + 2, round(it["w"] * 0.025))
                               if is_cell else 0)})

    # 补齐原稿没画的档位（光系 T2/T3/T4、暗系 T3）：档位标签 + 一个金框空位
    for k, (grp, label, lbox, sbox) in enumerate(PLACEHOLDER_TIERS):
        d = dy("", grp)
        if lbox:                              # 该档原本没有标签（暗系 T3 已有）就不补标签
            items.append({"t": "text", "name": label, "group": grp, "text": label, "lines": 1,
                          "box": [lbox[0], lbox[1] + d, lbox[2], lbox[3]], "color": "#ffffff",
                          "seq": PLACEHOLDER_TAG_SEQ + k})
        items.append({"t": "img", "name": label + "空位", "group": grp,
                      "box": [sbox[0], sbox[1] + d, sbox[2], sbox[3]],
                      "seq": PLACEHOLDER_SLOT_ID + k, "file": None, "char": None, "form": None,
                      "face": None, "cell": True, "big": False, "grow": False,
                      "ph": True, "bg": "transparent", "ring": 0})

    # 属性栏重排到同一套网格：与编辑器同一套规则（档内行距、两列列距、标签到首排间距）
    attr_grid_normalize(
        [it for it in items if it.get("cell") and it.get("group") in ATTR_ORDER],
        [it for it in items if it["t"] == "text" and it.get("group") in ATTR_ORDER
         and it["text"].strip()[:1] == "T" and it["text"].strip()[1:].isdigit()])

    down = {}                                    # 加格造成的整体下移（没有格位表时为空）
    attr_down = 0                                # 属性栏那一层的整体下移量
    slots_path = WEB / "psb_slots.json"
    if slots_path.exists():
        ed = json.loads(slots_path.read_text(encoding="utf-8"))
        rows = ed.get("allSlots") or ed.get("slots") or []
        detail = {int(r["slot"]): r for r in ed.get("slots", [])}
        mapping = {int(r["slot"]): r for r in rows}
        news = ed.get("newSlots") or []
        down = ed.get("down") or {}
        slot_shift = {int(k): v for k, v in (ed.get("slotShift") or {}).items()}
        layer_shift = {int(k): v for k, v in (ed.get("layerShift") or {}).items()}

        # 加格造成的整体下移：按层顺序累积（五属性栏算同一层，横排互不影响）
        base, cum = {}, 0
        for g in ("全场景必练T0", "全场景必练T0.5", "T1功能角色", "T2功能角色", "__attr__", "__tail__"):
            base[g] = cum
            cum += down.get(g, 0)
        attr_down = base["__attr__"]

        def drop_of(group, name):
            if group in base:
                return base[group]
            if group in ATTR_ORDER or (name or "").startswith("全属性梯度"):
                return base["__attr__"]
            if name in ("底边", "人物持立牌图片"):
                return base["__tail__"]
            return 0

        # 属性栏里就地插行：档位标签跟着让位（背板不算，它改为跟着变长）
        for it in items:
            if it.get("group") in ATTR_ORDER:
                it["box"][1] += layer_shift.get(int(it["seq"]), 0)

        # 网页上新加的格位：位置与描边来自格位表，头像同样从换过的形象取
        for ns in news:
            gy = (ns["box"][1] + slot_shift.get(int(ns["id"]), 0)
                  + drop_of(ns.get("group"), ns.get("name")))
            items.append({"t": "img", "name": ns.get("name") or "新格", "group": ns.get("group"),
                          "box": [ns["box"][0], gy, ns["box"][2], ns["box"][3]],
                          "seq": 900000 + int(ns["id"]), "file": None, "cell": True, "big": False,
                          "char": None, "form": None, "face": None,
                          "ring": ns.get("ring") or 8, "bg": ns.get("bg") or ""})

        cells = [it for it in items if it.get("cell")]
        src_of = {it["seq"]: dict(it) for it in cells}    # 原稿快照，免得改写时读到已换过的值
        kept, moved, drained = [], 0, 0
        for it in items:
            row = mapping.get(it.get("seq"))
            if not it.get("cell") or row is None:
                kept.append(it); continue
            cid = row.get("content")
            if cid is None:                       # 空出的洞：槽位还在，只是不挂头像
                drained += 1
                it["src"] = it["char"] = it["form"] = it["face"] = None
                kept.append(it); continue
            src = src_of.get(cid)
            if src is None:
                kept.append(it); continue
            it["file"], it["name"] = src["file"], src["name"]
            it["char"], it["form"] = src.get("char"), src.get("form")
            it["face"] = src.get("face")
            if row.get("char"):
                it["char"], it["form"] = row["char"], row.get("form")
                it["face"] = face_of(it["char"], it["form"]) or it["face"]
            if cid != it["seq"]:
                moved += 1
            kept.append(it)
        items = kept

        art_n = 0
        replaced, extra_texts = set(), []

        def push_text(sid, slot, box, txt, color, fs, lh):
            """插入说明文字：坐标由编辑器给出（已含加格造成的下移），故不再参与后面的整层下移"""
            extra_texts.append({
                "t": "text", "seq": 900000 + sid, "name": f"格{sid}说明", "group": None,
                "abs": True, "lines": max(1, txt.count("\n") + 1),
                "box": [round(box[0]), round(box[1]), box[2], box[3]],
                "text": txt, "color": color, "fs": fs, "lh": lh})

        for sid, r in detail.items():
            it = next((x for x in cells if x.get("seq") == sid), None)
            if it is not None and r.get("art"):
                it["src"] = r["art"]["src"]
                it["char"], it["form"] = r["art"].get("char"), r["art"].get("form")
                art_n += 1
            if r.get("textChanged"):
                if r.get("textFrom"):
                    replaced.add(int(r["textFrom"]))
                txt = (r.get("text") or "").strip()
                if txt:
                    push_text(sid, it, r.get("textBox") or [0, 0, 300, 44], txt,
                              r.get("textColor") or "#ffffff", r.get("textFs"), r.get("textLh"))

        if replaced:
            items = [x for x in items if x.get("seq") not in replaced]
        items.extend(extra_texts)

        dropped = 0
        for it in items:
            if it.get("abs"):
                continue
            d0 = drop_of(it.get("group"), it.get("name"))
            if d0:
                it["box"] = [it["box"][0], it["box"][1] + d0, it["box"][2], it["box"][3]]
                dropped += 1

        print(f"已按格位表摆放：{moved} 格换过头像，{drained} 格空出，"
              f"{art_n} 格换成头像库素材，{len(extra_texts)} 处说明文字")
        if news:
            print(f"网页新增格位 {len(news)} 个，因加格整体下移 {dropped} 个图层")

    edits_path = WEB / "psb_edits.json"
    applied = 0
    if edits_path.exists():
        ed = json.loads(edits_path.read_text(encoding="utf-8"))
        by_seq = {int(l["seq"]): l for l in ed.get("layers", [])}
        kept = []
        for it in items:
            e = by_seq.get(it["seq"])
            if not e:
                kept.append(it); continue
            if e.get("hidden"):
                applied += 1; continue
            if e.get("pos"):
                it["box"][0], it["box"][1] = e["pos"]
            if e.get("text") is not None:
                it["text"] = e["text"]
                it["lines"] = max(1, e["text"].count("\n") + 1)
            if e.get("char"):
                it["char"], it["form"] = e["char"], e.get("form")
            applied += 1
            kept.append(it)
        items = kept

    # 属性栏背板随格位加长：取最靠下的格底 + 原稿余量，五栏一起延长同样的量
    panel_bot = max([it["box"][1] + it["box"][3] for it in items
                     if it.get("name") == "矩形 1" and it.get("group")] or [0])
    cell_bot = {}
    for it in items:
        if it.get("cell") and it.get("group"):
            cell_bot[it["group"]] = max(cell_bot.get(it["group"], 0), it["box"][1] + it["box"][3])
    attr_grow = max([0] + [v + ATTR_PAD - panel_bot for v in cell_bot.values()])
    for it in items:
        if it.get("name") == "矩形 1" and it.get("group"):
            it["box"][3] += attr_grow

    # 背板往下延长后，画布底跟着走，且保持原稿里「背板底 → 画布底」那段版脚空间不变
    tail_room = max(40, (H + shift["__tail__"]) - panel_bot) if panel_bot else 40
    H += shift["__tail__"] + sum(down.values())    # 自动留白与加格撑高后，画布跟着加高
    H = max(H, panel_bot + attr_down + attr_grow + tail_room)
    # 版脚（底边、人物持立牌）贴着黑底最下端：黑底跟着画布走，版脚再跟着黑底走
    tail = [it for it in items if it.get("name") in ("底边", "人物持立牌图片")]
    tail_bot = max([it["box"][1] + it["box"][3] for it in tail] or [0])
    if tail and tail_bot < H:
        for it in tail:
            it["box"][1] += H - tail_bot

    # 格下说明栏：跟编辑器同一条规矩归到格位（紧贴格底 0~35px、水平居中、一洞一条），
    # 并且栏宽不超过头像宽度。原稿里有 9 条说明画得比头像还宽（最宽 429 对 320），
    # 编辑器早就收进格宽了，面板与网页成品页读的是这份数据，也得收，否则两边不一致。
    slots = [{"id": it["seq"], "box": it["box"]} for it in items if it.get("cell")]
    texts = [{"seq": it["seq"], "box": it["box"]} for it in items if it["t"] == "text"]
    owner = attach_slot_texts(slots, texts)
    by_seq = {it["seq"]: it for it in items}
    capped, caps = 0, 0
    for t in texts:
        s = owner.get(t["seq"])
        if s is None:
            continue
        cell, cap = by_seq[s["id"]], by_seq[t["seq"]]
        w = min(cap["box"][2], cell["box"][2])
        if w < cap["box"][2]:
            capped += 1
        cap["box"][0] = round(cap["box"][0] + (cap["box"][2] - w) / 2)   # 与编辑器同一算式
        cap["box"][2] = round(w)
        cap["cap"] = True
        caps += 1

    # 整版数据独立成文件：网页成品页、编辑器、面板读的是同一份
    board = {"w": W, "h": H,
             "bases": {"layers": "layers/", "faces": "faces/"},
             "items": items, "grades": grades}
    dump = json.dumps(board, ensure_ascii=False)
    # 统一写 LF：本机（Windows）默认会写成 CRLF，云上构建写 LF，
    # 两边字节不一致就会每次自动重建都多出一个「没有实际改动」的提交
    (WEB / "board.json").write_text(dump, encoding="utf-8", newline="\n")
    (WEB / "board_data.js").write_text("window.BOARD_DATA = " + dump + ";\n",
                                       encoding="utf-8", newline="\n")
    shutil.copy2(TMP / "board.js", WEB / "board.js")   # 渲染实现只有一份，面板侧从同一处复制
    (WEB / "index.html").write_text(HTML_TMPL, encoding="utf-8", newline="\n")
    n_img = sum(1 for i in items if i["t"] == "img")
    print(f"网页 -> {WEB / 'index.html'}（数据 board.json、渲染 board.js）"
          + (f"（已应用编辑改动 {applied} 处）" if applied else ""))
    print(f"图层 {len(items)} 个（图 {n_img} / 文字 {len(items) - n_img}）；待定身份 {len(set(pending))} 个")
    print(f"格下说明栏 {caps} 条，其中 {capped} 条超出头像宽度、已收进格宽并居中")
    for p in sorted(set(pending)):
        print("   ", p)


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<title>强度榜 PSB 整版实验稿</title>
<style>
  :root { --z: 0.26; }
  html,body { margin:0; background:#15171c; color:#dfe3ec;
              font-family:"Microsoft YaHei","Segoe UI",sans-serif; }
  #bar { position:sticky; top:0; z-index:99; display:flex; align-items:center; gap:10px;
         padding:10px 14px; background:#1b1e26; border-bottom:1px solid #2e3342; flex-wrap:wrap; }
  #bar b { font-size:13px; }
  #bar .hint { font-size:12px; color:#98a0b3; }
  button { background:#222634; color:#dfe3ec; border:1px solid #2e3342; border-radius:7px;
           padding:5px 12px; font-size:12px; cursor:pointer; }
  button.on { border-color:#6ea8fe; color:#8fb8f5; }
  #wrap { padding:16px; overflow:auto; }
  #stage { position:relative; background:#303030;
           transform-origin:0 0; transform:scale(var(--z)); }
  .lb { position:absolute; white-space:pre; }
  .lyr { position:absolute; }
  .lyr img { width:100%; height:100%; display:block; }
  .ring { position:absolute; inset:0; box-sizing:border-box; border-style:solid;
          pointer-events:none; z-index:3; }
  .tag { position:absolute; left:0; top:-17px; font-size:11px; color:#8fb8f5;
         background:#11131acc; padding:0 4px; border-radius:4px; display:none; white-space:nowrap; }
  body.tags .cell .tag { display:block; }
  .cell.blank { outline:2px dashed #464d60; outline-offset:-2px; }
  .cell.ph { outline:3px solid #fedd62; outline-offset:-3px; }   /* 补齐档位的金框空位 */
</style></head><body>
<div id="bar">
  <b>强度榜 PSB 整版实验稿</b>
  <span class="hint">版式与素材取自 PSB 原稿；角色格只显示实际挂上的头像（面板形象或头像库素材）</span>
  <button id="bTags">显示图层名</button>
  <button id="bBig">隐藏整图底</button>
  <button id="bZoomOut">缩小</button>
  <button id="bZoomIn">放大</button>
  <span class="hint" id="ztext"></span>
</div>
<div id="wrap"><div id="stage"></div></div>
<script src="board_data.js"></script>
<script src="board.js"></script>
<script>
/* 渲染实现只有一份（board.js）：网页成品页与面板只读页都调它，版面永远一致 */
BoardView.create(document.getElementById("stage"), window.BOARD_DATA);
</script></body></html>
"""

if __name__ == "__main__":
    main()
