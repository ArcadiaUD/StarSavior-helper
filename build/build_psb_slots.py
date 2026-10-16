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

SLOT_GROUPS = {"全场景必练T0", "全场景必练T0.5", "全场景必练T1", "T1功能角色", "T2功能角色",
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
# 原稿就有的塔层（headroom_shift 按它们算档间间隙补偿）。
# 「全场景必练T1」是后来新加的层，原稿里没有，不能进这里——它的下移量由存档的 down
# 表达（见 build_psb_full.py 的层顺序表），否则这里会取不到该组的 top/bot。
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
    uidx = unit_index()
    lib = []
    for cn, forms in faces.items():
        for fn, sp in forms.items():
            if not fn:                    # 空形态名是原型自己的脸，只用来兜底，不进头像库列表
                continue
            it = {"c": cn, "f": fn, "s": sp}
            no = uidx.get(Path(sp).stem)
            if no is not None:
                it["no"] = no             # 单位编号：面板角色详情页显示的就是它
            lib.append(it)
    lib.sort(key=lambda x: (x.get("no") if x.get("no") is not None else 1 << 30, x["c"], x["f"]))

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

    html = build_editor_html(slots=slots, others=others, roster=roster, grades=grades,
                             faces=facemap, panel=panel, lib=lib)
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





# ---------------- 编辑器源码只有一份 ----------------
# 实验台不再自带一份 HTML 模板：直接以仓库里的 docs/editor.html 为源码，把里面内联的数据块
# 换成这次从原稿生成的结果。以前这里存着一份模板、编辑器另有更新，两边必然漂移
# （2026-10-16 就落后过：存档改成完整版面、头像库补编号，实验台都没跟上）。
REPO = Path(__file__).resolve().parent.parent
EDITOR_SRC = REPO / "docs" / "editor.html"
DATA_BLOCKS = (
    ("const SLOTS_ORIG = ", "slots", ";"),
    ("const OTHERS_ORIG = ", "others", ";"),
    ("const ROSTER = ", "roster", ";"),
    ("const LIB = ", "lib", ";"),
    ("const FACES = ", "faces", ";"),
    ("const PANEL_BOX_ORIG = ", "panel", ";"),
    ("const GRADES = ", "grades", ";"),
)


def unit_index():
    """素材名（不含扩展名）→ 单位编号。

    与面板角色详情页显示的那个「单位编号」同一来源（out/journey_kb.json 的形态表）。
    头像库按它排序，不再按名字排。
    """
    p = PANEL / "out" / "journey_kb.json"
    if not p.is_file():
        return {}
    kb = json.loads(p.read_text(encoding="utf-8"))
    idx = {}
    for c in kb.get("characters") or []:
        for f in c.get("forms") or []:
            face = (f.get("face") or "").split("/")[-1]
            if face:
                idx.setdefault(Path(face).stem, f.get("unit_id"))
    return idx


def build_editor_html(**data):
    """读仓库里的编辑器，换掉数据块，得到实验台那一份。"""
    html = EDITOR_SRC.read_text(encoding="utf-8")
    for head, key, close in DATA_BLOCKS:
        # 数据块都写在一行里，按整行匹配 —— 用 .*? 会在数据里遇到 ] 就提前收尾
        pat = re.escape(head) + r".*$"
        rep = head + json.dumps(data[key], ensure_ascii=False) + close
        html, n = re.subn(pat, lambda _m: rep, html, count=1, flags=re.M)
        if n != 1:
            raise SystemExit("编辑器里找不到这段数据块：%s" % head)
    return html


if __name__ == "__main__":
    build()
