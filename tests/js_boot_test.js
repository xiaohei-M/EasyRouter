/* 启动流程回归测试：使用 index.html 的真实 id 集合模拟浏览器 DOM，
   验证“已登录”情况下主界面能正确显示（防止 #screen-app 这类空引用回归）。 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync("easyrouter/web/index.html", "utf8");
const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);
const hiddenIds = new Set();
for (const m of html.matchAll(/<(\w+)[^>]*id="([^"]+)"[^>]*class="([^"]*)"/g)) {
  if (m[3].split(/\s+/).includes("hidden")) hiddenIds.add(m[2]);
}

const nodes = new Map();
function makeEl(id) {
  const classes = new Set(hiddenIds.has(id) ? ["hidden"] : []);
  const el = {
    id, innerHTML: "", outerHTML: "", textContent: "", value: "", checked: false, disabled: false,
    dataset: {}, style: {}, children: [], parentElement: null, scrollTop: 0, scrollHeight: 0,
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      toggle: (c, force) => (force === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : force ? classes.add(c) : classes.delete(c)),
      contains: (c) => classes.has(c),
      _all: () => [...classes],
    },
    addEventListener: () => {}, removeEventListener: () => {},
    querySelector: () => makeEl("inner"), querySelectorAll: () => [],
    closest: () => null, appendChild: (c) => c, remove: () => {},
    focus: () => {}, select: () => {},
    getBoundingClientRect: () => ({ width: 800, height: 300, left: 0, top: 0 }),
    getContext: () => new Proxy({}, { get: () => () => ({}) }),
  };
  // 模拟浏览器：设置 innerHTML 时同步解析出带 id 的子节点
  let html = "";
  Object.defineProperty(el, "innerHTML", {
    get() { return html; },
    set(v) {
      html = String(v == null ? "" : v);
      const re = /id="([^"]+)"/g;
      let m;
      while ((m = re.exec(html))) {
        if (!nodes.has(m[1])) {
          const child = makeEl(m[1]);
          nodes.set(m[1], child);
        }
      }
    },
  });
  return el;
}
for (const id of ids) nodes.set(id, makeEl(id));

const navLinks = Array.from({ length: 6 }, () => makeEl("a"));
navLinks.forEach((a, i) => { a.dataset.view = ["overview", "devices", "traffic", "sessions", "settings", "system"][i]; });

const doc = makeEl("document");
doc.hidden = false;
doc.body = makeEl("body");
doc.getElementById = (id) => nodes.get(id) || null;
doc.querySelector = (sel) => {
  if (sel.startsWith("#")) return nodes.get(sel.slice(1)) || null;
  return makeEl("el");
};
doc.querySelectorAll = (sel) => {
  if (sel === "#nav a") return navLinks;
  if (sel === ".screen") return [...nodes.values()].filter((n) => n.id.startsWith("screen-"));
  if (sel === ".view") return [...nodes.values()].filter((n) => n.id.startsWith("view-"));
  return [];
};
doc.createElement = () => makeEl("div");

const windowObj = makeEl("window");
windowObj.document = doc;
windowObj.devicePixelRatio = 1;
windowObj.addEventListener = () => {};

const errors = [];
const sandbox = {
  window: windowObj, document: doc, console,
  fetch: async (url) => {
    const u = String(url);
    if (u.indexOf("/api/gateways") >= 0) {
      return {
        status: 200,
        json: async () => ({
          ok: true,
          gateways: [{
            id: "g1", name: "电信测试", ip: "192.168.10.1", method: "demo",
            result: { ok: true, sessions: 123, hosts: 7, ts: Math.floor(Date.now() / 1000), error: "", elapsed_ms: 5 },
          }],
          methods: { demo: "演示" }, running: false,
        }),
      };
    }
    if (u.indexOf("/api/interfaces") >= 0) {
      return {
        status: 200,
        json: async () => ({
          ok: true,
          interfaces: [
            { name: "lan0", mac: "00:11:22:33:44:55", addrs: ["192.168.1.1/24"], state: "up" },
            { name: "wan0", mac: "00:11:22:33:44:66", addrs: [], state: "up" },
          ],
        }),
      };
    }
    if (u.indexOf("/api/leases") >= 0) {
      return {
        status: 200,
        json: async () => ({
          ok: true, total: 1, bound: 1, online: 1, auto_bind: true,
          leases: [{
            mac: "3C:CD:57:0A:1F:01", ip: "192.168.1.100", name: "小米 14 Pro",
            hostname: "", online: true, allocated: 1790000000, expiry: 1820000000,
            bound: true, auto: true, pool: "", pool_name: "默认池", vendor: "小米",
            kind: "phone", lease_seconds: 31536000, expiring: false,
          }],
        }),
      };
    }
    if (u.indexOf("/api/settings") >= 0) {
      return {
        status: 200,
        json: async () => ({
          ok: true,
          backend: "demo",
          services: { dnsmasq: {}, nft: {}, wan: {} },
          config: {
            network: {
              wan: { interface: "wan0", mode: "none", ip: "", netmask: "255.255.255.0", gateway: "", pppoe_user: "", pppoe_password: "" },
              lan: { interface: "lan0", ip: "192.168.1.1", netmask: "255.255.255.0" },
            },
            dhcp: {
              enabled: true, start: "192.168.1.100", end: "192.168.1.149",
              lease_time: "12h", send_gateway: true, gateway: "", dns_servers: [],
              extra_options: "",
              static_leases: [{ mac: "AA:BB:CC:DD:EE:FF", ip: "192.168.1.160", name: "办公PC", pool: "p-office" }],
              pools: [
                { id: "p-office", name: "办公网", type: "tagged", enabled: true,
                  start: "192.168.1.150", end: "192.168.1.199", gateway: "192.168.10.1",
                  dns_servers: ["223.5.5.5"], lease_time: "2h" },
                { id: "p-guest", name: "访客 VLAN", type: "vlan", enabled: true,
                  vlan_id: 20, parent: "lan0", ip: "192.168.20.1",
                  netmask: "255.255.255.0", start: "192.168.20.100",
                  end: "192.168.20.199", gateway: "", lease_time: "1h" },
              ],
            },
            dns: { use_system: false, upstreams: ["223.5.5.5"], cache_size: 512 },
            monitor: { netbios: true, gateway_interval: 30 },
            firewall: { enabled: true },
            web: { lan_only: true },
          },
        }),
      };
    }
    return {
      status: 200,
      json: async () => ({ ok: true, setup_done: true, logged_in: true, backend: "demo", version: "1.0.0" }),
    };
  },
  setInterval: () => 0, clearInterval: () => {}, setTimeout: () => 0,
  Date, Math, JSON, Number, String, Array, Object, Boolean, RegExp, Promise,
  encodeURIComponent, decodeURIComponent, URLSearchParams,
  location: { reload: () => {} }, navigator: { userAgent: "node-test" },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const f of ["easyrouter/web/js/charts.js", "easyrouter/web/js/app.js"]) {
  try {
    vm.runInContext(fs.readFileSync(f, "utf8"), sandbox, { filename: f });
  } catch (e) {
    console.error("FAIL load", f, "\n", e.stack);
    process.exit(1);
  }
}

setTimeout(() => {
  const app = nodes.get("app");
  const login = nodes.get("screen-login");
  const okApp = app && !app.classList.contains("hidden");
  const loginHidden = login && login.classList.contains("hidden");
  console.log("app visible:", okApp, "| login hidden:", loginHidden, "| __ER_BOOTED__:", windowObj.__ER_BOOTED__);
  if (!okApp || !loginHidden) {
    console.error("FAIL: 登录后主界面未正确显示");
    process.exit(1);
  }
  if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
  console.log("PASS: 启动流程正常（已登录 → 主界面）");
  sandbox.switchView("gateways");
}, 150);

setTimeout(() => {
  const cards = nodes.get("gw-cards");
  const html = cards ? cards.innerHTML : "";
  const ok = html.indexOf("电信测试") >= 0 && html.indexOf("123") >= 0 && html.indexOf("7") >= 0;
  console.log("gateway cards rendered:", ok);
  if (!ok) {
    console.error("FAIL: 出口网关卡片未正确渲染\n", html.slice(0, 500));
    process.exit(1);
  }
  console.log("PASS: 出口网关页面渲染正常");
  sandbox.switchView("settings");
}, 350);

setTimeout(() => {
  const poolHtml = (nodes.get("s-pool-list") || {}).innerHTML || "";
  const staticHtml = (nodes.get("s-static-list") || {}).innerHTML || "";
  const ok = poolHtml.indexOf("办公网") >= 0 &&
    poolHtml.indexOf("访客 VLAN") >= 0 &&
    staticHtml.indexOf("p-office") >= 0;
  console.log("settings pools rendered:", ok);
  if (!ok) {
    console.error("FAIL: 设置页地址池未正确渲染");
    console.error("pool:", poolHtml.slice(0, 300));
    console.error("static:", staticHtml.slice(0, 300));
    process.exit(1);
  }
  console.log("PASS: 设置页地址池可配置入口正常（含 VLAN 池与静态绑定下拉）");
  sandbox.switchView("leases");
}, 750);

setTimeout(() => {
  const html = (nodes.get("lease-table") || {}).innerHTML || "";
  const ok = html.indexOf("小米 14 Pro") >= 0 && html.indexOf("192.168.1.100") >= 0 &&
    html.indexOf("3C:CD:57:0A:1F:01") >= 0;
  console.log("lease table rendered:", ok);
  if (!ok) {
    console.error("FAIL: DHCP 租约表格未正确渲染");
    process.exit(1);
  }
  console.log("PASS: DHCP 租约页面渲染正常");
}, 950);
