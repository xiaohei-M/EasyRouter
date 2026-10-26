/* ============ 易路由 轻量 Canvas 折线图（无第三方依赖） ============ */
(function () {
  "use strict";

  function fmtBps(v) {
    v = Math.max(0, v || 0);
    if (v >= 1e9) return (v / 1e9).toFixed(2) + " Gbps";
    if (v >= 1e6) return (v / 1e6).toFixed(1) + " Mbps";
    if (v >= 1e3) return (v / 1e3).toFixed(1) + " Kbps";
    return Math.round(v) + " bps";
  }

  function fmtVal(v, unit) {
    if (unit === "bps") return fmtBps(v);
    return String(Math.round(v || 0));
  }

  function fmtTime(t) {
    var d = new Date(t);
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  class LineChart {
    constructor(canvas, opts) {
      opts = opts || {};
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.series = opts.series || [];
      this.unit = opts.unit || "bps";
      this.maxPoints = opts.maxPoints || 180;
      this.points = [];
      this.hover = null;
      this.dpr = window.devicePixelRatio || 1;
      this._onMove = this._onMove.bind(this);
      this._onLeave = this._onLeave.bind(this);
      canvas.addEventListener("mousemove", this._onMove);
      canvas.addEventListener("mouseleave", this._onLeave);
      window.addEventListener("resize", this.draw.bind(this));
    }

    setPoints(points) {
      this.points = (points || []).slice(-this.maxPoints);
      this.draw();
    }

    _onMove(e) {
      var rect = this.canvas.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var geom = this._geom(rect.width, rect.height);
      if (!geom || !this.points.length) return;
      var idx = Math.round((x - geom.padL) / geom.stepX);
      if (idx < 0 || idx >= this.points.length) { this.hover = null; }
      else { this.hover = idx; }
      this.draw();
    }

    _onLeave() { this.hover = null; this.draw(); }

    _geom(w, h) {
      var padL = 58, padR = 12, padT = 12, padB = 24;
      var iw = w - padL - padR, ih = h - padT - padB;
      if (iw <= 10 || ih <= 10) return null;
      var stepX = this.points.length > 1 ? iw / (this.points.length - 1) : iw;
      return { padL: padL, padR: padR, padT: padT, padB: padB, iw: iw, ih: ih, stepX: stepX };
    }

    _maxValue() {
      var m = 0;
      for (var i = 0; i < this.points.length; i++) {
        var p = this.points[i];
        for (var s = 0; s < this.series.length; s++) {
          var v = p[this.series[s].key] || 0;
          if (v > m) m = v;
        }
      }
      return m * 1.12 || 1;
    }

    draw() {
      var canvas = this.canvas, ctx = this.ctx;
      var rect = canvas.getBoundingClientRect();
      if (rect.width < 5 || rect.height < 5) return;
      canvas.width = Math.round(rect.width * this.dpr);
      canvas.height = Math.round(rect.height * this.dpr);
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      var w = rect.width, h = rect.height;
      ctx.clearRect(0, 0, w, h);

      var geom = this._geom(w, h);
      if (!geom) return;
      var g = geom;

      // 空数据
      if (!this.points.length) {
        ctx.fillStyle = "#5f6d80";
        ctx.font = "13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("暂无数据，正在采样…", w / 2, h / 2);
        return;
      }

      var maxV = this._maxValue();
      var gridN = 4;

      // 网格与 Y 轴标签
      ctx.textAlign = "right";
      ctx.font = "10.5px Consolas, monospace";
      for (var i = 0; i <= gridN; i++) {
        var y = g.padT + (g.ih * i) / gridN;
        var val = maxV * (1 - i / gridN);
        ctx.strokeStyle = "#1d2836";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(g.padL, y);
        ctx.lineTo(w - g.padR, y);
        ctx.stroke();
        ctx.fillStyle = "#5f6d80";
        ctx.fillText(fmtVal(val, this.unit), g.padL - 6, y + 3);
      }

      // X 轴时间标签
      ctx.textAlign = "center";
      ctx.fillStyle = "#5f6d80";
      var n = this.points.length;
      if (n > 1) {
        ctx.textAlign = "left";
        ctx.fillText(fmtTime(this.points[0].t), g.padL, h - 6);
        ctx.textAlign = "center";
        ctx.fillText(fmtTime(this.points[Math.floor((n - 1) / 2)].t), g.padL + g.iw / 2, h - 6);
        ctx.textAlign = "right";
        ctx.fillText(fmtTime(this.points[n - 1].t), w - g.padR, h - 6);
      }

      var X = function (idx) { return g.padL + g.stepX * idx; };
      var Y = function (v) { return g.padT + g.ih * (1 - v / maxV); };

      // 折线
      for (var s = 0; s < this.series.length; s++) {
        var ser = this.series[s];
        ctx.beginPath();
        for (var idx = 0; idx < n; idx++) {
          var v = this.points[idx][ser.key] || 0;
          var px = X(idx), py = Y(v);
          if (idx === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        if (ser.fill !== false) {
          ctx.lineTo(X(n - 1), g.padT + g.ih);
          ctx.lineTo(X(0), g.padT + g.ih);
          ctx.closePath();
          var grad = ctx.createLinearGradient(0, g.padT, 0, g.padT + g.ih);
          grad.addColorStop(0, ser.color + "44");
          grad.addColorStop(1, ser.color + "00");
          ctx.fillStyle = grad;
          ctx.fill();
        }
        ctx.beginPath();
        for (idx = 0; idx < n; idx++) {
          v = this.points[idx][ser.key] || 0;
          px = X(idx); py = Y(v);
          if (idx === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.strokeStyle = ser.color;
        ctx.lineWidth = 1.8;
        ctx.lineJoin = "round";
        ctx.stroke();
      }

      // 悬浮提示
      if (this.hover !== null && this.hover < n) {
        var hx = X(this.hover);
        ctx.strokeStyle = "#3d4c61";
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(hx, g.padT);
        ctx.lineTo(hx, g.padT + g.ih);
        ctx.stroke();
        ctx.setLineDash([]);
        var p = this.points[this.hover];
        var lines = [fmtTime(p.t)];
        for (s = 0; s < this.series.length; s++) {
          lines.push(this.series[s].label + ": " + fmtVal(p[this.series[s].key] || 0, this.unit));
        }
        ctx.font = "11px Consolas, monospace";
        var tw = 0;
        for (i = 0; i < lines.length; i++) tw = Math.max(tw, ctx.measureText(lines[i]).width);
        tw += 20;
        var th = lines.length * 16 + 12;
        var bx = hx + 10, by = g.padT + 6;
        if (bx + tw > w - 6) bx = hx - tw - 10;
        ctx.fillStyle = "rgba(10,15,22,.92)";
        ctx.strokeStyle = "#2e3d52";
        ctx.beginPath();
        if (ctx.roundRect) { ctx.roundRect(bx, by, tw, th, 6); }
        else { ctx.rect(bx, by, tw, th); }
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#8b99ab";
        ctx.textAlign = "left";
        for (i = 0; i < lines.length; i++) {
          ctx.fillStyle = i === 0 ? "#5f6d80" : (this.series[i - 1] ? this.series[i - 1].color : "#8b99ab");
          ctx.fillText(lines[i], bx + 10, by + 16 + i * 16);
        }
      }
    }
  }

  window.LineChart = LineChart;
})();
