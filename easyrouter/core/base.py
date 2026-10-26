# -*- coding: utf-8 -*-
"""采集后端统一接口。Linux 真实后端与演示后端都实现该接口。"""


class BackendBase:
    name = "base"

    def start(self, cfg, log):
        """启动后端（应用系统配置、拉起子进程等）。"""

    def stop(self):
        """停止后端。"""

    def step(self, dt):
        """每个采样周期被调用（演示模式用其推进仿真）。"""

    def interfaces(self):
        """返回 {网卡名: (rx_bytes, tx_bytes)}。"""
        return {}

    def counters(self):
        """返回 {IP: {"rx": bytes, "tx": bytes}}（nftables 计数器）。"""
        return {}

    def conntrack(self):
        """返回 {"total": n, "by_ip": {ip:n}, "tcp":n, "udp":n, "icmp":n, "other":n, "remote": {ip:n}}。"""
        return {"total": 0, "by_ip": {}, "tcp": 0, "udp": 0, "icmp": 0, "other": 0, "remote": {}}

    def leases(self):
        """DHCP 租约列表：[{ip, mac, hostname, expiry}]。"""
        return []

    def neighbors(self):
        """邻居表：[{ip, mac, state}]。"""
        return []

    def system(self):
        """系统信息：{cpu, mem_total, mem_used, load1, load5, load15, uptime, temp}。"""
        return {"cpu": 0.0, "mem_total": 0, "mem_used": 0,
                "load1": 0.0, "load5": 0.0, "load15": 0.0, "uptime": 0, "temp": None}

    def wan_info(self):
        """WAN 状态：{mode, state, ip, netmask, gateway, dns, interface}。"""
        return {"mode": "none", "state": "未知", "ip": "", "netmask": "",
                "gateway": "", "dns": [], "interface": ""}

    def lan_info(self):
        return {"interface": "", "ip": "", "netmask": ""}

    def services(self):
        """服务状态，供系统页展示。"""
        return {"dnsmasq": {}, "nft": {}, "wan": {}}

    def apply(self, old_cfg, new_cfg):
        """应用配置变更。返回 (错误列表, 警告列表, 已应用说明列表)。"""
        return [], [], []

    def interface_list(self):
        """所有物理网卡：[{name, mac, addrs, state, is_loopback}]。"""
        return []

    def ensure_rules(self, active_ips):
        """确保在线设备的流量计数规则存在（Linux 后端实现，演示后端忽略）。"""

    def dns_activity(self):
        """最近的 DNS 查询事件 [(ts, client_ip, domain)]，用于应用识别。"""
        return []

    def nbns_name(self, ip):
        """通过 NetBIOS 查询设备名称，失败返回 None。"""
        return None

    def wake(self, mac):
        """网络唤醒。返回 (ok, message)。"""
        return False, "当前后端不支持网络唤醒"
