# -*- coding: utf-8 -*-
"""Linux 真实后端：整合 dnsmasq、nftables、网络、系统、conntrack、设备发现。"""
import ipaddress
import os
import socket

from . import linux_conntrack
from . import linux_devices
from . import linux_util
from .. import config as config_mod
from .base import BackendBase
from .linux_dnsmasq import DnsmasqService
from .linux_nft import NftService
from .linux_sys import SystemReader
from .linux_wan import NetworkManager
from .nbns import NetbiosResolver


class LinuxBackend(BackendBase):
    name = "linux"

    def __init__(self, log=None, conf_path="/etc/easyrouter/config.json",
                 lease_path="/var/lib/easyrouter/dnsmasq.leases",
                 dnsmasq_conf="/etc/easyrouter/dnsmasq.conf"):
        self.log = log
        self.conf_path = conf_path
        self.lease_path = lease_path
        self.dnsmasq_conf = dnsmasq_conf
        self.cfg = None
        self.sys = SystemReader()
        self.nft = NftService(log)
        self.dnsmasq = DnsmasqService(log)
        self.netmgr = NetworkManager(log)
        self.nbns = None
        self._lan_net = None

    # ---------------- 生命周期 ----------------
    def start(self, cfg, log=None):
        self.cfg = cfg
        os.makedirs("/var/run/easyrouter", exist_ok=True)
        # 系统开关：转发、连接跟踪计费
        ok, msg = linux_util.sysctl_set("net.ipv4.ip_forward", 1)
        if not ok:
            self._info("开启 IP 转发失败：%s" % msg)
        ok, msg = linux_util.sysctl_set("net.netfilter.nf_conntrack_acct", 1)
        if not ok:
            self._info("开启 conntrack 计费失败：%s" % msg)
        linux_util.sysctl_set("net.netfilter.nf_conntrack_max", 131072)

        if cfg.get("setup_done"):
            errs = self.netmgr.apply_lan(cfg)
            for e in errs:
                self._info("LAN 配置错误：%s" % e)
            for e in self.netmgr.apply_vlans(cfg):
                self._info("VLAN 配置错误：%s" % e)
            self._reapply_base(cfg)
            self.dnsmasq.start(cfg, self.dnsmasq_conf, self.lease_path)
            self.netmgr.apply_wan(cfg)
        self._init_nbns(cfg)

    def stop(self):
        self.dnsmasq.stop()
        self.netmgr.stop()

    def _info(self, msg):
        if self.log:
            self.log.info(msg)

    def _reapply_base(self, cfg):
        if cfg.get("firewall", {}).get("enabled", True):
            self.nft.apply_base(cfg)
        else:
            self._info("防火墙已关闭，跳过 nftables 规则应用")

    def _init_nbns(self, cfg):
        if cfg.get("monitor", {}).get("netbios", True) and cfg.get("setup_done"):
            try:
                net = ipaddress.IPv4Network(
                    "%s/%s" % (cfg["network"]["lan"]["ip"], cfg["network"]["lan"]["netmask"]),
                    strict=False)
                self._lan_net = net
                self.nbns = NetbiosResolver(str(net.broadcast_address), self.log)
            except Exception:
                self.nbns = None
        else:
            self.nbns = None

    # ---------------- 采集 ----------------
    def interfaces(self):
        return self.sys.iface_bytes()

    def counters(self):
        counters, _ = self.nft.read_counters()
        out = {}
        for (ip, direction), bytes_ in counters.items():
            d = out.setdefault(ip, {"rx": 0, "tx": 0})
            d[direction] = bytes_
        return out

    def conntrack(self):
        raw = linux_conntrack.read_all()
        total = linux_conntrack.read_count() or raw["total"]
        raw["total"] = total
        return raw

    def leases(self):
        return linux_devices.read_leases(self.lease_path)

    def neighbors(self):
        if not self.cfg:
            return []
        out, seen = [], set()
        for iface in config_mod.lan_interfaces(self.cfg):
            for n in linux_devices.read_neighbors(iface):
                if n["ip"] not in seen:
                    seen.add(n["ip"])
                    out.append(n)
        return out

    def system(self):
        total, used = self.sys.meminfo()
        l1, l5, l15 = self.sys.loadavg()
        return {"cpu": self.sys.cpu_percent(), "mem_total": total, "mem_used": used,
                "load1": l1, "load5": l5, "load15": l15,
                "uptime": self.sys.uptime(), "temp": self.sys.temperature()}

    def wan_info(self):
        if not self.cfg:
            return {"mode": "none", "state": "未配置", "ip": "", "gateway": "", "dns": [], "interface": ""}
        st = self.netmgr.wan_status(self.cfg)
        return st

    def lan_info(self):
        if not self.cfg:
            return {"interface": "", "ip": "", "netmask": ""}
        lan = self.cfg["network"]["lan"]
        return {"interface": lan["interface"], "ip": lan["ip"], "netmask": lan["netmask"]}

    def services(self):
        wan = self.netmgr.wan_status(self.cfg) if self.cfg else {}
        return {"dnsmasq": self.dnsmasq.status(), "nft": self.nft.status(), "wan": wan}

    def apply(self, old_cfg, new_cfg):
        errors, warnings, applied = [], [], []
        if new_cfg.get("firewall", {}).get("enabled") is False:
            warnings.append("防火墙已关闭：NAT 与流量计数不会生效，内网可能无法上网")

        wan_old, wan_new = old_cfg["network"]["wan"], new_cfg["network"]["wan"]
        lan_old, lan_new = old_cfg["network"]["lan"], new_cfg["network"]["lan"]
        wan_changed = wan_old != wan_new
        lan_changed = lan_old != lan_new
        pools_changed = old_cfg.get("dhcp", {}).get("pools") != new_cfg.get("dhcp", {}).get("pools")

        # 1. WAN
        if wan_changed:
            e, a = self.netmgr.apply_wan(new_cfg)
            errors += e
            applied += a
        # 2. LAN / VLAN
        if lan_changed:
            errors += self.netmgr.apply_lan(new_cfg)
            if not errors:
                applied.append("LAN 地址已更新为 %s/%s" % (lan_new["ip"], lan_new["netmask"]))
        if pools_changed:
            errors += self.netmgr.apply_vlans(new_cfg)
            applied.append("VLAN 地址池接口已更新")
        # 3. nftables（网卡或网段变化时重建）
        net_changed = wan_changed or lan_changed or pools_changed
        fw_changed = old_cfg.get("firewall", {}).get("enabled") != new_cfg.get("firewall", {}).get("enabled")
        if net_changed or fw_changed:
            self._reapply_base(new_cfg)
            if new_cfg.get("firewall", {}).get("enabled", True):
                applied.append("防火墙/NAT 规则已更新")
        # 4. dnsmasq（DHCP/DNS/LAN 变化时重启）
        dhcp_changed = (old_cfg.get("dhcp") != new_cfg.get("dhcp")
                        or old_cfg.get("dns") != new_cfg.get("dns")
                        or lan_changed)
        if dhcp_changed and new_cfg.get("setup_done"):
            self.dnsmasq.restart(new_cfg)
            if new_cfg["dhcp"].get("enabled"):
                gw = new_cfg["dhcp"].get("send_gateway", True)
                applied.append(
                    "DHCP 服务已重启（%s下发网关）" % ("" if gw else "不"))
        self.cfg = new_cfg
        self._init_nbns(new_cfg)
        return errors, warnings, applied

    def interface_list(self):
        return linux_devices.interface_list()

    def ensure_rules(self, active_ips):
        """为在线设备补齐计数规则，并清理已离线设备的规则。"""
        if not self.cfg or not self.cfg.get("firewall", {}).get("enabled", True):
            return 0
        added = self.nft.ensure_device_rules(self.cfg, set(active_ips))
        counters, handles = self.nft.read_counters()
        existing = {ip for (ip, _dir) in counters}
        stale = existing - set(active_ips)
        if stale:
            self.nft.remove_device_rules(stale)
        return added

    def dns_activity(self):
        return self.dnsmasq.dns_activity()

    def nbns_name(self, ip):
        if self.nbns:
            return self.nbns.resolve(ip)
        return None

    def wake(self, mac):
        try:
            parts = [int(x, 16) for x in mac.replace("-", ":").split(":")]
            if len(parts) != 6:
                return False, "MAC 地址格式错误"
            payload = b"\xff" * 6 + bytes(parts) * 16
            target = "255.255.255.255"
            if self._lan_net:
                target = str(self._lan_net.broadcast_address)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(payload, (target, 9))
            finally:
                sock.close()
            return True, "已向 %s 发送网络唤醒数据包" % mac.upper()
        except Exception as e:
            return False, "发送唤醒包失败：%s" % e
