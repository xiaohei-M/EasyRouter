# -*- coding: utf-8 -*-
"""HTTP 服务：路由分发、静态资源、认证/CSRF 防护、统一 JSON 输出。"""
import http.server
import contextvars
import json
import mimetypes
import os
import re
import urllib.parse

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# 每个请求的上下文（token / 客户端 IP），供 API 层读取
_req_ctx = contextvars.ContextVar("easyrouter_request", default=None)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}

# 用于解析 "key=value; key2=value2" 形式的 Cookie
COOKIE_RE = re.compile(r"(?:^|;\s*)([^=;\s]+)=([^;]*)")


class Route:
    __slots__ = ("method", "pattern", "handler", "auth")

    def __init__(self, method, pattern, handler, auth):
        self.method = method
        self.pattern = pattern
        self.handler = handler
        self.auth = auth

    def match(self, path):
        m = re.fullmatch(self.pattern, path)
        if not m:
            return None
        return m.groupdict()


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler, auth=True):
        self.routes.append(Route(method, pattern, handler, auth))

    def match(self, method, path):
        for r in self.routes:
            if r.method != method:
                continue
            m = r.match(path)
            if m is not None:
                return r, m
        return None


class AppServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, addr, app):
        super().__init__(addr, Handler)
        self.app = app

    def handle_error(self, request, client_address):
        """静默客户端断连类异常，其余交给默认处理。"""
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "EasyRouter/1.0"
    protocol_version = "HTTP/1.1"

    # ---------------- 日志 ----------------
    def log_message(self, fmt, *args):
        self.server.app.log.debug("HTTP %s", fmt % args)

    # ---------------- 分发 ----------------
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        app = self.server.app
        token = _req_ctx.set({
            "token": self._cookie("easyrouter_session"),
            "ip": (self.client_address[0] if self.client_address else "unknown"),
        })
        try:
            return self._dispatch_inner(method)
        finally:
            _req_ctx.reset(token)

    def _dispatch_inner(self, method):
        app = self.server.app
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if method == "GET" and self._is_static(path):
                return self._serve_static(path)

            matched = app.router.match(method, path)
            if matched is None:
                return self._json(404, {"ok": False, "error": "接口不存在：%s %s" % (method, path)})
            route, params = matched

            if method in ("POST", "PUT", "DELETE") and not self._csrf_ok():
                return self._json(403, {"ok": False, "error": "请求来源校验失败，已拒绝"})

            if route.auth and not self._authed():
                return self._json(401, {"ok": False, "error": "未登录或会话已过期", "code": 401})

            body = None
            if method in ("POST", "PUT"):
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                raw = self.rfile.read(length) if length else b""
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        return self._json(400, {"ok": False, "error": "请求体不是合法的 JSON"})

            result = route.handler(app, params, body, parsed.query)
            status = 200
            if isinstance(result, dict):
                status = result.pop("_status", 200)
            if path in ("/api/status", "/api/login", "/api/clientlog", "/api/setup"):
                app.log.info("[API] %s %s -> %s", method, path, status)
            return self._json(status, result)
        except (ConnectionError, TimeoutError):
            return
        except BrokenPipeError:
            return
        except Exception:
            app.log.exception("处理请求 %s %s 出错", method, self.path)
            try:
                self._json(500, {"ok": False, "error": "服务器内部错误"})
            except Exception:
                pass

    # ---------------- 静态资源 ----------------
    @staticmethod
    def _is_static(path):
        if path == "/":
            return True
        return path.startswith(("/css/", "/js/", "/favicon", "/img/"))

    def _serve_static(self, path):
        rel = "index.html" if path == "/" else path.lstrip("/")
        root = os.path.realpath(WEB_DIR)
        full = os.path.realpath(os.path.join(root, rel))
        if full != root and not full.startswith(root + os.sep):
            return self._json(404, {"ok": False, "error": "资源不存在"})
        if not os.path.isfile(full):
            return self._json(404, {"ok": False, "error": "资源不存在"})
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return self._json(404, {"ok": False, "error": "资源读取失败"})
        cache = "no-cache" if ext in (".html", ".js", ".css") else "public, max-age=3600"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        if ext == ".html":
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        for k, v in SAFE_HEADERS.items():
            if k != "Cache-Control":
                self.send_header(k, v)
        self.end_headers()
        self.server.app.log.info("[静态] %s -> %d 字节 (%s)", rel, len(data),
                                 self.client_address[0] if self.client_address else "?")
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionError):
            pass

    # ---------------- 安全 ----------------
    def _authed(self):
        token = self._cookie("easyrouter_session")
        return bool(token) and self.server.app.auth.valid(token)

    def _cookie(self, name):
        header = self.headers.get("Cookie") or ""
        for k, v in COOKIE_RE.findall(header):
            if k == name:
                return urllib.parse.unquote(v)
        return ""

    def _same_origin(self, value):
        try:
            return urllib.parse.urlsplit(value).netloc == (self.headers.get("Host") or "")
        except ValueError:
            return False

    def _csrf_ok(self):
        origin = self.headers.get("Origin")
        if origin:
            return self._same_origin(origin)
        referer = self.headers.get("Referer")
        if referer:
            return self._same_origin(referer)
        return True

    # ---------------- 输出 ----------------
    def _json(self, status, obj):
        cookies = {}
        if isinstance(obj, dict):
            cookies = obj.pop("_cookies", {}) or {}
        try:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        except TypeError:
            data = json.dumps({"ok": False, "error": "内部序列化错误"}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in SAFE_HEADERS.items():
            self.send_header(k, v)
        for name, (value, attrs) in cookies.items():
            parts = ["%s=%s" % (name, urllib.parse.quote(value))]
            for ak, av in attrs.items():
                parts.append("%s=%s" % (ak, av) if av else ak)
            self.send_header("Set-Cookie", "; ".join(parts))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionError):
            pass


def set_session_cookie(result, token, ttl_sec):
    """把会话令牌放进应答的 Set-Cookie。"""
    result["_cookies"] = {
        "easyrouter_session": (token, {"Max-Age": str(ttl_sec), "Path": "/", "HttpOnly": "",
                                       "SameSite": "Lax"})
    }
