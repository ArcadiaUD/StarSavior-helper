/* 支援卡榜整版渲染器：格位（洞）＋原稿其余图层。
 *
 * 数据形状（sc_board.json）：
 *   { w, h, bases:{layers, cards}, cards:[卡库…], items:[非格位图层与文字],
 *     slots:[{id, group, name, box, win, base, 原卡, 卡, 空}…] }
 * 两类东西分开画：
 *   非格位图层：图片走 bases.layers + it.file；文字用网页排版（颜色取自原稿整图）
 *   格位（洞）：底图是该格的原稿卡块；只有当挂的卡与原卡不同时，才用库卡面盖住窗口区域
 * 这样默认状态与原稿像素一致，换卡后立刻看到新卡。
 */
(function (global) {
  "use strict";

  var CSS = [
    ".scstage{position:absolute;left:0;top:0;transform-origin:0 0;transform:scale(var(--z));background:#303030;}",
    ".scstage .lb{position:absolute;white-space:pre;}",
    ".scstage .lyr{position:absolute;}",
    ".scstage .lyr img{width:100%;height:100%;display:block;}",
    ".scstage .slot{position:absolute;}",
    ".scstage .slot .f{position:absolute;left:0;top:0;width:100%;height:100%;display:block;}",
    ".scstage .slot .w{position:absolute;display:block;}",
    ".scstage .slot .w.hollow{border:2px dashed #6b7488;background:#0e1116aa;}",
    ".scstage .slot .hint{position:absolute;left:0;right:0;bottom:6px;text-align:center;font-size:15px;color:#7b8497;pointer-events:none;}",
    ".scstage .slot.sel{outline:3px solid #6ea8fe;outline-offset:-3px;}"
    ,".scstage .slot.drop{outline:4px solid #6ea8fe;outline-offset:-3px;background:#6ea8fe33;}",
    ".scstage .slot .tag{position:absolute;left:0;top:-16px;font-size:11px;color:#8fb8f5;background:#11131acc;padding:0 4px;border-radius:4px;display:none;white-space:nowrap;}",
    "body.sctags .scstage .slot .tag{display:block;}"
  ].join("");
  if (typeof document !== "undefined" && !document.getElementById("scstage-css")) {
    var st = document.createElement("style");
    st.id = "scstage-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function join(base, name) {
    if (!name) return "";
    if (/^(?:data:|https?:|file:|blob:|[a-zA-Z]:[\\/]|\/)/.test(name)) return name;
    base = base || "";
    if (base && base.charAt(base.length - 1) !== "/") base += "/";
    return base + name.split(/[\\/]/).pop();
  }

  function View(stage, board) {
    this.stage = stage;
    this.board = board;
    this.zoom = 0.26;
    stage.classList.add("scstage");
    stage.style.width = board.w + "px";
    stage.style.height = board.h + "px";
    this.nodes = {};
  }

  View.prototype.cardOf = function (id) {
    var cards = this.board.cards || [];
    for (var i = 0; i < cards.length; i++) if (cards[i].id === id) return cards[i];
    return null;
  };

  View.prototype.render = function () {
    var b = this.board, stage = this.stage, bases = b.bases || {};
    stage.innerHTML = "";
    this.nodes = {};
    var self = this;

    (b.items || []).forEach(function (it, idx) {
      var box = it.box, x = box[0], y = box[1], w = box[2], h = box[3];
      if (it.t === "text") {
        if (it.hidden) return;
        var t = document.createElement("div");
        t.className = "lb";
        t.dataset.idx = idx;
        t.style.left = x + "px"; t.style.top = y + "px"; t.style.width = w + "px";
        var lh = it.lh || Math.round(h / (it.lines || 1));
        var fs = it.fs || Math.round(lh * 0.78);
        t.style.fontSize = fs + "px";
        t.style.lineHeight = lh + "px";
        t.style.color = it.color || "#d8dbe3";
        t.style.fontWeight = it.bold ? "700" : (fs >= 46 ? "700" : "400");
        t.textContent = it.text;
        stage.appendChild(t);
        return;
      }
      var d = document.createElement("div");
      d.className = "lyr";
      d.dataset.idx = idx;
      d.style.left = x + "px"; d.style.top = y + "px";
      d.style.width = w + "px";
      d.style.height = (it.grow ? (b.h - y) : h) + "px";
      var img = document.createElement("img");
      img.src = join(bases.layers, it.file);
      img.alt = it.name || "";
      d.appendChild(img);
      stage.appendChild(d);
    });

    (b.slots || []).forEach(function (s) {
      var box = s.box, win = s.win;
      var d = document.createElement("div");
      d.className = "slot";
      d.dataset.slot = s.id;
      d.style.left = box[0] + "px"; d.style.top = box[1] + "px";
      d.style.width = box[2] + "px"; d.style.height = box[3] + "px";

      var frame = document.createElement("img");        /* 这一格自己的卡框（窗口已挖空） */
      frame.className = "f";
      frame.src = join((b.bases || {}).frames, s.frame);
      frame.alt = s.name || "";
      d.appendChild(frame);

      var card = self.cardOf(s["卡"]);
      var hole = document.createElement("div");          /* 窗口：空着就是洞，挂上卡就显示卡面 */
      hole.className = "w";
      hole.style.left = (win[0] - box[0]) + "px";
      hole.style.top = (win[1] - box[1]) + "px";
      hole.style.width = win[2] + "px";
      hole.style.height = win[3] + "px";
      if (card && !s["空"]) {
        var c = document.createElement("img");
        c.className = "c";
        c.style.width = "100%"; c.style.height = "100%"; c.style.display = "block";
        c.src = join((b.bases || {}).cards, card.file);
        c.alt = card["角色"] + "·" + card["卡名"];
        hole.appendChild(c);
      } else {
        hole.classList.add("hollow");
      }
      d.appendChild(hole);
      self.nodes[s.id] = { el: d, hole: hole, slot: s };

      var tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = s.name + (card ? " → " + card["角色"] + "·" + card["卡名"] : "（空位）");
      d.appendChild(tag);
      stage.appendChild(d);
    });
  };

  View.prototype.applyZoom = function () {
    this.stage.style.setProperty("--z", this.zoom);
  };

  View.prototype.start = function () {
    this.applyZoom();
    this.render();
    return this;
  };

  global.SCBoardView = {
    create: function (stage, board) { return new View(stage, board).start(); },
    View: View
  };
})(window);
