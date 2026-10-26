# -*- coding: utf-8 -*-
"""DHCP 租约：列表、手动绑定/解绑、首次分配自动固定。"""
import copy
import ipaddress
import threading
import time

from . import config as config_mod
from .monitor import ip_sort_key


def _static_map(cfg):
    out = {}
    for sl in cfg.get("dhcp", {}).get("static_leases", []):
        mac = config_mod.mac_norm(sl.get("mac"))
        if mac:
            out[mac] = sl
    return out


def _pool_map(cfg):
    return {p.get("id"): p for p in (cfg.get("dhcp", {}).get("pools") or [])}


def list_leases(app, q="", status="all"):
    cfg = app.cfg
    snap = app.monitor.snapshot(1)
    devices = {d["ip"]: d for d in snap.get("devices", [])}
    static = _static_map(cfg)
    pools = _pool_map(cfg)
    default_sec = config_mod.lease_seconds(cfg["dhcp"].get("lease_time"))
    now = int(time.time())
    q = (q or "").strip().lower()
    items = []
    for lease in app.backend.leases():
        mac = config_mod.mac_norm(lease.get("mac"))
        if not mac:
            continue
        ip = lease.get("ip", "")
        dev = devices.get(ip) or {}
        sl = static.get(mac)
        pool = pools.get(sl.get("pool")) if sl and sl.get("pool") else None
        lease_sec = default_sec
        if pool:
            lease_sec = config_mod.lease_seconds(pool.get("lease_time") or cfg["dhcp"].get("lease_time"))
        expiry = int(lease.get("expiry") or 0)
        allocated = (expiry - lease_sec) if expiry and lease_sec else None
        name = dev.get("name") or lease.get("hostname") or "未知设备"
        item = {
            "mac": mac,
            "ip": ip,
            "name": name,
            "hostname": lease.get("hostname") or "",
            "online": bool(dev.get("online")),
            "allocated": allocated,
            "expiry": expiry,
            "bound": bool(sl),
            "auto": bool(sl and sl.get("auto")),
            "pool": (sl or {}).get("pool") or "",
            "pool_name": (pool or {}).get("name") or "默认池",
            "vendor": dev.get("vendor", ""),
            "kind": dev.get("kind", "device"),
            "lease_seconds": lease_sec,
            "expiring": bool(expiry and 0 < expiry - now <= 86400),
        }
        if q and q not in item["name"].lower() and q not in ip.lower() and q not in mac.lower():
            continue
        if status == "online" and not item["online"]:
            continue
        if status == "offline" and item["online"]:
            continue
        if status == "bound" and not item["bound"]:
            continue
        if status == "unbound" and item["bound"]:
            continue
        if status == "expiring" and not item["expiring"]:
            continue
        items.append(item)
    items.sort(key=lambda x: ip_sort_key(x["ip"]))
    return {
        "leases": items,
        "total": len(items),
        "bound": sum(1 for x in items if x["bound"]),
        "online": sum(1 for x in items if x["online"]),
        "now": now,
    }


def bind_lease(app, mac, ip, name="", auto=False):
    mac = config_mod.mac_norm(mac)
    if not mac or not config_mod.is_ipv4(ip):
        return False, "MAC 或 IP 地址无效"
    if not config_mod.in_lan(app.cfg, ip):
        return False, "IP 不在 LAN 网段内"
    new = copy.deepcopy(app.cfg)
    leases = [sl for sl in new["dhcp"]["static_leases"]
              if config_mod.mac_norm(sl.get("mac")) != mac
              and sl.get("ip") != ip]
    leases.append({"mac": mac, "ip": ip, "name": (name or "").strip()[:32],
                   "pool": "", "auto": bool(auto)})
    new["dhcp"]["static_leases"] = leases
    errors, warnings, _applied = app.update_config(new)
    if errors:
        return False, "；".join(errors)
    return True, "已绑定 %s → %s" % (mac, ip)


def unbind_lease(app, mac):
    mac = config_mod.mac_norm(mac)
    if not mac:
        return False, "MAC 地址无效"
    new = copy.deepcopy(app.cfg)
    before = len(new["dhcp"]["static_leases"])
    new["dhcp"]["static_leases"] = [
        sl for sl in new["dhcp"]["static_leases"]
        if config_mod.mac_norm(sl.get("mac")) != mac]
    if len(new["dhcp"]["static_leases"]) == before:
        return False, "该设备没有绑定记录"
    errors, _warnings, _applied = app.update_config(new)
    if errors:
        return False, "；".join(errors)
    return True, "已解除绑定"


class LeaseBinder(threading.Thread):
    """首次分配自动固定 MAC↔IP。"""

    def __init__(self, app):
        super().__init__(daemon=True, name="easyrouter-lease-binder")
        self.app = app
        self._stop = threading.Event()

    def run(self):
        # 启动后稍等，避免和初始化冲突
        self._stop.wait(8)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                self.app.log.exception("自动绑定租约失败")
            self._stop.wait(15)

    def _tick(self):
        app = self.app
        if app.backend.name != "linux":
            return
        if not app.cfg.get("dhcp", {}).get("enabled") or \
                not app.cfg["dhcp"].get("auto_bind_first"):
            return
        new_cfg = copy.deepcopy(app.cfg)
        static = _static_map(new_cfg)
        used_ips = {sl.get("ip") for sl in new_cfg["dhcp"]["static_leases"]}
        added = []
        for lease in app.backend.leases():
            mac = config_mod.mac_norm(lease.get("mac"))
            if not mac or mac in static:
                continue
            ip = lease.get("ip", "")
            if not config_mod.is_ipv4(ip) or not config_mod.in_lan(new_cfg, ip):
                continue
            if ip in used_ips:
                continue
            new_cfg["dhcp"]["static_leases"].append({
                "mac": mac, "ip": ip,
                "name": (lease.get("hostname") or "")[:32],
                "pool": "", "auto": True,
            })
            static[mac] = new_cfg["dhcp"]["static_leases"][-1]
            used_ips.add(ip)
            added.append("%s→%s" % (mac, ip))
        if not added:
            return
        errors, _warnings, _applied = app.update_config(new_cfg)
        if errors:
            app.log.warning("自动绑定失败：%s", "；".join(errors))
        else:
            app.log.info("首次分配自动绑定：%s", "，".join(added))

    def stop(self):
        self._stop.set()
