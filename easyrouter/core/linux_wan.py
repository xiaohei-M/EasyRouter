# -*- coding: utf-8 -*-
"""网络管理：LAN 静态地址、WAN 四种模式（不管理/DHCP/静态/PPPoE）、运行状态。"""
import ipaddress
import json
import os
import subprocess
import threading
import time

from . import linux_util
from ..config import is_ipv4

RUN_DIR = "/var/run/easyrouter"
CONF_DIR = "/etc/easyrouter"


def _mask_prefix(mask):
    try:
        return ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen
    except Exception:
        return 24


class NetworkManager:
    def __init__(self, log=None):
        self.log = log
        self.procs = {}          # 名称 -> Popen
        self.mode = "none"
        self._lock = threading.Lock()

    def _info(self, msg):
        if self.log:
            self.log.info("[network] %s", msg)

    # ---------------- LAN ----------------
    def apply_lan(self, cfg):
        """设置 LAN 静态地址并启用网卡。返回错误列表。"""
        errors = []
        lan = cfg["network"]["lan"]
        iface = (lan.get("interface") or "").strip()
        if not iface:
            return ["LAN 网卡未配置"]
        if not os.path.isdir("/sys/class/net/" + iface):
            return ["LAN 网卡 %s 不存在" % iface]
        prefix = _mask_prefix(lan["netmask"])
        addr = "%s/%d" % (lan["ip"], prefix)
        linux_util.run(["ip", "link", "set", "dev", iface, "up"], timeout=10)
        linux_util.run(["ip", "addr", "flush", "dev", iface], timeout=10)
        rc, _, err = linux_util.run(
            ["ip", "addr", "add", addr, "dev", iface], timeout=10)
        if rc != 0:
            errors.append("设置 LAN 地址 %s 失败：%s" % (addr, err.strip()))
        else:
            self._info("LAN %s 已设置为 %s" % (iface, addr))
        return errors

    # ---------------- VLAN 地址池 ----------------
    def apply_vlans(self, cfg):
        """为 VLAN 地址池创建子接口并配置网关地址。返回错误列表。"""
        errors = []
        primary = cfg["network"]["lan"].get("interface") or ""
        for p in (cfg.get("dhcp", {}).get("pools") or []):
            if not p.get("enabled", True) or (p.get("type") or "tagged") != "vlan":
                continue
            iface = p.get("interface") or (
                "%s.%s" % (p.get("parent") or primary, p["vlan_id"]) if p.get("vlan_id") else "")
            if not iface:
                continue
            parent = p.get("parent") or primary
            if p.get("vlan_id"):
                if not os.path.isdir("/sys/class/net/" + iface):
                    rc, _, err = linux_util.run(
                        ["ip", "link", "add", "link", parent, "name", iface,
                         "type", "vlan", "id", str(p["vlan_id"])], timeout=10)
                    if rc != 0:
                        errors.append("创建 VLAN 接口 %s 失败：%s" % (iface, err.strip()))
                        continue
                linux_util.run(["ip", "link", "set", "dev", iface, "up"], timeout=10)
            if not is_ipv4(p.get("ip")):
                errors.append("VLAN 地址池 %s 未配置网关地址" % (p.get("name") or iface))
                continue
            prefix = _mask_prefix(p.get("netmask") or "255.255.255.0")
            addr = "%s/%d" % (p["ip"], prefix)
            rc, _, err = linux_util.run(
                ["ip", "addr", "replace", addr, "dev", iface], timeout=10)
            if rc != 0:
                errors.append("设置 VLAN 地址 %s 失败：%s" % (addr, err.strip()))
            else:
                self._info("VLAN %s 已设置为 %s" % (iface, addr))
            linux_util.run(["ip", "link", "set", "dev", iface, "up"], timeout=10)
        return errors

    # ---------------- WAN ----------------
    def _stop_all(self):
        for name, p in list(self.procs.items()):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
            self.procs.pop(name, None)

    def _spawn(self, name, args):
        try:
            p = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return None
        self.procs[name] = p
        return p

    def apply_wan(self, cfg):
        """按模式应用 WAN 配置。返回 (错误列表, 说明列表)。"""
        errors, applied = [], []
        wan = cfg["network"]["wan"]
        iface = (wan.get("interface") or "").strip()
        mode = wan.get("mode", "none")
        with self._lock:
            self._stop_all()
            self.mode = mode

            if mode == "none":
                applied.append("WAN 采用“不管理”模式：保留系统现有拨号/地址配置")
                return errors, applied

            if not iface or not os.path.isdir("/sys/class/net/" + iface):
                errors.append("WAN 网卡 %s 不存在" % (iface or "（未选择）"))
                return errors, applied

            linux_util.run(["ip", "link", "set", "dev", iface, "up"], timeout=10)

            if mode == "dhcp":
                rc, _, _ = linux_util.run(["which", "dhclient"], timeout=10)
                if rc != 0:
                    errors.append("未安装 dhclient，请执行：apt install isc-dhcp-client")
                    return errors, applied
                linux_util.run(["ip", "addr", "flush", "dev", iface], timeout=10)
                p = self._spawn("dhclient", [
                    "dhclient", "-4", "-v", "-pf",
                    os.path.join(RUN_DIR, "wan-dhclient.pid"), iface])
                if p is None:
                    errors.append("dhclient 启动失败")
                else:
                    applied.append("WAN 已切换为 DHCP 自动获取（%s）" % iface)
                    self._info("WAN DHCP 客户端已启动: %s" % iface)

            elif mode == "static":
                linux_util.run(["ip", "addr", "flush", "dev", iface], timeout=10)
                netmask = wan.get("netmask") or "255.255.255.0"
                prefix = _mask_prefix(netmask)
                addr = "%s/%d" % (wan["ip"], prefix)
                rc1, _, e1 = linux_util.run(["ip", "addr", "add", addr, "dev", iface], timeout=10)
                rc2, _, e2 = linux_util.run(["ip", "route", "replace", "default", "via",
                                             wan["gateway"], "dev", iface], timeout=10)
                if rc1 != 0:
                    errors.append("设置 WAN 静态地址失败：%s" % e1.strip())
                if rc2 != 0:
                    errors.append("设置 WAN 默认路由失败：%s" % e2.strip())
                if rc1 == 0 and rc2 == 0:
                    applied.append("WAN 静态地址已生效：%s 网关 %s" % (addr, wan["gateway"]))

            elif mode == "pppoe":
                opts = self._build_pppoe_conf(cfg)
                p = self._spawn("pppd", ["pppd", "file", opts])
                if p is None:
                    errors.append("未安装 pppd，请执行：apt install ppp")
                else:
                    applied.append("PPPoE 拨号已启动（%s），拨号成功后出口网卡为 ppp0" % iface)
                    self._info("PPPoE 拨号已启动: %s" % iface)
        return errors, applied

    def _build_pppoe_conf(self, cfg):
        wan = cfg["network"]["wan"]
        os.makedirs(CONF_DIR, exist_ok=True)
        path = os.path.join(CONF_DIR, "pppoe.conf")
        content = (
            "# 由 易路由 EasyRouter 自动生成\n"
            "plugin rp-pppoe.so\n"
            "%s\n"
            "user \"%s\"\n"
            "password \"%s\"\n"
            "noipdefault\n"
            "defaultroute\n"
            "usepeerdns\n"
            "persist\n"
            "maxfail 0\n"
            "holdoff 10\n"
            "lcp-echo-interval 20\n"
            "lcp-echo-failure 3\n"
        ) % (wan.get("interface", ""), wan.get("pppoe_user", ""), wan.get("pppoe_password", ""))
        linux_util.write_file_atomic(path, content, 0o600)
        return path

    def stop(self):
        with self._lock:
            self._stop_all()

    # ---------------- 状态 ----------------
    def _iface_addrs(self, iface):
        rc, stdout, _ = linux_util.run(["ip", "-j", "addr", "show", "dev", iface], timeout=10)
        if rc != 0:
            return []
        try:
            data = json.loads(stdout)
        except ValueError:
            return []
        out = []
        for obj in data:
            for a in obj.get("addr_info", []):
                if a.get("family") == "inet":
                    out.append("%s/%s" % (a["local"], a["prefixlen"]))
        return out

    def _default_gateway(self, iface):
        rc, stdout, _ = linux_util.run(["ip", "-4", "route", "show", "default"], timeout=10)
        if rc != 0:
            return ""
        for line in stdout.splitlines():
            parts = line.split()
            if "via" in parts:
                i = parts.index("via")
                if len(parts) > i + 1:
                    dev_idx = parts.index("dev") if "dev" in parts else -1
                    dev = parts[dev_idx + 1] if dev_idx >= 0 and len(parts) > dev_idx + 1 else ""
                    if not iface or dev == iface:
                        return parts[i + 1]
        return ""

    def wan_status(self, cfg):
        wan = cfg["network"]["wan"]
        iface = wan.get("interface", "") or ""
        mode = self.mode or wan.get("mode", "none")
        effective = iface
        if mode == "pppoe" and os.path.isdir("/sys/class/net/ppp0"):
            effective = "ppp0"
        addrs = self._iface_addrs(effective) if effective else []
        ip = addrs[0].split("/")[0] if addrs else ""
        gateway = self._default_gateway(effective) if effective else ""

        p = self.procs.get("dhclient") or self.procs.get("pppd")
        alive = bool(p and p.poll() is None)
        if mode == "none":
            state = "由系统管理"
        elif mode == "dhcp":
            state = "已获取地址" if ip else ("正在获取地址…" if alive else "获取失败（客户端未运行）")
        elif mode == "static":
            state = "静态地址已生效" if ip else "静态地址未生效"
        elif mode == "pppoe":
            state = "拨号成功" if effective == "ppp0" else ("正在拨号…" if alive else "拨号失败")
        else:
            state = "未知"
        dns = []
        for line in linux_util.read_file("/etc/resolv.conf").splitlines():
            if line.startswith("nameserver"):
                dns.append(line.split()[1])
        return {"mode": mode, "state": state, "ip": ip, "gateway": gateway,
                "dns": dns[:4], "interface": effective or iface,
                "running": alive}
