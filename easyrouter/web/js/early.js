/* 早期错误捕获与启动兜底（必须最先加载） */
(function () {
  "use strict";
  window.__ER_APP_LOADED__ = false;
  window.__ER_BOOTED__ = false;
  var sent = 0;

  function report(kind, message, stack) {
    if (sent >= 10) return;
    sent += 1;
    try {
      var payload = JSON.stringify({
        kind: kind,
        message: String(message || "").slice(0, 800),
        stack: String(stack || "").slice(0, 5000),
        url: location.href,
        ua: navigator.userAgent
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/clientlog", new Blob([payload], { type: "application/json" }));
      } else {
        fetch("/api/clientlog", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload
        });
      }
    } catch (e) { /* 忽略上报失败 */ }
  }

  window.__ER_REPORT__ = report;

  window.addEventListener("error", function (e) {
    var stack = (e.error && e.error.stack) || (e.filename + ":" + e.lineno + ":" + e.colno);
    report("error", e.message || "脚本或资源加载失败", stack);
  });

  window.addEventListener("unhandledrejection", function (e) {
    var r = e.reason || {};
    report("rejection", r.message || String(r), r.stack || "");
  });

  window.addEventListener("load", function () {
    setTimeout(function () {
      if (window.__ER_BOOTED__) return;
      var el = document.getElementById("boot-status");
      if (!el) return;
      el.classList.add("error");
      el.innerHTML =
        '<b>管理界面加载异常</b><br>' +
        '页面脚本未能正常启动（可能被浏览器扩展拦截，或缓存了旧版本）。<br>' +
        '请按 <kbd>Ctrl</kbd> + <kbd>F5</kbd> 强制刷新；若仍空白，请截图本提示。';
      report("boot-stuck", "boot-timeout: __ER_BOOTED__ 仍为 false", "");
    }, 4000);
  });
})();
