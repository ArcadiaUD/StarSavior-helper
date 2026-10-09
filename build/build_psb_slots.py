# -*- coding: utf-8 -*-
r"""格位式编辑器：格位固定、头像可换，右侧头像库调游戏内素材拖入洞中，每洞下方带可编辑文字栏。

用法:
    python build_psb_slots.py
输出:
    E:/AI/TempFiles/psb_web/editor.html
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

# 本机跑与仓库里跑（GitHub Actions）根目录不同，用环境变量切换，之后的逻辑完全一致
TMP = Path(os.environ.get("PSB_TMP") or r"E:/AI/TempFiles")
PANEL = Path(os.environ.get("PSB_PANEL") or r"E:/AI/WORK/StarSavior-helper/未打包/V1.0")
WEB = TMP / "psb_web"
LAYERS = TMP / "psb_layers"
FULL = TMP / "psb_full.png"

SLOT_GROUPS = {"全场景必练T0", "全场景必练T0.5", "T1功能角色", "T2功能角色",
               "光系", "暗系", "火系", "水系", "草系"}
NOT_SLOT = {"矩形 1", "光标"}          # 栏位背板与箭头，不是头像位
DROP_TEXT = {"查无此人"}               # 暗系 T3 补了空位框，原稿那行占位字样去掉
BIG = {"背景", "图层 1", "底边"}

INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00a0"), None)


def clean_name(s):
    """游戏原文里形态名夹着零宽字符（如「无瑕蓝玫瑰」末尾一个），查表前先归一化，
    否则查不到就会悄悄退回原型的脸和原型的稀有度。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "").translate(INVISIBLE))


def face_src(rec):
    """头像记录 → (stem, 图片路径)：先取小头像，再取大头像；面板脸库里没有就退回 codex 目录。"""
    for key in ("face_small", "face"):
        if not rec.get(key):
            continue
        stem = Path(rec[key]).stem
        for sub in ("faces", "codex"):
            p = PANEL / "assets" / sub / f"{stem}.webp"
            if p.exists():
                return stem, p
    return None, None

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


def attr_grid_normalize(cells, labels, tol=None):
    """把五个属性栏重排到同一套网格上：档内行距、两列列距、标签到首排的间距全部统一。

    原稿这五栏是手摆的：同一档内相邻两排的间距在 224~343 之间跳，档位标签到首排头像
    24~44 不等，同一排的两格还差一两像素，草系左列甚至从 2996 飘到 3005。
    这里按「五栏首排对齐同一条横线、档内每排间距 ATTR_ROW、两列间距 ATTR_COL、
    标签底边到首排 ATTR_GAP_TOP、本档最下排底边到下一档标签 ATTR_GAP_TIER」
    重算全部坐标；档位顺序、每档的排数与列数、标签自身尺寸都不动。

    cells 需带 group 与 box（就地改 box 的 x/y 与边长）；labels 需带 group、box 与 text。
    返回 {组: (档数, 排数, 最下排底边)}，供构建时打印。
    """
    plan = []
    tol = ALIGN_ROW_TOL if tol is None else tol
    for g in ATTR_ORDER:
        mine = [c for c in cells if c.get("group") == g]
        tags = sorted((t for t in labels if t.get("group") == g), key=lambda t: t["box"][1])
        if not mine or not tags:
            continue
        rows = []
        for c in sorted(mine, key=lambda c: c["box"][1]):
            if rows and c["box"][1] - rows[-1][0]["box"][1] <= tol:
                rows[-1].append(c)
            else:
                rows.append([c])
        rows = [sorted(r, key=lambda c: c["box"][0]) for r in rows]
        tiers = [[] for _ in tags]
        for r in rows:                       # 每一排归到它上方最近的那个档位标签
            above = [i for i, t in enumerate(tags) if t["box"][1] <= r[0]["box"][1]]
            tiers[above[-1] if above else 0].append(r)
        wide = [r for r in rows if len(r) == max(len(x) for x in rows)]
        ref = Counter(min(c["box"][0] for c in r) for r in wide).most_common(1)[0][0]
        plan.append((g, tags, tiers, ref))

    if not plan:
        return {}
    firsts = []
    for _, _, tiers, _ in plan:
        for t_rows in tiers:
            if t_rows:
                firsts.append(t_rows[0][0]["box"][1])
                break
    top = Counter(firsts).most_common(1)[0][0]

    out = {}
    for g, tags, tiers, ref in plan:
        rtop, n, bottom = top, 0, top
        for i, (t, t_rows) in enumerate(zip(tags, tiers)):
            t["box"][1] = rtop - t["box"][3] - ATTR_GAP_TOP
            t["box"][0] = round(ref + (ATTR_COL + ATTR_CELL - t["box"][2]) / 2)   # 水平居中于本栏两列
            for k, r in enumerate(t_rows):
                for j, c in enumerate(r):
                    c["box"][0] = ref + j * ATTR_COL
                    c["box"][1] = rtop + k * ATTR_ROW
                    c["box"][2] = c["box"][3] = ATTR_CELL
                n += 1
            if t_rows:
                bottom = rtop + (len(t_rows) - 1) * ATTR_ROW + ATTR_CELL
            if i + 1 < len(tags):
                rtop += max(0, len(t_rows) - 1) * ATTR_ROW + ATTR_CELL + ATTR_GAP_TIER \
                        + ATTR_TAG_H + ATTR_GAP_TOP
        out[g] = (len(tags), n, bottom)
    return out


def attach_slot_texts(slots, texts):
    """格下说明文字归位：紧贴格位底部（0~35px）、水平居中于格位（中心差 <60px）；一洞只接管一条。

    收紧这两个阈值是为了不误抓档位标题（T1功能角色…）与属性栏的 T0~T4 标签——
    它们同样落在格位下方，但离格底 43px 以上、且是分组标签，不是格子的说明。
    编辑器与静态版共用这条规则。slots 元素需带 box 与 id（或 seq），texts 需带 box 与 seq。
    返回 {文字 seq: 格位}。
    """
    key = lambda s: s["id"] if "id" in s else s["seq"]
    out, used = {}, set()
    for t in texts:
        tc = t["box"][0] + t["box"][2] / 2
        hit, best = None, None
        for s in slots:
            if key(s) in used:
                continue
            sc = s["box"][0] + s["box"][2] / 2
            bot = s["box"][1] + s["box"][3]
            if abs(tc - sc) < 60 and 0 <= t["box"][1] - bot <= 35:
                if best is None or abs(tc - sc) < best:
                    best, hit = abs(tc - sc), s
        if hit is not None:
            used.add(key(hit))
            out[t["seq"]] = hit
    return out


# ---- 自动留白：每个大类整体下移，给格位下方的文字栏腾出 2~3 行行高 ----
GAP_ROWS = 3                    # 格位底到下一档标题之间留出的行数
DEFAULT_LH = 50                 # 参照行高，与文字栏默认规格一致
TOWER_GROUPS = ["全场景必练T0", "全场景必练T0.5", "T1功能角色", "T2功能角色"]
ATTR_ORDER = ["光系", "暗系", "火系", "水系", "草系"]
ATTR_KEY = "__attr__"
ATTR_TITLE_PREFIX = "全属性梯度"      # 属性栏的大标题，图层未归组，须手动并入
TAIL_NAMES = {"底边", "人物持立牌图片"}      # 版脚装饰，随最后一个大类一起下移
GROW_NAMES = {"图层 1"}        # 铺满整幅的黑色底图：高度跟着画布走，加多少格都盖到底
ALIGN_ROW_TOL = 30             # 属性栏「同一行」的容差：原稿手摆坐标差一两像素

# 作者原稿里没画的档位，按本栏的档间距续排补上，各给一个金框空位占位（原稿坐标）
PLACEHOLDER_TIERS = (
    # 组, 档位标签, 标签框, 空位框
    ("光系", "T3", [327, 4282, 92, 58], [149, 4384, 213, 213]),
    ("光系", "T4", [327, 4639, 92, 58], [149, 4741, 213, 213]),
    ("暗系", "T3", None,                [857, 4383, 213, 213]),
    ("光系", "T2", [327, 3925, 92, 58], [149, 4027, 213, 213]),
)
PLACEHOLDER_TAG_SEQ = 8601     # 补出来的档位标签占的图层号
PLACEHOLDER_SLOT_ID = 7001     # 补出来的空位占的格位号（避开网页上加格的 1000 起编号）
ATTR_PAD = 297                 # 原稿里最紧那一栏（草系）背板底到最下格底的余量，延长时照抄
ATTR_ROW = 230                 # 属性栏同一档内相邻两排的纵向间距（原稿里最常见的档内间距）
ATTR_COL = 232                 # 属性栏两列之间的横向间距（原稿里三栏都是 232）
ATTR_CELL = 213                # 属性栏头像格的统一边长
ATTR_GAP_TOP = 44              # 档位标签底边 → 本档首排头像顶边
ATTR_GAP_TIER = 42             # 本档最下排头像底边 → 下一档档位标签顶边
ATTR_TAG_H = 59                # 档位标签的名义高度，用来推下一档首排的位置
ATTR_STEP = ATTR_ROW           # 属性栏就地插行时，下面内容让开的一行


def headroom_shift(raw, gap_rows=GAP_ROWS, lh=DEFAULT_LH):
    """算出各组的整体下移量：把「上一档格位底 → 本档标题顶」的间隙补足到 gap_rows 行行高。

    下移是累积的——某一档补了多少，它后面所有档一起跟着走，所以每档头像行下方
    都会空出同样多的位置放说明栏。下半部五个属性栏纵向共用同一区间，算作一个大类；
    版脚装饰随最后一个大类一起走。
    """
    need = gap_rows * lh
    top, bot = {}, {}
    for it in raw:
        y0, y1 = ((it["y"], it["y"] + it["h"]) if it["kind"] == "img"
                  else (it["bbox"][1], it["bbox"][3]))
        g = it.get("group")
        if g:
            top[g] = min(top.get(g, y0), y0)
            if it["kind"] == "img" and it["name"] not in NOT_SLOT:
                bot[g] = max(bot.get(g, y1), y1)
        if g == ATTR_KEY or it["name"].startswith(ATTR_TITLE_PREFIX):
            top[ATTR_KEY] = min(top.get(ATTR_KEY, y0), y0)
            bot[ATTR_KEY] = max(bot.get(ATTR_KEY, y1), y1)
    for g in ATTR_ORDER:
        top[ATTR_KEY] = min(top.get(ATTR_KEY, top[g]), top[g])
        bot[ATTR_KEY] = max(bot.get(ATTR_KEY, bot[g]), bot[g])
    out, prev, prev_bot = {}, 0, None
    for g in TOWER_GROUPS + [ATTR_KEY]:
        if prev_bot is not None:
            prev += max(0, need - (top[g] - prev_bot))
        out[g] = prev
        for name in (ATTR_ORDER if g == ATTR_KEY else [g]):
            out[name] = prev
        prev_bot = bot[g]
    out["__tail__"] = prev
    return out


def group_dy(shift):
    """图层下移量：本组自己的偏移；属性栏大标题并入属性栏；版脚装饰跟随末尾大类。"""
    def f(name, group):
        if group in shift:
            return shift[group]
        if name.startswith(ATTR_TITLE_PREFIX):
            return shift[ATTR_KEY]
        return shift["__tail__"] if name in TAIL_NAMES else 0
    return f


def ring_width(path):
    """量这个格位图原本的描边宽度（作者统一画的金色细框），新边框要正好盖在它上面。"""
    im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim != 3 or im.shape[2] != 4:
        return 0
    h, w = im.shape[:2]

    def gold(px):
        b, g, r, a = (int(v) for v in px)
        return a > 200 and r > 180 and g > 150 and b < 160

    def run(seq):
        n = 0
        for p in seq:
            if not gold(p):
                break
            n += 1
        return n
    mid_row, mid_col = im[h // 2], im[:, w // 2]
    return max(run(mid_row), run(mid_row[::-1]), run(mid_col), run(mid_col[::-1]))


def slot_bg(path):
    """格位框内的底色。

    原稿格位图是「金框 + 浅色底 + 立绘 + 职业角标」压平的一张图，立绘抠不掉，
    所以删掉整张、只把这层底色取出来，格位改用底色 + 稀有度环来画。
    取四角内侧若干像素的中位数：立绘居中、角标只压一角，中位数仍落在底色上。
    """
    im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim != 3:
        return "#2b3038"
    h, w = im.shape[:2]
    pts = [(30, 30), (30, w - 31), (h - 31, 30), (h - 31, w - 31),
           (h // 2, 34), (h // 2, w - 35)]
    cols = []
    for y, x in pts:
        if not (0 <= y < h and 0 <= x < w):
            continue
        px = im[y, x]
        if len(px) == 4 and px[3] < 128:
            continue
        cols.append(px[:3])
    if not cols:
        return "#2b3038"
    b, g, r = (int(v) for v in np.median(np.array(cols), axis=0))
    return f"#{r:02x}{g:02x}{b:02x}"


TEXT_COLORS = TMP / "psb_textcolor.json"


def text_colors():
    """文字层自己的填充色（作者在 PS 里设的），按原稿位置索引；读不到就返回空表。"""
    try:
        rows = json.loads(TEXT_COLORS.read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return {}
    return {tuple(r["bbox"]): r["fill"] for r in rows if r.get("fill")}


def text_color(full, box):
    """取这段文字本身的颜色。

    区域里文字只占一小部分，所以比较上下两端的偏离程度，取偏离更大的那一侧：
    深底白字取最亮像素，浅底黑字取最暗像素。只按「取最亮」会在浅色底上把底色取成字色。
    """
    x, y, w, h = box
    crop = full[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        return "#d8dbe3"
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hi, lo = np.percentile(gray, 92), np.percentile(gray, 8)
    med = np.percentile(gray, 50)
    mask = (gray >= hi) if (hi - med) >= (med - lo) else (gray <= lo)
    if mask.sum() < 10:
        mask = np.ones_like(gray, bool)
    b, g, r = [int(crop[:, :, i][mask].mean()) for i in range(3)]
    return f"#{r:02x}{g:02x}{b:02x}"


def role_grades():
    """角色名 / 角色名|形态名 → SSR / SR。形态名统一去掉零宽字符，免得跟格位上的形态名对不上。"""
    codex = json.loads((PANEL / "out" / "codex.json").read_text(encoding="utf-8"))
    out = {}
    for c in codex["roster"]:
        out[c["name"]] = c.get("grade") or ""
        for f in (c.get("forms") or []):
            out[c["name"] + "|" + clean_name(f["title"])] = f.get("grade") or c.get("grade") or ""
    return out


def face_index():
    codex = json.loads((PANEL / "out" / "codex.json").read_text(encoding="utf-8"))
    out_dir = WEB / "faces"
    out_dir.mkdir(parents=True, exist_ok=True)
    idx, copied, roster, grades = {}, {}, [], {}
    for c in codex["roster"]:
        forms, titles = {}, []
        grades[c["name"]] = c.get("grade") or ""
        # 空形态名 = 原型自己的脸，跟各形态并列放进同一张表
        stem, src = face_src(c)
        if stem:
            forms[""] = f"faces/{stem}.webp"
            copied[stem] = src
        for f in (c.get("forms") or []):
            title = clean_name(f["title"])
            titles.append(title)
            grades[c["name"] + "|" + title] = f.get("grade") or c.get("grade") or ""
            stem, src = face_src(f)
            if stem:
                forms.setdefault(title, f"faces/{stem}.webp")
                copied[stem] = src
        idx[c["name"]] = forms
        roster.append({"n": c["name"], "f": titles})
    for stem, src in copied.items():
        dst = out_dir / f"{stem}.webp"
        if not dst.exists():
            shutil.copy2(src, dst)
    return idx, roster, grades


def build():
    doc = json.loads((LAYERS / "layers.json").read_text(encoding="utf-8"))
    raw, (W, H) = doc["items"], doc["size"]
    full = cv2.imdecode(np.fromfile(FULL, dtype=np.uint8), cv2.IMREAD_COLOR)
    faces, roster, grades = face_index()
    tc = text_colors()
    lib = sorted(({"c": cn, "f": fn, "s": sp} for cn, forms in faces.items() for fn, sp in forms.items()
                  if fn),                       # 空形态名是原型自己的脸，只用来兜底，不进左侧头像库列表
                 key=lambda x: (x["c"], x["f"]))

    dst_dir = WEB / "layers"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for it in raw:
        if it["kind"] == "img" and not (dst_dir / it["file"]).exists():
            shutil.copy2(LAYERS / it["file"], dst_dir)

    slots, others = [], []
    shift = headroom_shift(raw)
    dy = group_dy(shift)
    for it in raw:
        name, grp = it["name"], it.get("group")
        d = dy(name, grp)
        is_slot = it["kind"] == "img" and grp in SLOT_GROUPS and name not in NOT_SLOT
        if is_slot:
            who = LAYER_MAP.get(name, (None, None))
            face = None
            if who[0] in faces:
                forms = faces[who[0]]
                face = forms.get(clean_name(who[1])) or forms.get("")
            slots.append({"id": it["seq"], "name": name, "group": grp, "file": it["file"],
                          "box": [it["x"], it["y"] + d, it["w"], it["h"]],
                          "attr": grp in ATTR_ORDER,
                          "ring": max(ring_width(LAYERS / it["file"]) + 2,
                                      round(it["w"] * 0.025)),
                          "bg": slot_bg(LAYERS / it["file"]),
                          "char": who[0], "form": who[1], "face": face})
            continue
        if it["kind"] == "text":
            txt = (it.get("text") or "").replace("\r", "\n").strip()
            if not txt or txt in DROP_TEXT:
                continue
            bx = it["bbox"]
            src = [bx[0], bx[1], bx[2] - bx[0], bx[3] - bx[1]]     # 取色要按原稿位置
            others.append({"t": "text", "seq": it["seq"], "name": name, "group": grp,
                           "box": [src[0], src[1] + d, src[2], src[3]],
                           "text": txt, "lines": max(1, txt.count("\n") + 1),
                           "color": tc.get(tuple(bx)) or text_color(full, src)})
            continue
        others.append({"t": "img", "seq": it["seq"], "name": name, "group": grp,
                       "box": [it["x"], it["y"] + d, it["w"], it["h"]], "file": it["file"],
                       "big": name in BIG, "grow": name in GROW_NAMES,
                       "bg": name in BIG or name in NOT_SLOT})

    # 补齐原稿没画的档位（光系 T2/T3/T4、暗系 T3）：档位标签 + 一个金框空位
    for k, (grp, label, lbox, sbox) in enumerate(PLACEHOLDER_TIERS):
        d = dy("", grp)
        if lbox:                              # 该档原本没有标签（暗系 T3 已有）就不补标签
            others.append({"t": "text", "seq": PLACEHOLDER_TAG_SEQ + k, "name": label,
                           "group": grp, "text": label, "lines": 1, "color": "#ffffff",
                           "box": [lbox[0], lbox[1] + d, lbox[2], lbox[3]]})
        slots.append({"id": PLACEHOLDER_SLOT_ID + k, "name": label + "空位", "group": grp,
                      "file": "", "box": [sbox[0], sbox[1] + d, sbox[2], sbox[3]],
                      "attr": True, "ph": True, "ring": 0, "bg": "transparent",
                      "char": None, "form": None, "face": None})

    # 属性栏重排到同一套网格：档内行距、两列列距、档位标签到首排的间距都统一
    grid = attr_grid_normalize(
        [s for s in slots if s["attr"]],
        [o for o in others if o["t"] == "text" and o["group"] in ATTR_ORDER
         and o["text"].strip()[:1] == "T" and o["text"].strip()[1:].isdigit()])

    # 格下说明文字归到格位，成为该洞下方的可编辑文字栏
    texts = [o for o in others if o["t"] == "text"]
    owned = attach_slot_texts(slots, texts)
    for t in texts:
        s = owned.get(t["seq"])
        if s is not None:
            s["text"] = {"text": t["text"], "color": t["color"], "box": t["box"],
                         "lines": t["lines"], "from": t["seq"]}
    taken = set(owned)
    others = [o for o in others if o["seq"] not in taken]

    H += shift["__tail__"]                       # 整版下移后画布跟着加高

    # 角色 → 面板头像：格位不再挂原稿立绘，改按身份查这张表取图
    facemap = {}
    for cn, forms in faces.items():
        if not forms:
            continue
        for fn, sp in forms.items():
            facemap[cn + "|" + fn] = sp
        facemap[cn] = forms.get("") or next(iter(forms.values()))

    # 每个属性栏的背板矩形：属性栏加格不得越出这个框
    panel = {}
    for it in raw:
        if it["name"] == "矩形 1" and it["kind"] == "img" and it.get("group") in ATTR_ORDER:
            panel[it["group"]] = [it["x"], it["y"] + dy("矩形 1", it["group"]), it["w"], it["h"]]

    html = (HTML_TMPL.replace("__SLOTS__", json.dumps(slots, ensure_ascii=False))
                     .replace("__OTHERS__", json.dumps(others, ensure_ascii=False))
                     .replace("__ROSTER__", json.dumps(roster, ensure_ascii=False))
                     .replace("__GRADES__", json.dumps(grades, ensure_ascii=False))
                     .replace("__FACES__", json.dumps(facemap, ensure_ascii=False))
                     .replace("__PANEL__", json.dumps(panel, ensure_ascii=False))
                     .replace("__LIB__", json.dumps(lib, ensure_ascii=False))
                     .replace("__ATTRPAD__", str(ATTR_PAD))
                     .replace("__ATTRSTEP__", str(ATTR_STEP))
                     .replace("__W__", str(W)).replace("__H__", str(H)))
    (WEB / "editor.html").write_text(html, encoding="utf-8")
    print(f"格位编辑器 -> {WEB / 'editor.html'}")
    print(f"自动留白（每档格位下方留 {GAP_ROWS} 行）: "
          + "、".join(f"{g.replace(ATTR_KEY, '五属性栏')} 下移 {shift[g]}"
                      for g in TOWER_GROUPS + [ATTR_KEY]))
    print(f"格位 {len(slots)}；其他图层 {len(others)}；角色 {len(roster)}；头像库 {len(lib)} 张")
    print("属性栏网格（行距 %d / 列距 %d / 标签到首排 %d）: " % (ATTR_ROW, ATTR_COL, ATTR_GAP_TOP)
          + "、".join(f"{g} {m}档{n}格 底{b}" for g, (m, n, b) in grid.items()))
    print(f"格下文字栏预填 {sum(1 for s in slots if 'text' in s and not s['attr'])} 个"
          f"（属性栏 {sum(1 for s in slots if s['attr'])} 个格位不设说明栏）")
    pend = sorted({s["name"] for s in slots if not s["char"] and not s.get("ph")})
    print(f"身份待定格位 {len(pend)}: {pend}")


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<title>强度榜格位编辑器</title>
<style>
  :root { --z: 0.26; }
  html,body { margin:0; background:#15171c; color:#dfe3ec;
              font-family:"Microsoft YaHei","Segoe UI",sans-serif; }
  #bar { display:flex; align-items:center; gap:8px;
         padding:8px 12px; background:#1b1e26; border-bottom:1px solid #2e3342; flex-wrap:wrap; }
  #head { position:sticky; top:0; z-index:98; }
  #bar b { font-size:13px; }
  .hint { font-size:12px; color:#98a0b3; }
  button { background:#222634; color:#dfe3ec; border:1px solid #2e3342; border-radius:7px;
           padding:5px 11px; font-size:12px; cursor:pointer; }
  button.on { border-color:#6ea8fe; color:#8fb8f5; }
  button:disabled { opacity:.4; cursor:default; }
  #toast { position:fixed; left:50%; top:66px; transform:translateX(-50%); z-index:120;
           background:#2a3040; border:1px solid #3d4560; color:#dfe3ec; font-size:13px;
           padding:8px 14px; border-radius:8px; opacity:0; transition:opacity .18s;
           pointer-events:none; }
  #toast.on { opacity:1; }
  #wrap { padding:16px; overflow:auto; }
  #fit { position:relative; width:calc(__W__px * var(--z)); height:calc(__H__px * var(--z)); }
  #stage { position:absolute; top:0; left:0; width:__W__px; height:__H__px; background:#303030;
           transform-origin:0 0; transform:scale(var(--z)); }
  .lb { position:absolute; white-space:pre; }
  .bg { position:absolute; pointer-events:none; }
  .bg img { width:100%; height:100%; display:block; }
  /* 素材可拖模式：只有真正铺满整幅的大底图让点击穿透，其余素材都能被鼠标命中 */
  body.pickbg .bg:not(.wall) { pointer-events:auto; cursor:move; }
  body.pickbg .bg:not(.wall):hover { outline:1px dashed #6ea8fe; }
  .slot { position:absolute; cursor:grab; }
  .slot img { width:100%; height:100%; display:block; pointer-events:none;
              position:relative; z-index:1; }
  .ring { position:absolute; inset:0; box-sizing:border-box; border-style:solid;
          pointer-events:none; z-index:3; }
  body.frames .slot::before, body.frames .slot::after {
    content:""; position:absolute; width:26%; height:26%; pointer-events:none;
    border:6px solid #8ab4ff; z-index:2; box-sizing:border-box; }
  body.frames .slot::before { left:0; top:0; border-right:0; border-bottom:0; }
  body.frames .slot::after  { right:0; bottom:0; border-left:0; border-top:0; }
  .slot.empty { outline:3px dashed #ff8b8b; background:#000000aa; }
  .slot.blank { outline:2px dashed #464d60; outline-offset:-2px; }
  .slot.blank.empty { outline:3px dashed #ff8b8b; background:#000000aa; }
  .slot.ph { outline:3px solid #fedd62; outline-offset:-3px; }   /* 补齐档位的金框空位 */
  .slot.empty img { display:none; }
  .slot.dragging img { opacity:.2; }
  .slot.drop { outline:4px solid #6ea8fe; outline-offset:-3px; background:#6ea8fe33; }
  .slot.sel { outline:2px solid #6ea8fe; outline-offset:-2px; }
  .slot.fromlib img { box-shadow:inset 0 0 0 3px #5fd3a0; }
  .sltext { position:absolute; white-space:pre-wrap; overflow-wrap:anywhere;
            cursor:text; border-radius:4px; padding:1px 3px; }
  .sltext.hint { overflow:hidden; background:#8fb8f526; border-bottom:3px dashed #8fb8f599; }
  .sltext.hint.open { background:#00000066; border-bottom-color:#6ea8fe; }
  .sltext:focus { outline:2px solid #6ea8fe; background:#00000066; }
  .sltext:empty::before { content:"＋ 填说明"; color:#8fb8f580; }
  .tag { position:absolute; left:0; top:-17px; font-size:11px; color:#8fb8f5;
         background:#11131acc; padding:0 4px; border-radius:4px; display:none; white-space:nowrap; }
  body.tags .slot .tag { display:block; }
  body.tags .slot.pending .tag { color:#ff8b8b; }
  #ghost { position:fixed; pointer-events:none; z-index:9999; opacity:.85;
           outline:2px solid #6ea8fe; border-radius:4px; overflow:hidden;
           box-shadow:0 6px 18px #000a; }
  #ghost img { width:100%; height:100%; display:block; }
  #libBtn { position:fixed; right:16px; top:44%; z-index:60; writing-mode:vertical-rl;
            padding:14px 8px; font-size:13px; letter-spacing:2px;
            background:#1b1e26; border:1px solid #2e3342; border-radius:10px; }
  #libBtn.on { border-color:#6ea8fe; color:#8fb8f5; }
  body.libopen #libBtn { right:330px; }
  #lib { position:fixed; right:0; top:46px; bottom:0; width:312px; z-index:120;
         background:#15171cf5; border-left:1px solid #2e3342; display:none;
         flex-direction:column; }
  #lib.open { display:flex; }
  #lib .hd { padding:10px 12px; border-bottom:1px solid #2e3342; display:flex;
             align-items:center; gap:8px; font-size:13px; }
  #lib .hd input { flex:1; background:#101319; color:#dfe3ec; border:1px solid #2e3342;
                   border-radius:6px; padding:5px 8px; font-size:12px; }
  #lib .bd { flex:1; overflow:auto; padding:10px; display:grid; gap:8px;
             grid-template-columns:repeat(3, 1fr); align-content:start; }
  .libItem { cursor:grab; text-align:center; }
  .libItem img { width:100%; aspect-ratio:1/1; object-fit:cover; border-radius:8px;
                 border:1px solid #2e3342; display:block; background:#0e1116; }
  .libItem span { font-size:10px; color:#98a0b3; display:block; margin-top:3px;
                  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .libItem:hover img { border-color:#6ea8fe; }
  #insp { position:fixed; right:14px; bottom:14px; width:268px; background:#1b1e26ee;
          border:1px solid #2e3342; border-radius:10px; padding:10px 12px; font-size:12px;
          box-shadow:0 6px 24px #0008; display:none; z-index:61; }
  #insp .t { font-weight:700; margin-bottom:6px; word-break:break-all; }
  #insp .r { display:flex; align-items:center; gap:6px; margin:5px 0; flex-wrap:wrap; }
  #insp select { flex:1; background:#101319; color:#dfe3ec; border:1px solid #2e3342;
          border-radius:5px; padding:3px; font-size:12px; }
  .sub { color:#98a0b3; }
  #textbar { display:none; align-items:center; gap:8px; flex-wrap:wrap;
            padding:8px 12px; background:#1b1e26; border-bottom:1px solid #2e3342; font-size:12px; }
  #textbar.on { display:flex; }
  #textbar .t { font-weight:700; }
  #textbar select { background:#101319; color:#dfe3ec; border:1px solid #2e3342;
                   border-radius:5px; padding:3px 6px; font-size:12px; max-width:340px; }
  #textbar input[type=number], #textbar input[type=text] { background:#101319; color:#dfe3ec;
                   border:1px solid #2e3342; border-radius:5px; padding:3px 6px; font-size:12px; }
  #textbar input[type=number] { width:62px; }
  #textbar input[type=text] { width:280px; }
  #textbar input[type=color] { width:34px; height:22px; padding:0; background:#101319;
                   border:1px solid #2e3342; border-radius:5px; }
  #textbar button.on { background:#2a3b5c; border-color:#6ea8fe; color:#dfe3ec; }
  #textbar input:disabled, #textbar select:disabled, #textbar button:disabled { opacity:.45; }
  #textbar .sep { width:1px; height:20px; background:#2e3342; margin:0 4px; }
  #textbar button { padding:4px 9px; font-size:12px; }
  .movable { cursor: move; }
  .movable:hover { outline:1px dashed #6ea8fe66; }
  .moving { z-index:999 !important; outline:1px dashed #6ea8fe; }
  .bg.pick, .lb.pick { outline:2px solid #fedd62; z-index:500; }
  .nt { position:absolute; white-space:pre; padding:2px 4px; border-radius:4px;
        outline:1px dashed #6ea8fe55; z-index:70; cursor:move; }
  .nt:hover { outline-color:#6ea8fe; }
  .nt[contenteditable=true] { cursor:text; outline:1px solid #6ea8fe; }
#ghbox { display:none; position:fixed; right:18px; top:60px; width:352px; z-index:900;
         background:#1b1e26; border:1px solid #2e3342; border-radius:10px; padding:14px;
         box-shadow:0 14px 34px #0009; font-size:12px; line-height:1.6; }
#ghbox.on { display:block; }
#ghbox h4 { margin:0 0 6px; font-size:13px; }
#ghbox p { margin:0 0 9px; color:#98a0b3; }
#ghbox input { width:100%; box-sizing:border-box; background:#15171c; color:#dfe3ec;
               border:1px solid #2e3342; border-radius:6px; padding:6px 8px; font-size:12px; }
#ghbox .r { display:flex; gap:8px; align-items:center; margin-top:10px; }
#ghState.ok { color:#8fd694; }
#ghState.bad { color:#f08a7a; }
</style></head><body>
<div id="head">
<div id="bar">
  <b>强度榜格位编辑器</b>
  <span class="hint">拖头像到别的洞即交换 · 右侧头像库可拖入洞中 · 说明栏：有内容的常驻显示，空的显示为一条浅色虚线，鼠标移到洞上即展开</span>
  <button id="bFrame">显示取景角标</button>
  <button id="bTags">显示图层名</button>
  <button id="bBig">隐藏整图底</button>
  <button id="bPick" class="on">素材可拖</button>
  <button id="bUndo" disabled>↶ 撤回</button>
  <button id="bAdd">＋ 格</button>
  <button id="bText">文字</button>
  <button id="bOut">缩小</button>
  <button id="bIn">放大</button>
  <button id="bSave">导出改动</button>
  <button id="bLoad">导入改动</button>
  <button id="bClear">清空改动</button>
  <button id="bGh">连接 GitHub</button>
  <button id="bPush" disabled>存到仓库</button>
  <span class="hint" id="ghState">未连接仓库</span>
  <span class="hint" id="ztext"></span>
  <input id="file" type="file" accept=".json" style="display:none">
</div>
<div id="textbar">
  <span class="t">文字</span>
  <span class="sub">条目</span><select id="tbPick"></select>
  <span class="sep"></span>
  <span class="sub">内容</span><input id="tbText" type="text" placeholder="输入文字内容">
  <span class="sub">字号</span><input id="tbFs" type="number" step="2" min="8">
  <span class="sub">颜色</span><input id="tbColor" type="color">
  <button id="tbBold">加粗</button>
  <span class="sub">X</span><input id="tbX" type="number" step="1">
  <span class="sub">Y</span><input id="tbY" type="number" step="1">
  <span class="sep"></span>
  <button id="tbNew">＋ 新建文本</button>
  <button id="tbHide">隐藏该条</button>
  <button id="tbRevert">还原该条</button>
  <span class="sub" id="tbInfo"></span>
  <button id="tbClose">关闭</button>
</div>
</div>
<div id="toast"></div>
<div id="ghbox">
  <h4>连接 GitHub（保存到仓库）</h4>
  <p>贴一个细粒度令牌：只勾选这个仓库的 <b>Contents 读写</b>，并设一个有效期。令牌只存在这台浏览器里，不会发到别处。不在仓库协作者名单里的账号即使连接成功也只能看不能存。</p>
  <input id="ghToken" type="password" placeholder="github_pat_..." autocomplete="off">
  <div class="r"><button id="ghDo">连接</button><button id="ghForget">清除令牌</button><span class="hint" id="ghMsg"></span></div>
</div>
<div id="wrap"><div id="fit"><div id="stage"></div></div></div>
<button id="libBtn">头像库</button>
<div id="lib">
  <div class="hd">游戏内头像 <input id="libQ" placeholder="搜角色名"><button id="libClose">×</button></div>
  <div class="bd" id="libList"></div>
</div>
<div id="insp">
  <div class="t" id="iName">未选中</div>
  <div class="r"><span class="sub" id="iInfo"></span></div>
  <div class="r" id="iCharRow">角色 <select id="iChar"></select></div>
  <div class="r"><button id="iEmpty">取出头像（空出该洞）</button><button id="iRevert">还原该洞</button></div>
  <div class="r"><span class="sub" id="iCount"></span><button id="iClose">取消选中</button></div>
</div>
<script>
const SLOTS = __SLOTS__;
const OTHERS = __OTHERS__;
const ROSTER = __ROSTER__;
const LIB = __LIB__;
const FACES = __FACES__;                         /* 角色名 / 角色名|形态名 → 面板头像 */
const PANEL_BOX = __PANEL__;                     /* 每个属性栏的背板矩形，加格不得越出 */
const GRADES = __GRADES__;                       /* 角色名 / 角色名|形态名 → SSR / SR */
const RARITY_COLOR = { SSR: "#fedd62", SR: "#a874e8", "": "#8b93a8" };
const stage = document.getElementById("stage");
/* 提示条：加格越界这类情况只提示一下，不用弹窗打断操作 */
let toastT = 0;
function flash(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("on");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("on"), 2400);
}
let z = 0.26, hideBig = false, sel = null, drag = null, dropTarget = null;

/* place[洞] = 该洞头像来自哪个洞；art[洞] = 该洞换成了头像库里的素材；"" 表示空出
   newSlots = 网页上新增的格位（行尾追加、满行换行）；down = 各组因新增行而增加的高度，
   按组顺序累积作用到后面所有内容上
   slotShift[格位] / layerShift[图层] = 属性栏里「就地插行」造成的个人位移：在哪个格位
   后面插了一行，那个格位以下（含档位标签 T几）就整体下移一行高 */
const edit = { place:{}, art:{}, text:{}, slotText:{}, char:{}, tstyle:{}, pos:{}, nt:[],
               newSlots:[], down:{}, slotShift:{}, layerShift:{} };
try {
  const s = JSON.parse(localStorage.getItem("psbSlots") || "null");
  if (s) for (const k of ["place","art","text","slotText","char","tstyle","pos"]) if (s[k]) edit[k] = s[k];
  if (s && s.nt) edit.nt = s.nt;
  if (s && s.newSlots) edit.newSlots = s.newSlots;
  if (s && s.down) edit.down = s.down;
  if (s && s.slotShift) edit.slotShift = s.slotShift;
  if (s && s.layerShift) edit.layerShift = s.layerShift;
} catch (e) {}
const save = () => {
  try { localStorage.setItem("psbSlots", JSON.stringify(edit)); } catch (e) {}
  const cur = snap();
  if (undoLock || undoBase === null || cur === undoBase) { undoBase = cur; return; }
  undoStack.push(undoBase);
  if (undoStack.length > UNDO_MAX) undoStack.shift();
  undoBase = cur;
  undoState();
};
const EMPTY = "";
const contentOf = id => edit.place[id] !== undefined ? edit.place[id] : id;
const isSlotEmpty = id => contentOf(id) === EMPTY;
const artOf = id => edit.art[id] || null;

/* ---- 撤回：每次提交前压一份改动快照，撤回即回到上一步 ----
   所有改动都汇聚到 save()，所以在 save 里记录上一次状态最省事，也不会漏掉操作。 */
const undoStack = [], UNDO_MAX = 80;
const snap = () => JSON.stringify(edit);
let undoBase = null, undoLock = false;
const undoState = () => { document.getElementById("bUndo").disabled = !undoStack.length; };
function applyEdit(s) {
  const o = JSON.parse(s);
  for (const k of ["place","art","text","slotText","char","tstyle","pos"]) edit[k] = o[k] || {};
  edit.nt = o.nt || []; edit.newSlots = o.newSlots || []; edit.down = o.down || {};
  edit.slotShift = o.slotShift || {}; edit.layerShift = o.layerShift || {};
}
function undo() {
  if (!undoStack.length) return;
  undoLock = true;
  applyEdit(undoStack.pop());
  try { localStorage.setItem("psbSlots", JSON.stringify(edit)); } catch (e) {}
  undoBase = snap(); undoLock = false;
  freeDrag = null; drag = null; dropTarget = null; sel = null;
  hideInsp(); render(); tbFill(); undoState();
}
const charOf = s => {
  if (edit.char[s.id] !== undefined) return edit.char[s.id];
  const a = artOf(s.id);
  if (a) return a.char ? a.char + (a.form ? "|" + a.form : "") : "";
  return s.char ? s.char + (s.form ? "|" + s.form : "") : "";
};
const textOf = s => edit.slotText[s.id] !== undefined ? edit.slotText[s.id] : (s.text ? s.text.text : "");
const gradeOf = s => {
  const c = charOf(s);
  return c ? (GRADES[c] || GRADES[c.split("|")[0]] || "") : "";
};
const textBoxOf = s => {
  const d = downOf(s.group, s.name);
  const b = s.text ? s.text.box : [s.box[0], s.box[1] + s.box[3] + 8, s.box[2], 0];
  return [b[0], b[1] + d, b[2], b[3]];
};

/* ---- 格位表：作者原稿的格位 + 网页上行尾新增的格位 ---- */
const ATTR_G = ["光系", "暗系", "火系", "水系", "草系"];
const TAIL_G = ["底边", "人物持立牌图片"];
const ORD_G = ["全场景必练T0", "全场景必练T0.5", "T1功能角色", "T2功能角色", "__attr__", "__tail__"];
const STEP_X = 410, STEP_Y = 410, ATTR_STEP = __ATTRSTEP__, GAP_X = 45;
const slotsAll = () => SLOTS.concat(edit.newSlots || []);
const findSlot = id => slotsAll().find(s => s.id === id) || null;
/* 分组层级：上半部四档各占一层（上下排列），五属性栏共享一层（横排，互不影响），版脚在最后。
   某一层新增了一行，就按这个顺序把后面所有层整体往下让。 */
const ordKey = (group, name) => {
  if (ORD_G.indexOf(group) >= 0) return group;
  if (ATTR_G.indexOf(group) >= 0) return "__attr__";
  if (name && name.indexOf("全属性梯度") === 0) return "__attr__";
  if (name && TAIL_G.indexOf(name) >= 0) return "__tail__";
  return "";
};
const cumDown = key => {
  let n = 0;
  for (const g of ORD_G) { if (g === key) break; n += (edit.down || {})[g] || 0; }
  return n;
};
const downOf = (group, name) => { const k = ordKey(group, name); return k ? cumDown(k) : 0; };
/* 属性栏里就地插行造成的个人位移：插入点以下（含档位标签）整体让开一行高 */
const shiftOf = id => (edit.slotShift || {})[id] || 0;
const lshiftOf = seq => (edit.layerShift || {})[seq] || 0;
const boxOf = s => [s.box[0], s.box[1] + shiftOf(s.id) + downOf(s.group, s.name),
                    s.box[2], s.box[3]];
/* 头像来源：头像库拖入的素材优先，其次是该身份在面板里的头像；两样都没有就是空位。
   原稿那张格位图（金框 + 浅底 + 立绘）不再使用。 */
const faceOf = s => {
  if (isSlotEmpty(s.id)) return null;            /* 空出的洞不挂头像 */
  const a = artOf(s.id);
  if (a) return a.src;
  const c = charOf(s);
  if (!c) return null;
  return FACES[c] || FACES[c.split("|")[0]] || null;
};
function barFits(sid, l, t, w, h) {
  const area = w * h;
  const hit = b => {
    const ox = Math.min(l + w, b[0] + b[2]) - Math.max(l, b[0]);
    const oy = Math.min(t + h, b[1] + b[3]) - Math.max(t, b[1]);
    return ox > 0 && oy > 0 && ox * oy > area * 0.15;
  };
  for (const o of OTHERS) {
    if (o.bg) continue;                        /* 背景、底边、栏位背板、光标：不算拦路 */
    if (hit([o.box[0], o.box[1] + downOf(o.group, o.name), o.box[2], o.box[3]])) return false;
  }
  for (const o of slotsAll()) {
    if (o.id === sid) continue;
    if (hit(boxOf(o))) return false;
  }
  return true;
}
function barRectOf(s) {
  const tb = textBoxOf(s), ts = specOf(), b = boxOf(s);
  const lines = s.text ? (s.text.lines || 1) : 1;
  const h = ts.lh * lines;
  /* 栏宽不超过头像宽度；原稿文字比头像宽时居中收进格宽 */
  const w = Math.min(tb[2], b[2]);
  const left = tb[0] + (tb[2] - w) / 2;
  /* 有原稿说明：按原文字框纵向居中；没有：格底下方 3px，放不下才贴格内下缘 */
  let top = s.text ? tb[1] + tb[3] / 2 - h / 2 : b[1] + b[3] + 3;
  if (!s.text && !barFits(s.id, left, top, w, h)) top = b[1] + b[3] - h - 4;
  return { left, top, width: w, height: h, hint: !s.text };
}
const specOf = () => ({ fs: 40, lh: 50 });      /* 说明栏统一规格 */
const tstyleOf = k => (edit.tstyle && edit.tstyle[k]) || {};
const posOf = (k, x, y) => (edit.pos && edit.pos[k]) || [x, y];
const textStyleOf = s => {
  const st = tstyleOf("s" + s.id);
  return { color: st.color || (s.text ? s.text.color : "#e8ebf2"),
           size: st.fs || specOf().fs, lh: st.lh || specOf().lh };
};

function barOf(id) { return stage.querySelector('[data-slot-text="' + id + '"]'); }
function setBarOpen(t, open) {
  if (!t || !t.classList.contains("hint")) return;
  t.classList.toggle("open", open);
  t.style.fontSize = open ? t.dataset.fs + "px" : "0px";
  t.style.minHeight = open ? t.dataset.nh + "px" : "0px";
  t.style.height = open ? "" : "6px";
  t.style.top = (parseFloat(t.dataset.top) + (open ? 0 : t.dataset.nh - 6)) + "px";
}

/* 铺满整幅的大底图：让点击穿透，否则会挡住所有头像格位 */
const WALL = o => o.t === "img" && o.box[2] * o.box[3] >= __W__ * __H__ * 0.5;
/* 五个属性栏的背板（矩形 1）：随格位加格一起往下延长 */
const IS_PANEL = o => o.t === "img" && o.name === "矩形 1" && ATTR_G.indexOf(o.group) >= 0;
const ATTR_PAD = __ATTRPAD__;   /* 原稿里背板底到最下格底的余量，延长时按同样的余量留 */

let rseq = 0;                    /* 渲染代号：重建 DOM 后旧元素的 blur 处理器据此认出自己已被替换 */
function render() {
  rseq += 1;
  stage.innerHTML = "";
  /* 版面因加格变高后，画布与滚动区都要跟着长 */
  const totalDown = ORD_G.reduce((n, g) => n + ((edit.down || {})[g] || 0), 0);
  /* 属性栏背板随格位加长：取五栏里最靠下的格底、加上原稿的底部余量，五栏一起延长同样的量 */
  const panelBottom = Math.max(...ATTR_G.map(g => PANEL_BOX[g] ? PANEL_BOX[g][1] + PANEL_BOX[g][3] : 0));
  const attrGrow = Math.max(0, ...ATTR_G.map(g => {
    const p = PANEL_BOX[g], mine = slotsAll().filter(s => s.group === g);
    if (!p || !mine.length) return 0;
    return Math.max(...mine.map(s => s.box[1] + shiftOf(s.id) + s.box[3]))
           + ATTR_PAD - (p[1] + p[3]);
  }));
  const canvasH = Math.max(__H__ + totalDown, panelBottom + cumDown("__attr__") + attrGrow
                           + (panelBottom ? Math.max(40, __H__ - panelBottom) : 40));
  /* 版脚（底边、人物持立牌）贴着黑底最下端：黑底跟着画布走，版脚再跟着黑底走 */
  const tailBottom = Math.max(0, ...OTHERS.filter(o => TAIL_G.indexOf(o.name) >= 0)
      .map(o => o.box[1] + o.box[3] + downOf(o.group, o.name)));
  const tailDrop = Math.max(0, canvasH - tailBottom);
  stage.style.height = canvasH + "px";
  document.getElementById("fit").style.height = "calc(" + canvasH + "px * var(--z))";
  const all = [
    ...OTHERS.map(o => ({ seq:o.seq, kind:"other", o })),
    ...slotsAll().map(s => ({ seq:s.id, kind:"slot", s }))
  ].sort((a, b) => a.seq - b.seq);
  for (const item of all) {
    if (item.kind === "other") {
      const o = item.o, ok = "o" + o.seq;
      if (hideBig && o.big) continue;
      const ost = tstyleOf(ok);
      if (ost.hide) continue;
      const el = document.createElement("div");
      el.className = (o.t === "text" ? "lb" : "bg") + (WALL(o) ? " wall" : "");
      const p = posOf(ok, o.box[0], o.box[1]);
      /* 属性栏档位标签跟着插行让位；版脚再额外贴到黑底最下端 */
      const dy0 = downOf(o.group, o.name) + lshiftOf(o.seq)
                  + (TAIL_G.indexOf(o.name) >= 0 ? tailDrop : 0);
      el.style.left = p[0] + "px"; el.style.top = (p[1] + dy0) + "px";
      el.style.width = (o.t === "text" ? o.box[2] + 40 : o.box[2]) + "px";
      /* 黑底那张标了 grow 的跟着画布走；属性栏背板随加格延长；其余按原尺寸 */
      el.style.height = (o.grow ? (canvasH - (p[1] + dy0))
                                : o.box[3] + (IS_PANEL(o) ? attrGrow : 0)) + "px";
      if (o.t === "text") {
        const lh = Math.round(o.box[3] / (o.lines || 1));
        const fs = ost.fs || Math.round(lh * 0.78);
        el.style.fontSize = fs + "px";
        el.style.lineHeight = (ost.lh || (ost.fs ? Math.round(ost.fs * 1.22) : lh)) + "px";
        el.style.color = ost.color || o.color;
        el.style.fontWeight = ost.bold === undefined ? (lh >= 46 ? "700" : "400")
                                                     : (ost.bold ? "700" : "400");
        if (ost.fs || ost.lh) { el.style.height = "auto"; el.style.minHeight = o.box[3] + "px"; }
        el.textContent = edit.text[o.seq] !== undefined ? edit.text[o.seq] : o.text;
        el.addEventListener("dblclick", e => { e.stopPropagation(); editText(o, el); });
      } else {
        const img = document.createElement("img");
        img.src = "layers/" + o.file;
        img.draggable = false;
        el.appendChild(img);
      }
      el.dataset.seq = o.seq;
      el.dataset.key = ok;
      el.dataset.rseq = rseq;
      el.title = (o.name || "") + " · 可拖动";
      el.classList.add("movable");
      el.addEventListener("pointerdown", e => startFreeDrag(e, el, ok));
      stage.appendChild(el);
      continue;
    }
    const s = item.s, a = artOf(s.id), b = boxOf(s), face = faceOf(s);
    const el = document.createElement("div");
    el.className = "slot" + (face ? "" : " blank") + (isSlotEmpty(s.id) ? " empty" : "")
                 + (s.ph ? " ph" : "") + (a ? " fromlib" : "") + (sel === s.id ? " sel" : "");
    el.style.left = b[0] + "px"; el.style.top = b[1] + "px";
    el.style.width = b[2] + "px"; el.style.height = b[3] + "px";
    el.style.background = s.bg || "#2b3038";
    el.dataset.slot = s.id;
    if (face) {
      const img = document.createElement("img");
      img.src = face;
      img.alt = charOf(s) || s.name;
      el.appendChild(img);
      const ring = document.createElement("i");   /* 原稿金边随原图一起去掉，框改由这里按稀有度画 */
      ring.className = "ring";
      ring.style.borderWidth = Math.max(s.ring || 6, 2) + "px";
      ring.style.borderColor = RARITY_COLOR[gradeOf(s)] || RARITY_COLOR[""];
      el.appendChild(ring);
    }
    const tag = document.createElement("span");
    tag.className = "tag";
    const c = charOf(s), fromSlot = findSlot(contentOf(s.id));
    tag.textContent = s.group + " · " + s.name + " ← "
                    + (a ? "头像库·" + a.char
                         : face ? (fromSlot ? fromSlot.name : "面板头像") : "空位")
                    + (c ? "（" + c.replace("|", "·") + "）" : "（未指定）");
    el.appendChild(tag);
    el.addEventListener("pointerdown", e => startDrag(e, s, el));
    el.addEventListener("pointerenter", () => setBarOpen(barOf(s.id), true));
    el.addEventListener("pointerleave", () => {
      const a = document.activeElement;
      if (a && a.dataset && a.dataset.slotText === String(s.id)) return;
      setBarOpen(barOf(s.id), false);
    });
    el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("drop"); });
    el.addEventListener("dragleave", () => el.classList.remove("drop"));
    el.addEventListener("drop", e => {
      e.preventDefault(); el.classList.remove("drop");
      let d = null;
      try { d = JSON.parse(e.dataTransfer.getData("text/plain") || "null"); } catch (err) {}
      if (!d || !d.src) return;
      edit.art[s.id] = { src: d.src, char: d.c || null, form: d.f || null };
      delete edit.char[s.id];
      save(); render();
    });
    stage.appendChild(el);
    if (s.attr) continue;              /* 全属性梯度排行榜的格位不带说明栏 */
    if (tstyleOf("s" + s.id).hide) continue;   /* 文字条里隐藏的说明栏 */
    const ts = textStyleOf(s), R = barRectOf(s);
    const hint = R.hint && textOf(s) === "";
    const t = document.createElement("div");
    t.className = "sltext" + (hint ? " hint" : "");
    t.style.left = R.left + "px";
    t.style.top = (R.top + (hint ? R.height - 6 : 0)) + "px";
    t.style.width = R.width + "px";
    t.style.minHeight = R.height + "px";
    t.style.fontSize = ts.size + "px";
    t.style.color = ts.color;
    t.style.fontWeight = tstyleOf("s" + s.id).bold ? "700" : "";
    t.style.lineHeight = ts.lh + "px";
    t.textContent = textOf(s);
    t.contentEditable = "true";
    t.dataset.slotText = s.id;
    t.dataset.fs = ts.size; t.dataset.nh = R.height; t.dataset.top = R.top;
    t.dataset.rseq = rseq;
    if (hint) setBarOpen(t, false);
    t.addEventListener("pointerdown", e => e.stopPropagation());
    /* 文字栏只管打字，不接受拖放：否则头像库素材拖到栏上会把带的信息嵌进输入框 */
    t.addEventListener("dragover", e => { e.preventDefault(); e.dataTransfer.dropEffect = "none"; });
    t.addEventListener("drop", e => { e.preventDefault(); e.stopPropagation(); });
    t.addEventListener("pointerenter", () => setBarOpen(t, true));
    t.addEventListener("pointerleave", () => { if (document.activeElement !== t) setBarOpen(t, false); });
    t.addEventListener("focus", () => setBarOpen(t, true));
    t.addEventListener("blur", () => {
      if (t.dataset.rseq !== String(rseq)) return;   /* 元素已被重建，忽略这次 blur */
      const v = t.textContent;
      const wasHint = t.classList.contains("hint");
      if (v === (s.text ? s.text.text : "")) delete edit.slotText[s.id];
      else edit.slotText[s.id] = v;
      save(); refreshCount();
      if (wasHint !== (!s.text && !v)) render(); else setBarOpen(t, false);
    });
    stage.appendChild(t);
  }
  /* 自定义文本（PS 式新建文字层） */
  for (const nt of (edit.nt || [])) {
    if (nt.hide) continue;
    const el = document.createElement("div");
    el.className = "nt";
    const p = posOf("n" + nt.id, nt.x, nt.y);
    el.style.left = p[0] + "px"; el.style.top = p[1] + "px";
    el.style.fontSize = nt.fs + "px";
    el.style.lineHeight = Math.round(nt.fs * 1.25) + "px";
    el.style.color = nt.color;
    el.style.fontWeight = nt.bold ? "700" : "400";
    el.style.minWidth = Math.max(80, nt.fs * 1.5) + "px";
    el.textContent = nt.txt || "双击输入文字";
    el.dataset.key = "n" + nt.id;
    el.dataset.rseq = rseq;
    el.title = "自定义文本 · 拖动移位置 · 双击改字";
    el.addEventListener("pointerdown", e => startFreeDrag(e, el, "n" + nt.id));
    el.addEventListener("dblclick", e => { e.stopPropagation(); editNT(nt, el); });
    stage.appendChild(el);
  }
  document.getElementById("ztext").textContent = "缩放 " + Math.round(z * 100) + "%";
  refreshCount();
}

function editText(o, el) {
  el.contentEditable = "true"; el.focus();
  el.addEventListener("dragover", e => { e.preventDefault(); e.dataTransfer.dropEffect = "none"; });
  el.addEventListener("drop", e => { e.preventDefault(); e.stopPropagation(); });
  el.addEventListener("blur", () => {
    el.contentEditable = "false";
    if (el.dataset.rseq !== String(rseq)) return;   /* 元素已被重建，忽略这次 blur */
    edit.text[o.seq] = el.textContent;
    save();
  }, { once: true });
}

/* ---- 自由拖动：背景素材、原稿文字层、自定义文本 ---- */
let freeDrag = null;
function startFreeDrag(e, el, key) {
  if (e.button !== 0 || el.isContentEditable) return;
  e.preventDefault(); e.stopPropagation();
  freeDrag = { el, key, sx: e.clientX, sy: e.clientY,
               x0: parseFloat(el.style.left) || 0, y0: parseFloat(el.style.top) || 0,
               moved: false };
  el.classList.add("moving");
}
document.addEventListener("pointermove", e => {
  if (!freeDrag) return;
  const dx = (e.clientX - freeDrag.sx) / z, dy = (e.clientY - freeDrag.sy) / z;
  if (Math.abs(dx) > 2 || Math.abs(dy) > 2) freeDrag.moved = true;
  freeDrag.el.style.left = Math.round(freeDrag.x0 + dx) + "px";
  freeDrag.el.style.top = Math.round(freeDrag.y0 + dy) + "px";
});
document.addEventListener("pointerup", () => {
  if (!freeDrag) return;
  const el = freeDrag.el, key = freeDrag.key, moved = freeDrag.moved;
  el.classList.remove("moving");
  freeDrag = null;
  if (!moved) return;
  const x = Math.round(parseFloat(el.style.left) || 0), y = Math.round(parseFloat(el.style.top) || 0);
  if (key[0] === "n") {
    const nt = (edit.nt || []).find(t => "n" + t.id === key);
    if (nt) { nt.x = x; nt.y = y; }
  } else {
    const o = OTHERS.find(t => "o" + t.seq === key);
    edit.pos[key] = [x, y - (o ? downOf(o.group, o.name) : 0)];   /* 存基线坐标，加格时跟着下移 */
  }
  save(); tbSync();
});

/* ---- 新建文本（PS 式文字层） ---- */
function editNT(nt, el) {
  el.contentEditable = "true";
  el.focus();
  const r = document.createRange();
  r.selectNodeContents(el);
  const sl = window.getSelection();
  sl.removeAllRanges(); sl.addRange(r);
  el.addEventListener("blur", () => {
    el.contentEditable = "false";
    if (el.dataset.rseq !== String(rseq)) return;   /* 元素已被重建，忽略这次 blur */
    const v = el.textContent.replace(/\s+/g, " ").trim();
    nt.txt = v || "双击输入文字";
    save(); render(); tbFill();
  }, { once: true });
}
function addNT() {
  const wrapEl = document.getElementById("wrap");
  const id = (edit.nt || []).reduce((m, t) => Math.max(m, t.id), 0) + 1;
  const cx = Math.round((wrapEl.scrollLeft + wrapEl.clientWidth / 2) / z) - 140;
  const cy = Math.round((wrapEl.scrollTop + wrapEl.clientHeight / 2) / z);
  const nt = { id: id,
               x: Math.max(0, Math.min(cx, __W__ - 360)),
               y: Math.max(0, Math.min(cy, __H__ - 120)),
               txt: "新文字", fs: 40, color: "#ffffff", bold: false };
  edit.nt.push(nt);
  save(); render();
  if (tbEl("textbar").classList.contains("on")) { tbCur = "n" + id; tbFill(); }
  const el = stage.querySelector('[data-key="n' + id + '"]');
  if (el) editNT(nt, el);
  return nt;
}

/* ---- 加格：新格接在「选中那一格」的后面 ----
   先看它所在的那一排还有没有位置：有就补在它后面；这一排已经排满，才在该组最下面一行
   的下方新起一排。横向只往后接、纵向只在换排时往下走，所以其它头像的纵轴一格不动；
   新起一排时该组变高，按组顺序把后面的档位、属性栏、版脚整体往下让。 */
const cluster = (vals, tol) => {                 /* 原稿是手摆的，同一行/列的坐标会差一两像素 */
  const out = [];
  for (const v of vals.slice().sort((a, b) => a - b)) {
    const g = out[out.length - 1];
    if (g && v - g[g.length - 1] <= tol) g.push(v); else out.push([v]);
  }
  return out;
};
const modeOf = a => {                            /* 一簇里出现最多的那个值就是这一列的标准位置 */
  const n = {}; let best = a[0], bn = 0;
  for (const v of a) { n[v] = (n[v] || 0) + 1; if (n[v] > bn) { bn = n[v]; best = v; } }
  return best;
};
function addSlot(seedId) {
  const s = findSlot(seedId);
  if (!s) { flash("先在画布上点选一个格位，新格会加在它后面"); return; }
  const grp = s.group, attr = !!s.attr, W = s.box[2], Hh = s.box[3];
  const kin = slotsAll().filter(x => x.group === grp);
  const rows = cluster(kin.map(k => k.box[1]), 30);
  const lastY = rows[rows.length - 1][0];
  const rowAt = (yy, list) => list.filter(k => Math.abs(k.box[1] - yy) <= 30)
                                  .sort((a, b) => a.box[0] - b.box[0]);
  const mine = rowAt((rows.find(r => r.some(v => Math.abs(v - s.box[1]) <= 30)) || [s.box[1]])[0], kin);
  let x, y = mine[0].box[1], grown = 0, insert = null;
  if (attr) {
    const cols = cluster(kin.map(k => k.box[0]), 30).map(modeOf);
    if (mine.length < cols.length) x = cols[mine.length];      /* 这一排后面还空着，补上去 */
    else {              /* 这一排满了：就在它下面就地插一行，后面的档位与 T 几 标签整体让开 */
      const a = mine[0];
      x = cols[0]; y = a.box[1] + ATTR_STEP;
      insert = { anchor: a, top: boxOf(a)[1] };
    }
    const p = PANEL_BOX[grp];
    /* 纵向不再设上限：新起的排会把背板一起往下延长，五栏同长 */
    if (p && (x < p[0] - 1 || x + W > p[0] + p[2] + 1)) {
      flash("这一排横向已经到边框，放不下了"); return;
    }
  } else {
    const tail = mine[mine.length - 1];
    x = tail.box[0] + STEP_X;                                  /* 接在选中那一排的队尾 */
    if (x + W > __W__ - GAP_X) {                               /* 这一排顶到右边缘：在最下面一行下面新起一排 */
      const lrow = rowAt(lastY, kin);
      x = lrow[0].box[0]; y = lastY + STEP_Y; grown = STEP_Y;
    }
  }
  const id = (edit.newSlots || []).reduce((m, t) => Math.max(m, t.id), 999) + 1;
  const n = (edit.newSlots || []).filter(t => t.group === grp).length + 1;
  const ns = { id, new: true, group: grp, name: "新格" + n, attr,
               box: [x, y, W, Hh], ring: s.ring || Math.max(6, Math.round(W * 0.025)),
               bg: s.bg || "#2b3038" };
  edit.newSlots = (edit.newSlots || []).concat(ns);
  if (grown) edit.down[grp] = (edit.down[grp] || 0) + grown;   /* 后面所有层整体往下让 */
  if (insert) {
    /* 插入点以下（不含锚点那一排）的格位与档位标签各让一行；新行沿用锚点的位移 */
    for (const k of kin) if (boxOf(k)[1] > insert.top + 1) {
      edit.slotShift[k.id] = (edit.slotShift[k.id] || 0) + ATTR_STEP;
    }
    for (const o of OTHERS) {
      if (o.group !== grp || IS_PANEL(o)) continue;
      if (o.box[1] + lshiftOf(o.seq) + downOf(o.group, o.name) > insert.top + 1) {
        edit.layerShift[o.seq] = (edit.layerShift[o.seq] || 0) + ATTR_STEP;
      }
    }
    edit.slotShift[id] = shiftOf(insert.anchor.id);
  }
  save(); render(); tbFill();
  const el = stage.querySelector('[data-slot="' + id + '"]');
  if (el) { select(ns, el); el.scrollIntoView({ block: "center" }); }
}

function startDrag(e, s, el) {
  e.preventDefault();
  select(s, el);
  if (isSlotEmpty(s.id)) return;
  const r = el.getBoundingClientRect();
  const ghost = document.createElement("div");
  ghost.id = "ghost";
  ghost.style.width = r.width + "px"; ghost.style.height = r.height + "px";
  const cur = el.querySelector("img");      /* 金框空位这类没有头像子元素，幽灵按底色走 */
  if (cur) {
    const img = document.createElement("img");
    img.src = cur.src;
    ghost.appendChild(img);
  } else {
    ghost.style.background = s.bg && s.bg !== "transparent" ? s.bg : "#2b3038";
    ghost.style.outlineColor = s.ph ? "#fedd62" : "#6ea8fe";
  }
  document.body.appendChild(ghost);
  drag = { s, el, ghost, ox: e.clientX - r.left, oy: e.clientY - r.top };
  el.classList.add("dragging");
  moveGhost(e);
}
function moveGhost(e) {
  drag.ghost.style.left = (e.clientX - drag.ox) + "px";
  drag.ghost.style.top = (e.clientY - drag.oy) + "px";
}
document.addEventListener("pointermove", e => {
  if (!drag) return;
  moveGhost(e);
  const t = document.elementFromPoint(e.clientX, e.clientY);
  const slotEl = t && t.closest ? t.closest(".slot") : null;
  const id = slotEl ? parseInt(slotEl.dataset.slot, 10) : null;
  if (dropTarget && dropTarget !== id) {
    const prev = stage.querySelector('[data-slot="' + dropTarget + '"]');
    if (prev) prev.classList.remove("drop");
  }
  dropTarget = id;
  if (id !== null && id !== drag.s.id) {
    const cur = stage.querySelector('[data-slot="' + id + '"]');
    if (cur) cur.classList.add("drop");
  }
});
document.addEventListener("pointerup", e => {
  if (!drag) return;
  const srcId = drag.s.id;
  drag.ghost.remove();
  drag.el.classList.remove("dragging");
  const t = document.elementFromPoint(e.clientX, e.clientY);
  const slotEl = t && t.closest ? t.closest(".slot") : null;
  const dstId = slotEl ? parseInt(slotEl.dataset.slot, 10) : null;
  for (const el of stage.querySelectorAll(".drop")) el.classList.remove("drop");
  drag = null; dropTarget = null;
  if (dstId !== null && dstId !== srcId) swap(srcId, dstId);
  else render();
});

function charKeyOfSlot(id) {
  if (edit.char[id] !== undefined) return edit.char[id];
  const a = artOf(id);
  if (a) return a.char ? a.char + (a.form ? "|" + a.form : "") : "";
  const cid = contentOf(id);
  if (cid === EMPTY) return "";
  const src = findSlot(cid) || findSlot(id);
  return src && src.char ? src.char + (src.form ? "|" + src.form : "") : "";
}
function swap(a, b) {
  const ca = contentOf(a), cb = contentOf(b);
  const aa = artOf(a), ab = artOf(b);
  const ka = charKeyOfSlot(a), kb = charKeyOfSlot(b);
  edit.place[a] = cb === b ? b : cb;
  edit.place[b] = ca === a ? a : ca;
  const putArt = (id, v) => { if (v) edit.art[id] = v; else delete edit.art[id]; };
  putArt(a, ab); putArt(b, aa);
  const putChar = (id, k) => { if (k) edit.char[id] = k; else delete edit.char[id]; };
  putChar(a, kb); putChar(b, ka);
  save(); sel = null; hideInsp(); render();
}

function select(s, el) {
  sel = s.id;
  for (const e of stage.querySelectorAll(".slot.sel")) e.classList.remove("sel");
  if (el) el.classList.add("sel");
  document.getElementById("insp").style.display = "block";
  const a = artOf(s.id), cid = contentOf(s.id), src = findSlot(cid) || s;
  document.getElementById("iName").textContent = s.group + " · " + s.name;
  document.getElementById("iInfo").textContent = isSlotEmpty(s.id) ? "该洞已空出"
    : a ? "头像来自头像库：" + (a.char || "未命名") : "头像来自：" + src.group + " · " + src.name;
  const dd = document.getElementById("iChar");
  dd.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = ""; o0.textContent = "（待定）";
  dd.appendChild(o0);
  for (const c of ROSTER) {
    const g = document.createElement("optgroup"); g.label = c.n;
    for (const f of (c.f && c.f.length ? c.f : [""])) {
      const o = document.createElement("option");
      o.value = f ? c.n + "|" + f : c.n;
      o.textContent = f ? c.n + " · " + f : c.n + " · 原型";
      g.appendChild(o);
    }
    dd.appendChild(g);
  }
  dd.value = charOf(s);
  dd.onchange = () => {
    if (dd.value) edit.char[s.id] = dd.value; else delete edit.char[s.id];
    save(); render();
  };
  document.getElementById("iEmpty").onclick = () => {
    edit.place[s.id] = EMPTY; delete edit.art[s.id]; delete edit.char[s.id];
    save(); sel = null; hideInsp(); render();
  };
  document.getElementById("iRevert").onclick = () => {
    delete edit.place[s.id]; delete edit.art[s.id]; delete edit.char[s.id];
    delete edit.slotText[s.id];
    save(); render();
  };
  document.getElementById("iClose").onclick = () => { sel = null; hideInsp(); render(); };
}
function hideInsp() { document.getElementById("insp").style.display = "none"; }

function changed() {
  const out = [];
  for (const s of slotsAll()) {
    const cid = contentOf(s.id), empty = cid === EMPTY, a = artOf(s.id);
    const ch = edit.char[s.id];
    const st = s.attr ? undefined : edit.slotText[s.id];   /* 属性栏格位没有说明栏 */
    const textChanged = st !== undefined && st !== (s.text ? s.text.text : "");
    if (cid === s.id && !a && ch === undefined && !textChanged) continue;
    const [c, f] = (ch || "").split("|");
    const ts = textStyleOf(s), R = barRectOf(s);
    out.push({ slot: s.id, group: s.group, name: s.name,
               content: empty ? null : cid,
               contentName: empty ? null : (findSlot(cid) || s).name,
               art: a ? { src: a.src, char: a.char, form: a.form } : null,
               char: ch ? c : null, form: f || null,
               textChanged: textChanged, text: textChanged ? st : null,
               textFrom: s.text ? s.text.from : null,
               textBox: textChanged ? [R.left, Math.round(R.top), R.width, R.height] : null,
               textColor: textChanged ? ts.color : null,
               textFs: textChanged ? ts.size : null,
               textLh: textChanged ? ts.lh : null });
  }
  return out;
}
function refreshCount() {
  document.getElementById("iCount").textContent = "已改 " + changed().length + " 处";
}

/* ---- 自由拖动工具提示 ---- */

/* ---------- 文字条：只作用于网页显示，改动存在浏览器本地 ---------- */
let tbCur = "";
const tbEl = id => document.getElementById(id);
const HEX6 = c => {
  const v = String(c || "").trim();
  if (/^#[0-9a-f]{6}$/i.test(v)) return v;
  const m = v.match(/(\d+)\D+(\d+)\D+(\d+)/);
  return m ? "#" + [1, 2, 3].map(i => (+m[i]).toString(16).padStart(2, "0")).join("") : "#ffffff";
};
const ntf = k => (edit.nt || []).find(t => "n" + t.id === k) || null;
const tbBase = k => {
  if (k[0] === "s") {
    const s = findSlot(Number(k.slice(1)));
    return { group: s.group, txt: textOf(s), st: textStyleOf(s),
             color: s.text ? s.text.color : "#e8ebf2", kind: "slot" };
  }
  if (k[0] === "n") {
    const nt = ntf(k) || { txt: "", fs: 40, color: "#ffffff", x: 0, y: 0 };
    return { group: "自定义文本", txt: nt.txt,
             st: { size: nt.fs, lh: Math.round(nt.fs * 1.25) }, color: nt.color,
             pos: posOf(k, nt.x, nt.y), kind: "nt" };
  }
  const o = OTHERS.find(x => "o" + x.seq === k);
  const lh0 = Math.round(o.box[3] / (o.lines || 1));
  return { group: o.group || "未分组",
           txt: o.t === "text" ? (edit.text[o.seq] !== undefined ? edit.text[o.seq] : o.text)
                               : "图片素材：" + o.name,
           st: { size: o.t === "text" ? (tstyleOf(k).fs || Math.round(lh0 * 0.78)) : 0,
                 lh: tstyleOf(k).lh || lh0 },
           color: o.color || "#ffffff",
           pos: (p => [p[0], p[1] + downOf(o.group, o.name)])(posOf(k, o.box[0], o.box[1])),
           kind: o.t === "text" ? "text" : "img" };
};
function tbFill() {
  const sel = tbEl("tbPick"), keep = tbCur;
  sel.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = ""; ph.textContent = "— 选择要编辑的文字 —";
  sel.appendChild(ph);
  const sets = [["说明栏（洞下）", slotsAll().filter(s => !s.attr).map(s => "s" + s.id)],
                ["原稿文字", OTHERS.filter(o => o.t === "text").map(o => "o" + o.seq)],
                ["素材图层", OTHERS.filter(o => o.t !== "text").map(o => "o" + o.seq)],
                ["自定义文本", (edit.nt || []).map(t => "n" + t.id)]];
  for (const [label, keys] of sets) {
    if (!keys.length) continue;
    const og = document.createElement("optgroup"); og.label = label;
    for (const k of keys) {
      const b = tbBase(k);
      if (!b) continue;
      const sum = String(b.txt || "").replace(/\s+/g, " ").trim();
      const op = document.createElement("option");
      op.value = k;
      op.textContent = (tstyleOf(k).hide ? "✕ " : "") + (b.group ? b.group + " · " : "")
                     + (sum ? sum.slice(0, 22) : "（空）");
      og.appendChild(op);
    }
    sel.appendChild(og);
  }
  sel.value = keep && sel.querySelector('option[value="' + keep + '"]') ? keep : "";
  tbSync();
}
function tbSync() {
  tbCur = tbEl("tbPick").value;
  const on = !!tbCur, b = on ? tbBase(tbCur) : null, st = tstyleOf(tbCur);
  const canStyle = on && b.kind !== "img";
  const canMove = on && b.kind !== "slot";
  tbEl("tbText").disabled = !canStyle;
  for (const id of ["tbFs", "tbColor", "tbBold"]) tbEl(id).disabled = !canStyle;
  tbEl("tbX").disabled = !canMove; tbEl("tbY").disabled = !canMove;
  tbEl("tbHide").disabled = !on; tbEl("tbRevert").disabled = !on;
  tbEl("tbRevert").textContent = on && b.kind === "nt" ? "删除该条" : "还原该条";
  if (!on) {
    tbEl("tbInfo").textContent = "共 " + slotsAll().filter(s => !s.attr).length + " 条说明栏 + "
                               + OTHERS.filter(o => o.t === "text").length + " 条原稿文字 + "
                               + OTHERS.filter(o => o.t !== "text").length + " 个素材图层，"
                               + "自定义文本 " + (edit.nt || []).length + " 条";
    tbEl("tbX").value = ""; tbEl("tbY").value = "";
    return;
  }
  tbEl("tbText").value = b.txt;
  tbEl("tbFs").value = b.st.size || 0;
  tbEl("tbColor").value = HEX6(st.color || b.color);
  tbEl("tbBold").classList.toggle("on", !!st.bold);
  tbEl("tbHide").classList.toggle("on", !!st.hide);
  if (canMove) { tbEl("tbX").value = Math.round(b.pos[0]); tbEl("tbY").value = Math.round(b.pos[1]); }
  else { tbEl("tbX").value = ""; tbEl("tbY").value = ""; }
  const moved = edit.pos && edit.pos[tbCur];
  tbEl("tbInfo").textContent = (b.group || "") + (st.hide ? " · 已隐藏" : "")
                             + (moved ? " · 已挪位置" : "")
                             + (st.fs || st.color || st.bold !== undefined ? " · 已改样式" : "");
  for (const e of stage.querySelectorAll('.pick')) e.classList.remove('pick');
  if (tbCur[0] === "o") {
    const e = stage.querySelector('[data-key="' + tbCur + '"]');
    if (e) e.classList.add("pick");
  }
}
const tbMove = () => {
  if (!tbCur) return;
  const x = parseInt(tbEl("tbX").value, 10), y = parseInt(tbEl("tbY").value, 10);
  if (isNaN(x) || isNaN(y)) return;
  if (tbCur[0] === "n") { const nt = ntf(tbCur); if (nt) { nt.x = x; nt.y = y; } }
  else {
    const o = OTHERS.find(t => "o" + t.seq === tbCur);
    edit.pos[tbCur] = [x, y - (o ? downOf(o.group, o.name) : 0)];
  }
  save(); render(); tbSync();
};
function tbSet(patch) {
  if (!tbCur) return;
  if (tbCur[0] === "n") {
    const nt = ntf(tbCur); if (!nt) return;
    if (patch.fs) nt.fs = patch.fs;
    if (patch.color) nt.color = patch.color;
    if (patch.bold !== undefined) { if (patch.bold) nt.bold = true; else delete nt.bold; }
    if (patch.hide !== undefined) { if (patch.hide) nt.hide = true; else delete nt.hide; }
    save(); render(); tbSync();
    return;
  }
  const st = edit.tstyle[tbCur] = edit.tstyle[tbCur] || {};
  for (const k in patch) { if (patch[k] === null) delete st[k]; else st[k] = patch[k]; }
  if (!Object.keys(st).length) delete edit.tstyle[tbCur];
  save(); render(); tbSync();
}
tbEl("tbPick").onchange = tbSync;
tbEl("tbText").onchange = e => {
  if (!tbCur) return;
  const v = e.target.value;
  if (tbCur[0] === "s") {
    const s = findSlot(Number(tbCur.slice(1)));
    if (v === (s.text ? s.text.text : "")) delete edit.slotText[s.id];
    else edit.slotText[s.id] = v;
  } else if (tbCur[0] === "n") {
    const nt = ntf(tbCur);
    if (nt) nt.txt = v || "双击输入文字";
  } else {
    const o = OTHERS.find(x => "o" + x.seq === tbCur);
    if (v === o.text) delete edit.text[o.seq]; else edit.text[o.seq] = v;
  }
  save(); render(); refreshCount(); tbFill();
};
tbEl("tbFs").onchange = e => tbSet({ fs: Math.max(8, parseInt(e.target.value, 10) || 0) });
tbEl("tbColor").onchange = e => tbSet({ color: e.target.value });
tbEl("tbBold").onclick = () => {
  const n = ntf(tbCur);
  tbSet({ bold: (n ? n.bold : tstyleOf(tbCur).bold) ? null : true });
};
tbEl("tbHide").onclick = () => {
  const n = ntf(tbCur);
  const cur = n ? n.hide : tstyleOf(tbCur).hide;
  tbSet({ hide: cur ? null : true });
};
tbEl("tbRevert").onclick = () => {
  if (!tbCur) return;
  delete edit.tstyle[tbCur];
  if (edit.pos) delete edit.pos[tbCur];
  if (tbCur[0] === "s") delete edit.slotText[tbCur.slice(1)];
  else if (tbCur[0] === "o") delete edit.text[+tbCur.slice(1)];
  else if (tbCur[0] === "n") edit.nt = (edit.nt || []).filter(t => "n" + t.id !== tbCur);
  save(); render(); refreshCount(); tbFill();
};
tbEl("tbNew").onclick = () => addNT();
tbEl("tbX").onchange = tbMove;
tbEl("tbY").onchange = tbMove;
function tbClose() {
  tbEl("textbar").classList.remove("on");
  tbEl("bText").classList.remove("on");
}
tbEl("tbClose").onclick = tbClose;
tbEl("bText").onclick = e => {
  const p = tbEl("textbar");
  p.classList.toggle("on");
  e.target.classList.toggle("on", p.classList.contains("on"));
  if (p.classList.contains("on")) tbFill();
};
function exportData() {
  const totalDown = ORD_G.reduce((n, g) => n + ((edit.down || {})[g] || 0), 0);
  return { canvas: [__W__, __H__ + totalDown], slots: changed(),
           pos: edit.pos || {}, nt: edit.nt || [],
           newSlots: edit.newSlots || [], down: edit.down || {},
           slotShift: edit.slotShift || {}, layerShift: edit.layerShift || {},
           allSlots: slotsAll().map(s => ({ slot: s.id, group: s.group, name: s.name,
                                            attr: !!s.attr, box: boxOf(s),
                                            ring: s.ring || 6, bg: s.bg || "",
                                            content: isSlotEmpty(s.id) ? null : contentOf(s.id) })) };
}
/* ---------- 导出到本地文件（没有仓库写权限时的退路） ---------- */
function exportLocal() {
  const data = exportData();
  const blob = new Blob([JSON.stringify(data, null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "psb_slots.json"; a.click();
}

/* ---------- 云端保存 ----------
   令牌只存这台浏览器；能不能存不靠页面判断，靠仓库权限：写入被拒就是没权限。
   保存前先校验，坏数据一律不写进仓库。 */
const GH = { owner: "ArcadiaUD", repo: "StarSavior-helper", branch: "main",
             path: "docs/psb_slots.json", token: "", login: "", canPush: false, busy: false };
const TOKEN_KEY = "psbGhToken";
const ghEl = id => document.getElementById(id);
function ghState(text, cls) {
  const e = ghEl("ghState");
  e.textContent = text;
  e.className = "hint" + (cls ? " " + cls : "");
}
function ghHeaders(extra) {
  return Object.assign({ "Authorization": "Bearer " + GH.token,
                         "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28" }, extra || {});
}
function ghFetch(path, opt) {
  const o = Object.assign({}, opt || {});
  o.headers = ghHeaders(o.headers);
  return fetch("https://api.github.com" + path, o);
}
function b64utf8(s) {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
/* 写入前校验：坏数据写进仓库会直接打穿面板，这里一律拦下 */
function validatePayload(data) {
  if (!Array.isArray(data.canvas) || data.canvas.length !== 2 ||
      !data.canvas.every(n => typeof n === "number" && isFinite(n) && n > 0))
    return "画布尺寸不合法";
  const [W, H] = data.canvas;
  const all = data.allSlots;
  if (!Array.isArray(all) || !all.length) return "格位列表为空";
  const sid = v => (typeof v === "string" || typeof v === "number") ? String(v) : "";
  const seen = new Set();
  for (const s of all) {
    if (!s) return "格位列表里有空项";
    const id = sid(s.slot);
    if (!id) return "有格位缺编号";
    if (seen.has(id)) return "格位编号重复：" + id;
    seen.add(id);
    if (!Array.isArray(s.box) || s.box.length !== 4 ||
        !s.box.every(n => typeof n === "number" && isFinite(n)))
      return "格位坐标不合法：" + id;
    const [x, y, w, h] = s.box;
    if (x < -2 || y < -2 || x + w > W + 2 || y + h > H + 2)
      return "格位越出画布：" + id;
  }
  // 位移是按「可拖动项」（文字条、图层名）建键的，不是格位编号，所以只校验数值形状
  for (const k of Object.keys(data.pos || {})) {
    const v = data.pos[k];
    if (!Array.isArray(v) || v.length !== 2 ||
        !v.every(n => typeof n === "number" && isFinite(n)))
      return "位移数值不合法：" + k;
  }
  for (const l of (data.slots || [])) {
    if (!l) return "改动记录里有空项";
    const id = sid(l.slot);
    if (!seen.has(id)) return "改动记录指向了不存在的格位：" + id;
    if (l.content !== null && l.content !== undefined && !sid(l.content))
      return "内容引用不合法：" + id;
    if (l.char) {
      const k = l.char + (l.form ? "|" + l.form : "");
      if (!(FACES[k] || FACES[l.char])) return "头像身份查不到：" + k + "（" + id + "）";
    }
    if (l.art && !/^(layers|faces)\//.test(l.art.src || ""))
      return "素材引用不合法：" + id + " → " + (l.art && l.art.src);
  }
  return null;
}
function ghSetConnected() {
  ghEl("bPush").disabled = !GH.canPush;
  ghEl("ghbox").classList.remove("on");
}
async function ghConnect(silent) {
  const typed = (ghEl("ghToken").value || "").trim();
  const token = typed || GH.token;
  if (!token) { ghEl("ghbox").classList.add("on"); ghEl("ghMsg").textContent = "先贴令牌"; return; }
  GH.token = token;
  if (!silent) ghState("校验令牌…");
  try {
    const r = await ghFetch(`/repos/${GH.owner}/${GH.repo}`);
    if (!r.ok) throw new Error("读仓库失败 " + r.status + (r.status === 401 ? "（令牌无效或已过期）" : ""));
    const repo = await r.json();
    const me = await ghFetch("/user");
    GH.login = me.ok ? (await me.json()).login : "";
    GH.canPush = !!(repo.permissions && repo.permissions.push);
    ghSetConnected();
    if (GH.canPush) {
      localStorage.setItem(TOKEN_KEY, token);
      ghState("已连接 " + (GH.login || "?") + " · 可保存", "ok");
    } else {
      ghState("已连接 " + (GH.login || "?") + " · 只读", "bad");
    }
  } catch (e) {
    GH.canPush = false; ghSetConnected();
    ghState("连接失败", "bad");
    ghEl("ghbox").classList.add("on");
    ghEl("ghMsg").textContent = e.message;
  }
}
/* ---------- 「已生效」反馈 ----------
   保存成功只代表存档进了仓库，站点要等云端重建完才换数据。这里拿自己刚提交的那份
   存档去比对云端写下的指纹，对上了就说明重建完成，状态从「已保存」变「已生效」。 */
const MARK_URL = "https://raw.githubusercontent.com/ArcadiaUD/StarSavior-helper/main/docs/board_build.json";
const MARK_WAIT_MS = 180000;
let ghPollT = null, ghPendingSha = null;

async function ghSha256(text) {
  /* 本地用 file:// 打开时没有 crypto.subtle，这种情况只显示「已保存」 */
  if (!(window.crypto && crypto.subtle)) return null;
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(d)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function ghWaitEffect(payload, shortSha) {
  const sha = await ghSha256(payload);
  if (!sha) { ghState("已保存 " + shortSha, "ok"); return; }
  ghPendingSha = sha;
  const t0 = Date.now();
  ghState("已保存 " + shortSha + " · 站点重建中…", "ok");
  clearInterval(ghPollT);
  ghPollT = setInterval(async () => {
    if (ghPendingSha !== sha) { clearInterval(ghPollT); return; }
    try {
      const r = await fetch(MARK_URL + "?t=" + Date.now(), { cache: "no-store" });
      if (r.ok) {
        const m = await r.json();
        if (m && m.slots_sha256 === sha) {
          clearInterval(ghPollT); ghPendingSha = null;
          ghState("已生效（" + Math.round((Date.now() - t0) / 1000) + " 秒）· " + shortSha, "ok");
          flash("站点已生效");
          return;
        }
      }
    } catch (e) {}
    if (Date.now() - t0 > MARK_WAIT_MS) {
      clearInterval(ghPollT); ghPendingSha = null;
      ghState("已保存 " + shortSha + "（站点还没重建完）", "bad");
    }
  }, 3000);
}

async function ghPush() {
  if (GH.busy) return;
  if (!GH.canPush) { flash("没连上仓库或没有写权限，保存被拒"); return; }
  let data;
  try { data = exportData(); } catch (e) { flash("导出失败：" + e.message); return; }
  const bad = validatePayload(data);
  if (bad) { flash("校验未过，已拒绝写入：" + bad); return; }
  GH.busy = true;
  ghState("保存中…");
  const url = `/repos/${GH.owner}/${GH.repo}/contents/${GH.path}`;
  try {
    let sha = null;
    const cur = await ghFetch(url + "?ref=" + GH.branch);
    if (cur.ok) sha = (await cur.json()).sha;
    else if (cur.status !== 404) throw new Error("读取当前版本失败 " + cur.status);
    const payload = JSON.stringify(data, null, 1);
    const body = { message: "编辑保存（" + (GH.login || "协作者") + "）",
                   content: b64utf8(payload), branch: GH.branch };
    if (sha) body.sha = sha;
    const put = () => ghFetch(url, { method: "PUT", body: JSON.stringify(body) });
    let r = await put();
    if (r.status === 409 || r.status === 422) {           /* 别人刚好也存过，取新版本再试一次 */
      const c2 = await ghFetch(url + "?ref=" + GH.branch);
      if (c2.ok) { body.sha = (await c2.json()).sha; r = await put(); }
    }
    if (!r.ok) throw new Error(r.status + " " + (await r.text()).slice(0, 160));
    const out = await r.json();
    const short = out.commit.sha.slice(0, 7);
    flash("已存到仓库 " + short);
    await ghWaitEffect(payload, short);
  } catch (e) {
    ghState("保存失败", "bad");
    flash("保存失败：" + e.message);
  } finally {
    GH.busy = false;
  }
}
ghEl("bGh").onclick = () => {
  const box = ghEl("ghbox");
  box.classList.toggle("on");
  if (box.classList.contains("on")) ghEl("ghToken").focus();
};
ghEl("ghDo").onclick = () => ghConnect(false);
ghEl("ghToken").onkeydown = e => { if (e.key === "Enter") ghConnect(false); };
ghEl("ghForget").onclick = () => {
  GH.token = ""; GH.login = ""; GH.canPush = false;
  localStorage.removeItem(TOKEN_KEY);
  ghEl("ghToken").value = ""; ghSetConnected(); ghState("未连接仓库");
};
ghEl("bPush").onclick = ghPush;
document.getElementById("bSave").onclick = () => { if (GH.canPush) ghPush(); else exportLocal(); };
addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
    e.preventDefault();
    if (GH.canPush) ghPush();
    else { exportLocal(); flash("还没连上仓库（或没有写权限），已改为导出文件"); }
  }
});
/* 上次连过就静默复连，省得每次重贴令牌 */
(function () {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) { GH.token = t; ghState("恢复连接…"); ghConnect(true); }
})();
document.getElementById("bLoad").onclick = () => document.getElementById("file").click();
document.getElementById("file").onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    try {
      const data = JSON.parse(rd.result);
      if (data.pos) edit.pos = data.pos;
      if (data.nt) edit.nt = data.nt;
      edit.newSlots = data.newSlots || [];
      edit.down = data.down || {};
      edit.slotShift = data.slotShift || {};
      edit.layerShift = data.layerShift || {};
      for (const l of data.slots || []) {
        if (l.content === null) edit.place[l.slot] = EMPTY;
        else if (l.content !== undefined) edit.place[l.slot] = l.content;
        if (l.art) edit.art[l.slot] = l.art;
        if (l.char) edit.char[l.slot] = l.char + (l.form ? "|" + l.form : "");
        else delete edit.char[l.slot];
        if (l.textChanged) edit.slotText[l.slot] = l.text || "";
      }
      save(); render(); tbFill();
    } catch (err) { flash("导入失败：" + err.message); }
  };
  rd.readAsText(f);
};
document.getElementById("bClear").onclick = () => {
  if (!confirm("清空全部改动，回到作者原稿？")) return;
  for (const k of ["place","art","text","slotText","char","tstyle","pos"]) edit[k] = {};
  edit.nt = []; edit.newSlots = []; edit.down = {};
  edit.slotShift = {}; edit.layerShift = {};
  save(); sel = null; hideInsp(); render(); tbFill();
};

function renderLib() {
  const q = document.getElementById("libQ").value.trim();
  const box = document.getElementById("libList");
  box.innerHTML = "";
  for (const it of LIB) {
    if (q && !(it.c.includes(q) || it.f.includes(q))) continue;
    const d = document.createElement("div");
    d.className = "libItem";
    d.draggable = true;
    d.title = it.c + " · " + it.f;
    const img = document.createElement("img");
    img.src = it.s;
    img.draggable = false;
    const sp = document.createElement("span");
    sp.textContent = it.c;
    d.appendChild(img); d.appendChild(sp);
    d.addEventListener("dragstart", e => {
      e.dataTransfer.setData("text/plain", JSON.stringify({ src: it.s, c: it.c, f: it.f }));
      e.dataTransfer.effectAllowed = "copy";
    });
    box.appendChild(d);
  }
}
document.getElementById("libBtn").onclick = e => {
  const lib = document.getElementById("lib");
  lib.classList.toggle("open");
  document.body.classList.toggle("libopen", lib.classList.contains("open"));
  e.target.classList.toggle("on");
  if (lib.classList.contains("open")) renderLib();
};
document.getElementById("libClose").onclick = () => {
  document.getElementById("lib").classList.remove("open");
  document.body.classList.remove("libopen");
  document.getElementById("libBtn").classList.remove("on");
};
document.getElementById("libQ").addEventListener("input", renderLib);

document.getElementById("bFrame").onclick = e => { document.body.classList.toggle("frames"); e.target.classList.toggle("on"); };
document.getElementById("bTags").onclick = e => { document.body.classList.toggle("tags"); e.target.classList.toggle("on"); };
document.getElementById("bBig").onclick = e => { hideBig = !hideBig; e.target.classList.toggle("on"); render(); };
document.body.classList.add("pickbg");           /* 素材默认可拖 */
document.getElementById("bPick").onclick = e => {
  const on = document.body.classList.toggle("pickbg");
  e.target.classList.toggle("on", on);
};
document.getElementById("bOut").onclick = () => { z = Math.max(0.1, z - 0.06); setZoom(); };
document.getElementById("bIn").onclick = () => { z = Math.min(1.2, z + 0.06); setZoom(); };
document.getElementById("bUndo").onclick = undo;
document.getElementById("bAdd").onclick = () => {
  if (sel === null) { flash("先在画布上点选一个格位，新格会加在它后面"); return; }
  addSlot(sel);
};
document.addEventListener("keydown", e => {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || String(e.key).toLowerCase() !== "z") return;
  const a = document.activeElement, tag = a ? a.tagName : "";
  if (a && (a.isContentEditable || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA")) return;
  e.preventDefault(); undo();
});
undoBase = snap();
setZoom();
function setZoom() { document.getElementById("fit").style.setProperty("--z", z); render(); }
render();
</script></body></html>
"""

if __name__ == "__main__":
    build()
