/* 前端脚本冒烟测试：用最小 DOM 桩执行 charts.js + app.js，捕获顶层运行时错误。 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function makeEl(tag) {
  const el = {
    tagName: tag || "div",
    id: "",
    className: "",
    innerHTML: "",
    outerHTML: "",
    textContent: "",
    value: "",
    checked: false,
    disabled: false,
    dataset: {},
    style: {},
    children: [],
    firstElementChild: null,
    parentElement: null,
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, force) { if (force === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); } else if (force) this._s.add(c); else this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return makeEl("div"); },
    querySelectorAll() { return []; },
    closest() { return null; },
    appendChild(c) { this.children.push(c); return c; },
    remove() {},
    focus() {},
    select() {},
    scrollTop: 0,
    scrollHeight: 0,
    getBoundingClientRect() { return { width: 800, height: 300, left: 0, top: 0 }; },
    getContext() { return new Proxy({}, { get: () => () => ({}) }); },
  };
  return el;
}

const doc = makeEl("document");
doc.createElement = () => makeEl("div");
doc.querySelector = () => makeEl("div");
doc.querySelectorAll = () => [];
doc.getElementById = () => null;
doc.hidden = false;
doc.body = makeEl("body");

const win = makeEl("window");
win.devicePixelRatio = 1;
win.document = doc;
win.addEventListener = () => {};

const errors = [];
const sandbox = {
  window: win,
  document: doc,
  console,
  fetch: async () => ({
    status: 200,
    json: async () => ({ ok: true, setup_done: true, logged_in: false, backend: "demo", version: "1.0.0" }),
  }),
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: (fn) => 0,
  Date,
  Math,
  JSON,
  Number,
  String,
  Array,
  Object,
  Boolean,
  RegExp,
  Promise,
  encodeURIComponent,
  decodeURIComponent,
  URLSearchParams,
  location: { reload() {} },
  alert: () => {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
process.on("uncaughtException", (e) => errors.push("uncaught: " + e.stack));
process.on("unhandledRejection", (e) => errors.push("unhandledRejection: " + (e && e.stack || e)));

function run(file) {
  const code = fs.readFileSync(file, "utf8");
  try {
    vm.runInContext(code, sandbox, { filename: file });
    console.log("OK  ", path.basename(file));
  } catch (e) {
    errors.push(path.basename(file) + ": " + e.stack);
    console.log("FAIL", path.basename(file), "\n", e.stack);
  }
}

run("easyrouter/web/js/charts.js");
run("easyrouter/web/js/app.js");

setTimeout(() => {
  if (errors.length) { console.log("\n=== ERRORS ==="); errors.forEach((e) => console.log(e)); process.exit(1); }
  console.log("no top-level errors");
}, 100);
