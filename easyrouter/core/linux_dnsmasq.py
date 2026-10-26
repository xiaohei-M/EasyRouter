# -*- coding: utf-8 -*-
"""dnsmasq 服务编排：生成配置、拉起/重启/看护子进程、读取租约。

关键需求实现：当 DHCP 配置为“不下发网关”时生成 `dhcp-option=3`（不带值），
dnsmasq 将完全不发送路由器(option 3)，客户端“默认网关”一栏即为空。
（参见 dnsmasq 官方示例配置与官方邮件列表的确认。）
"""
import ipaddress
import re
import subprocess
import threading
import time
from collections import deque

from . import linux_util
from .. import config as config_mod


class DnsmasqService:
    def __init__(self, log=None):
        self.log = log
        self.proc = None
        self.restarts = 0
        self.last_error = ""
        self.conf_path = ""
        self.lease_path = ""
        self.log_tail = deque(maxlen=400)
        self.dns_events = deque(maxlen=5000)
        self._dns_re = re.compile(r"query\[[A-Za-z0-9]+\]\s+(\S+)\s+from\s+(\S+)")
        self._lock = threading.Lock()
        self._stop = False
        self._watchdog = None
        self._stable_since = 0.0

    # ---------------- 配置生成 ----------------
    def build_conf(self, cfg):
        lan = cfg["network"]["lan"]
        wan = cfg["network"]["wan"]
        dhcp = cfg["dhcp"]
        dns = cfg["dns"]
        pools = [p for p in (dhcp.get("pools") or []) if p.get("enabled", True)]
        vlan_pools = [p for p in pools if (p.get("type") or "tagged") == "vlan"]

        lan_ifs = [lan["interface"]]
        listen_addrs = [lan["ip"]]
        for p in vlan_pools:
            iface = self._pool_iface(cfg, p)
            if iface and iface not in lan_ifs:
                lan_ifs.append(iface)
            if p.get("ip"):
                listen_addrs.append(p["ip"])

        L = ["# 由 易路由 EasyRouter 自动生成，请勿手工修改", "", "# ===== 监听接口 ====="]
        for iface in lan_ifs:
            if iface:
                L.append("interface=%s" % iface)
        L.append("bind-interfaces")
        for addr in listen_addrs:
            L.append("listen-address=%s" % addr)
        if wan.get("interface") and wan["interface"] not in lan_ifs:
            L.append("except-interface=%s" % wan["interface"])
            L.append("no-dhcp-interface=%s" % wan["interface"])

        L += [
            "",
            "# ===== DNS 行为 =====",
            "domain-needed",
            "bogus-priv",
            "cache-size=%d" % int(dns.get("cache_size", 512)),
            "",
            "# ===== 上游 DNS =====",
        ]
        if dns.get("use_system"):
            L.append("resolv-file=/etc/resolv.conf")
        else:
            L.append("no-resolv")
            for u in dns.get("upstreams", []):
                L.append("server=%s" % u)

        L += [
            "",
            "dhcp-leasefile=%s" % self.lease_path,
            "dhcp-authoritative",
            "log-queries=extra",
            "",
            "# ===== DHCP 服务器 =====",
        ]
        if dhcp.get("enabled"):
            lease = dhcp.get("lease_time", "12h")
            extra = ",%s" % lease if lease != "infinite" else ""
            # 默认地址池（未绑定标签的客户端）
            L.append("# 默认地址池：%s ~ %s" % (dhcp["start"], dhcp["end"]))
            L.append("dhcp-range=%s,%s,%s%s" % (
                dhcp["start"], dhcp["end"], lan["netmask"], extra))
            if dhcp.get("send_gateway", True):
                gw = (dhcp.get("gateway") or "").strip() or lan["ip"]
                L.append("# 下发网关（默认网关 = %s）" % gw)
                L.append("dhcp-option=option:router,%s" % gw)
            else:
                L.append("# 【不下发网关】客户端获得的“默认网关”一栏为空")
                L.append("dhcp-option=3")
            dns_servers = dhcp.get("dns_servers") or [lan["ip"]]
            for d in dns_servers:
                L.append("dhcp-option=option:dns-server,%s" % d)

            # 附加地址池
            for p in pools:
                pid = p.get("id") or ""
                ptype = (p.get("type") or "tagged").lower()
                if not pid:
                    continue
                pleases = p.get("lease_time") or lease
                pextra = ",%s" % pleases if pleases != "infinite" else ""
                if ptype == "vlan":
                    netmask = p.get("netmask") or "255.255.255.0"
                    router = (p.get("gateway") or "").strip() or p.get("ip") or ""
                    range_netmask = netmask
                else:
                    router = (p.get("gateway") or "").strip() or lan["ip"]
                    range_netmask = lan["netmask"]
                # 排除地址：从地址池中扣除后拆成多段 dhcp-range
                try:
                    if ptype == "vlan":
                        pool_net = ipaddress.IPv4Network(
                            "%s/%s" % (p["ip"], range_netmask), strict=False)
                    else:
                        pool_net = config_mod.lan_network(cfg)
                    excludes = config_mod.parse_excludes(p.get("exclude"), pool_net)
                except Exception:
                    excludes = []
                segs = config_mod.subtract_ip_ranges(
                    ipaddress.IPv4Address(p["start"]),
                    ipaddress.IPv4Address(p["end"]), excludes)
                L.append("")
                L.append("# 附加地址池：%s（%s）" % (p.get("name") or pid, ptype))
                if not segs:
                    L.append("# 该地址池所有地址均被排除")
                for seg_start, seg_end in segs:
                    L.append("dhcp-range=set:%s,%s,%s,%s%s" % (
                        pid, ipaddress.IPv4Address(seg_start),
                        ipaddress.IPv4Address(seg_end), range_netmask, pextra))
                if router:
                    L.append("dhcp-option=tag:%s,3,%s" % (pid, router))
                pdns = p.get("dns_servers") or ([router] if router else [])
                for d in pdns:
                    L.append("dhcp-option=tag:%s,6,%s" % (pid, d))
                for line in str(p.get("extra_options") or "").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        L.append("dhcp-option=tag:%s,%s" % (pid, line))

            for sl in dhcp.get("static_leases", []):
                pool_id = (sl.get("pool") or "").strip()
                tag = ",set:%s" % pool_id if pool_id else ""
                L.append("dhcp-host=%s%s,%s,%s,infinite" % (
                    sl["mac"].upper(), tag, sl["ip"], sl.get("name") or ""))
            extra_opts = (dhcp.get("extra_options") or "").strip()
            if extra_opts:
                L.append("# 高级自定义选项")
                L += [x.rstrip() for x in extra_opts.splitlines() if x.strip()]
        else:
            L.append("# DHCP 服务已关闭")
        return "\n".join(L) + "\n"

    @staticmethod
    def _pool_iface(cfg, pool):
        if pool.get("interface"):
            return str(pool["interface"])
        if pool.get("vlan_id"):
            parent = pool.get("parent") or cfg["network"]["lan"].get("interface") or ""
            return "%s.%s" % (parent, pool["vlan_id"]) if parent else ""
        return ""

    # ---------------- 进程管理 ----------------
    def start(self, cfg, conf_path, lease_path):
        self.conf_path = conf_path
        self.lease_path = lease_path
        self.restarts = 0
        self.last_error = ""
        self._stop = False
        self._last_cfg = cfg
        self._spawn(cfg)

    def _spawn(self, cfg):
        if cfg is not None:
            self._last_cfg = cfg
        with self._lock:
            if self._stop:
                return
            if self.proc and self.proc.poll() is None:
                return
            conf = self.build_conf(cfg)
            if not linux_util.write_file_atomic(self.conf_path, conf, 0o644):
                self.last_error = "无法写入配置文件 %s" % self.conf_path
                self._info("生成 dnsmasq 配置失败：%s" % self.last_error)
                return
            try:
                self.proc = subprocess.Popen(
                    ["dnsmasq", "-C", self.conf_path, "-k", "--log-facility=-"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, errors="replace",
                )
            except FileNotFoundError:
                self.last_error = "未找到 dnsmasq 程序，请先安装 dnsmasq-base"
                self._info(self.last_error)
                return
            self._info("dnsmasq 已启动 (pid=%d)" % self.proc.pid)
            threading.Thread(target=self._read_stdout, args=(self.proc,), daemon=True).start()
            self._ensure_watchdog()

    def _read_stdout(self, proc):
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                m = self._dns_re.search(line)
                if m:
                    self.dns_events.append((time.time(), m.group(2), m.group(1).rstrip(".")))
                self._info(line)
        except Exception:
            pass

    def dns_activity(self):
        return list(self.dns_events)

    def _ensure_watchdog(self):
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watch, daemon=True)
        self._watchdog.start()

    def _watch(self):
        while not self._stop:
            time.sleep(5)
            with self._lock:
                if self._stop or self.proc is None:
                    continue
                if self.proc.poll() is None:
                    if self.restarts > 0:
                        self._stable_since = self._stable_since or time.time()
                    continue
                code = self.proc.poll()
                self.last_error = "dnsmasq 进程退出（代码 %s）" % code
                self._info("dnsmasq 退出，%d 秒后重启" % min(60, 3 * 2 ** self.restarts))
                self.proc = None
                time.sleep(min(60, 3 * 2 ** self.restarts))
                self.restarts += 1
                self._stable_since = 0.0
                if self.restarts <= 8:
                    self._spawn(self._last_cfg)
                else:
                    self.last_error = "dnsmasq 连续重启超过 8 次，已放弃自动重启，请检查配置"

    def restart(self, cfg):
        self._last_cfg = cfg
        with self._lock:
            self._stop_proc()
            self._spawn(cfg)

    def _stop_proc(self):
        p = self.proc
        self.proc = None
        if p:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def stop(self):
        self._stop = True
        with self._lock:
            self._stop_proc()

    def _info(self, msg):
        self.log_tail.append(msg)
        if self.log:
            self.log.info("[dnsmasq] %s", msg)

    # ---------------- 状态 ----------------
    def status(self):
        with self._lock:
            running = bool(self.proc and self.proc.poll() is None)
            pid = self.proc.pid if running else 0
            return {
                "running": running,
                "pid": pid,
                "restarts": self.restarts,
                "last_error": self.last_error,
                "log_tail": list(self.log_tail)[-60:],
                "conf_path": self.conf_path,
            }
