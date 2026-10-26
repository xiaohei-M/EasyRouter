# -*- coding: utf-8 -*-
"""监控采集线程：合并租约/邻居/流量/会话，产出设备列表、速率、历史曲线。"""
import ipaddress
import threading
import time
from collections import deque

from . import config as config_mod
from . import apps as apps_mod
from .core import oui as oui_mod

ONLINE_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE"}


def ip_sort_key(ip):
    try:
        return int(ipaddress.IPv4Address(ip))
    except Exception:
        return 2 ** 32


def _kind_of(vendor, name, hostname):
    """根据厂商/名称关键字猜测设备类型，用于界面图标。"""
    text = ("%s %s %s" % (vendor, name, hostname)).lower()
    if any(k in text for k in ("手机", "iphone", "phone", "android", "redmi", "mate")):
        return "phone"
    if any(k in text for k in ("平板", "ipad", "tablet", "pad")):
        return "tablet"
    if any(k in text for k in ("电视", "tv", "盒子", "box", "hisense", "skyworth")):
        return "tv"
    if any(k in text for k in ("nas", "群晖", "synology", "qnap", "威联通")):
        return "nas"
    if any(k in text for k in ("摄像头", "camera", "cam", "海康", "hikvision", "监控")):
        return "camera"
    if any(k in text for k in ("音箱", "speaker", "echo", "天猫", "小爱", "音响")):
        return "speaker"
    if any(k in text for k in ("打印机", "printer", "hp", "epson", "canon")):
        return "printer"
    if any(k in text for k in ("路由器", "router", "网关", "gateway", "mesh", "中继")):
        return "router"
    if any(k in text for k in ("游戏", "playstation", "ps5", "xbox", "switch", "任天堂")):
        return "game"
    if any(k in text for k in ("扫地", "洗衣机", "冰箱", "空调", "插座", "灯泡", "灯", "开关",
                               "门锁", "窗帘", "sensor", "传感器")):
        return "iot"
    if any(k in text for k in ("手表", "watch", "手环")):
        return "watch"
    if any(k in text for k in ("电脑", "笔记本", "台式", "thinkpad", "macbook", "mac", "pc",
                               "book", "联想", "戴尔", "惠普", "华硕", "intel", "windows", "realtek")):
        return "computer"
    return "device"


class Monitor(threading.Thread):
    def __init__(self, cfg, backend, store, log):
        super().__init__(daemon=True, name="easyrouter-monitor")
        self.cfg = cfg
        self.backend = backend
        self.store = store
        self.log = log
        self.lock = threading.RLock()
        self.interval = float(cfg["monitor"].get("interval", 2.0))
        self._stop_ev = threading.Event()
        self._boot_time = time.time()

        self.aliases = dict(store.get_aliases())
        # 注意：DB 里是元组 (rx, tx)，这里转成可写列表
        self.totals = {ip: [v[0], v[1]] for ip, v in store.get_totals().items()}
        self.prev_counters = {}                          # (ip, dir) -> bytes
        self.prev_iface = {}                             # name -> (rx, tx)
        self.iface_rate = {}                             # name -> {rx_rate, tx_rate, rx_total, tx_total}
        self.dev_rate = {}                               # (ip, dir) -> bps(ema)
        self.devices = {}                                # ip -> dict
        self.by_mac = {}                                 # mac -> ip
        self.sessions = {"total": 0, "tcp": 0, "udp": 0, "icmp": 0, "other": 0, "remote": {}}
        self.apps = []
        self.dns_events = deque(maxlen=8000)
        self._last_dns_ts = 0.0
        self.history = deque(maxlen=int(cfg["monitor"].get("history_points", 600)))
        self.sess_history = deque(maxlen=int(cfg["monitor"].get("history_points", 600)))
        self.wan = {"mode": "none", "state": "未知", "ip": "", "gateway": "", "dns": [], "interface": ""}
        self.lan = {"interface": "", "ip": "", "netmask": ""}
        self.system = {"cpu": 0.0, "mem_total": 0, "mem_used": 0,
                       "load1": 0.0, "load5": 0.0, "load15": 0.0, "uptime": 0, "temp": None}
        self.services = {"dnsmasq": {}, "nft": {}, "wan": {}}
        self.known = {r["mac"]: r for r in store.known_get()}
        self.nbns_names = {}                             # ip -> name
        self._last_nbns = {}                             # ip -> ts
        self._nbns_this_tick = 0
        self._last_db_save = 0.0
        self._last_known = 0.0
        self._tick_n = 0

    # ---------------- 线程 ----------------
    def run(self):
        self.backend.start(self.cfg, self.log)
        while not self._stop_ev.is_set():
            t0 = time.time()
            try:
                self.tick()
            except Exception:
                self.log.exception("监控采样出错")
            used = time.time() - t0
            self._stop_ev.wait(max(0.2, self.interval - used))

    def stop(self):
        self._stop_ev.set()
        try:
            self.backend.stop()
        except Exception:
            pass
        self._flush_db()

    # ---------------- 采样 ----------------
    def tick(self):
        dt = max(0.1, self.interval)
        self._tick_n += 1
        self._nbns_this_tick = 0
        now = time.time()

        # 0. 后端步进（演示模式推进仿真）
        try:
            self.backend.step(dt)
        except Exception:
            pass

        # 1. 网卡速率
        try:
            iface_bytes = self.backend.interfaces()
        except Exception:
            iface_bytes = {}
        for name, (rx, tx) in iface_bytes.items():
            prev = self.prev_iface.get(name)
            if prev is None:
                prev = (rx, tx)
            rx_rate = max(0.0, rx - prev[0]) / dt
            tx_rate = max(0.0, tx - prev[1]) / dt
            self.prev_iface[name] = (rx, tx)
            cur = self.iface_rate.setdefault(
                name, {"rx_rate": 0.0, "tx_rate": 0.0, "rx_total": rx, "tx_total": tx})
            cur["rx_rate"] = self._ema(cur["rx_rate"], rx_rate)
            cur["tx_rate"] = self._ema(cur["tx_rate"], tx_rate)
            cur["rx_total"] = rx
            cur["tx_total"] = tx

        # 2. nftables 计数器 → 每设备速率与累计流量
        try:
            counters = self.backend.counters()
        except Exception:
            counters = {}
        seen_keys = set()
        for ip, c in counters.items():
            for direction in ("rx", "tx"):
                key = (ip, direction)
                seen_keys.add(key)
                val = c[direction]
                prev = self.prev_counters.get(key)
                if prev is None:
                    delta = 0          # 首次观测：仅记录基线
                elif val < prev:
                    delta = val        # 计数器被重置（重启/重建规则）
                else:
                    delta = val - prev
                self.prev_counters[key] = val
                rate = delta / dt
                self.dev_rate[key] = self._ema(self.dev_rate.get(key, 0.0), rate)
                tot = self.totals.setdefault(ip, [0, 0])
                tot[0 if direction == "rx" else 1] += delta
        for key in [k for k in list(self.prev_counters) if k not in seen_keys]:
            self.prev_counters.pop(key, None)
            self.dev_rate.pop(key, None)

        # 3. 连接跟踪：出口会话总数 + 每设备会话数
        try:
            ct = self.backend.conntrack()
        except Exception:
            ct = {}
        by_src = ct.get("by_src") or {}
        by_dst = ct.get("by_dst") or {}
        by_ip_ct = ct.get("by_ip") or {}
        sess_by_ip = {}
        for ip in set(list(by_src) + list(by_dst) + list(by_ip_ct)):
            n = by_ip_ct.get(ip, 0) + by_src.get(ip, 0) + by_dst.get(ip, 0)
            if n > 0:
                sess_by_ip[ip] = n

        # 计算内网设备会话合计（以 LAN 设备为源的会话）与远程目标
        lan_nets, lan_ip = [], ""
        try:
            lan_nets = config_mod.lan_networks(self.cfg)
            lan_ip = self.cfg["network"]["lan"]["ip"]
        except Exception:
            pass

        def _in_lan(ip):
            try:
                addr = ipaddress.IPv4Address(ip)
            except Exception:
                return False
            return any(addr in n for n in lan_nets)

        lan_total = 0
        if lan_nets:
            source = by_src or by_ip_ct
            for ip, n in source.items():
                if ip != lan_ip and _in_lan(ip):
                    lan_total += n

        remote = ct.get("remote") or {}
        if by_dst:
            tmp = {}
            for ip, n in by_dst.items():
                if ip == lan_ip or _in_lan(ip):
                    continue
                tmp[ip] = n
            remote = dict(sorted(tmp.items(), key=lambda kv: -kv[1])[:50])

        self.sessions = {
            "total": ct.get("total", 0),
            "lan_total": lan_total,
            "tcp": ct.get("tcp", 0),
            "udp": ct.get("udp", 0),
            "icmp": ct.get("icmp", 0),
            "other": ct.get("other", 0),
            "remote": remote,
        }

        # 4. 设备发现与合并
        try:
            leases = self.backend.leases()
            neigh = self.backend.neighbors()
        except Exception:
            leases, neigh = [], []
        self._merge_devices(leases, neigh, sess_by_ip, counters, now)

        # 4.5 应用识别（DNS 域名特征）
        try:
            for ts, cip, domain in self.backend.dns_activity():
                if ts > self._last_dns_ts:
                    self.dns_events.append((ts, cip, domain))
                    self._last_dns_ts = max(self._last_dns_ts, ts)
        except Exception:
            pass
        cutoff = now - 900
        while self.dns_events and self.dns_events[0][0] < cutoff:
            self.dns_events.popleft()
        self.apps = self._aggregate_apps(now)

        # 5. 历史曲线
        wan_if = self._wan_iface()
        lan_if = (self.cfg.get("network", {}).get("lan", {}) or {}).get("interface", "")
        wan_rate = self.iface_rate.get(wan_if, {})
        lan_rate = self.iface_rate.get(lan_if, {})
        t_ms = int(now * 1000)
        self.history.append({
            "t": t_ms,
            "wan_rx": int(wan_rate.get("rx_rate", 0)),
            "wan_tx": int(wan_rate.get("tx_rate", 0)),
            "lan_rx": int(lan_rate.get("rx_rate", 0)),
            "lan_tx": int(lan_rate.get("tx_rate", 0)),
            "sessions": self.sessions["total"],
        })
        self.sess_history.append({"t": t_ms, "total": self.sessions["total"]})

        # 6. 低频任务
        if self._tick_n % 5 == 1:
            try:
                self.system = self.backend.system()
                self.wan = self.backend.wan_info()
                self.lan = self.backend.lan_info()
                self.services = self.backend.services()
            except Exception:
                self.log.exception("读取系统信息失败")
            # 补齐/清理 nft 计数规则
            try:
                with self.lock:
                    active = [ip for ip, d in self.devices.items() if d["online"]]
                self.backend.ensure_rules(active)
            except Exception:
                self.log.exception("维护 nft 计数规则失败")

        if now - self._last_db_save >= float(self.cfg["monitor"].get("db_flush_sec", 15)):
            self._flush_db()
        if now - self._last_known >= 60:
            self._save_known()

    @staticmethod
    def _ema(old, new, alpha=0.55):
        return old + (new - old) * alpha

    def _wan_iface(self):
        wan = (self.cfg.get("network", {}).get("wan") or {})
        iface = wan.get("interface", "")
        if wan.get("mode") == "pppoe" and "ppp0" in self.iface_rate:
            return "ppp0"
        if iface in self.iface_rate:
            return iface
        if "wan0" in self.iface_rate:
            return "wan0"
        return iface

    # ---------------- 设备合并 ----------------
    def _merge_devices(self, leases, neigh, sess_by_ip, counters, now):
        try:
            lan_nets = config_mod.lan_networks(self.cfg)
        except Exception:
            lan_nets = []

        def in_lan(ip):
            try:
                addr = ipaddress.IPv4Address(ip)
            except Exception:
                return False
            return any(addr in n for n in lan_nets)

        keep_ts = int(now) - int(self.cfg["monitor"].get("offline_keep_days", 7)) * 86400

        leases_by_ip = {l["ip"]: l for l in leases}
        leases_by_mac = {l["mac"]: l for l in leases if l.get("mac")}
        neigh_by_ip = {n["ip"]: n for n in neigh}

        cur_ips = set(neigh_by_ip) | set(leases_by_ip)
        for ip, d in self.devices.items():
            if lan_nets and not in_lan(ip):
                continue
            if ip in counters or d.get("online"):
                cur_ips.add(ip)

        new_devices = {}
        for ip in cur_ips:
            if lan_nets and not in_lan(ip):
                continue
            lease = leases_by_ip.get(ip)
            n = neigh_by_ip.get(ip)
            old = self.devices.get(ip)
            mac = ""
            if lease:
                mac = lease["mac"]
            if not mac and n:
                mac = n["mac"]
            if not mac and old:
                mac = old["mac"]
            mac = config_mod.mac_norm(mac)
            if not mac:
                continue
            # 如果该 MAC 此前出现在别的 IP（换 IP 了），合并历史
            prev_ip = self.by_mac.get(mac)
            if prev_ip and prev_ip != ip and prev_ip in self.devices:
                prev_dev = self.devices[prev_ip]
                if not old or prev_dev.get("last_seen", 0) > old.get("last_seen", 0):
                    old = prev_dev

            state = n["state"] if n else ("LEASE" if lease else "")
            if not state and old:
                state = old.get("state", "")
            expiry = lease["expiry"] if lease else 0
            if not expiry and old:
                expiry = old.get("lease_expiry", 0)

            rx_rate = self.dev_rate.get((ip, "rx"), 0.0)
            tx_rate = self.dev_rate.get((ip, "tx"), 0.0)
            sessions = sess_by_ip.get(ip, 0)
            last_seen = old.get("last_seen", 0) if old else 0

            first_seen = old.get("first_seen", int(now)) if old else int(now)
            if not old:
                k = self.known.get(mac)
                if k:
                    first_seen = min(first_seen, k["first_seen"])
                    last_seen = max(last_seen, k["last_seen"])

            online = state in ONLINE_STATES or state == "LEASE" or sessions > 0 \
                or rx_rate > 0 or tx_rate > 0 or (expiry and expiry > now)
            if online:
                last_seen = int(now)
            elif old and old.get("online") and int(now) - last_seen <= 300:
                online = True      # 短暂失联缓冲（ARP 表抖动）

            # 名称解析优先级：别名 > DHCP主机名 > NetBIOS/历史名称 > 厂商设备 > 未知设备
            hostname = lease["hostname"] if lease else ""
            alias = self.aliases.get(mac, "")
            nb_name = self.nbns_names.get(ip, "")
            vendor = oui_mod.vendor_of(mac)
            if alias:
                name, name_src = alias, "alias"
            elif hostname:
                name, name_src = hostname, "dhcp"
            elif nb_name:
                name, name_src = nb_name, "netbios"
            elif old and old.get("name_src") == "netbios":
                name, name_src = old["name"], "netbios"
            else:
                name, name_src = (vendor + "设备") if vendor else "未知设备", "guess"

            if old and old.get("name_src") == "alias" and not alias:
                pass  # 别名被删除后回退到其它来源，上面已处理

            dev = {
                "ip": ip, "mac": mac, "name": name, "name_src": name_src,
                "alias": bool(alias), "hostname": hostname, "vendor": vendor,
                "kind": _kind_of(vendor, name, hostname),
                "online": online, "state": state, "lease_expiry": expiry,
                "first_seen": first_seen, "last_seen": last_seen,
                "rx_rate": round(rx_rate), "tx_rate": round(tx_rate),
                "rx_total": self.totals.get(ip, [0, 0])[0],
                "tx_total": self.totals.get(ip, [0, 0])[1],
                "sessions": sessions,
            }
            if old and old.get("name_src") == "netbios" and not dev["name"].endswith("设备") \
                    and not hostname and not alias and not nb_name:
                dev["name"] = old["name"]
            new_devices[ip] = dev

            # 尝试 NetBIOS 补名（限速：每个 tick 最多 1 台）
            if dev["online"] and not alias and not hostname \
                    and dev["name_src"] in ("guess", "netbios") \
                    and self.cfg["monitor"].get("netbios", True):
                self._maybe_nbns(ip, mac)

        with self.lock:
            # 淘汰：长期离线且不在当前列表的设备
            for ip in list(self.devices):
                d = self.devices[ip]
                if ip not in new_devices and d.get("last_seen", 0) < keep_ts:
                    old_mac = d["mac"]
                    self.devices.pop(ip, None)
                    if self.by_mac.get(old_mac) == ip:
                        self.by_mac.pop(old_mac, None)
            self.devices = new_devices
            self.by_mac = {d["mac"]: ip for ip, d in new_devices.items()}
            if self.nbns_names:
                for ip, name in list(self.nbns_names.items()):
                    if ip in self.devices and self.devices[ip]["name_src"] != "netbios":
                        self.devices[ip]["name"] = name
                        self.devices[ip]["name_src"] = "netbios"
                        self.devices[ip]["kind"] = _kind_of(
                            self.devices[ip]["vendor"], name, self.devices[ip]["hostname"])

    def _maybe_nbns(self, ip, mac):
        if self._nbns_this_tick >= 1:
            return
        if ip in self._last_nbns and time.time() - self._last_nbns[ip] < 300:
            return
        self._last_nbns[ip] = time.time()
        self._nbns_this_tick += 1
        try:
            name = self.backend.nbns_name(ip)
        except Exception:
            name = None
        if name:
            self.nbns_names[ip] = name
            with self.lock:
                d = self.devices.get(ip)
                if d:
                    d["name"] = name
                    d["name_src"] = "netbios"
                    d["kind"] = _kind_of(d["vendor"], name, d["hostname"])

    def _aggregate_apps(self, now):
        """按 DNS 查询聚合应用访问情况（最近 15 分钟），含每台设备明细。"""
        stats = {}
        for ts, ip, domain in self.dns_events:
            name, cat, icon = apps_mod.classify(domain)
            s = stats.setdefault(name, {
                "name": name, "category": cat, "icon": icon,
                "clients": {}, "queries": 0, "last": 0, "domains": {}})
            c = s["clients"].setdefault(ip, {"queries": 0, "last": 0})
            c["queries"] += 1
            c["last"] = max(c["last"], ts)
            s["queries"] += 1
            s["last"] = max(s["last"], ts)
            s["domains"][domain] = s["domains"].get(domain, 0) + 1
        out = []
        for s in stats.values():
            top = sorted(s["domains"].items(), key=lambda kv: -kv[1])[:3]
            devices = []
            for ip, info in s["clients"].items():
                dev = self.devices.get(ip) or {}
                devices.append({
                    "ip": ip,
                    "name": dev.get("name", ip),
                    "mac": dev.get("mac", ""),
                    "vendor": dev.get("vendor", ""),
                    "kind": dev.get("kind", "device"),
                    "online": bool(dev.get("online", False)),
                    "queries": info["queries"],
                    "last_seen": int(info["last"]),
                })
            devices.sort(key=lambda d: (-d["queries"], ip_sort_key(d["ip"])))
            out.append({
                "name": s["name"], "category": s["category"], "icon": s["icon"],
                "clients": len(devices), "queries": s["queries"],
                "last_seen": int(s["last"]),
                "domains": [d for d, _n in top],
                "devices": devices,
            })
        out.sort(key=lambda a: -a["queries"])
        return out

    # ---------------- 持久化 ----------------
    def _flush_db(self):
        self._last_db_save = time.time()
        with self.lock:
            totals = {ip: (v[0], v[1]) for ip, v in self.totals.items()}
        try:
            self.store.save_totals(totals)
        except Exception:
            self.log.exception("保存累计流量失败")

    def _save_known(self):
        self._last_known = time.time()
        with self.lock:
            rows = [(d["mac"], d["first_seen"], d["last_seen"], d["ip"])
                    for d in self.devices.values()]
        try:
            self.store.known_update(rows)
        except Exception:
            self.log.exception("保存设备档案失败")

    # ---------------- 对外接口 ----------------
    def reload_aliases(self):
        with self.lock:
            self.aliases = dict(self.store.get_aliases())

    def set_totals(self, totals):
        with self.lock:
            self.totals = {ip: [int(v[0]), int(v[1])] for ip, v in (totals or {}).items()}

    def set_alias(self, mac, name):
        mac = config_mod.mac_norm(mac)
        if not mac:
            return False, "MAC 地址无效"
        self.store.set_alias(mac, name)
        if name:
            self.aliases[mac] = name
            with self.lock:
                ip = self.by_mac.get(mac)
                if ip and ip in self.devices:
                    self.devices[ip]["name"] = name
                    self.devices[ip]["name_src"] = "alias"
                    self.devices[ip]["alias"] = True
                    self.devices[ip]["kind"] = _kind_of(
                        self.devices[ip]["vendor"], name, self.devices[ip]["hostname"])
        else:
            self.aliases.pop(mac, None)
        return True, "已保存"

    def update_cfg(self, new_cfg):
        with self.lock:
            self.cfg = new_cfg
            self.interval = float(new_cfg["monitor"].get("interval", 2.0))
            cap = int(new_cfg["monitor"].get("history_points", 600))
            if self.history.maxlen != cap:
                self.history = deque(self.history, maxlen=cap)
                self.sess_history = deque(self.sess_history, maxlen=cap)

    def snapshot(self, history_points=180):
        """返回 API 需要的完整快照。"""
        with self.lock:
            devices = [dict(d) for d in self.devices.values()]
            history = [dict(h) for h in list(self.history)[-history_points:]]
            sess_history = [dict(h) for h in list(self.sess_history)[-history_points:]]
            apps = [dict(a) for a in self.apps]
            iface = {k: dict(v) for k, v in self.iface_rate.items()}
            sessions = dict(self.sessions)
            wan = dict(self.wan)
            lan = dict(self.lan)
            system = dict(self.system)
            services = {k: dict(v) if isinstance(v, dict) else v for k, v in self.services.items()}
            cfg = self.cfg
            uptime = self._boot_time
        return {
            "devices": devices,
            "apps": apps,
            "history": history,
            "sess_history": sess_history,
            "interfaces": iface,
            "sessions": sessions,
            "wan": wan,
            "lan": lan,
            "system": system,
            "services": services,
            "cfg": cfg,
            "boot_time": uptime,
        }

    def devices_sorted(self, key="ip"):
        with self.lock:
            devices = [dict(d) for d in self.devices.values()]
        if key == "ip":
            devices.sort(key=lambda d: (not d["online"], ip_sort_key(d["ip"])))
        elif key == "mac":
            devices.sort(key=lambda d: (not d["online"], d["mac"]))
        elif key == "traffic":
            devices.sort(key=lambda d: -(d["rx_rate"] + d["tx_rate"]))
        elif key == "sessions":
            devices.sort(key=lambda d: -d["sessions"])
        elif key == "name":
            devices.sort(key=lambda d: d["name"])
        return devices
