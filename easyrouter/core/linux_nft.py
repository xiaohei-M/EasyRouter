# -*- coding: utf-8 -*-
"""nftables 编排：NAT/转发基础规则 + 每设备流量计数器（rx/tx）。"""
import ipaddress
import json
import re
import threading

from . import linux_util

TABLE_FAMILY = "inet"
TABLE_NAME = "easyrouter"

IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _safe_iface(name):
    return name if (name and IFACE_RE.match(name)) else ""


def _safe_ip(ip):
    return ip if (ip and IP_RE.match(ip)) else ""


class NftService:
    def __init__(self, log=None):
        self.log = log
        self.last_error = ""
        self._lock = threading.Lock()
        self.rule_count = 0

    def _info(self, msg):
        if self.log:
            self.log.info("[nftables] %s", msg)

    def _lan_ifs(self, cfg):
        """默认 LAN + 所有启用的 VLAN 地址池接口。"""
        ifs = []
        primary = _safe_iface(cfg["network"]["lan"].get("interface", ""))
        if primary:
            ifs.append(primary)
        for p in (cfg.get("dhcp", {}).get("pools") or []):
            if not p.get("enabled", True) or (p.get("type") or "tagged") != "vlan":
                continue
            iface = p.get("interface")
            if not iface and p.get("vlan_id"):
                parent = p.get("parent") or primary
                iface = "%s.%s" % (parent, p["vlan_id"]) if parent else ""
            iface = _safe_iface(iface)
            if iface and iface not in ifs:
                ifs.append(iface)
        return ifs

    @staticmethod
    def _iface_set(ifs):
        return "{ " + ", ".join('"%s"' % i for i in ifs) + " }"

    # ---------------- 基础规则集 ----------------
    def base_ruleset(self, cfg):
        lan_ifs = self._lan_ifs(cfg)
        if not lan_ifs:
            raise ValueError("LAN 网卡名称无效")
        lan_set = self._iface_set(lan_ifs)
        return (
            'add table inet easyrouter\n'
            'flush table inet easyrouter\n'
            'table inet easyrouter {\n'
            '  chain forward {\n'
            '    type filter hook forward priority filter; policy drop;\n'
            '    jump acct\n'
            '    ct state established,related accept\n'
            '    ct state invalid drop\n'
            '    iifname %s oifname != %s accept\n'
            '    iifname != %s oifname %s ct state established,related accept\n'
            '  }\n'
            '  chain postrouting {\n'
            '    type nat hook postrouting priority srcnat; policy accept;\n'
            '    oifname != %s masquerade\n'
            '  }\n'
            '  chain acct {\n'
            '  }\n'
            '}\n' % (lan_set, lan_set, lan_set, lan_set, lan_set)
        )

    def apply_base(self, cfg):
        """应用（重建）基础规则集。返回 (ok, error)。"""
        with self._lock:
            try:
                ruleset = self.base_ruleset(cfg)
            except ValueError as e:
                return False, str(e)
            rc, _, err = linux_util.run(
                ["nft", "-f", "-"], timeout=30, input=ruleset)
            if rc != 0:
                self.last_error = err.strip() or "nft 执行失败"
                self._info("规则集应用失败: %s" % self.last_error)
                return False, self.last_error
            self.last_error = ""
            self._info("nftables 基础规则已应用")
            return True, ""

    # ---------------- 设备计数器规则 ----------------
    def _iface_for_ip(self, cfg, ip):
        """根据设备 IP 找到它所属的 LAN/VLAN 接口。"""
        lan = cfg["network"]["lan"]
        primary = _safe_iface(lan.get("interface", ""))
        try:
            addr = ipaddress.IPv4Address(ip)
            if addr in ipaddress.IPv4Network(
                    "%s/%s" % (lan["ip"], lan["netmask"]), strict=False):
                return primary
            for p in (cfg.get("dhcp", {}).get("pools") or []):
                if not p.get("enabled", True) or (p.get("type") or "tagged") != "vlan":
                    continue
                net = ipaddress.IPv4Network(
                    "%s/%s" % (p["ip"], p.get("netmask") or "255.255.255.0"), strict=False)
                if addr in net:
                    if p.get("interface"):
                        return _safe_iface(p["interface"])
                    if p.get("vlan_id"):
                        parent = p.get("parent") or primary
                        return _safe_iface("%s.%s" % (parent, p["vlan_id"]))
        except Exception:
            pass
        return primary

    def _rule_args(self, cfg, ip, direction):
        lan_if = _safe_iface(self._iface_for_ip(cfg, ip))
        ip = _safe_ip(ip)
        if not lan_if or not ip:
            return None
        base = ["nft", "add", "rule", TABLE_FAMILY, TABLE_NAME, "acct"]
        if direction == "tx":
            return base + ["iifname", lan_if, "oifname", "!=", lan_if,
                           "ip", "saddr", ip, "counter", "comment", "dev:%s:tx" % ip]
        return base + ["iifname", "!=", lan_if, "oifname", lan_if,
                       "ip", "daddr", ip, "counter", "comment", "dev:%s:rx" % ip]

    def add_device_rule(self, cfg, ip, direction):
        args = self._rule_args(cfg, ip, direction)
        if not args:
            return False
        rc, _, _ = linux_util.run(args, timeout=15)
        return rc == 0

    def delete_rule(self, handle):
        rc, _, _ = linux_util.run(
            ["nft", "delete", "rule", TABLE_FAMILY, TABLE_NAME, "acct", "handle", str(handle)],
            timeout=15)
        return rc == 0

    def read_counters(self):
        """读取 acct 链中所有计数器。

        返回 (counters, handles)：
          counters: {(ip, dir): bytes}
          handles:  {(ip, dir): handle}
        """
        counters, handles = {}, {}
        rc, stdout, _ = linux_util.run(
            ["nft", "-j", "list", "table", TABLE_FAMILY, TABLE_NAME], timeout=30)
        if rc != 0:
            return counters, handles
        try:
            data = json.loads(stdout)
        except ValueError:
            return counters, handles
        for obj in data.get("nftables", []):
            table = obj.get("table", {})
            if table.get("name") != TABLE_NAME:
                continue
            chain = table.get("chain")
            if chain and chain.get("name") == "acct":
                self._parse_chain(chain, counters, handles)
        return counters, handles

    @staticmethod
    def _parse_chain(chain, counters, handles):
        for rule in chain.get("rule", []) or []:
            handle = rule.get("handle")
            if not handle:
                continue
            comment, cbytes = None, None
            for expr in rule.get("expr", []):
                if "comment" in expr:
                    comment = expr["comment"]
                elif "counter" in expr:
                    cbytes = (expr["counter"] or {}).get("bytes", 0)
            if not comment or not comment.startswith("dev:"):
                continue
            parts = comment.split(":")
            if len(parts) != 3:
                continue
            ip, direction = parts[1], parts[2]
            if direction not in ("rx", "tx"):
                continue
            counters[(ip, direction)] = cbytes or 0
            handles[(ip, direction)] = handle

    def ensure_device_rules(self, cfg, ips):
        """为所有设备 IP 补齐 rx/tx 计数规则。返回新增条数。"""
        counters, _ = self.read_counters()
        added = 0
        for ip in ips:
            ip = _safe_ip(ip)
            if not ip:
                continue
            for direction in ("rx", "tx"):
                if (ip, direction) not in counters:
                    if self.add_device_rule(cfg, ip, direction):
                        added += 1
        return added

    def remove_device_rules(self, ips):
        """删除指定 IP 的全部计数规则（设备清理时使用）。"""
        _, handles = self.read_counters()
        removed = 0
        for ip in ips:
            for direction in ("rx", "tx"):
                h = handles.get((ip, direction))
                if h and self.delete_rule(h):
                    removed += 1
        return removed

    def status(self):
        rc, _, _ = linux_util.run(
            ["nft", "list", "table", TABLE_FAMILY, TABLE_NAME], timeout=15)
        ok = rc == 0
        if not ok and self.last_error == "":
            self.last_error = "nftables 表不存在或无法读取"
        return {"ok": ok, "last_error": self.last_error,
                "rules": self._count_rules() if ok else 0}

    def _count_rules(self):
        rc, stdout, _ = linux_util.run(
            ["nft", "list", "table", TABLE_FAMILY, TABLE_NAME], timeout=15)
        if rc != 0:
            return 0
        return sum(1 for line in stdout.splitlines() if line.lstrip().startswith(("counter", "accept", "drop", "masquerade", "jump")))
