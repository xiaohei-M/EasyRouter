# -*- coding: utf-8 -*-
"""本地演示服务 API 冒烟测试（需要 demo 已在 8080 运行）。"""
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
        method="GET" if data is None else "POST",
    )
    with opener.open(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


print("login:", call("/api/login", {"password": "admin123"})["ok"])
g = call("/api/gateways")
print("gateways:", [x["name"] for x in g["gateways"]])
save = call("/api/gateways/save", {"gateways": [
    {"id": x["id"], "name": x["name"], "ip": x["ip"], "method": x["method"]}
    for x in g["gateways"]
]})
print("save:", save["ok"], save.get("count"))
g2 = call("/api/gateways")
print("gateways after save:", [x["name"] for x in g2["gateways"]])
det = call("/api/gateways/detect", {"ip": "127.0.0.1"})["detect"]
print("detect suggest:", det["suggest"], det["suggest_text"])
print("detect http:", det["http"].get("status"), det["http"].get("title"))
s = call("/api/settings", {"dhcp": {"send_gateway": True, "gateway": "192.168.10.1"}})
print("save custom gateway:", s["ok"])
print("custom gateway now:", call("/api/settings")["config"]["dhcp"].get("gateway"))
call("/api/settings", {"dhcp": {"gateway": ""}})
print("restored gateway:", repr(call("/api/settings")["config"]["dhcp"].get("gateway")))
