/* ============ 易路由 EasyRouter 管理控制台（全中文） ============ */
"use strict";
window.__ER_APP_LOADED__ = true;

/* ---------- 工具 ---------- */
function $(sel, root) { return (root || document).querySelector(sel); }
function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function fmtRate(v) {
  v = Math.max(0, v || 0);
  if (v >= 1e9) return (v / 1e9).toFixed(2) + " Gbps";
  if (v >= 1e6) return (v / 1e6).toFixed(1) + " Mbps";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + " Kbps";
  return Math.round(v) + " bps";
}
function fmtBytes(n) {
  n = Math.max(0, n || 0);
  var u = ["B", "KB", "MB", "GB", "TB", "PB"];
  var i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2)) + " " + u[i];
}
function fmtPct(v) { return (v == null ? "-" : Number(v).toFixed(1) + "%"); }
function fmtDur(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600),
    m = Math.floor(sec % 3600 / 60), s = sec % 60;
  if (d > 0) return d + " 天 " + h + " 小时";
  if (h > 0) return h + " 小时 " + m + " 分";
  if (m > 0) return m + " 分 " + s + " 秒";
  return s + " 秒";
}
function fmtAgo(ts) {
  if (!ts) return "—";
  var diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  if (diff < 86400 * 30) return Math.floor(diff / 86400) + " 天前";
  return fmtDateTime(ts * 1000);
}
function fmtDateTime(ts) {
  var d = new Date(ts || Date.now());
  var p = function (n) { return (n < 10 ? "0" : "") + n; };
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
    " " + p(d.getHours()) + ":" + p(d.getMinutes());
}
/* ---------- 租期编辑器（年/月/日/时/分） ---------- */
function leaseToParts(value) {
  var inf = value === "infinite";
  var sec = 0;
  if (!inf) {
    var m = /^(\d+)([smhdw])$/.exec(String(value || ""));
    if (m) sec = parseInt(m[1], 10) * ({ s: 1, m: 60, h: 3600, d: 86400, w: 604800 }[m[2]] || 1);
    else if (/^\d+$/.test(String(value || ""))) sec = parseInt(value, 10);
    else sec = 12 * 3600;
  }
  var y = Math.floor(sec / 31536000); sec %= 31536000;
  var mo = Math.floor(sec / 2592000); sec %= 2592000;
  var d = Math.floor(sec / 86400); sec %= 86400;
  var h = Math.floor(sec / 3600); sec %= 3600;
  var mi = Math.floor(sec / 60);
  return { inf: inf, y: y, mo: mo, d: d, h: h, mi: mi };
}

function leaseEditorHtml(prefix) {
  var fields = [["y", "年"], ["mo", "月"], ["d", "日"], ["h", "时"], ["mi", "分"]];
  var html = '<div class="lease-grid">';
  fields.forEach(function (x) {
    html += '<label>' + x[1] + '<input type="number" min="0" id="' + prefix + "-" + x[0] + '" value="0"></label>';
  });
  html += '</div>';
  html += '<label class="inline" style="margin-top:6px"><input type="checkbox" id="' + prefix + '-inf"> 永久（不自动回收地址）</label>';
  html += '<div class="lease-presets">' +
    '<button type="button" class="btn xs" data-lease-preset="3600">1 小时</button>' +
    '<button type="button" class="btn xs" data-lease-preset="86400">1 天</button>' +
    '<button type="button" class="btn xs" data-lease-preset="604800">7 天</button>' +
    '<button type="button" class="btn xs" data-lease-preset="2592000">30 天</button>' +
    '<button type="button" class="btn xs" data-lease-preset="31536000">1 年</button>' +
    '<button type="button" class="btn xs" data-lease-preset="infinite">永久</button></div>';
  html += '<div class="gw-hint" id="' + prefix + '-total"></div>';
  return html;
}

function initLeaseEditor(prefix, value) {
  var parts = leaseToParts(value);
  var ids = ["y", "mo", "d", "h", "mi"];
  ids.forEach(function (k) {
    var el = document.getElementById(prefix + "-" + k);
    if (el) el.value = parts[k];
  });
  var inf = document.getElementById(prefix + "-inf");
  if (inf) inf.checked = parts.inf;
  function totalSecs() {
    return ["y", "mo", "d", "h", "mi"].reduce(function (sum, k, i) {
      var el = document.getElementById(prefix + "-" + k);
      var mul = [31536000, 2592000, 86400, 3600, 60][i];
      return sum + (el ? (parseInt(el.value, 10) || 0) * mul : 0);
    }, 0);
  }
  function sync() {
    var isInf = inf && inf.checked;
    ids.forEach(function (k) {
      var el = document.getElementById(prefix + "-" + k);
      if (el) el.disabled = !!isInf;
    });
    var tip = document.getElementById(prefix + "-total");
    if (!tip) return;
    if (isInf) { tip.textContent = "永久有效（不自动回收地址）"; return; }
    var sec = totalSecs();
    tip.textContent = "合计约 " + (sec / 86400).toFixed(2) + " 天（" + sec + " 秒）";
  }
  ids.forEach(function (k) {
    var el = document.getElementById(prefix + "-" + k);
    if (el) el.addEventListener("input", sync);
  });
  if (inf) inf.addEventListener("change", sync);
  var root = document.getElementById(prefix + "-total");
  if (root) {
    var wrap = root.parentElement;
    if (wrap && wrap.querySelectorAll) {
      wrap.querySelectorAll("[data-lease-preset]").forEach(function (b) {
        b.addEventListener("click", function () {
          var v = b.dataset.leasePreset;
          if (v === "infinite") {
            if (inf) inf.checked = true;
          } else {
            if (inf) inf.checked = false;
            var p = leaseToParts(parseInt(v, 10) + "s");
            ids.forEach(function (k) {
              var el = document.getElementById(prefix + "-" + k);
              if (el) el.value = p[k];
            });
          }
          sync();
        });
      });
    }
  }
  sync();
}

function readLeaseEditor(prefix) {
  var inf = document.getElementById(prefix + "-inf");
  if (inf && inf.checked) return "infinite";
  var mul = [31536000, 2592000, 86400, 3600, 60];
  var total = ["y", "mo", "d", "h", "mi"].reduce(function (sum, k, i) {
    var el = document.getElementById(prefix + "-" + k);
    return sum + (el ? (parseInt(el.value, 10) || 0) * mul[i] : 0);
  }, 0);
  if (total < 60) total = 60;
  return total + "s";
}

var KIND_ICON = {  phone: "📱", tablet: "📱", computer: "💻", tv: "📺", nas: "🗄️", camera: "📷",
  speaker: "🔊", printer: "🖨️", router: "📡", game: "🎮", iot: "🏠", watch: "⌚", device: "🖥️"
};
function kindIcon(kind) { return KIND_ICON[kind] || KIND_ICON.device; }

async function api(path, opts) {
  opts = opts || {};
  var res;
  try {
    res = await fetch(path, {
      method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : {},
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
    });
  } catch (e) {
    throw new Error("无法连接到路由器管理服务");
  }
  var data = null;
  try { data = await res.json(); } catch (e) { /* 非 JSON */ }
  if (res.status === 401) { showLogin(); throw new Error("登录已过期"); }
  if (res.status === 429 && data) { throw new Error(data.error || "请求过于频繁"); }
  if (!data || data.ok === false) {
    var msg = (data && (data.error || (data.errors || []).join("；"))) || ("请求失败（" + res.status + "）");
    throw new Error(msg);
  }
  return data;
}

/* ---------- 提示与模态框 ---------- */
function toast(msg, type, ms) {
  var root = $("#toast-root");
  var t = document.createElement("div");
  t.className = "toast " + (type || "ok");
  t.textContent = msg;
  root.appendChild(t);
  setTimeout(function () { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, (ms || 3500));
  setTimeout(function () { t.remove(); }, (ms || 3500) + 350);
}
function openModal(title, bodyHtml, actions, wide) {
  var root = $("#modal-root");
  root.innerHTML = '<div class="modal-mask"><div class="modal' + (wide ? " wide" : "") + '"><h3>' + esc(title) + '</h3>' +
    '<div class="modal-body">' + bodyHtml + '</div>' +
    '<div class="actions">' + actions + '</div></div></div>';
  return root.firstElementChild;
}
function closeModal() { $("#modal-root").innerHTML = ""; }
function confirmModal(title, bodyHtml, confirmText, danger) {
  return new Promise(function (resolve) {
    var mask = openModal(title, bodyHtml +
      '<div class="field"><span>请输入「' + esc(confirmText) + '」确认</span>' +
      '<input type="text" id="m-confirm-input" placeholder="' + esc(confirmText) + '"></div>',
      '<button class="btn ghost" id="m-cancel">取消</button>' +
      '<button class="btn ' + (danger ? "danger" : "primary") + '" id="m-ok" disabled>确定</button>');
    var ok = $("#m-ok", mask), cancel = $("#m-cancel", mask), input = $("#m-confirm-input", mask);
    input.addEventListener("input", function () { ok.disabled = input.value.trim() !== confirmText; });
    cancel.addEventListener("click", function () { closeModal(); resolve(false); });
    ok.addEventListener("click", function () { closeModal(); resolve(true); });
    input.focus();
  });
}
function promptModal(title, label, value, placeholder) {
  return new Promise(function (resolve) {
    var mask = openModal(title,
      '<div class="field"><span>' + esc(label) + '</span>' +
      '<input type="text" id="m-input" value="' + esc(value || "") + '" placeholder="' + esc(placeholder || "") + '" maxlength="32"></div>',
      '<button class="btn ghost" id="m-cancel">取消</button>' +
      '<button class="btn primary" id="m-ok">确定</button>');
    var input = $("#m-input", mask);
    input.focus();
    input.select();
    $("#m-cancel", mask).addEventListener("click", function () { closeModal(); resolve(null); });
    $("#m-ok", mask).addEventListener("click", function () { closeModal(); resolve(input.value.trim()); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { closeModal(); resolve(input.value.trim()); }
    });
  });
}

/* ---------- 全局状态 ---------- */
var state = {
  view: "overview",
  status: null,
  devicesSort: "ip", devicesQ: "", onlyOnline: false,
  leaseQ: "", leaseStatus: "all",
  cfg: null, interfaces: [],
  gateways: [], gatewayMethods: {},
  appsData: [],
  jobs: {}
};

var ovChart = null, tfChart = null, ssChart = null;
var viewBuilt = {};

function stopJob(name) {
  if (state.jobs[name]) { clearInterval(state.jobs[name]); delete state.jobs[name]; }
}
function startJob(name, fn, ms) {
  stopJob(name);
  fn();
  state.jobs[name] = setInterval(function () {
    if (document.hidden) return;
    fn();
  }, ms);
}

/* ---------- 登录 / 安装状态 ---------- */
function showScreen(name) {
  $$(".screen").forEach(function (s) { s.classList.add("hidden"); });
  // 主界面 #app 与登录/向导 #screen-* 是两套容器，注意不要去找不存在的 #screen-app
  $("#app").classList.toggle("hidden", name !== "app");
  var target = document.getElementById("screen-" + name);
  if (target) { target.classList.remove("hidden"); }
  window.__ER_BOOTED__ = true;
  var boot = document.getElementById("boot-status");
  if (boot) { boot.remove(); }
}

function showLogin() {
  stopJob("overview"); stopJob("devices"); stopJob("leases"); stopJob("traffic"); stopJob("sessions");
  stopJob("gateways"); stopJob("apps"); stopJob("system");
  showScreen("login");
}

function showBootError(message, detail) {
  try {
    var boot = document.getElementById("boot-status");
    if (boot) {
      boot.classList.add("error");
      boot.innerHTML = '<b>管理界面启动失败</b><br>' + esc(message) +
        (detail ? '<br><span class="muted small">' + esc(String(detail).slice(0, 400)) + '</span>' : "") +
        '<br>请按 <kbd>Ctrl</kbd> + <kbd>F5</kbd> 强制刷新后重试。';
    }
    if (window.__ER_REPORT__) window.__ER_REPORT__("boot-failed", message, detail);
  } catch (e) { /* 忽略 */ }
}

async function boot() {
  try {
    var st = await api("/api/status");
    state.status = st;
    $("#login-hint").classList.toggle("hidden", st.backend !== "demo");
    $("#side-foot").textContent = "v" + st.version + " · " + (st.backend === "demo" ? "演示模式" : "正式版");
    $("#demo-badge").classList.toggle("hidden", st.backend !== "demo");
    if (!st.setup_done) { showScreen("setup"); initSetup(); return; }
    if (!st.logged_in) { showLogin(); return; }
    showScreen("app");
    enterApp();
  } catch (e) {
    showBootError("无法获取系统状态（" + (e && e.message ? e.message : e) + "）", e && e.stack);
  }
}

function enterApp() {
  startJob("overview", pollOverview, 2000);
  switchView(state.view);
  var clock = $("#top-clock");
  function tickClock() {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    var weeks = ["日", "一", "二", "三", "四", "五", "六"];
    clock.textContent = p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds()) + " 星期" + weeks[d.getDay()];
  }
  tickClock();
  setInterval(tickClock, 1000);
}

/* ---------- 登录表单 ---------- */
$("#login-form").addEventListener("submit", async function (e) {
  e.preventDefault();
  var err = $("#login-error");
  err.classList.add("hidden");
  var btn = e.submitter; if (btn) btn.disabled = true;
  try {
    await api("/api/login", { body: { password: $("#login-pass").value } });
    toast("登录成功，欢迎回来！", "ok");
    await boot();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
  } finally { if (btn) btn.disabled = false; }
});
$("#btn-logout").addEventListener("click", async function () {
  try { await api("/api/logout", { body: {} }); } catch (e) { /* 忽略 */ }
  showLogin();
});

/* ---------- 导航 ---------- */
function switchView(name) {
  state.view = name;
  $$("#nav a").forEach(function (a) { a.classList.toggle("active", a.dataset.view === name); });
  $$(".view").forEach(function (v) { v.classList.add("hidden"); });
  $("#view-" + name).classList.remove("hidden");
  if (name === "overview") startJob("overview", pollOverview, 2000);
  else stopJob("overview");
  if (name === "devices") { buildDevices(); startJob("devices", pollDevices, 4000); }
  else stopJob("devices");
  if (name === "leases") { buildLeases(); startJob("leases", pollLeases, 5000); }
  else stopJob("leases");
  if (name === "traffic") { buildTraffic(); startJob("traffic", pollTraffic, 4000); }
  else stopJob("traffic");
  if (name === "sessions") { buildSessions(); startJob("sessions", pollSessions, 4000); }
  else stopJob("sessions");
  if (name === "apps") { buildApps(); startJob("apps", pollApps, 5000); }
  else stopJob("apps");
  if (name === "gateways") { buildGateways(); startJob("gateways", pollGateways, 8000); }
  else stopJob("gateways");
  if (name === "settings") buildSettings();
  if (name === "system") { buildSystem(); startJob("system", pollSystem, 5000); }
  else stopJob("system");
}
$$("#nav a").forEach(function (a) {
  a.addEventListener("click", function () { switchView(a.dataset.view); });
});
document.addEventListener("click", function (e) {
  var go = e.target.closest("[data-goto]");
  if (go) switchView(go.dataset.goto);
});

/* ================================================================
 * 概览
 * ================================================================ */
function buildOverview() {
  var v = $("#view-overview");
  v.innerHTML =
    '<div class="grid cards" id="ov-cards"></div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>实时吞吐（WAN 出口）</h3>' +
    '    <div class="chart-legend"><span><i class="sw" style="background:#4f8cff"></i>下行（内网→外网拉取）</span>' +
    '    <span><i class="sw" style="background:#38d39f"></i>上行（内网→外网上传）</span></div></div>' +
    '  <div class="panel-body"><div class="chart-box"><canvas id="ov-chart"></canvas></div></div>' +
    '</div>' +
    '<div class="grid cols2" style="margin-top:14px">' +
    '  <div class="panel"><div class="panel-head"><h3>设备流量 TOP 5</h3>' +
    '    <a class="hint" data-goto="devices" style="cursor:pointer">查看全部设备 →</a></div>' +
    '    <div class="panel-body no-pad"><div class="table-wrap"><table id="ov-top"></table></div></div></div>' +
    '  <div class="panel"><div class="panel-head"><h3>系统与 DHCP</h3></div>' +
    '    <div class="panel-body" id="ov-sysinfo"></div></div>' +
    '</div>';
  ovChart = new LineChart($("#ov-chart"), {
    series: [{ key: "wan_rx", label: "下行", color: "#4f8cff" },
             { key: "wan_tx", label: "上行", color: "#38d39f" }],
    unit: "bps"
  });
  viewBuilt.overview = true;
}

function wanStateChip(w) {
  var ok = w && w.ip && (w.state || "").indexOf("获取") < 0 && (w.state || "").indexOf("拨号中") < 0
    && (w.state || "").indexOf("失败") < 0;
  return '<span class="chip ' + (ok ? "ok" : "bad") + '" id="chip-wan"><i class="dot"></i>WAN · ' +
    esc((w && w.ip) || "未连接") + '<b>·</b> ' + esc((w && w.mode) || "") + '</span>';
}

function pollOverview() {
  api("/api/overview").then(function (d) {
    var w = d.wan, lan = d.lan, sys = d.system, dh = d.dhcp, sess = d.sessions;
    $("#chip-wan").outerHTML = wanStateChip(w);
    $("#chip-lan").outerHTML =
      '<span class="chip ok" id="chip-lan"><i class="dot"></i>LAN · ' + esc(lan.ip || "未配置") +
      '<b>·</b> ' + esc(lan.interface || "") + '</span>';
    $("#chip-online").innerHTML = "在线设备 · <b>" + d.online_count + "</b> / " + d.device_count;
    $("#chip-sessions").innerHTML = "出口会话 · <b>" + sess.total + "</b>";

    if (!viewBuilt.overview) buildOverview();
    var memPct = sys.mem_total ? Math.round(sys.mem_used * 100 / sys.mem_total) : 0;
    $("#ov-cards").innerHTML =
      '<div class="stat-card"><div class="label"><span class="ico">🌐</span>外网 WAN</div>' +
      '  <div class="value">' + esc(w.ip || "未连接") + '</div>' +
      '  <div class="sub">' + esc(w.state || "") + ' · 网关 ' + esc(w.gateway || "—") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🏠</span>内网 LAN</div>' +
      '  <div class="value">' + esc(lan.ip || "未配置") + '</div>' +
      '  <div class="sub">' + esc(lan.interface || "") + ' / ' + esc(lan.netmask || "") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🖥️</span>在线设备</div>' +
      '  <div class="value">' + d.online_count + '<small class="muted" style="font-size:15px"> / ' + d.device_count + '</small></div>' +
      '  <div class="sub">DHCP 活跃租约 ' + dh.active_leases + ' 个</div></div>' +
      '<div class="stat-card" style="border-color:rgba(79,140,255,.45)"><div class="label"><span class="ico">🔗</span>出口会话总数</div>' +
      '  <div class="value big">' + sess.total + '</div>' +
      '  <div class="sub">TCP ' + sess.tcp + ' · UDP ' + sess.udp + ' · ICMP ' + sess.icmp + '</div>' +
      '  <a class="hint" data-goto="sessions" style="cursor:pointer">查看会话监控 →</a></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">⚡</span>CPU 使用率</div>' +
      '  <div class="value">' + fmtPct(sys.cpu) + '</div>' +
      '  <div class="bar"><i style="width:' + Math.min(100, sys.cpu || 0) + '%"></i></div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🧠</span>内存使用</div>' +
      '  <div class="value">' + fmtBytes(sys.mem_used) + '<small class="muted" style="font-size:13px"> / ' + fmtBytes(sys.mem_total) + '</small></div>' +
      '  <div class="bar"><i style="width:' + memPct + '%"></i></div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">⏱️</span>运行时间</div>' +
      '  <div class="value" style="font-size:20px">' + fmtDur(sys.uptime) + '</div>' +
      '  <div class="sub">负载 ' + sys.load1 + ' / ' + sys.load5 + ' / ' + sys.load15 +
      (sys.temp != null ? ' · 温度 ' + sys.temp + '℃' : "") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">📡</span>DHCP 服务器</div>' +
      '  <div class="value" style="font-size:20px">' + (dh.enabled ? "已开启" : "已关闭") + '</div>' +
      '  <div class="sub">地址池 ' + esc(dh.range) + ' · ' + esc(dh.lease_time) + '</div>' +
      '  <div class="sub" style="color:' + (dh.send_gateway ? "var(--green)" : "var(--red)") + '">' +
      (dh.send_gateway ? "✓ 向客户端下发网关" : "✗ 不下发网关（客户端网关为空）") + '</div></div>';

    ovChart.setPoints(d.history || []);
    var top = d.top_devices || [];
    $("#ov-top").innerHTML =
      "<thead><tr><th>设备</th><th>IP 地址</th><th class=\"num\">下行</th><th class=\"num\">上行</th></tr></thead><tbody>" +
      (top.length ? top.map(function (t) {
        return "<tr><td><span class=\"kind-ico\">" + kindIcon(t.kind) + "</span>" + esc(t.name) + "</td>" +
          "<td class=\"mono\">" + esc(t.ip) + "</td>" +
          "<td class=\"num rate\"><span class=\"dn\">↓ " + fmtRate(t.rx_rate) + "</span></td>" +
          "<td class=\"num rate\"><span class=\"up\">↑ " + fmtRate(t.tx_rate) + "</span></td></tr>";
      }).join("") : "<tr><td colspan=\"4\" class=\"muted\" style=\"text-align:center;padding:18px\">暂无流量数据</td></tr>") +
      "</tbody>";

    var svc = {};
    $("#ov-sysinfo").innerHTML =
      '<div class="muted small" style="margin-bottom:10px">' +
      '版本 v' + esc(d.version) + ' · 启动于 ' + fmtDateTime(d.boot_time * 1000) + '</div>' +
      '<table><tbody>' +
      '<tr><td>DNS 上游</td><td class="mono muted">' + esc((dh.upstreams || []).join(", ") || "—") + '</td></tr>' +
      '<tr><td>WAN 接口</td><td class="mono">' + esc(w.interface || "—") + '</td></tr>' +
      '<tr><td>LAN 接口</td><td class="mono">' + esc(lan.interface || "—") + '</td></tr>' +
      '<tr><td>运行时长</td><td>' + fmtDur(sys.uptime) + '</td></tr>' +
      '</tbody></table>' +
      '<div style="margin-top:10px"><a class="btn ghost sm" data-goto="settings" style="cursor:pointer">⚙️ 打开网络设置</a>' +
      ' <a class="btn ghost sm" data-goto="traffic" style="cursor:pointer">📈 打开流量监控</a></div>';
  }).catch(function (e) {
    if (state.view !== "overview") return;
    $("#chip-sessions").innerHTML = "出口会话 · <b>连接失败</b>";
  });
}

/* ================================================================
 * 设备监控
 * ================================================================ */
function buildDevices() {
  var v = $("#view-devices");
  v.innerHTML =
    '<div class="toolbar">' +
    '  <div class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>' +
    '    <input id="dev-q" placeholder="搜索名称 / IP / MAC…"></div>' +
    '  <select id="dev-sort"><option value="ip">按 IP 地址排序（默认）</option><option value="mac">按 MAC 排序</option>' +
    '    <option value="name">按名称排序</option><option value="traffic">按流量排序</option>' +
    '    <option value="sessions">按会话数排序</option></select>' +
    '  <label class="inline"><input type="checkbox" id="dev-online-only"> 仅显示在线</label>' +
    '  <span class="spacer"></span>' +
    '  <span class="muted small" id="dev-count"></span>' +
    '  <button class="btn sm" id="dev-refresh">↻ 立即刷新</button>' +
    '</div>' +
    '<div class="panel"><div class="panel-body no-pad"><div class="table-wrap">' +
    '<table id="dev-table"><thead><tr>' +
    '<th>状态</th><th>设备名称</th><th>IP 地址</th><th>MAC 地址</th><th>厂商</th>' +
    '<th class="num">连接数</th><th class="num">下行速率</th><th class="num">上行速率</th>' +
    '<th class="num">累计下行</th><th class="num">累计上行</th><th>最后活跃</th><th>操作</th>' +
    '</tr></thead><tbody></tbody></table></div></div></div>';
  $("#dev-q").addEventListener("input", function () {
    state.devicesQ = this.value.trim().toLowerCase();
    pollDevices();
  });
  $("#dev-sort").value = state.devicesSort;
  $("#dev-sort").addEventListener("change", function () { state.devicesSort = this.value; pollDevices(); });
  $("#dev-online-only").addEventListener("change", function () { state.onlyOnline = this.checked; pollDevices(); });
  $("#dev-refresh").addEventListener("click", pollDevices);
  viewBuilt.devices = true;
}

function renderDeviceRows(devices) {
  if (!devices.length) {
    return '<tr><td colspan="12" class="muted" style="text-align:center;padding:22px">没有符合条件的设备</td></tr>';
  }
  return devices.map(function (d) {
    var online = d.online;
    var rate = online ?
      '<span class="dn">↓ ' + fmtRate(d.rx_rate) + '</span>' :
      '<span class="muted">—</span>';
    var rateUp = online ?
      '<span class="up">↑ ' + fmtRate(d.tx_rate) + '</span>' :
      '<span class="muted">—</span>';
    return '<tr class="' + (online ? "" : "offline") + '" data-mac="' + esc(d.mac) + '" data-ip="' + esc(d.ip) + '">' +
      '<td>' + (online ? '<span class="status-dot on"></span><span class="badge on">在线</span>'
                       : '<span class="status-dot off"></span><span class="badge off">离线</span>') +
      (d.name_src === "alias" ? ' <span class="badge" title="用户自定义名称">自定</span>' : "") + '</td>' +
      '<td class="name-cell" data-act="rename" title="点击修改名称"><span class="kind-ico">' + kindIcon(d.kind) +
      '</span><b>' + esc(d.name) + '</b><span class="edit-hint">✎</span>' +
      (d.hostname && d.hostname !== d.name ? '<span class="sub-text">主机名 ' + esc(d.hostname) + '</span>' : "") + '</td>' +
      '<td class="mono">' + esc(d.ip) + '</td>' +
      '<td class="mono">' + esc(d.mac) + '</td>' +
      '<td>' + esc(d.vendor || "—") + '</td>' +
      '<td class="num">' + d.sessions + '</td>' +
      '<td class="num rate">' + rate + '</td>' +
      '<td class="num rate">' + rateUp + '</td>' +
      '<td class="num">' + fmtBytes(d.rx_total) + '</td>' +
      '<td class="num">' + fmtBytes(d.tx_total) + '</td>' +
      '<td class="muted">' + fmtAgo(d.last_seen) + '</td>' +
      '<td><button class="btn xs ghost" data-act="rename">改名</button> ' +
      (online ? '<button class="btn xs" disabled>已在线</button>'
              : '<button class="btn xs" data-act="wake" title="发送网络唤醒数据包">唤醒</button>') + '</td>' +
      '</tr>';
  }).join("");
}

function pollDevices() {
  var q = encodeURIComponent(state.devicesQ || "");
  api("/api/devices?sort=" + encodeURIComponent(state.devicesSort) + (q ? "&q=" + q : ""))
    .then(function (d) {
      var list = d.devices;
      if (state.onlyOnline) list = list.filter(function (x) { return x.online; });
      $("#dev-count").textContent = "共 " + list.length + " 台（在线 " + d.online + " 台）";
      $("#dev-table tbody").innerHTML = renderDeviceRows(list);
    })
    .catch(function (e) { toast("加载设备列表失败：" + e.message, "err"); });
}

/* ================================================================
 * DHCP 租约
 * ================================================================ */
function buildLeases() {
  $("#view-leases").innerHTML =
    '<div class="toolbar">' +
    '  <div class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>' +
    '    <input id="lease-q" placeholder="搜索名称 / IP / MAC…"></div>' +
    '  <select id="lease-status">' +
    '    <option value="all">全部租约</option><option value="online">在线</option>' +
    '    <option value="offline">离线</option><option value="bound">已绑定</option>' +
    '    <option value="unbound">未绑定</option><option value="expiring">24 小时内到期</option>' +
    '  </select>' +
    '  <span class="spacer"></span>' +
    '  <span class="muted small" id="lease-count"></span>' +
    '  <button class="btn sm" id="lease-refresh">↻ 刷新</button>' +
    '</div>' +
    '<div class="panel"><div class="panel-head"><h3>DHCP 已分配地址</h3>' +
    '  <span class="hint" id="lease-auto"></span></div>' +
    '  <div class="panel-body no-pad"><div class="table-wrap">' +
    '    <table id="lease-table"><thead><tr><th>状态</th><th>设备名称</th><th>IP 地址</th>' +
    '    <th>MAC 地址</th><th>分配时间</th><th>到期时间</th><th>地址池</th><th>绑定</th><th>操作</th>' +
    '    </tr></thead><tbody></tbody></table></div></div></div>';
  $("#lease-q").addEventListener("input", function () { state.leaseQ = this.value.trim(); pollLeases(); });
  $("#lease-status").addEventListener("change", function () { state.leaseStatus = this.value; pollLeases(); });
  $("#lease-refresh").addEventListener("click", pollLeases);
}

function pollLeases() {
  var q = encodeURIComponent(state.leaseQ || "");
  var st = state.leaseStatus || "all";
  api("/api/leases?status=" + encodeURIComponent(st) + (q ? "&q=" + q : "")).then(function (d) {
    $("#lease-count").textContent = "共 " + d.total + " 条 · 已绑定 " + d.bound + " · 在线 " + d.online;
    $("#lease-auto").innerHTML = d.auto_bind
      ? '<span class="badge on">首次分配自动固定：已开启</span>'
      : '<span class="badge">首次分配自动固定：未开启</span>';
    var rows = (d.leases || []).map(function (l) {
      var rem = l.lease_seconds === 0 ? "永久"
        : (l.expiry ? fmtDur(l.expiry - Date.now() / 1000) : "—");
      return '<tr>' +
        '<td>' + (l.online ? '<span class="status-dot on"></span>在线' : '<span class="status-dot off"></span>离线') + '</td>' +
        '<td><span class="kind-ico">' + kindIcon(l.kind) + '</span><b>' + esc(l.name) + '</b>' +
        (l.auto ? ' <span class="badge">自动固定</span>' : "") + '</td>' +
        '<td class="mono">' + esc(l.ip) + '</td>' +
        '<td class="mono">' + esc(l.mac) + '</td>' +
        '<td class="muted">' + (l.allocated ? fmtDateTime(l.allocated * 1000) : "—") + '</td>' +
        '<td class="muted">' + (l.lease_seconds === 0 ? "永久" : (l.expiry ? fmtDateTime(l.expiry * 1000) : "—")) +
        '<span class="sub-text">剩余 ' + rem + '</span></td>' +
        '<td class="muted">' + esc(l.pool_name || "默认池") + '</td>' +
        '<td>' + (l.bound ? '<span class="badge on">已绑定</span>' : '<span class="badge">未绑定</span>') + '</td>' +
        '<td>' + (l.bound
          ? '<button class="btn xs danger" data-lease-act="unbind" data-mac="' + esc(l.mac) + '">解绑</button>'
          : '<button class="btn xs" data-lease-act="bind" data-mac="' + esc(l.mac) + '" data-ip="' + esc(l.ip) + '" data-name="' + esc(l.name) + '">绑定</button>') +
        '</td></tr>';
    }).join("");
    $("#lease-table").innerHTML =
      '<thead><tr><th>状态</th><th>设备名称</th><th>IP 地址</th><th>MAC 地址</th>' +
      '<th>分配时间</th><th>到期时间</th><th>地址池</th><th>绑定</th><th>操作</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="9" class="muted" style="text-align:center;padding:22px">没有符合条件的租约</td></tr>') +
      '</tbody>';
  }).catch(function (e) { toast("加载 DHCP 租约失败：" + e.message, "err"); });
}

document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-lease-act]");
  if (!btn) return;
  var act = btn.dataset.leaseAct;
  var body = act === "bind"
    ? { mac: btn.dataset.mac, ip: btn.dataset.ip, name: btn.dataset.name }
    : { mac: btn.dataset.mac };
  var url = act === "bind" ? "/api/leases/bind" : "/api/leases/unbind";
  api(url, { body: body }).then(function (r) {
    toast(r.message, "ok");
    pollLeases();
    if (state.view === "devices") pollDevices();
  }).catch(function (er) { toast(er.message, "err"); });
});


function buildTraffic() {
  var v = $("#view-traffic");
  v.innerHTML =
    '<div class="grid cards" id="tf-cards"></div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>实时吞吐曲线</h3>' +
    '    <div class="chart-legend"><span><i class="sw" style="background:#4f8cff"></i>下行</span>' +
    '    <span><i class="sw" style="background:#38d39f"></i>上行</span></div></div>' +
    '  <div class="panel-body"><div class="chart-box"><canvas id="tf-chart"></canvas></div></div>' +
    '</div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>网卡流量</h3><span class="hint">来自 /proc/net/dev 网卡计数器</span></div>' +
    '  <div class="panel-body no-pad"><div class="table-wrap"><table id="tf-iface"></table></div></div>' +
    '</div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>设备流量（按 IP 顺序排列）</h3>' +
    '    <span class="hint">基于 nftables 每设备计数器</span></div>' +
    '  <div class="panel-body no-pad"><div class="table-wrap"><table id="tf-devices"></table></div></div>' +
    '</div>';
  tfChart = new LineChart($("#tf-chart"), {
    series: [{ key: "wan_rx", label: "下行", color: "#4f8cff" },
             { key: "wan_tx", label: "上行", color: "#38d39f" }],
    unit: "bps"
  });
  viewBuilt.traffic = true;
}

function pollTraffic() {
  api("/api/traffic").then(function (d) {
    var wan = d.wan || {};
    var ifaces = d.interfaces || [];
    var rx = 0, tx = 0;
    ifaces.forEach(function (i) { if (i.name !== "lo") { rx += i.rx_rate; tx += i.tx_rate; } });
    $("#tf-cards").innerHTML =
      '<div class="stat-card"><div class="label"><span class="ico">⬇️</span>总下行速率</div>' +
      '  <div class="value big" style="color:var(--accent)">' + fmtRate(rx) + '</div>' +
      '  <div class="sub">WAN ' + esc(wan.interface || "—") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">⬆️</span>总上行速率</div>' +
      '  <div class="value big" style="color:var(--green)">' + fmtRate(tx) + '</div>' +
      '  <div class="sub">全部网卡合计（不含 lo）</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">📥</span>内网设备累计下行</div>' +
      '  <div class="value">' + fmtBytes(d.totals.rx) + '</div>' +
      '  <div class="sub">自本服务记录以来</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">📤</span>内网设备累计上行</div>' +
      '  <div class="value">' + fmtBytes(d.totals.tx) + '</div>' +
      '  <div class="sub">自本服务记录以来</div></div>';
    tfChart.setPoints(d.history || []);
    $("#tf-iface").innerHTML =
      "<thead><tr><th>网卡</th><th class=\"num\">下行速率</th><th class=\"num\">上行速率</th>" +
      "<th class=\"num\">累计下行</th><th class=\"num\">累计上行</th></tr></thead><tbody>" +
      ifaces.map(function (i) {
        return "<tr><td class=\"mono\"><b>" + esc(i.name) + "</b>" +
          (i.name === (wan.interface || "") ? ' <span class="badge">出口</span>' : "") + "</td>" +
          "<td class=\"num rate\"><span class=\"dn\">↓ " + fmtRate(i.rx_rate) + "</span></td>" +
          "<td class=\"num rate\"><span class=\"up\">↑ " + fmtRate(i.tx_rate) + "</span></td>" +
          "<td class=\"num\">" + fmtBytes(i.rx_total) + "</td>" +
          "<td class=\"num\">" + fmtBytes(i.tx_total) + "</td></tr>";
      }).join("") + "</tbody>";
    var devs = d.devices || [];
    $("#tf-devices").innerHTML =
      "<thead><tr><th>设备名称</th><th>IP 地址</th><th>MAC 地址</th><th class=\"num\">下行速率</th>" +
      "<th class=\"num\">上行速率</th><th class=\"num\">累计下行</th><th class=\"num\">累计上行</th>" +
      "<th class=\"num\">连接数</th></tr></thead><tbody>" +
      (devs.length ? devs.map(function (x) {
        return '<tr class="' + (x.online ? "" : "offline") + '"><td><span class="kind-ico">' +
          kindIcon(x.kind) + '</span>' + esc(x.name) + '</td>' +
          '<td class="mono">' + esc(x.ip) + '</td><td class="mono">' + esc(x.mac) + '</td>' +
          '<td class="num rate"><span class="dn">↓ ' + fmtRate(x.rx_rate) + '</span></td>' +
          '<td class="num rate"><span class="up">↑ ' + fmtRate(x.tx_rate) + '</span></td>' +
          '<td class="num">' + fmtBytes(x.rx_total) + '</td>' +
          '<td class="num">' + fmtBytes(x.tx_total) + '</td>' +
          '<td class="num">' + x.sessions + '</td></tr>';
      }).join("") : '<tr><td colspan="8" class="muted" style="text-align:center;padding:22px">暂无设备流量数据</td></tr>') +
      "</tbody>";
  }).catch(function (e) { toast("加载流量数据失败：" + e.message, "err"); });
}

/* ================================================================
 * 会话监控
 * ================================================================ */
function buildSessions() {
  var v = $("#view-sessions");
  v.innerHTML =
    '<div class="grid cards" id="ss-cards"></div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>出口会话总数走势</h3>' +
    '    <span class="hint">来自本机内核连接跟踪（conntrack），含经本机转发的会话与本机自身连接，并非上游光猫/运营商设备的会话表</span></div>' +
    '  <div class="panel-body"><div class="chart-box"><canvas id="ss-chart"></canvas></div></div>' +
    '</div>' +
    '<div class="grid cols2" style="margin-top:14px">' +
    '  <div class="panel"><div class="panel-head"><h3>设备会话排行</h3><span class="hint">按会话数从多到少</span></div>' +
    '    <div class="panel-body no-pad"><div class="table-wrap"><table id="ss-devices"></table></div></div></div>' +
    '  <div class="panel"><div class="panel-head"><h3>远程目标 TOP 15</h3><span class="hint">内网设备正在访问的外网地址</span></div>' +
    '    <div class="panel-body no-pad"><div class="table-wrap"><table id="ss-remote"></table></div></div></div>' +
    '</div>';
  ssChart = new LineChart($("#ss-chart"), {
    series: [{ key: "total", label: "会话总数", color: "#9d7bff" }],
    unit: "count"
  });
  viewBuilt.sessions = true;
}

function pollSessions() {
  api("/api/sessions").then(function (d) {
    var total = d.total || 0;
    var tcpP = total ? d.tcp * 100 / total : 0;
    var udpP = total ? d.udp * 100 / total : 0;
    var icmpP = total ? d.icmp * 100 / total : 0;
    var otherP = total ? d.other * 100 / total : 0;
    $("#ss-cards").innerHTML =
      '<div class="stat-card" style="border-color:rgba(157,123,255,.5)"><div class="label"><span class="ico">🔗</span>出口会话总数</div>' +
      '  <div class="value big">' + total + '</div>' +
      '  <div class="sub">内核连接跟踪表当前条目；其中内网设备会话 ' + (d.lan_total || 0) + '，其余为本机自身连接</div>' +
      '  <div class="proto-bars"><i style="width:' + tcpP + '%;background:#4f8cff"></i>' +
      '  <i style="width:' + udpP + '%;background:#38d39f"></i>' +
      '  <i style="width:' + icmpP + '%;background:#ffd166"></i>' +
      '  <i style="width:' + otherP + '%;background:#5f6d80"></i></div>' +
      '  <div class="proto-legend"><span><i class="sw" style="background:#4f8cff"></i>TCP <b>' + d.tcp + '</b></span>' +
      '  <span><i class="sw" style="background:#38d39f"></i>UDP <b>' + d.udp + '</b></span>' +
      '  <span><i class="sw" style="background:#ffd166"></i>ICMP <b>' + d.icmp + '</b></span>' +
      '  <span><i class="sw" style="background:#5f6d80"></i>其他 <b>' + d.other + '</b></span></div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🖥️</span>有会话的设备</div>' +
      '  <div class="value">' + (d.devices || []).length + '</div>' +
      '  <div class="sub">存在活跃连接的内网设备数</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🌍</span>远程目标</div>' +
      '  <div class="value">' + (d.remote_top || []).length + '</div>' +
      '  <div class="sub">TOP 列表按连接数统计</div></div>';
    ssChart.setPoints(d.history || []);
    var devs = d.devices || [];
    $("#ss-devices").innerHTML =
      "<thead><tr><th>设备</th><th>IP 地址</th><th class=\"num\">会话数</th><th class=\"num\">下行</th><th class=\"num\">上行</th></tr></thead><tbody>" +
      (devs.length ? devs.slice(0, 40).map(function (x) {
        var pct = Math.min(100, Math.round(x.sessions * 100 / Math.max(1, devs[0].sessions)));
        return '<tr><td><span class="kind-ico">' + kindIcon(x.kind) + '</span>' + esc(x.name) + '</td>' +
          '<td class="mono">' + esc(x.ip) + '</td>' +
          '<td class="num"><b>' + x.sessions + '</b><div class="bar" style="margin-top:4px"><i style="width:' + pct + '%"></i></div></td>' +
          '<td class="num rate"><span class="dn">↓ ' + fmtRate(x.rx_rate) + '</span></td>' +
          '<td class="num rate"><span class="up">↑ ' + fmtRate(x.tx_rate) + '</span></td></tr>';
      }).join("") : '<tr><td colspan="5" class="muted" style="text-align:center;padding:22px">暂无会话数据</td></tr>') + "</tbody>";
    var rem = d.remote_top || [];
    $("#ss-remote").innerHTML =
      "<thead><tr><th>外网地址</th><th class=\"num\">会话数</th></tr></thead><tbody>" +
      (rem.length ? rem.map(function (r) {
        return '<tr><td class="mono">' + esc(r.ip) + '</td><td class="num">' + r.count + '</td></tr>';
      }).join("") : '<tr><td colspan="2" class="muted" style="text-align:center;padding:22px">暂无数据</td></tr>') +
      "</tbody>";
  }).catch(function (e) { toast("加载会话数据失败：" + e.message, "err"); });
}

/* ================================================================
 * 应用监控（基于 DNS 域名识别）
 * ================================================================ */
function buildApps() {
  $("#view-apps").innerHTML =
    '<div class="toolbar">' +
    '  <div><h3 style="font-size:16px">应用监控</h3>' +
    '  <div class="muted small">根据内网 DNS 请求识别应用（最近 15 分钟），类似任务管理器按应用汇总</div></div>' +
    '  <span class="spacer"></span>' +
    '  <span class="muted small">识别依据：DNS 域名特征；加密/直连 IP 的流量可能归入“其他”</span>' +
    '</div>' +
    '<div class="grid cards" id="app-cards"></div>' +
    '<div class="panel" style="margin-top:14px"><div class="panel-head"><h3>应用列表</h3>' +
    '  <span class="hint">按 DNS 请求数排序；设备列显示最近使用该应用的终端</span></div>' +
    '  <div class="panel-body no-pad"><div class="table-wrap">' +
    '    <table id="app-table"><thead><tr><th>应用</th><th>分类</th><th class="num">设备数</th>' +
    '    <th class="num">DNS 请求</th><th>最近活跃</th><th>代表域名</th><th>使用设备</th></tr></thead>' +
    '    <tbody></tbody></table></div></div></div>';
}

function pollApps() {
  api("/api/apps").then(function (d) {
    $("#app-cards").innerHTML =
      '<div class="stat-card"><div class="label"><span class="ico">🧩</span>识别到的应用</div>' +
      '  <div class="value">' + d.total_apps + '</div><div class="sub">最近 15 分钟有 DNS 活动</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🖥️</span>活跃设备</div>' +
      '  <div class="value">' + d.active_devices + '</div><div class="sub">产生过 DNS 请求的设备</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🔎</span>DNS 请求总数</div>' +
      '  <div class="value">' + d.total_queries + '</div><div class="sub">最近 15 分钟</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">📚</span>覆盖分类</div>' +
      '  <div class="value">' + new Set((d.apps || []).map(function (a) { return a.category; })).size + '</div>' +
      '  <div class="sub">社交 / 视频 / 游戏 / 办公等</div></div>';
    var apps = d.apps || [];
    state.appsData = apps;
    var maxQ = apps.length ? apps[0].queries : 1;
    $("#app-table tbody").innerHTML = apps.length ? apps.map(function (a, ai) {
      var pct = Math.min(100, Math.round(a.queries * 100 / Math.max(1, maxQ)));
      var devs = (a.devices || []).slice(0, 4).map(function (x) {
        return '<span class="badge" title="' + esc(x.ip) + " " + esc(x.mac || "") + '">' + esc(x.name) + '</span>';
      }).join(" ");
      if ((a.devices || []).length > 4) devs += ' <span class="muted small">+' + (a.devices.length - 4) + '</span>';
      return '<tr data-app-idx="' + ai + '" style="cursor:pointer" title="点击查看设备明细">' +
        '<td><span style="font-size:16px">' + esc(a.icon || "🌐") + '</span> <b>' +
        esc(a.name) + '</b><div class="bar" style="margin-top:4px"><i style="width:' + pct + '%"></i></div></td>' +
        '<td><span class="badge">' + esc(a.category) + '</span></td>' +
        '<td class="num">' + a.clients + '</td>' +
        '<td class="num">' + a.queries + '</td>' +
        '<td class="muted">' + fmtAgo(a.last_seen) + '</td>' +
        '<td class="mono small muted">' + esc((a.domains || []).join("、")) + '</td>' +
        '<td>' + devs + '</td></tr>';
    }).join("") : '<tr><td colspan="7" class="muted" style="text-align:center;padding:22px">暂无应用识别数据，等待 DNS 请求…</td></tr>';
  }).catch(function (e) { toast("加载应用监控失败：" + e.message, "err"); });
}

function openAppDetail(app) {
  var rows = (app.devices || []).map(function (d) {
    return '<tr><td>' + (d.online
      ? '<span class="status-dot on"></span><span class="badge on">在线</span>'
      : '<span class="status-dot off"></span><span class="badge off">离线</span>') + '</td>' +
      '<td><span class="kind-ico">' + kindIcon(d.kind) + '</span><b>' + esc(d.name) + '</b></td>' +
      '<td class="mono">' + esc(d.ip) + '</td>' +
      '<td class="mono">' + esc(d.mac || "—") + '</td>' +
      '<td>' + esc(d.vendor || "—") + '</td>' +
      '<td class="num">' + d.queries + '</td>' +
      '<td class="muted">' + fmtAgo(d.last_seen) + '</td></tr>';
  }).join("");
  openModal("应用详情 · " + app.name,
    '<div class="muted small" style="margin-bottom:10px">' +
    esc(app.category) + ' · 共 ' + app.clients + ' 台设备 · ' + app.queries +
    ' 次 DNS 请求<br>识别域名：<span class="mono">' + esc((app.domains || []).join("、")) + '</span></div>' +
    '<div class="table-wrap"><table><thead><tr><th>状态</th><th>设备名称</th><th>IP 地址</th>' +
    '<th>MAC 地址</th><th>厂商</th><th class="num">请求数</th><th>最近活跃</th></tr></thead><tbody>' +
    (rows || '<tr><td colspan="7" class="muted" style="text-align:center;padding:18px">暂无设备明细</td></tr>') +
    '</tbody></table></div>',
    '<button class="btn primary" id="app-detail-close">关闭</button>', true);
  var btn = document.getElementById("app-detail-close");
  if (btn) btn.addEventListener("click", closeModal);
}

document.addEventListener("click", function (e) {
  var tr = e.target.closest("[data-app-idx]");
  if (!tr) return;
  var app = (state.appsData || [])[Number(tr.dataset.appIdx)];
  if (app) openAppDetail(app);
});


function buildGateways() {
  var v = $("#view-gateways");
  v.innerHTML =
    '<div class="toolbar">' +
    '  <div><h3 style="font-size:16px">出口网关监控</h3>' +
    '    <div class="muted small">逐台采集上游路由器/光猫的会话数与在线主机数；软路由仅做 DHCP 时请以这里为准</div></div>' +
    '  <span class="spacer"></span>' +
    '  <button class="btn sm" id="gw-probe">↻ 立即探测</button>' +
    '  <button class="btn primary sm" id="gw-add">＋ 添加上游网关</button>' +
    '</div>' +
    '<div class="grid gw-grid" id="gw-cards"></div>' +
    '<div class="panel" style="margin-top:14px"><div class="panel-head"><h3>采集方式说明</h3></div>' +
    '  <div class="panel-body muted small" style="line-height:1.9">' +
    '    <p>• <b>SSH</b>：适合 OpenWrt / 可登录路由器，读取 conntrack 与 DHCP 租约，数据最准确。</p>' +
    '    <p>• <b>SNMP</b>：设备开启 SNMP 后，填写会话数 / 在线主机数对应的 OID（不同厂商不同）。</p>' +
    '    <p>• <b>HTTP</b>：设备提供 JSON 接口时按字段路径取值；普通光猫页面通常需要登录，通用性差。</p>' +
    '    <p>• 添加时可点“自动检测”，扫描端口并识别 OpenWrt / SSH / SNMP，给出推荐方式。</p>' +
    '  </div>' +
    '</div>';
  $("#gw-probe").addEventListener("click", function () {
    api("/api/gateways/probe", { body: {} }).then(function (r) {
      toast(r.message, "ok");
      setTimeout(pollGateways, 900);
    }).catch(function (e) { toast(e.message, "err"); });
  });
  $("#gw-add").addEventListener("click", function () { gatewayModal(null); });
}

function gwMethodLabel(m) {
  return (state.gatewayMethods && state.gatewayMethods[m]) || m || "自动";
}

function renderGatewayCards(d) {
  var list = d.gateways || [];
  var box = $("#gw-cards");
  if (!list.length) {
    box.innerHTML = '<div class="gw-empty">还没有添加上游网关。<br>' +
      '<button class="btn primary sm" id="gw-empty-add" style="margin-top:12px">＋ 添加第一台上游网关</button></div>';
    var b = $("#gw-empty-add");
    if (b) b.addEventListener("click", function () { gatewayModal(null); });
    return;
  }
  box.innerHTML = list.map(function (g) {
    var r = g.result || {};
    var ok = r.ok;
    var sessions = (r.sessions === null || r.sessions === undefined) ? "—" : r.sessions;
    var hosts = (r.hosts === null || r.hosts === undefined) ? "—" : r.hosts;
    var ts = r.ts ? fmtAgo(r.ts) : "尚未采集";
    var err = r.error || "";
    return '<div class="gw-card">' +
      '<div class="gw-head"><span class="status-dot ' + (ok ? "on" : "off") + '"></span><b>' + esc(g.name) + '</b>' +
      '<span class="badge">' + esc(gwMethodLabel(g.method)) + '</span></div>' +
      '<div class="gw-ip mono">' + esc(g.ip) + '</div>' +
      '<div class="gw-metrics">' +
      '  <div><span>会话数</span><b class="' + (sessions === "—" ? "na" : "") + '">' + sessions + '</b></div>' +
      '  <div><span>在线主机</span><b class="' + (hosts === "—" ? "na" : "") + '">' + hosts + '</b></div>' +
      '</div>' +
      '<div class="gw-foot">' + (ok ? "✓ 采集成功 · " : "✗ 采集失败 · ") + esc(ts) +
      (r.elapsed_ms ? " · " + r.elapsed_ms + " ms" : "") +
      (err ? '<br><span class="err" title="' + esc(err) + '">' + esc(err.slice(0, 140)) + '</span>' : "") +
      '</div>' +
      '<div class="gw-actions">' +
      '  <button class="btn xs" data-gw-act="probe" data-id="' + esc(g.id) + '">探测</button>' +
      '  <button class="btn xs" data-gw-act="edit" data-id="' + esc(g.id) + '">编辑</button>' +
      '  <button class="btn xs danger" data-gw-act="del" data-id="' + esc(g.id) + '">删除</button>' +
      '</div></div>';
  }).join("");
}

function pollGateways() {
  api("/api/gateways").then(function (d) {
    state.gateways = d.gateways || [];
    state.gatewayMethods = d.methods || {};
    renderGatewayCards(d);
  }).catch(function () { /* 静默 */ });
}

function cleanGw(g) {
  var keys = ["id", "name", "ip", "method", "snmp_community", "sessions_oid", "hosts_oid",
    "username", "password", "sessions_cmd", "hosts_cmd",
    "http_url", "http_user", "http_password", "sessions_json", "hosts_json"];
  var out = {};
  keys.forEach(function (k) {
    if (g[k] !== undefined && g[k] !== null && g[k] !== "") out[k] = g[k];
  });
  return out;
}

function saveGateways(list) {
  return api("/api/gateways/save", { body: { gateways: list } });
}

function gwDetectHtml(det) {
  var ports = det.ports || {};
  var open = Object.keys(ports).filter(function (p) { return ports[p]; });
  var rows = '<div class="kv"><span>开放端口</span><span class="mono">' +
    (open.length ? open.join(", ") : "未发现常见管理端口") + "</span></div>";
  if (det.http && det.http.status) {
    rows += '<div class="kv"><span>Web 管理</span><span>' +
      esc((det.http.title || "无标题") + (det.http.server ? " · " + det.http.server : "")) + "</span></div>";
  }
  if (det.ssh_banner) {
    rows += '<div class="kv"><span>SSH</span><span class="mono">' + esc(det.ssh_banner) + "</span></div>";
  }
  if (det.snmp && det.snmp.ok) {
    rows += '<div class="kv"><span>SNMP</span><span class="mono">' + esc(det.snmp.sysdescr) + "</span></div>";
  }
  rows += '<div class="kv"><span>建议</span><span>' + esc(det.suggest_text) + "</span></div>";
  return '<div class="detect-box">' + rows + "</div>";
}

function gatewayModal(existing) {
  var gw = existing ? JSON.parse(JSON.stringify(existing)) : { method: "auto", snmp_community: "public" };
  var isDemo = state.status && state.status.backend === "demo";
  var opts = [
    ["auto", "自动探测（暂不采集）"],
    ["snmp", "SNMP v2c"],
    ["ssh", "SSH 命令"],
    ["http", "HTTP JSON 接口"]
  ];
  if (isDemo) opts.push(["demo", "演示（模拟数据）"]);
  var methodOpts = opts.map(function (o) {
    return '<option value="' + o[0] + '"' + (gw.method === o[0] ? " selected" : "") + '>' + esc(o[1]) + "</option>";
  }).join("");

  var sshSessions = gw.sessions_cmd || "cat /proc/net/nf_conntrack 2>/dev/null | wc -l";
  var sshHosts = gw.hosts_cmd ||
    "cat /proc/net/nf_conntrack 2>/dev/null | grep -o 'src=[0-9.]*' | cut -d= -f2 | sort -u | wc -l";
  var body =
    '<div class="grid cols2" style="gap:10px">' +
    '  <label class="field"><span>网关名称</span><input id="gwf-name" value="' + esc(gw.name || "") + '" placeholder="如：电信宽带"></label>' +
    '  <label class="field"><span>网关 IP</span><input id="gwf-ip" class="mono" value="' + esc(gw.ip || "") + '" placeholder="192.168.10.1"></label>' +
    '</div>' +
    '<div class="grid cols2" style="gap:10px">' +
    '  <label class="field"><span>采集方式</span><select id="gwf-method">' + methodOpts + '</select></label>' +
    '  <div class="field"><span>自动检测</span><button class="btn sm" id="gwf-detect" type="button">扫描该网关</button></div>' +
    '</div>' +
    '<div id="gwf-detect-box"></div>' +
    '<div id="gwf-snmp" class="gw-form-section hidden">' +
    '  <h4>SNMP v2c 参数</h4>' +
    '  <div class="field"><span>团体名（community）</span><input id="gwf-community" class="mono" value="' + esc(gw.snmp_community || "public") + '"></div>' +
    '  <div class="field"><span>会话数 OID</span><input id="gwf-sessions-oid" class="mono" value="' + esc(gw.sessions_oid || "") + '" placeholder="如 1.3.6.1.4.1.xxxx.1.0"></div>' +
    '  <div class="field"><span>在线主机数 OID</span><input id="gwf-hosts-oid" class="mono" value="' + esc(gw.hosts_oid || "") + '" placeholder="可选"></div>' +
    '  <div class="gw-hint">不同厂商 OID 不同；两项至少填一项。</div>' +
    '</div>' +
    '<div id="gwf-ssh" class="gw-form-section hidden">' +
    '  <h4>SSH 命令采集</h4>' +
    '  <div class="grid cols2" style="gap:10px">' +
    '    <label class="field"><span>用户名</span><input id="gwf-user" value="' + esc(gw.username || "root") + '"></label>' +
    '    <label class="field"><span>密码</span><input id="gwf-pass" type="password" placeholder="' + (gw.has_password ? "已保存，留空保持不变" : "留空则使用密钥登录") + '"></label>' +
    '  </div>' +
    '  <div class="field"><span>会话数命令</span><input id="gwf-sessions-cmd" class="mono" value="' + esc(sshSessions) + '"></div>' +
    '  <div class="field"><span>在线主机命令</span><input id="gwf-hosts-cmd" class="mono" value="' + esc(sshHosts) + '"></div>' +
    '  <div class="gw-hint">默认：会话数取 conntrack 条目；在线主机按 conntrack 去重源 IP 统计（最能反映“正在使用该网关的设备”）。<br>' +
    '  也可改为 ARP 表（ip neigh show | grep -c lladdr）或 DHCP 租约（cat /tmp/dhcp.leases | wc -l）。<br>' +
    '  密码登录需安装 sshpass（apt install sshpass），或配置免密密钥。</div>' +
    '</div>' +
    '<div id="gwf-http" class="gw-form-section hidden">' +
    '  <h4>HTTP JSON 接口</h4>' +
    '  <div class="field"><span>接口地址</span><input id="gwf-http-url" class="mono" value="' + esc(gw.http_url || "") + '" placeholder="http://192.168.10.1/api/status"></div>' +
    '  <div class="grid cols2" style="gap:10px">' +
    '    <label class="field"><span>用户名（可选）</span><input id="gwf-http-user" value="' + esc(gw.http_user || "") + '"></label>' +
    '    <label class="field"><span>密码（可选）</span><input id="gwf-http-pass" type="password" placeholder="' + (gw.has_http_password ? "已保存，留空保持不变" : "") + '"></label>' +
    '  </div>' +
    '  <div class="grid cols2" style="gap:10px">' +
    '    <label class="field"><span>会话数字段路径</span><input id="gwf-sessions-json" class="mono" value="' + esc(gw.sessions_json || "") + '" placeholder="data.sessions"></label>' +
    '    <label class="field"><span>在线主机字段路径</span><input id="gwf-hosts-json" class="mono" value="' + esc(gw.hosts_json || "") + '" placeholder="data.hosts"></label>' +
    '  </div>' +
    '  <div class="gw-hint">字段路径用点号分隔；留空则取响应中的第一个数字。</div>' +
    '</div>' +
    '<div id="gwf-error" class="form-error hidden" style="margin-top:12px"></div>';

  var mask = openModal(existing ? "编辑上游网关" : "添加上游网关", body,
    '<button class="btn ghost" id="gwf-cancel">取消</button>' +
    '<button class="btn primary" id="gwf-save">保存</button>', true);

  function val(id) { var el = $("#" + id, mask); return el ? el.value.trim() : ""; }
  function cerr(msg) {
    var el = $("#gwf-error", mask);
    el.textContent = msg;
    el.classList.remove("hidden");
  }
  function syncSections() {
    var m = $("#gwf-method", mask).value;
    $("#gwf-snmp", mask).classList.toggle("hidden", m !== "snmp");
    $("#gwf-ssh", mask).classList.toggle("hidden", m !== "ssh");
    $("#gwf-http", mask).classList.toggle("hidden", m !== "http");
  }
  $("#gwf-method", mask).addEventListener("change", syncSections);
  syncSections();

  $("#gwf-detect", mask).addEventListener("click", function () {
    var ip = val("gwf-ip");
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) { cerr("请先填写正确的网关 IP 地址"); return; }
    var box = $("#gwf-detect-box", mask);
    box.innerHTML = '<div class="detect-box">正在扫描端口 / HTTP / SSH / SNMP，请稍候…</div>';
    api("/api/gateways/detect", { body: { ip: ip } }).then(function (r) {
      var det = r.detect;
      box.innerHTML = gwDetectHtml(det) +
        '<div style="margin-top:8px"><button class="btn xs" id="gwf-adopt" type="button">采用建议方式</button></div>';
      var adopt = $("#gwf-adopt", mask);
      adopt.addEventListener("click", function () {
        var m = det.suggest && det.suggest !== "unknown" ? det.suggest : "auto";
        $("#gwf-method", mask).value = m;
        syncSections();
        toast("已选择：" + gwMethodLabel(m), "ok");
      });
    }).catch(function (e) {
      box.innerHTML = '<div class="detect-box"><span class="bad">检测失败：' + esc(e.message) + "</span></div>";
    });
  });

  $("#gwf-cancel", mask).addEventListener("click", closeModal);
  $("#gwf-save", mask).addEventListener("click", async function () {
    var g = {
      name: val("gwf-name"), ip: val("gwf-ip"), method: $("#gwf-method", mask).value,
      snmp_community: val("gwf-community"),
      sessions_oid: val("gwf-sessions-oid"), hosts_oid: val("gwf-hosts-oid"),
      username: val("gwf-user"), password: val("gwf-pass"),
      sessions_cmd: val("gwf-sessions-cmd"), hosts_cmd: val("gwf-hosts-cmd"),
      http_url: val("gwf-http-url"), http_user: val("gwf-http-user"),
      http_password: val("gwf-http-pass"),
      sessions_json: val("gwf-sessions-json"), hosts_json: val("gwf-hosts-json")
    };
    if (gw.id) g.id = gw.id;
    if (!g.name) return cerr("请填写网关名称");
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(g.ip)) return cerr("请填写正确的 IPv4 地址");
    if (g.method === "snmp" && !g.sessions_oid && !g.hosts_oid) return cerr("SNMP 方式至少填写一个 OID");
    if (g.method === "ssh" && !g.sessions_cmd && !g.hosts_cmd) return cerr("SSH 方式至少填写一条命令");
    if (g.method === "http" && !/^https?:\/\//.test(g.http_url)) return cerr("HTTP 方式请填写 http(s) 地址");

    var list = (state.gateways || []).map(cleanGw);
    if (g.id) {
      var idx = -1;
      for (var i = 0; i < list.length; i++) if (list[i].id === g.id) { idx = i; break; }
      if (idx >= 0) list[idx] = g; else list.push(g);
    } else {
      list.push(g);
    }
    try {
      var r = await saveGateways(list);
      toast(r.message || "已保存", "ok");
      closeModal();
      setTimeout(pollGateways, 700);
    } catch (e) {
      cerr(e.message);
    }
  });
}

document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-gw-act]");
  if (!btn) return;
  var act = btn.dataset.gwAct, gid = btn.dataset.id;
  var gw = (state.gateways || []).filter(function (x) { return x.id === gid; })[0];
  if (!gw) return;
  if (act === "probe") {
    api("/api/gateways/probe", { body: { id: gid } }).then(function (r) {
      toast(r.message, "ok");
      setTimeout(pollGateways, 1000);
    }).catch(function (er) { toast(er.message, "err"); });
  } else if (act === "edit") {
    gatewayModal(gw);
  } else if (act === "del") {
    confirmModal("删除网关", "确定删除「" + esc(gw.name) + "」的监控配置吗？<br>只会删除本系统的配置，不会影响该路由器。", "确认删除", true)
      .then(function (yes) {
        if (!yes) return;
        var list = (state.gateways || []).filter(function (x) { return x.id !== gid; }).map(cleanGw);
        saveGateways(list).then(function () {
          toast("已删除", "ok");
          pollGateways();
        }).catch(function (er) { toast(er.message, "err"); });
      });
  }
});

/* ================================================================
 * 网络设置
 * ================================================================ */
function buildSettings() {
  var v = $("#view-settings");
  v.innerHTML = '<div class="muted" style="margin-bottom:12px">正在加载配置…</div>';
  Promise.all([api("/api/settings"), api("/api/interfaces")]).then(function (rs) {
    var data = rs[0];
    state.cfg = data.config;
    state.interfaces = rs[1].interfaces || [];
    state.services = data.services;
    renderSettingsForm(v, data);
  }).catch(function (e) {
    v.innerHTML = '<div class="form-error">加载设置失败：' + esc(e.message) + '</div>';
  });
}

function ifaceOptions(selected) {
  return state.interfaces.map(function (i) {
    var label = i.name + (i.mac ? "（" + i.mac + "）" : "");
    return '<option value="' + esc(i.name) + '"' + (i.name === selected ? " selected" : "") + '>' +
      esc(label) + '</option>';
  }).join("");
}

function renderSettingsForm(v, data) {
  var c = data.config, wan = c.network.wan, lan = c.network.lan,
    dh = c.dhcp, dns = c.dns;
  var wanStatic = wan.mode === "static", wanPppoe = wan.mode === "pppoe";
  v.innerHTML =
    '<div class="settings-grid">' +

    /* ---- LAN ---- */
    '<div class="setting-card"><div class="panel"><div class="panel-head"><h3>🏠 LAN 内网设置</h3>' +
    '<span class="hint">修改后本机地址立即变更，请用新地址访问管理页</span></div><div class="panel-body">' +
    '<div class="setting-row"><span class="label">网卡</span><select id="s-lan-iface" class="grow">' + ifaceOptions(lan.interface) + '</select></div>' +
    '<div class="setting-row"><span class="label">网关地址</span><input id="s-lan-ip" class="grow mono" value="' + esc(lan.ip) + '"></div>' +
    '<div class="setting-row"><span class="label">子网掩码</span><input id="s-lan-mask" class="grow mono" value="' + esc(lan.netmask) + '"></div>' +
    '</div></div></div>' +

    /* ---- WAN ---- */
    '<div class="setting-card"><div class="panel"><div class="panel-head"><h3>🌐 WAN 外网设置</h3>' +
    '<span class="hint">不管理 = 由系统自行拨号/配置，本机只做转发</span></div><div class="panel-body">' +
    '<div class="setting-row"><span class="label">模式</span><select id="s-wan-mode" class="grow">' +
    '<option value="none"' + (wan.mode === "none" ? " selected" : "") + '>不管理（系统已自行配置/拨号）</option>' +
    '<option value="dhcp"' + (wan.mode === "dhcp" ? " selected" : "") + '>DHCP 自动获取</option>' +
    '<option value="static"' + (wan.mode === "static" ? " selected" : "") + '>静态地址</option>' +
    '<option value="pppoe"' + (wan.mode === "pppoe" ? " selected" : "") + '>PPPoE 宽带拨号</option>' +
    '</select></div>' +
    '<div class="setting-row"><span class="label">网卡</span><select id="s-wan-iface" class="grow">' +
    '<option value="">不使用</option>' + ifaceOptions(wan.interface) + '</select></div>' +
    '<div id="s-wan-static"' + (wanStatic ? "" : ' class="hidden"') + '>' +
    '  <div class="setting-row"><span class="label">IP 地址</span><input id="s-wan-ip" class="grow mono" value="' + esc(wan.ip) + '"></div>' +
    '  <div class="setting-row"><span class="label">子网掩码</span><input id="s-wan-mask" class="grow mono" value="' + esc(wan.netmask) + '"></div>' +
    '  <div class="setting-row"><span class="label">网关</span><input id="s-wan-gw" class="grow mono" value="' + esc(wan.gateway) + '"></div>' +
    '</div>' +
    '<div id="s-wan-pppoe"' + (wanPppoe ? "" : ' class="hidden"') + '>' +
    '  <div class="setting-row"><span class="label">宽带账号</span><input id="s-pppoe-user" class="grow" value="' + esc(wan.pppoe_user) + '"></div>' +
    '  <div class="setting-row"><span class="label">宽带密码</span><input id="s-pppoe-pass" type="password" class="grow" placeholder="留空表示保持不变"></div>' +
    '  <div class="highlight-box warn">PPPoE 拨号成功后出口网卡为 ppp0，拨号由 pppd 完成（需安装 ppp）。</div>' +
    '</div>' +
    '</div></div></div>' +

    /* ---- DHCP ---- */
    '<div class="setting-card"><div class="panel"><div class="panel-head"><h3>📡 DHCP 服务器</h3>' +
    '<span class="hint">由 dnsmasq 提供服务，保存后自动重启生效</span></div><div class="panel-body">' +
    '<div class="setting-row"><span class="label">启用 DHCP</span><label class="switch"><input type="checkbox" id="s-dhcp-on"' +
    (dh.enabled ? " checked" : "") + '><i></i></label><span class="muted small" id="s-dhcp-state"></span></div>' +
    '<div class="setting-row grid2"><div class="field-inline"><span>起始</span><input id="s-dhcp-start" class="mono" value="' + esc(dh.start) + '"></div>' +
    '<div class="field-inline"><span>结束</span><input id="s-dhcp-end" class="mono" value="' + esc(dh.end) + '"></div></div>' +
    '<div class="setting-row" style="align-items:flex-start"><span class="label">租期</span><div class="grow" id="s-lease-editor">' +
    leaseEditorHtml("s-lease") + '</div></div>' +
    '<div class="setting-row"><span class="label">首次自动固定</span><label class="switch"><input type="checkbox" id="s-auto-bind"' +
    (dh.auto_bind_first ? " checked" : "") + '><i></i></label>' +
    '<span class="muted small">新设备首次分配后自动固定 MAC↔IP，重启后仍使用同一地址</span></div>' +
    '<div class="setting-row"><span class="label">下发网关</span><label class="switch"><input type="checkbox" id="s-dhcp-gw"' +
    (dh.send_gateway ? " checked" : "") + '><i></i></label></div>' +
    '<div class="setting-row" id="s-gw-addr-row"><span class="label">网关地址</span>' +
    '<input id="s-dhcp-gw-addr" class="grow mono" value="' + esc(dh.gateway || "") +
    '" placeholder="留空 = 软路由 LAN 地址；也可填上游路由器地址"></div>' +
    '<div class="highlight-box gateway-off" id="s-gw-tip"></div>' +
    '<div class="setting-row"><span class="label">下发 DNS</span><input id="s-dhcp-dns" class="grow mono" value="' +
    esc((dh.dns_servers || []).join(", ")) + '" placeholder="留空 = 使用路由器地址"></div>' +
    '<div class="setting-row"><span class="label">静态分配</span><div class="grow"><div id="s-static-list"></div>' +
    '<button class="btn sm" id="s-static-add" type="button">＋ 添加一条静态分配</button></div></div>' +
    '<div class="setting-row"><span class="label">附加地址池</span><div class="grow"><div id="s-pool-list"></div>' +
    '<button class="btn sm" id="s-pool-add" type="button">＋ 添加地址池（同网段/VLAN）</button>' +
    '<div class="gw-hint">同网段池需在静态分配中把设备绑定到池；VLAN 池需交换机划分对应 VLAN。</div></div></div>' +
    '<div class="setting-row"><span class="label">高级选项</span><textarea id="s-dhcp-extra" placeholder="附加 dnsmasq 配置，每行一条（可选）">' +
    esc(dh.extra_options || "") + '</textarea></div>' +
    '</div></div></div>' +

    /* ---- DNS / 其他 ---- */
    '<div class="setting-card"><div class="panel"><div class="panel-head"><h3>🧭 DNS 与其他</h3></div><div class="panel-body">' +
    '<div class="setting-row"><span class="label">上游 DNS</span><input id="s-dns-up" class="grow mono" value="' +
    esc((dns.upstreams || []).join(", ")) + '" placeholder="多个用逗号分隔"></div>' +
    '<div class="setting-row"><span class="label">缓存条数</span><input id="s-dns-cache" type="number" class="grow" value="' + esc(dns.cache_size) + '"></div>' +
    '<div class="setting-row"><span class="label">跟随系统</span><label class="switch"><input type="checkbox" id="s-dns-sys"' +
    (dns.use_system ? " checked" : "") + '><i></i></label><span class="muted small">使用 /etc/resolv.conf 而非上面的上游</span></div>' +
    '<div class="setting-row"><span class="label">防火墙/NAT</span><label class="switch"><input type="checkbox" id="s-fw"' +
    (c.firewall.enabled !== false ? " checked" : "") + '><i></i></label><span class="muted small">关闭后内网无法上网</span></div>' +
    '<div class="setting-row"><span class="label">NetBIOS 命名</span><label class="switch"><input type="checkbox" id="s-nbns"' +
    (c.monitor.netbios ? " checked" : "") + '><i></i></label><span class="muted small">自动向设备询问计算机名</span></div>' +
    '<div class="setting-row"><span class="label">仅内网可管理</span><label class="switch"><input type="checkbox" id="s-lan-only"' +
    (c.web.lan_only !== false ? " checked" : "") + '><i></i></label><span class="muted small">拒绝外网访问管理页面（规划中）</span></div>' +
    '</div></div></div>' +
    '</div>' +

    '<div style="margin-top:16px;display:flex;gap:10px;align-items:center">' +
    '<button class="btn primary" id="s-save" style="min-width:160px">💾 保存并应用</button>' +
    '<span class="muted small">保存后将自动重建防火墙/重启 DHCP 服务，所需时间约 1-2 秒</span></div>' +
    '<div id="s-result" class="hidden" style="margin-top:12px"></div>';

  // 网关提示
  var tip = $("#s-gw-tip");
  initLeaseEditor("s-lease", dh.lease_time);
  function gwTip() {
    var on = $("#s-dhcp-gw").checked;
    var custom = $("#s-dhcp-gw-addr").value.trim();
    $("#s-gw-addr-row").classList.toggle("hidden", !on);
    tip.className = "highlight-box" + (on ? "" : " gateway-off");
    if (!on) {
      tip.innerHTML = '<b>已开启「不下发网关」</b>：DHCP 应答中不包含路由器选项（dnsmasq ' +
        '<span class="mono">dhcp-option=3</span>），客户端“默认网关”一栏将保持<b>空白</b>。';
    } else if (custom) {
      tip.innerHTML = '<b>下发自定义网关</b>：客户端“默认网关”将被设置为上游路由器 ' +
        '<span class="mono">' + esc(custom) + '</span>，适合本机仅做 DHCP、由上游路由器负责出口的场景。';
    } else {
      tip.innerHTML = '<b>已开启网关下发</b>：客户端“默认网关”将被设置为本机 LAN 地址 ' +
        '<span class="mono">' + esc($("#s-lan-ip").value) + '</span>。';
    }
  }
  gwTip();
  $("#s-dhcp-gw-addr").addEventListener("input", gwTip);
  $("#s-dhcp-gw").addEventListener("change", gwTip);

  function wanModeToggle() {
    var m = $("#s-wan-mode").value;
    $("#s-wan-static").classList.toggle("hidden", m !== "static");
    $("#s-wan-pppoe").classList.toggle("hidden", m !== "pppoe");
  }
  $("#s-wan-mode").addEventListener("change", wanModeToggle);

  // 静态分配列表 + 附加地址池
  var leases = dh.static_leases || [];
  var pools = (dh.pools || []).map(function (p) { return JSON.parse(JSON.stringify(p)); });

  function poolLabel(p) {
    return (p.type === "vlan"
      ? "VLAN " + esc(p.vlan_id || p.interface || "?")
      : "同网段") + " · " + esc(p.start || "") + "~" + esc(p.end || "");
  }

  function renderStatic() {
    var box = $("#s-static-list");
    box.innerHTML = leases.map(function (sl, idx) {
      var poolOpts = '<option value="">默认池</option>' + pools.map(function (p) {
        return '<option value="' + esc(p.id) + '"' + (sl.pool === p.id ? " selected" : "") + ">" +
          esc(p.name || p.id) + "</option>";
      }).join("");
      return '<div class="setting-row" style="margin-bottom:6px">' +
        '<input class="mono" data-sl="mac" value="' + esc(sl.mac) + '" placeholder="MAC 地址">' +
        '<input class="mono" data-sl="ip" value="' + esc(sl.ip) + '" placeholder="IP 地址">' +
        '<input data-sl="name" value="' + esc(sl.name || "") + '" placeholder="备注名（可选）" style="max-width:130px">' +
        '<select data-sl="pool" style="max-width:130px">' + poolOpts + '</select>' +
        '<button class="btn xs danger" data-sl-del="' + idx + '" type="button">删除</button></div>';
    }).join("") || '<div class="muted small" style="margin-bottom:6px">暂无静态分配</div>';
    $$("[data-sl-del]", box).forEach(function (b) {
      b.addEventListener("click", function () {
        leases.splice(parseInt(b.dataset.slDel, 10), 1);
        renderStatic();
      });
    });
  }

  function renderPools() {
    var box = $("#s-pool-list");
    box.innerHTML = pools.map(function (p, i) {
      return '<div class="setting-row" style="margin-bottom:6px">' +
        '<span class="grow"><b>' + esc(p.name || ("地址池 " + (i + 1))) + '</b> ' +
        '<span class="badge">' + (p.type === "vlan" ? "VLAN" : "同网段") + '</span> ' +
        '<span class="muted small mono">' + poolLabel(p) +
        (p.gateway ? " · 网关 " + esc(p.gateway) : "") + '</span></span>' +
        '<button class="btn xs" data-pool-edit="' + i + '" type="button">编辑</button>' +
        '<button class="btn xs danger" data-pool-del="' + i + '" type="button">删除</button></div>';
    }).join("") || '<div class="muted small" style="margin-bottom:6px">暂无附加地址池</div>';
    $$("[data-pool-edit]", box).forEach(function (b) {
      b.addEventListener("click", function () { poolModal(parseInt(b.dataset.poolEdit, 10)); });
    });
    $$("[data-pool-del]", box).forEach(function (b) {
      b.addEventListener("click", function () {
        pools.splice(parseInt(b.dataset.poolDel, 10), 1);
        renderPools();
        renderStatic();
      });
    });
  }

  function leaseToMinutes(s) {
    s = String(s || "").trim();
    if (!s || s === "infinite") return 0;
    var m = /^(\d+)([smhdw])$/.exec(s);
    if (!m) return 720;
    var n = parseInt(m[1], 10);
    if (m[2] === "m") return n;
    if (m[2] === "h") return n * 60;
    if (m[2] === "d") return n * 1440;
    if (m[2] === "w") return n * 10080;
    return Math.max(1, Math.round(n / 60));
  }

  function minutesToLease(n) {
    n = parseInt(n, 10);
    return (!n || n <= 0) ? "infinite" : (n + "m");
  }

  function ipNum(ip) {
    var a = String(ip).split(".");
    if (a.length !== 4) return null;
    var n = 0;
    for (var i = 0; i < 4; i++) {
      var v = parseInt(a[i], 10);
      if (isNaN(v) || v < 0 || v > 255) return null;
      n = n * 256 + v;
    }
    return n;
  }

  function poolModal(idx) {
    var lanIface = $("#s-lan-iface").value;
    var lanIp = $("#s-lan-ip").value.trim();
    var lanMask = $("#s-lan-mask").value.trim();
    var p = idx >= 0 ? JSON.parse(JSON.stringify(pools[idx])) : {
      id: "pool-" + Math.random().toString(36).slice(2, 8),
      name: "", type: "tagged", enabled: true, vlan_id: "",
      parent: lanIface, ip: "", netmask: "255.255.255.0",
      start: "", end: "", gateway: "", dns_servers: [], lease_time: "120m"
    };
    var vlanPools = pools.filter(function (x) {
      return x.type === "vlan" && (x.vlan_id || x.interface);
    });
    var selIface = p.type === "vlan" ? ("vlan:" + p.id) : "primary";
    var ifaceOpts = '<option value="primary"' + (selIface === "primary" ? " selected" : "") + ">" +
      esc(lanIface + " · " + lanIp + "（同网段）") + "</option>";
    vlanPools.forEach(function (x) {
      var ifname = x.interface || ((x.parent || lanIface) + "." + x.vlan_id);
      ifaceOpts += '<option value="vlan:' + esc(x.id) + '"' + (selIface === "vlan:" + x.id ? " selected" : "") + ">" +
        esc(ifname + " · " + x.ip + "（VLAN " + x.vlan_id + "）") + "</option>";
    });
    ifaceOpts += '<option value="new"' + (selIface === "new" ? " selected" : "") + ">＋ 新建 VLAN 子接口…</option>";
    if (p.type === "vlan" && !pools.some(function (x) { return x.id === p.id; })) {
      selIface = "new";
    }
    var dns = p.dns_servers || [];
    var body =
      '<div class="grid cols2" style="gap:10px">' +
      '  <label class="field"><span>地址池名称</span><input id="pf-name" value="' + esc(p.name) + '" placeholder="如：办公网/访客网络"></label>' +
      '  <label class="field"><span>服务接口</span><select id="pf-iface">' + ifaceOpts + '</select></label>' +
      '</div>' +
      '<div id="pf-newvlan" class="gw-form-section hidden">' +
      '  <h4>VLAN 子接口</h4>' +
      '  <div class="grid cols2" style="gap:10px">' +
      '    <label class="field"><span>VLAN ID</span><input id="pf-vlan-id" class="mono" value="' + esc(p.vlan_id || "") + '" placeholder="如 20"></label>' +
      '    <label class="field"><span>父接口</span><input id="pf-parent" class="mono" value="' + esc(p.parent || lanIface) + '"></label>' +
      '  </div>' +
      '  <div class="grid cols2" style="gap:10px">' +
      '    <label class="field"><span>本机 VLAN 地址</span><input id="pf-ip" class="mono" value="' + esc(p.ip || "") + '" placeholder="192.168.20.1"></label>' +
      '    <label class="field"><span>子网掩码</span><input id="pf-mask" class="mono" value="' + esc(p.netmask || "255.255.255.0") + '"></label>' +
      '  </div>' +
      '  <div class="gw-hint">保存后自动创建 <span class="mono">父接口.VLANID</span> 子接口；交换机对应端口需为 Trunk。</div>' +
      '</div>' +
      '<div class="grid cols2" style="gap:10px">' +
      '  <div class="field"><span>客户端地址池</span><div style="display:flex;gap:6px;align-items:center">' +
      '    <input id="pf-start" class="mono" value="' + esc(p.start) + '" placeholder="192.168.1.100">' +
      '    <span class="muted">—</span>' +
      '    <input id="pf-end" class="mono" value="' + esc(p.end) + '" placeholder="192.168.1.199">' +
      '  </div></div>' +
      '  <label class="field"><span>子网掩码</span><input id="pf-mask-main" class="mono" value="' + esc(p.type === "vlan" ? (p.netmask || "255.255.255.0") : lanMask) + '"></label>' +
      '</div>' +
      '<div class="grid cols2" style="gap:10px">' +
      '  <label class="field"><span>网关地址（留空 = 接口地址）</span><input id="pf-gateway" class="mono" value="' + esc(p.gateway) + '" placeholder="' + esc(p.type === "vlan" ? (p.ip || "本机 VLAN 地址") : lanIp) + '"></label>' +
      '</div>' +
      '<div class="field"><span>租期（年 / 月 / 日 / 时 / 分）</span><div id="pf-lease-editor">' + leaseEditorHtml("pf-lease") + '</div></div>' +
      '<div class="grid cols2" style="gap:10px">' +
      '  <label class="field"><span>主 DNS</span><input id="pf-dns1" class="mono" value="' + esc(dns[0] || "") + '" placeholder="留空 = 网关地址"></label>' +
      '  <label class="field"><span>次 DNS</span><input id="pf-dns2" class="mono" value="' + esc(dns[1] || "") + '" placeholder="可选"></label>' +
      '</div>' +
      '<label class="field"><span>排除地址（可选）</span><input id="pf-exclude" class="mono" value="' + esc(p.exclude || "") +
      '" placeholder="单个 IP 或范围，如 192.168.1.150, 192.168.1.160-192.168.1.165"></label>' +
      '<label class="field"><span>自定义 DHCP 选项（每行：代码,值）</span><textarea id="pf-options" placeholder="例如：43,01:04:C0:A8:0A:01">' +
      esc(p.extra_options || "") + '</textarea></label>' +
      '<div class="highlight-box" id="pf-remain">剩余可用地址：—</div>' +
      '<div class="gw-hint" id="pf-tag-hint"></div>' +
      '<div id="pf-error" class="form-error hidden" style="margin-top:10px"></div>';

    var mask = openModal(idx >= 0 ? "编辑地址池" : "新建地址池", body,
      '<button class="btn ghost" id="pf-cancel">取消</button>' +
      '<button class="btn primary" id="pf-save">保存</button>', true);
    initLeaseEditor("pf-lease", p.lease_time);

    function val(id) { var el = $("#" + id, mask); return el ? el.value.trim() : ""; }
    function syncIface() {
      var v = $("#pf-iface", mask).value;
      var isPrimary = v === "primary";
      $("#pf-newvlan", mask).classList.toggle("hidden", v !== "new");
      $("#pf-mask-main", mask).readOnly = isPrimary;
      $("#pf-tag-hint", mask).innerHTML = isPrimary
        ? "同网段地址池不会自动参与分配：需在“静态分配”中把设备绑定到本池，未绑定设备仍使用默认池。"
        : "VLAN 内客户端会自动使用此池；网关留空时为本机 VLAN 地址。";
      if (isPrimary) {
        $("#pf-mask-main", mask).value = lanMask;
        $("#pf-gateway", mask).placeholder = lanIp;
      } else if (v.indexOf("vlan:") === 0) {
        var pid = v.slice(5);
        var x = pools.filter(function (q) { return q.id === pid; })[0];
        if (x) {
          $("#pf-vlan-id", mask).value = x.vlan_id || "";
          $("#pf-parent", mask).value = x.parent || lanIface;
          $("#pf-ip", mask).value = x.ip || "";
          $("#pf-mask", mask).value = x.netmask || "255.255.255.0";
          $("#pf-mask-main", mask).value = x.netmask || "255.255.255.0";
          $("#pf-gateway", mask).placeholder = x.ip || "";
        }
      } else {
        $("#pf-gateway", mask).placeholder = "本机 VLAN 地址";
      }
      updateRemain();
    }
    function excludeRanges(text) {
      var out = [];
      String(text || "").split(/[,，;\s]+/).forEach(function (t) {
        if (!t) return;
        var parts = t.split("-");
        var a = ipNum(parts[0]);
        var b = parts.length > 1 ? ipNum(parts[1]) : a;
        if (a === null || b === null) return;
        out.push([Math.min(a, b), Math.max(a, b)]);
      });
      return out;
    }
    function updateRemain() {
      var s = ipNum(val("pf-start")), e = ipNum(val("pf-end"));
      var el = $("#pf-remain", mask);
      if (s === null || e === null) { el.textContent = "剩余可用地址：请填写完整地址范围"; return; }
      var n = e - s + 1;
      excludeRanges(val("pf-exclude")).forEach(function (r) {
        var a = Math.max(r[0], s), b = Math.min(r[1], e);
        if (b >= a) n -= (b - a + 1);
      });
      el.textContent = n > 0 ? ("剩余可用地址：" + n + " 个") : "地址范围无效或已全部被排除";
    }
    $("#pf-iface", mask).addEventListener("change", syncIface);
    ["pf-start", "pf-end", "pf-exclude"].forEach(function (id) {
      $("#" + id, mask).addEventListener("input", updateRemain);
    });
    syncIface();

    $("#pf-cancel", mask).addEventListener("click", closeModal);
    $("#pf-save", mask).addEventListener("click", function () {
      var err = $("#pf-error", mask);
      function fail(msg) { err.textContent = msg; err.classList.remove("hidden"); }
      var ifaceSel = $("#pf-iface", mask).value;
      var type = ifaceSel === "primary" ? "tagged" : "vlan";
      var name = val("pf-name") || ("地址池 " + (pools.length + 1));
      var start = val("pf-start"), end = val("pf-end");
      var netmask = val("pf-mask-main");
      var gw = val("pf-gateway");
      var leaseText = readLeaseEditor("pf-lease");
      var dnsArr = [val("pf-dns1"), val("pf-dns2")].filter(Boolean);
      if (!start || !end) return fail("请填写客户端地址池的起始/结束地址");
      if (ipNum(start) === null || ipNum(end) === null) return fail("地址格式不正确");
      var np = {
        id: p.id, name: name, type: type, enabled: true,
        start: start, end: end, lease_time: leaseText,
        gateway: gw, dns_servers: dnsArr,
        exclude: val("pf-exclude"),
        extra_options: val("pf-options"),
        vlan_id: "", parent: "", ip: "", netmask: netmask || "255.255.255.0"
      };
      if (type === "vlan") {
        var vlanId = val("pf-vlan-id"), parent = val("pf-parent") || lanIface;
        var vip = val("pf-ip"), vmask = val("pf-mask") || "255.255.255.0";
        if (!vlanId && !vip) return fail("VLAN 池需要填写 VLAN ID 与本机 VLAN 地址");
        if (!vip) return fail("请填写本机 VLAN 地址");
        np.vlan_id = vlanId;
        np.parent = parent;
        np.ip = vip;
        np.netmask = vmask;
        np.interface = (p.type === "vlan" && p.interface) ? p.interface : "";
      }
      if (idx >= 0) pools[idx] = np; else pools.push(np);
      closeModal();
      renderPools();
      renderStatic();
    });
  }

  renderStatic();
  renderPools();
  $("#s-static-add").addEventListener("click", function () {
    leases.push({ mac: "", ip: "", name: "", pool: "" });
    renderStatic();
  });
  $("#s-pool-add").addEventListener("click", function () { poolModal(-1); });

  $("#s-save").addEventListener("click", async function () {
    var btn = this;
    btn.disabled = true;
    var out = $("#s-result");
    out.className = "hidden";
    // 收集静态分配
    var sl = [];
    $$("[data-sl=mac]").forEach(function (m) {
      var row = m.parentElement;
      sl.push({
        mac: m.value.trim(),
        ip: $('[data-sl=ip]', row).value.trim(),
        name: $('[data-sl=name]', row).value.trim(),
        pool: $('[data-sl=pool]', row).value
      });
    });
    var payload = {
      network: {
        lan: { interface: $("#s-lan-iface").value, ip: $("#s-lan-ip").value.trim(), netmask: $("#s-lan-mask").value.trim() },
        wan: {
          interface: $("#s-wan-iface").value,
          mode: $("#s-wan-mode").value,
          ip: $("#s-wan-ip").value.trim(),
          netmask: $("#s-wan-mask").value.trim(),
          gateway: $("#s-wan-gw").value.trim(),
          pppoe_user: $("#s-pppoe-user").value.trim(),
          pppoe_password: $("#s-pppoe-pass").value
        }
      },
      dhcp: {
        enabled: $("#s-dhcp-on").checked,
        start: $("#s-dhcp-start").value.trim(),
        end: $("#s-dhcp-end").value.trim(),
        lease_time: readLeaseEditor("s-lease"),
        auto_bind_first: $("#s-auto-bind").checked,
        send_gateway: $("#s-dhcp-gw").checked,
        gateway: $("#s-dhcp-gw-addr").value.trim(),
        dns_servers: $("#s-dhcp-dns").value.split(/[,，\s]+/).filter(Boolean),
        static_leases: sl,
        pools: pools,
        extra_options: $("#s-dhcp-extra").value
      },
      dns: {
        use_system: $("#s-dns-sys").checked,
        upstreams: $("#s-dns-up").value.split(/[,，\s]+/).filter(Boolean),
        cache_size: parseInt($("#s-dns-cache").value || "512", 10)
      },
      monitor: { netbios: $("#s-nbns").checked },
      firewall: { enabled: $("#s-fw").checked },
      web: { lan_only: $("#s-lan-only").checked }
    };
    try {
      var r = await api("/api/settings", { body: payload });
      var lines = [];
      if (r.errors && r.errors.length) lines.push("⚠ " + r.errors.join("；"));
      (r.applied || []).forEach(function (x) { lines.push("✓ " + x); });
      (r.warnings || []).forEach(function (x) { lines.push("! " + x); });
      if (!lines.length) lines.push("✓ 配置已保存");
      out.innerHTML = '<div class="form-ok">' + lines.map(esc).join("<br>") + "</div>";
      out.className = "";
      toast("设置已保存并应用", "ok");
      buildSettings();
    } catch (e) {
      out.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>";
      out.className = "";
      toast("保存失败：" + e.message, "err", 6000);
    } finally {
      btn.disabled = false;
    }
  });
}

/* ================================================================
 * 系统
 * ================================================================ */
function buildSystem() {
  var v = $("#view-system");
  v.innerHTML =
    '<div class="grid cards" id="sys-cards"></div>' +
    '<div class="grid cols2" style="margin-top:14px">' +
    '  <div class="panel"><div class="panel-head"><h3>🔑 修改管理密码</h3></div><div class="panel-body">' +
    '    <div class="field"><span>原密码</span><input type="password" id="pwd-old" autocomplete="current-password"></div>' +
    '    <div class="field"><span>新密码（至少 6 位）</span><input type="password" id="pwd-new" autocomplete="new-password"></div>' +
    '    <div class="field"><span>确认新密码</span><input type="password" id="pwd-new2" autocomplete="new-password"></div>' +
    '    <button class="btn primary" id="pwd-save">保存新密码</button>' +
    '    <div id="pwd-msg" class="hidden" style="margin-top:10px"></div>' +
    '  </div></div>' +
    '  <div class="panel"><div class="panel-head"><h3>⏻ 重启 / 关机</h3></div><div class="panel-body">' +
    '    <p class="muted small" style="margin-bottom:12px">演示模式只会模拟操作，真实设备上将以 root 执行系统命令。</p>' +
    '    <div style="display:flex;gap:10px">' +
    '      <button class="btn danger" id="sys-reboot">🔄 重启路由器</button>' +
    '      <button class="btn danger" id="sys-poweroff">⏻ 关机</button>' +
    '    </div>' +
    '  </div></div>' +
    '</div>' +
    '<div class="panel" style="margin-top:14px"><div class="panel-head"><h3>💾 备份与恢复</h3>' +
    '  <span class="hint">配置 / 设备别名 / 累计流量 / 网关凭据</span></div><div class="panel-body">' +
    '  <div style="display:flex;gap:10px;flex-wrap:wrap">' +
    '    <button class="btn primary" id="bk-export">导出备份</button>' +
    '    <button class="btn" id="bk-pick">选择备份恢复</button>' +
    '    <input type="file" id="bk-file" accept=".json,application/json" style="display:none">' +
    '  </div>' +
    '  <div class="gw-hint" style="margin-top:8px">备份包含管理密码哈希和网关凭据，请妥善保管；恢复会覆盖当前配置并重启服务。</div>' +
    '  <div id="bk-msg" class="hidden" style="margin-top:8px"></div>' +
    '</div></div>' +
    '<div class="panel" style="margin-top:14px"><div class="panel-head"><h3>⬆️ 应用升级</h3>' +
    '  <span class="hint">仅升级易路由应用，不升级 Debian 系统</span></div><div class="panel-body">' +
    '  <div id="upg-status" class="muted small" style="margin-bottom:10px">正在读取版本…</div>' +
    '  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">' +
    '    <button class="btn" id="upg-pick">选择升级包（.zip）</button>' +
    '    <input type="file" id="upg-file" accept=".zip,application/zip" style="display:none">' +
    '    <button class="btn primary" id="upg-run" disabled>开始升级</button>' +
    '    <span class="muted small" id="upg-file-name"></span>' +
    '  </div>' +
    '  <div class="gw-hint" style="margin-top:8px">升级包需包含 easyrouter/ 目录和 VERSION 文件。升级会重启服务约 10 秒，健康检查失败会自动回滚。</div>' +
    '  <div id="upg-msg" class="hidden" style="margin-top:8px"></div>' +
    '  <div id="upg-backups" class="muted small" style="margin-top:8px"></div>' +
    '</div></div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>📄 运行日志</h3>' +
    '    <span class="hint">应用日志 + dnsmasq 服务日志（自动刷新）</span></div>' +
    '  <div class="panel-body"><div class="log-box" id="sys-log">加载中…</div></div>' +
    '</div>' +
    '<div class="panel" style="margin-top:14px">' +
    '  <div class="panel-head"><h3>ℹ️ 关于</h3></div><div class="panel-body" id="sys-about"></div></div>';
  $("#pwd-save").addEventListener("click", async function () {
    var msg = $("#pwd-msg");
    msg.className = "hidden";
    var o = $("#pwd-old").value, n = $("#pwd-new").value, n2 = $("#pwd-new2").value;
    if (n.length < 6) { msg.innerHTML = '<div class="form-error">新密码至少 6 位</div>'; msg.className = ""; return; }
    if (n !== n2) { msg.innerHTML = '<div class="form-error">两次输入的新密码不一致</div>'; msg.className = ""; return; }
    try {
      var r = await api("/api/password", { body: { old_password: o, new_password: n } });
      msg.innerHTML = '<div class="form-ok">' + esc(r.message) + "</div>";
      msg.className = "";
      $("#pwd-old").value = $("#pwd-new").value = $("#pwd-new2").value = "";
      toast(r.message, "ok");
    } catch (e) {
      msg.innerHTML = '<div class="form-error">' + esc(e.message) + "</div>";
      msg.className = "";
    }
  });
  $("#bk-export").addEventListener("click", function () {
    api("/api/backup").then(function (d) {
      var blob = new Blob([JSON.stringify(d.backup, null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      var ts = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 16);
      a.href = URL.createObjectURL(blob);
      a.download = "easyrouter-backup-" + ts + ".json";
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 3000);
      toast("备份已导出", "ok");
    }).catch(function (e) { toast(e.message, "err"); });
  });
  $("#bk-pick").addEventListener("click", function () { $("#bk-file").click(); });
  $("#bk-file").addEventListener("change", function () {
    var f = this.files && this.files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () {
      var data;
      try { data = JSON.parse(reader.result); }
      catch (e) {
        $("#bk-msg").innerHTML = '<div class="form-error">备份文件不是有效的 JSON</div>';
        $("#bk-msg").className = "";
        return;
      }
      confirmModal("恢复备份", "将用备份覆盖当前配置、设备别名和累计流量，并重启相关服务。<br>确定继续吗？", "确认恢复", true)
        .then(function (yes) {
          if (!yes) return;
          api("/api/backup/restore", { body: { backup: data } }).then(function (r) {
            toast(r.message, "ok");
            setTimeout(function () { location.reload(); }, 1200);
          }).catch(function (e) {
            $("#bk-msg").innerHTML = '<div class="form-error">' + esc(e.message) + "</div>";
            $("#bk-msg").className = "";
          });
        });
    };
    reader.readAsText(f);
  });
  // 应用升级
  var upgB64 = "", upgName = "";
  function upgMsg(html, cls) {
    var el = $("#upg-msg");
    el.innerHTML = html;
    el.className = cls || "";
  }
  function loadUpgradeStatus() {
    api("/api/system/upgrade").then(function (d) {
      $("#upg-status").innerHTML = "当前版本 <b>v" + esc(d.current_version) + "</b> · " +
        (d.demo ? "演示模式：只校验升级包，不替换程序"
          : (d.supported ? "支持自动升级（root + systemd）" : "当前环境不支持自动升级（需要 root + systemd）"));
      var b = d.backups || [];
      $("#upg-backups").innerHTML = b.length
        ? "可用回滚备份：" + b.slice(0, 3).map(function (x, i) {
          return '<button class="btn xs" data-upg-restore="' + esc(x.name) + '">' + esc(x.name) + "</button>";
        }).join(" ")
        : "暂无升级备份";
      $$("[data-upg-restore]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          confirmModal("回滚应用", "将恢复备份 " + esc(btn.dataset.upgRestore) + "，是否继续？", "确认回滚", true)
            .then(function (yes) {
              if (!yes) return;
              api("/api/system/upgrade/restore", { body: { name: btn.dataset.upgRestore } })
                .then(function (r) { toast(r.message, "ok"); })
                .catch(function (e) { toast(e.message, "err"); });
            });
        });
      });
    }).catch(function (e) { $("#upg-status").textContent = "读取升级状态失败：" + e.message; });
  }
  $("#upg-pick").addEventListener("click", function () { $("#upg-file").click(); });
  $("#upg-file").addEventListener("change", function () {
    var f = this.files && this.files[0];
    if (!f) return;
    if (f.size > 12 * 1024 * 1024) { upgMsg('<div class="form-error">升级包不能超过 12MB</div>'); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var bytes = new Uint8Array(reader.result), bin = "";
      for (var i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      upgB64 = btoa(bin);
      upgName = f.name;
      $("#upg-file-name").textContent = f.name;
      $("#upg-run").disabled = false;
      upgMsg('<div class="form-ok">升级包已读取，点“开始升级”继续</div>');
    };
    reader.readAsArrayBuffer(f);
  });
  $("#upg-run").addEventListener("click", function () {
    if (!upgB64) return;
    confirmModal("应用升级", "将替换当前应用并重启服务（约 10 秒）。<br>健康检查失败会自动回滚。确定继续吗？", "确认升级", true)
      .then(function (yes) {
        if (!yes) return;
        $("#upg-run").disabled = true;
        upgMsg('<div class="form-ok">正在上传并安装升级包…</div>');
        api("/api/system/upgrade", { body: { filename: upgName, data: upgB64 } })
          .then(function (r) {
            upgMsg('<div class="form-ok">' + esc(r.message) + "（版本 " + esc(r.version) + "）</div>");
            toast(r.message, "ok", 6000);
            if (r.restarting) {
              $("#upg-status").textContent = "升级完成，服务重启中，约 15 秒后自动刷新…";
              setTimeout(function () { location.reload(); }, 15000);
            } else {
              loadUpgradeStatus();
            }
          })
          .catch(function (e) {
            upgMsg('<div class="form-error">升级失败：' + esc(e.message) + "</div>");
            $("#upg-run").disabled = false;
          });
      });
  });
  loadUpgradeStatus();
  $("#sys-reboot").addEventListener("click", function () {
    confirmModal("重启路由器", "重启会中断所有内网连接约 1 分钟，确定继续吗？", "确认重启", true)
      .then(async function (yes) {
        if (!yes) return;
        try {
          var r = await api("/api/system/action", { body: { action: "reboot", confirm: "确认重启" } });
          toast(r.message, "warn");
        } catch (e) { toast(e.message, "err"); }
      });
  });
  $("#sys-poweroff").addEventListener("click", function () {
    confirmModal("关机", "关机后需要到设备旁手动开机，确定继续吗？", "确认关机", true)
      .then(async function (yes) {
        if (!yes) return;
        try {
          var r = await api("/api/system/action", { body: { action: "poweroff", confirm: "确认关机" } });
          toast(r.message, "warn");
        } catch (e) { toast(e.message, "err"); }
      });
  });
  viewBuilt.system = true;
  pollSystem();
}

function pollSystem() {
  api("/api/settings").then(function (d) {
    var svc = d.services || {};
    var dm = svc.dnsmasq || {}, nft = svc.nft || {}, wan = svc.wan || {};
    $("#sys-cards").innerHTML =
      '<div class="stat-card"><div class="label"><span class="ico">🛠️</span>DHCP/DNS 服务 (dnsmasq)</div>' +
      '  <div class="value" style="font-size:20px;color:' + (dm.running ? "var(--green)" : "var(--red)") + '">' +
      (dm.running ? "运行中" : "已停止") + '</div>' +
      '  <div class="sub">PID ' + (dm.pid || "—") + ' · 重启 ' + (dm.restarts || 0) + ' 次' +
      (dm.last_error ? '<br><span style="color:var(--red)">' + esc(dm.last_error) + "</span>" : "") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🧱</span>防火墙 (nftables)</div>' +
      '  <div class="value" style="font-size:20px;color:' + (nft.ok ? "var(--green)" : "var(--red)") + '">' +
      (nft.ok ? "规则正常" : "异常") + '</div>' +
      '  <div class="sub">' + (nft.rules || 0) + ' 条规则（含每设备计数器）' +
      (nft.last_error ? '<br><span style="color:var(--red)">' + esc(nft.last_error) + "</span>" : "") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🌐</span>WAN 连接</div>' +
      '  <div class="value" style="font-size:20px">' + esc(wan.ip || "未连接") + '</div>' +
      '  <div class="sub">模式 ' + esc(wan.mode || "—") + ' · ' + esc(wan.state || "") + '</div></div>' +
      '<div class="stat-card"><div class="label"><span class="ico">🐍</span>运行后端</div>' +
      '  <div class="value" style="font-size:20px">' + (d.backend === "demo" ? "演示模式" : "Linux 真实模式") + '</div>' +
      '  <div class="sub">' + (d.backend === "demo" ? "当前为模拟数据，用于预览界面" : "已接管本机网络服务") + '</div></div>';
  }).catch(function () { /* 静默 */ });
  api("/api/logs").then(function (d) {
    var lines = (d.dnsmasq || []).slice(-80).map(function (x) { return "[dnsmasq] " + x; });
    lines = (d.app || []).slice(-80).concat(lines);
    $("#sys-log").innerHTML = lines.map(function (x) {
      var cls = /error|失败|退出/i.test(x) ? "err" : (/warn/i.test(x) ? "warn" : "");
      return '<span class="' + cls + '">' + esc(x) + "</span>";
    }).join("\n") || "暂无日志";
    $("#sys-log").scrollTop = $("#sys-log").scrollHeight;
  }).catch(function () { });
  if (!state.about) {
    api("/api/status").then(function (st) {
      state.about = true;
      $("#sys-about").innerHTML =
        '<table><tbody>' +
        '<tr><td>产品</td><td>易路由 EasyRouter（全中文软路由系统）</td></tr>' +
        '<tr><td>版本</td><td>v' + esc(st.version) + '</td></tr>' +
        '<tr><td>模式</td><td>' + (st.backend === "demo" ? "演示模式" : "正式模式") + '</td></tr>' +
        '<tr><td>DHCP 引擎</td><td>dnsmasq（支持不下发网关：dhcp-option=3）</td></tr>' +
        '<tr><td>流量统计</td><td>nftables 每设备计数器</td></tr>' +
        '<tr><td>会话统计</td><td>内核连接跟踪 conntrack</td></tr>' +
        '</tbody></table>';
    }).catch(function () { });
  }
}

/* ================================================================
 * 安装向导
 * ================================================================ */
var setupStep = 1;
var setupData = { password: "", password2: "", wan_interface: "", lan_interface: "",
  lan_ip: "192.168.1.1", lan_netmask: "255.255.255.0", send_gateway: true,
  gateway: "", wan_mode: "none" };

function initSetup() {
  setupStep = 1;
  renderSetup();
}
function renderSetup() {
  $$("#setup-steps li").forEach(function (li) {
    var n = parseInt(li.dataset.step, 10);
    li.classList.toggle("active", n === setupStep);
    li.classList.toggle("done", n < setupStep);
  });
  $("#setup-prev").classList.toggle("hidden", setupStep <= 1);
  $("#setup-next").textContent = setupStep >= 4 ? "完成安装" : "下一步";
  $("#setup-error").classList.add("hidden");
  var body = $("#setup-body");
  if (setupStep === 1) {
    body.innerHTML =
      '<div class="field"><span>设置管理员密码（至少 6 位）</span>' +
      '<input type="password" id="st-pw1" value="' + esc(setupData.password) + '" placeholder="用于登录管理页"></div>' +
      '<div class="field"><span>再次输入密码</span>' +
      '<input type="password" id="st-pw2" value="' + esc(setupData.password2) + '" placeholder="确认密码"></div>';
  } else if (setupStep === 2) {
    api("/api/interfaces").then(function (r) {
      state.interfaces = r.interfaces || [];
      var list = state.interfaces.map(function (i) {
        return '<div class="iface-option' + (setupData.lan_interface === i.name ? " sel" : "") +
          '" data-if="' + esc(i.name) + '"><b class="mono">' + esc(i.name) + '</b>' +
          '<span class="mono">MAC ' + esc(i.mac || "—") + '</span>' +
          '<span class="state muted">' + (i.addrs || []).join(", ") + " · " + (i.state === "up" ? "已连接" : "未连接") + '</span>' +
          '<span class="badge">点选为 LAN</span></div>';
      }).join("");
      body.innerHTML =
        '<div class="muted small" style="margin-bottom:10px">点击选择作为<b> LAN 内网</b>的网卡（接交换机/AP/电脑）：</div>' +
        '<div id="st-if-list">' + list + '</div>' +
        '<div class="field" style="margin-top:12px"><span>WAN 外网网卡（与 LAN 相同的选“不使用”，表示外网已由系统拨号）</span>' +
        '<select id="st-wan"><option value="">不使用（系统已自行配置外网）</option>' +
        state.interfaces.map(function (i) {
          return '<option value="' + esc(i.name) + '"' + (setupData.wan_interface === i.name ? " selected" : "") + '>' +
            esc(i.name) + "</option>";
        }).join("") + '</select></div>';
      $$("#st-if-list .iface-option").forEach(function (el) {
        el.addEventListener("click", function () {
          setupData.lan_interface = el.dataset.if;
          $$("#st-if-list .iface-option").forEach(function (x) { x.classList.remove("sel"); });
          el.classList.add("sel");
        });
      });
    }).catch(function (e) { body.innerHTML = '<div class="form-error">读取网卡失败：' + esc(e.message) + "</div>"; });
  } else if (setupStep === 3) {
    var gwOn = setupData.send_gateway;
    body.innerHTML =
      '<div class="field"><span>LAN 网关地址（管理页地址）</span>' +
      '<input id="st-lan-ip" class="mono" value="' + esc(setupData.lan_ip) + '"></div>' +
      '<div class="field"><span>子网掩码</span><input id="st-mask" class="mono" value="' + esc(setupData.lan_netmask) + '"></div>' +
      '<div class="setting-row" style="margin-bottom:10px"><span class="label" style="flex:0 0 130px">向客户端下发网关</span>' +
      '<label class="switch"><input type="checkbox" id="st-gw"' + (gwOn ? " checked" : "") + '><i></i></label></div>' +
      '<div class="field" id="st-gw-addr-wrap"><span>下发的网关地址（留空 = 本机 LAN 地址）</span>' +
      '<input id="st-gw-addr" class="mono" value="' + esc(setupData.gateway || "") +
      '" placeholder="例如上游路由器 192.168.10.1"></div>' +
      '<div class="highlight-box' + (gwOn ? "" : " gateway-off") + '" id="st-gw-tip"></div>' +
      '<div class="field" style="margin-top:12px"><span>WAN 模式</span><select id="st-wanmode">' +
      '<option value="none">不管理（系统已自行配置/拨号）</option>' +
      '<option value="dhcp">DHCP 自动获取</option>' +
      '<option value="static">静态地址</option>' +
      '<option value="pppoe">PPPoE 宽带拨号</option></select></div>';
    var tip = $("#st-gw-tip");
    function gwTip() {
      var on = $("#st-gw").checked;
      var custom = $("#st-gw-addr").value.trim();
      $("#st-gw-addr-wrap").classList.toggle("hidden", !on);
      tip.className = "highlight-box" + (on ? "" : " gateway-off");
      if (!on) {
        tip.innerHTML = "<b>不下发网关</b>：DHCP 应答不含路由器选项，客户端“默认网关”一栏为空，仅获得 IP 与 DNS。";
      } else if (custom) {
        tip.innerHTML = "<b>下发自定义网关</b>：客户端默认网关将指向 <span class='mono'>" +
          esc(custom) + "</span>（适合本机只做 DHCP、由上游路由器负责出口）。";
      } else {
        tip.innerHTML = "<b>下发网关</b>：客户端默认网关将指向本机 LAN 地址。";
      }
    }
    gwTip();
    $("#st-gw").addEventListener("change", gwTip);
    $("#st-gw-addr").addEventListener("input", gwTip);
    $("#st-wanmode").value = setupData.wan_mode;
  } else {
    body.innerHTML =
      '<table><tbody>' +
      '<tr><td>管理员</td><td>admin（密码已设置）</td></tr>' +
      '<tr><td>WAN 网卡</td><td class="mono">' + esc(setupData.wan_interface || "不使用（系统已配置）") + '</td></tr>' +
      '<tr><td>LAN 网卡</td><td class="mono">' + esc(setupData.lan_interface || "未选择") + '</td></tr>' +
      '<tr><td>LAN 地址</td><td class="mono">' + esc(setupData.lan_ip) + " / " + esc(setupData.lan_netmask) + '</td></tr>' +
      '<tr><td>DHCP 网关</td><td>' + (setupData.send_gateway
        ? "✓ 下发（" + esc(setupData.gateway || "本机 LAN 地址") + "）"
        : "✗ 不下发（客户端网关为空）") + '</td></tr>' +
      '<tr><td>WAN 模式</td><td>' + esc(setupData.wan_mode) + '</td></tr>' +
      '</tbody></table>' +
      '<div class="highlight-box warn" style="margin-top:10px">点击「完成安装」后将立即应用网络配置。' +
      '如果 LAN 地址发生变化，请用新地址 <b class="mono">http://' + esc(setupData.lan_ip) + '</b> 访问管理页。</div>';
  }
}

$("#setup-form").addEventListener("submit", async function (e) {
  e.preventDefault();
  var err = $("#setup-error");
  err.classList.add("hidden");
  function fail(msg) { err.textContent = msg; err.classList.remove("hidden"); }

  if (setupStep === 1) {
    setupData.password = $("#st-pw1").value;
    setupData.password2 = $("#st-pw2").value;
    if (setupData.password.length < 6) return fail("密码至少需要 6 位");
    if (setupData.password !== setupData.password2) return fail("两次输入的密码不一致");
  } else if (setupStep === 2) {
    setupData.wan_interface = $("#st-wan").value;
    if (!setupData.lan_interface) return fail("请先点击选择 LAN 内网网卡");
    if (setupData.wan_interface === setupData.lan_interface) return fail("WAN 与 LAN 不能是同一块网卡");
  } else if (setupStep === 3) {
    setupData.lan_ip = $("#st-lan-ip").value.trim();
    setupData.lan_netmask = $("#st-mask").value.trim();
    setupData.send_gateway = $("#st-gw").checked;
    setupData.gateway = $("#st-gw-addr").value.trim();
    setupData.wan_mode = $("#st-wanmode").value;
    var ipRe = /^\d{1,3}(\.\d{1,3}){3}$/;
    if (!ipRe.test(setupData.lan_ip)) return fail("LAN 地址格式不正确");
    if (!ipRe.test(setupData.lan_netmask)) return fail("子网掩码格式不正确");
    if (setupData.send_gateway && setupData.gateway && !ipRe.test(setupData.gateway)) {
      return fail("下发的网关地址格式不正确");
    }
  }

  if (setupStep < 4) { setupStep += 1; renderSetup(); return; }

  var btn = e.submitter; if (btn) btn.disabled = true;
  try {
    var r = await api("/api/setup", { body: {
      admin_password: setupData.password,
      wan_interface: setupData.wan_interface,
      lan_interface: setupData.lan_interface,
      lan_ip: setupData.lan_ip,
      lan_netmask: setupData.lan_netmask,
      send_gateway: setupData.send_gateway,
      dhcp_gateway: setupData.gateway,
      wan_mode: setupData.wan_mode
    } });
    var lines = (r.errors || []).map(function (x) { return "⚠ " + x; })
      .concat((r.applied || []).map(function (x) { return "✓ " + x; }))
      .concat((r.warnings || []).map(function (x) { return "! " + x; }));
    toast((lines.length ? lines.join("；") : r.message || "安装完成"), lines.some(function (x) { return x[0] === "⚠"; }) ? "warn" : "ok", 8000);
    location.reload();
  } catch (ex) {
    fail(ex.message);
    if (btn) btn.disabled = false;
  }
});
$("#setup-prev").addEventListener("click", function () {
  if (setupStep > 1) { setupStep -= 1; renderSetup(); }
});

/* ================================================================
 * 设备操作（改名 / 唤醒）——事件委托
 * ================================================================ */
document.addEventListener("click", async function (e) {
  var act = e.target.closest("[data-act]");
  if (!act) return;
  var tr = act.closest("tr");
  if (!tr) return;
  var mac = tr.dataset.mac, ip = tr.dataset.ip;
  if (act.dataset.act === "rename") {
    var name = promptModal("修改设备名称", "设备名称（留空则恢复自动识别）", tr.querySelector(".name-cell b").textContent, "例如：书房台式机");
    name = await name;
    if (name === null) return;
    try {
      var r = await api("/api/devices/alias", { body: { mac: mac, name: name } });
      toast(r.message, "ok");
      if (state.view === "devices") pollDevices();
      if (state.view === "traffic") pollTraffic();
    } catch (ex) { toast(ex.message, "err"); }
  } else if (act.dataset.act === "wake") {
    try {
      var r2 = await api("/api/devices/wake", { body: { mac: mac } });
      toast(r2.message, r2.ok ? "ok" : "err");
    } catch (ex) { toast(ex.message, "err"); }
  }
});

/* ---------- 启动 ---------- */
boot();
