# -*- coding: utf-8 -*-
"""演示后端：在任意平台（含 Windows）模拟一台软路由，用于界面预览与开发调试。"""
import random
import time

from .base import BackendBase
from .oui import vendor_of


class DemoBackend(BackendBase):
    name = "demo"

    # 演示设备：名称 / IP / MAC / 厂商 / 类型 / 常态带宽区间 (bps)
    DEMO = [
        ("小米 14 Pro",            "192.168.1.100", "3C:CD:57:0A:1F:01", "小米", "phone",    (2e5, 6e6)),
        ("iPhone 15",              "192.168.1.101", "F0:98:9D:3B:55:02", "Apple", "phone",   (3e5, 8e6)),
        ("MacBook Pro",            "192.168.1.102", "38:C9:86:71:AA:03", "Apple", "computer",(1e6, 4e7)),
        ("客厅电视",               "192.168.1.103", "A4:2B:B0:9C:E1:04", "TP-Link", "tv",   (5e5, 4e7)),
        ("群晖 NAS",               "192.168.1.104", "00:11:32:8F:2D:05", "群晖", "nas",     (1e5, 2e7)),
        ("办公室打印机",           "192.168.1.105", "3C:52:82:B7:19:06", "惠普", "printer", (1e4, 2e5)),
        ("门口摄像头",             "192.168.1.106", "44:19:B6:C3:77:07", "海康威视", "camera",(2e5, 3e6)),
        ("小爱音箱",               "192.168.1.107", "78:11:DC:5E:82:08", "小米", "speaker", (3e4, 3e5)),
        ("iPad Air",               "192.168.1.108", "AC:BC:32:F1:48:09", "Apple", "tablet", (2e5, 6e6)),
        ("ThinkPad X1",            "192.168.1.109", "3C:2E:F9:D4:C6:10", "联想", "computer",(5e5, 3e7)),
        ("扫地机器人",             "192.168.1.110", "F0:B4:29:6A:B3:11", "小米", "iot",     (5e4, 8e5)),
        ("天猫精灵",               "192.168.1.111", "40:B4:CD:2E:90:12", "亚马逊", "speaker",(2e4, 2e5)),
        ("PS5 游戏机",             "192.168.1.112", "70:20:84:19:F7:13", "索尼", "game",    (2e5, 6e7)),
        ("海尔洗衣机",             "192.168.1.113", "64:09:80:3C:D2:14", "小米", "iot",     (1e4, 1e5)),
        ("台式机",                 "192.168.1.114", "00:E0:4C:52:6B:15", "Realtek", "computer",(3e5, 8e7)),
        ("访客手机",               "192.168.1.115", "8C:77:12:41:E8:16", "三星", "phone",   (2e5, 5e6)),
        ("树莓派",                 "192.168.1.116", "B8:27:EB:10:4A:17", "树莓派", "iot",   (5e4, 1e6)),
        ("旧路由器(中继)",         "192.168.1.117", "50:C7:BF:88:0D:18", "TP-Link", "router",(8e4, 1e6)),
    ]

    def __init__(self):
        self.cfg = None
        self.log = None
        self.rng = random.Random(20241023)
        self.started = time.time()
        self.iface_bytes = {"wan0": [0, 0], "lan0": [0, 0], "lo": [0, 0]}
        self.dev_bytes = {}      # ip -> [rx, tx]
        self.dev_rate = {}       # ip -> [rx_rate, tx_rate] 平滑值
        self.sessions = {}       # ip -> int
        self.online = {}         # ip -> bool
        self.remote_counts = {"223.5.5.5": 8, "119.29.29.29": 6, "8.8.8.8": 4,
                              "114.114.114.114": 3, "180.101.50.242": 5, "110.42.100.31": 7}
        self._total_sessions = 0
        self._init_devices()

    def _init_devices(self):
        for name, ip, mac, vendor, kind, rng in self.DEMO:
            self.dev_bytes[ip] = [0, 0]
            self.dev_rate[ip] = [0.0, 0.0]
            self.sessions[ip] = self.rng.randint(2, 25)
            self.online[ip] = ip != "192.168.1.117"  # 旧路由器暂时离线
        self.online["192.168.1.105"] = False         # 打印机离线
        self.dev_bytes["192.168.1.104"][0] = 96 * 2 ** 30
        self.dev_bytes["192.168.1.104"][1] = 42 * 2 ** 30
        self.dev_bytes["192.168.1.102"][0] = 18 * 2 ** 30
        self.dev_bytes["192.168.1.102"][1] = 6 * 2 ** 30

    # ---------------- BackendBase 接口 ----------------
    def start(self, cfg, log):
        self.cfg = cfg
        self.log = log
        self.started = time.time()

    def stop(self):
        pass

    def step(self, dt):
        """推进仿真：带宽随机游走、会话数变化。"""
        wan_rx = wan_tx = 0
        for name, ip, mac, vendor, kind, (lo, hi) in self.DEMO:
            if not self.online[ip]:
                self.dev_rate[ip] = [0.0, 0.0]
                self.sessions[ip] = 0
                continue
            burst = 3.5 if self.rng.random() < 0.06 else 1.0
            if kind in ("tv", "computer", "game", "nas"):
                burst = 5.0 if self.rng.random() < 0.12 else 1.0
            target_rx = self.rng.uniform(lo, hi) * burst
            target_tx = self.rng.uniform(lo * 0.4, hi * 0.5) * burst
            cur_rx, cur_tx = self.dev_rate[ip]
            cur_rx += (target_rx - cur_rx) * 0.25
            cur_tx += (target_tx - cur_tx) * 0.25
            self.dev_rate[ip] = [cur_rx, cur_tx]
            self.dev_bytes[ip][0] += int(cur_rx * dt)
            self.dev_bytes[ip][1] += int(cur_tx * dt)
            wan_rx += cur_tx
            wan_tx += cur_rx
            if self.rng.random() < 0.3:
                self.sessions[ip] = max(1, self.sessions[ip] + self.rng.randint(-3, 4))
        self.iface_bytes["wan0"][0] += int(wan_rx * dt)
        self.iface_bytes["wan0"][1] += int(wan_tx * dt)
        self.iface_bytes["lan0"][0] += int(wan_tx * dt)
        self.iface_bytes["lan0"][1] += int(wan_rx * dt)
        lan_sessions = sum(n for ip, n in self.sessions.items() if self.online.get(ip))
        # 会话总数 = 内网设备会话 + 本机自身连接（DNS/管理页等），保证总数不小于设备合计
        self._total_sessions = lan_sessions + self.rng.randint(35, 85)
        # 偶尔有设备上线/下线
        if self.rng.random() < 0.01:
            ip = self.rng.choice(list(self.online.keys()))
            self.online[ip] = not self.online[ip]

    def interfaces(self):
        return {k: tuple(v) for k, v in self.iface_bytes.items()}

    def counters(self):
        return {ip: {"rx": v[0], "tx": v[1]} for ip, v in self.dev_bytes.items() if self.online.get(ip)}

    def conntrack(self):
        by_ip = {ip: n for ip, n in self.sessions.items() if self.online.get(ip)}
        total = self._total_sessions
        tcp = int(total * 0.82)
        udp = int(total * 0.15)
        icmp = 4
        return {"total": total, "by_ip": by_ip, "tcp": tcp, "udp": udp,
                "icmp": icmp, "other": max(0, total - tcp - udp - icmp),
                "remote": dict(self.remote_counts)}

    def leases(self):
        now = time.time()
        out = []
        for name, ip, mac, vendor, kind, _ in self.DEMO:
            out.append({"ip": ip, "mac": mac, "hostname": self._hostname(name, kind),
                        "expiry": int(now + 3600)})
        return out

    @staticmethod
    def _hostname(name, kind):
        mapping = {
            "客厅电视": "Xiaomi-TV", "群晖 NAS": "NAS", "办公室打印机": "HP-LaserJet",
            "门口摄像头": "IPC-Door", "小爱音箱": "AI-Speaker", "天猫精灵": "Tmall-Genie",
            "PS5 游戏机": "PS5", "海尔洗衣机": "Washer", "树莓派": "raspberrypi",
            "扫地机器人": "Roborock",
        }
        if name in mapping:
            return mapping[name]
        if kind == "phone":
            return ""  # 手机不提供主机名，用于演示 NetBIOS/别名命名
        return ""

    def neighbors(self):
        out = []
        for name, ip, mac, vendor, kind, _ in self.DEMO:
            if self.online.get(ip):
                out.append({"ip": ip, "mac": mac, "state": "REACHABLE"})
        return out

    def system(self):
        cpu = 9.0 + abs(self.rng.gauss(0, 4)) * 3
        mem_total = 8 * 2 ** 30
        mem_used = int(mem_total * (0.22 + 0.05 * self.rng.random()))
        uptime = time.time() - self.started
        return {"cpu": round(min(cpu, 99.0), 1), "mem_total": mem_total, "mem_used": mem_used,
                "load1": round(0.2 + 0.3 * self.rng.random(), 2),
                "load5": round(0.2 + 0.2 * self.rng.random(), 2),
                "load15": round(0.15 + 0.2 * self.rng.random(), 2),
                "uptime": uptime, "temp": 46.0 + self.rng.random() * 12}

    def wan_info(self):
        return {"mode": "none", "state": "演示模式（未连接真实外网）",
                "ip": "100.64.0.2", "netmask": "255.255.255.0", "gateway": "100.64.0.1",
                "dns": ["223.5.5.5"], "interface": "wan0"}

    def lan_info(self):
        return {"interface": "lan0", "ip": "192.168.1.1", "netmask": "255.255.255.0"}

    def services(self):
        return {
            "dnsmasq": {"running": True, "pid": 4321, "restarts": 0, "last_error": "",
                        "log_tail": [
                            "dnsmasq[4321]: started, version 2.90",
                            "dnsmasq-dhcp[4321]: DHCP, IP range 192.168.1.100 -- 192.168.1.199, lease time 12h",
                            "dnsmasq[4321]: reading /var/lib/easyrouter/dnsmasq.leases",
                            "dnsmasq[4321]: using nameserver 223.5.5.5#53",
                        ]},
            "nft": {"ok": True, "last_error": "", "rules": 2 * len(self.dev_bytes) + 8},
            "wan": {"mode": "演示", "state": "正常", "pid": 0},
        }

    def apply(self, old_cfg, new_cfg):
        self.cfg = new_cfg
        return [], [], ["演示模式：配置已保存（真实设备上将自动下发并应用）"]

    def interface_list(self):
        return [
            {"name": "wan0", "mac": "00:1B:21:AA:00:01", "addrs": ["100.64.0.2/24"],
             "state": "up", "is_loopback": False},
            {"name": "lan0", "mac": "00:1B:21:AA:00:02", "addrs": ["192.168.1.1/24"],
             "state": "up", "is_loopback": False},
            {"name": "eth2", "mac": "00:1B:21:AA:00:03", "addrs": [], "state": "down",
             "is_loopback": False},
        ]

    def nbns_name(self, ip):
        """模拟 NetBIOS 应答：返回演示设备的名称。"""
        for name, dip, mac, vendor, kind, _ in self.DEMO:
            if dip == ip:
                return name
        return None

    def wake(self, mac):
        return True, "演示模式：已模拟发送网络唤醒数据包给 %s" % (mac or "该设备")

    def dns_activity(self):
        """模拟 DNS 查询事件，供应用监控演示。"""
        now = time.time()
        samples = [
            ("192.168.1.100", "api.weixin.qq.com"),
            ("192.168.1.100", "short.weixin.qq.com"),
            ("192.168.1.101", "www.douyin.com"),
            ("192.168.1.101", "v26.douyinvod.com"),
            ("192.168.1.102", "api.github.com"),
            ("192.168.1.102", "www.bilibili.com"),
            ("192.168.1.103", "upos-sz-mirror.bilivideo.com"),
            ("192.168.1.103", "v.qq.com"),
            ("192.168.1.104", "music.163.com"),
            ("192.168.1.108", "www.xiaohongshu.com"),
            ("192.168.1.109", "www.taobao.com"),
            ("192.168.1.111", "api.m.jd.com"),
            ("192.168.1.112", "steamcontent.com"),
            ("192.168.1.114", "www.baidu.com"),
            ("192.168.1.115", "api.weibo.cn"),
        ]
        out = []
        for _ in range(self.rng.randint(4, 9)):
            ip, dom = self.rng.choice(samples)
            out.append((now - self.rng.randint(0, 5), ip, dom))
        return out
