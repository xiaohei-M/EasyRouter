# -*- coding: utf-8 -*-
"""设备信息来源：dnsmasq 租约文件、ARP/邻居表、网卡列表。"""
import json
import os

from . import linux_util


def read_leases(path="/var/lib/easyrouter/dnsmasq.leases"):
    """解析 dnsmasq 租约文件：expiry mac ip hostname clientid"""
    out = []
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                try:
                    expiry = int(parts[0])
                except ValueError:
                    expiry = 0
                hostname = parts[3] if parts[3] != "*" else ""
                out.append({"expiry": expiry, "mac": parts[1].upper(),
                            "ip": parts[2], "hostname": hostname})
    except OSError:
        pass
    return out


def read_neighbors(iface):
    """ip -4 neigh：返回 [{ip, mac, state}]。"""
    out = []
    if not iface:
        return out
    rc, stdout, _ = linux_util.run(["ip", "-4", "neigh", "show", "dev", iface], timeout=10)
    if rc != 0:
        return out
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 1:
            continue
        ip = parts[0]
        mac, state = "", ""
        for i, p in enumerate(parts):
            if p == "lladdr" and i + 1 < len(parts):
                mac = parts[i + 1].upper()
            if p in ("REACHABLE", "STALE", "DELAY", "PROBE", "FAILED", "INCOMPLETE", "NONE"):
                state = p
        out.append({"ip": ip, "mac": mac, "state": state or "STALE"})
    return out


def interface_list():
    """列出所有网卡：[{name, mac, addrs, state, is_loopback}]"""
    out = []
    net_dir = "/sys/class/net"
    if not os.path.isdir(net_dir):
        return out
    rc, stdout, _ = linux_util.run(["ip", "-j", "addr", "show"], timeout=10)
    addrs = {}
    if rc == 0:
        try:
            for it in json.loads(stdout):
                addrs[it.get("ifname", "")] = [
                    a.get("local", "") for a in it.get("addr_info", [])
                    if a.get("family") == "inet"
                ]
        except (ValueError, TypeError):
            pass
    for name in sorted(os.listdir(net_dir)):
        mac = linux_util.read_file(os.path.join(net_dir, name, "address"), "").strip().upper()
        state = linux_util.read_file(os.path.join(net_dir, name, "operstate"), "unknown").strip()
        flags = linux_util.read_file(os.path.join(net_dir, name, "flags"), "0x0").strip()
        is_loopback = bool(int(flags, 16) & 0x8)
        out.append({"name": name, "mac": mac, "addrs": addrs.get(name, []),
                    "state": state, "is_loopback": is_loopback})
    return out
