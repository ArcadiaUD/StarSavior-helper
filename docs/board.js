/* 强度榜整版渲染器：网页成品页与面板只读页共用这一份实现。
 *
 * 数据形状（board.json 与 window.BOARD_DATA 同构）：
 *   { w, h, bases: {layers, faces}, items: [...图层...], grades: {"角色名|形态名": "SSR"|"SR"} }
 * bases 是素材前缀：网页侧是 "layers/"、"faces/"；面板侧是 assets 下的绝对 file:// 前缀。
 * 两类图层取值不同：
 *   格位（it.cell）：头像走 faces 头像库（it.src 优先，否则 it.face），没有就是空位
 *   普通图层：图片走 layers/ + it.file
 */
(function (global) {
  "use strict";

  var RARITY_COLOR = { SSR: "#fedd62", SR: "#a874e8", "": "#8b93a8" };

  function isAbs(name) {                     /* 本来就是绝对地址或数据地址就不动它 */
    return /^(?:data:|https?:|file:|blob:|[a-zA-Z]:[\\/]|\/)/.test(name || "");
  }

  function joinBase(base, name) {
    if (!name) return null;
    if (isAbs(name)) return name;
    base = base || "";
    if (base && base.charAt(base.length - 1) !== "/") base += "/";
    return base + name.split(/[\\/]/).pop();
  }

  function sourceOf(board, it) {
    var bases = board.bases || {};
    if (it.cell) return joinBase(bases.faces, it.src || it.face);
    return joinBase(bases.layers, it.file);
  }

  function View(stage, board) {
    this.stage = stage;
    this.board = board;
    this.hideBig = false;
    this.zoom = 0.26;
    stage.style.width = board.w + "px";
    stage.style.height = board.h + "px";
  }

  View.prototype.rank = function (char, form) {
    var g = this.board.grades || {};
    if (!char) return "";
    return g[char + (form ? "|" + form : "")] || g[char] || "";
  };

  View.prototype.render = function () {
    var board = this.board, stage = this.stage, hideBig = this.hideBig, self = this;
    stage.innerHTML = "";
    for (var i = 0; i < board.items.length; i++) {   /* 正序插入：seq 自底向上编，后插的层压在上面 */
      var it = board.items[i], box = it.box;
      var x = box[0], y = box[1], w = box[2], h = box[3];
      if (it.t === "text") {
        var t = document.createElement("div");
        t.className = "lb";
        t.style.left = x + "px"; t.style.top = y + "px"; t.style.width = w + "px";
        if (it.cap) {    /* 格下说明栏：栏宽已被收进头像宽，字比栏宽时按编辑器那套折行并居中 */
          t.style.whiteSpace = "pre-wrap";
          t.style.overflowWrap = "anywhere";
          t.style.textAlign = "center";
        }
        var lh = it.lh || Math.round(h / (it.lines || 1));
        var fs = it.fs || Math.round(lh * 0.78);
        t.style.fontSize = fs + "px";
        t.style.lineHeight = lh + "px";
        t.style.color = it.color;
        t.style.fontWeight = fs >= 46 ? "700" : "400";
        t.textContent = it.text;
        stage.appendChild(t);
        continue;
      }
      if (hideBig && it.big) continue;
      var d = document.createElement("div");
      d.className = "lyr" + (it.cell ? " cell" : "");
      d.style.left = x + "px"; d.style.top = y + "px"; d.style.width = w + "px";
      /* 铺满整幅的黑底标了 grow：高度顶到画布底，往下加多少格都不会露出来 */
      d.style.height = (it.grow ? (board.h - y) : h) + "px";
      if (it.cell) d.style.background = it.bg || "#2b3038";
      if (it.ph) d.classList.add("ph");
      /* 格位不用 PSB 原稿那张图（金框 + 立绘 + 角标）：只显示实际挂上去的头像 */
      var face = sourceOf(board, it);
      if (face) {
        var img = document.createElement("img");
        img.src = face;
        img.alt = it.name;
        d.appendChild(img);
      } else if (it.cell) {
        d.classList.add("blank");
      }
      if (it.cell && face) {
        var ring = document.createElement("i");      /* 稀有度边框：SSR 金 / SR 紫 */
        ring.className = "ring";
        ring.style.borderWidth = Math.max(it.ring || 6, 2) + "px";
        ring.style.borderColor = RARITY_COLOR[self.rank(it.char, it.form)] || RARITY_COLOR[""];
        d.appendChild(ring);
      }
      if (it.cell) {
        var tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = it.name + (it.char ? " → " + it.char + (it.form ? "·" + it.form : "") : "（未指定）");
        d.appendChild(tag);
      }
      stage.appendChild(d);
    }
    this.syncZoomText();
  };

  View.prototype.applyZoom = function () {
    this.stage.style.setProperty("--z", this.zoom);
  };

  View.prototype.zoomBy = function (step) {
    this.zoom = Math.min(1.2, Math.max(0.1, this.zoom + step));
    this.applyZoom();
    this.syncZoomText();
  };

  View.prototype.setZoom = function (z) {
    this.zoom = Math.min(1.2, Math.max(0.1, z));
    this.applyZoom();
    this.syncZoomText();
  };

  View.prototype.syncZoomText = function () {
    var out = document.getElementById("ztext");
    if (out) out.textContent = "缩放 " + Math.round(this.zoom * 100) + "%";
  };

  /* 页面上的那几个开关按钮：有就绑，没有就跳过（面板页与网页页共用同一套按钮） */
  View.prototype.bindBar = function () {
    var self = this;
    function on(id, fn) { var el = document.getElementById(id); if (el) el.onclick = fn; }
    on("bTags", function (e) { document.body.classList.toggle("tags"); e.target.classList.toggle("on"); });
    on("bBig", function (e) { self.hideBig = !self.hideBig; e.target.classList.toggle("on"); self.render(); });
    on("bZoomIn", function () { self.zoomBy(0.06); });
    on("bZoomOut", function () { self.zoomBy(-0.06); });
  };

  View.prototype.start = function () {
    this.applyZoom();
    this.render();
    this.bindBar();
    return this;
  };

  global.BoardView = {
    create: function (stage, board) { return new View(stage, board).start(); },
    View: View,
    RARITY_COLOR: RARITY_COLOR
  };
})(window);
