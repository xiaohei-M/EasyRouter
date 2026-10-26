# -*- coding: utf-8 -*-
"""多地址池 API 冒烟测试（demo，运行于 8080）。"""
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
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


print("login:", call("/api/login", {"password": "admin123"})["ok"])
pools = [
    {"id": "p-office", "name": "办公网", "type": "tagged", "enabled": True,
     "start": "192.168.1.150", "end": "192.168.1.199", "gateway": "192.168.10.1",
     "dns_servers": ["223.5.5.5"], "lease_time": "2h"},
    {"id": "p-guest", "name": "访客 VLAN", "type": "vlan", "enabled": True,
     "vlan_id": 20, "parent": "lan0", "ip": "192.168.20.1",
     "netmask": "255.255.255.0", "start": "192.168.20.100",
     "end": "192.168.20.199", "lease_time": "1h"},
]
leases = [
    {"mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.160", "name": "办公PC", "pool": "p-office"},
    {"mac": "AA:BB:CC:DD:EE:02", "ip": "192.168.20.110", "name": "访客PC", "pool": "p-guest"},
]
r = call("/api/settings", {"dhcp": {"pools": pools, "static_leases": leases}})
print("save pools:", r["ok"], r.get("applied"))
cfg = call("/api/settings")["config"]
print("pools now:", [(p["name"], p["type"], p.get("vlan_id")) for p in cfg["dhcp"]["pools"]])
print("leases now:", [(x["name"], x["pool"]) for x in cfg["dhcp"]["static_leases"]])
# 恢复
call("/api/settings", {"dhcp": {"pools": [], "static_leases": []}})
print("restored:", call("/api/settings")["config"]["dhcp"]["pools"])
