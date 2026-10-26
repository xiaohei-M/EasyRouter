# -*- coding: utf-8 -*-
"""应用升级接口冒烟测试（demo）。"""
import base64
import io
import json
import urllib.error
import urllib.request
import http.cookiejar
import zipfile

BASE = "http://127.0.0.1:8080"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, data=None, expect_error=False):
    req = urllib.request.Request(
        BASE + path,
        data=None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="GET" if data is None else "POST")
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        if expect_error:
            return e.code, body
        raise


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


print("login:", call("/api/login", {"password": "admin123"})[1]["ok"])
st = call("/api/system/upgrade")[1]
print("status:", st["current_version"], "demo=", st["demo"], "supported=", st["supported"])

data = make_zip({
    "VERSION": "1.1.0\n",
    "easyrouter/__init__.py": 'APP_NAME = "test"\nVERSION = "1.1.0"\n',
})
b64 = base64.b64encode(data).decode()
status, r = call("/api/system/upgrade", {"filename": "test.zip", "data": b64})
print("install:", status, r["ok"], r["version"], r["message"])

bad = base64.b64encode(b"not a zip").decode()
status, r = call("/api/system/upgrade", {"filename": "bad.zip", "data": bad}, expect_error=True)
print("bad zip:", status, r.get("error"))

evil = make_zip({
    "VERSION": "1.1.0",
    "easyrouter/__init__.py": "VERSION='1.1.0'",
    "../evil.txt": "x",
})
status, r = call("/api/system/upgrade", {"filename": "evil.zip",
                                         "data": base64.b64encode(evil).decode()},
                 expect_error=True)
print("path traversal:", status, r.get("error"))
