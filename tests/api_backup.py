# -*- coding: utf-8 -*-
"""备份/恢复 API 冒烟测试。"""
import json
import http.cookiejar
import urllib.request

BASE = "http://127.0.0.1:8080"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="GET" if data is None else "POST")
    with opener.open(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


print("login:", call("/api/login", {"password": "admin123"})["ok"])
b = call("/api/backup")["backup"]
print("backup:", b["format"], "version", b["version"], "aliases", len(b["aliases"]),
      "totals", len(b["totals"]), "lease", b["config"]["dhcp"]["lease_time"])
call("/api/settings", {"dhcp": {"lease_time": "1d", "auto_bind_first": True}})
print("modified:", call("/api/settings")["config"]["dhcp"]["lease_time"])
r = call("/api/backup/restore", {"backup": b})
print("restore:", r["ok"], r["message"])
cfg = call("/api/settings")["config"]["dhcp"]
print("after restore:", cfg["lease_time"], "auto_bind:", cfg["auto_bind_first"])
