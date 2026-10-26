# -*- coding: utf-8 -*-
"""DHCP 租约 API 冒烟测试。"""
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
d = call("/api/leases")
print("leases:", d["total"], "bound:", d["bound"], "online:", d["online"], "auto:", d["auto_bind"])
print("first:", d["leases"][0]["name"], d["leases"][0]["ip"], d["leases"][0]["mac"],
      "bound=", d["leases"][0]["bound"], "alloc=", d["leases"][0]["allocated"])
target = next((x for x in d["leases"] if not x["bound"]), None)
if target:
    r = call("/api/leases/bind", {"mac": target["mac"], "ip": target["ip"], "name": target["name"]})
    print("bind:", r["ok"], r["message"])
    d2 = call("/api/leases")
    t2 = next(x for x in d2["leases"] if x["mac"] == target["mac"])
    print("after bind:", t2["bound"], "auto=", t2["auto"])
    r = call("/api/leases/unbind", {"mac": target["mac"]})
    print("unbind:", r["ok"], r["message"])
r = call("/api/settings", {"dhcp": {"lease_time": "31536000s", "auto_bind_first": True}})
print("settings save:", r["ok"])
c = call("/api/settings")["config"]["dhcp"]
print("lease_time:", c["lease_time"], "auto_bind:", c["auto_bind_first"])
call("/api/settings", {"dhcp": {"lease_time": "12h", "auto_bind_first": False}})
print("restored:", call("/api/settings")["config"]["dhcp"]["lease_time"])
