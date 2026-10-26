# -*- coding: utf-8 -*-
"""配置管理：默认配置、加载、保存、校验（错误信息全部为中文）。"""
import copy
import ipaddress
import json
import os
import re

LEASE_PAT = re.compile(r"^(\d+[smhdw]|infinite)$")


DEFAULTS = {
    "version": 1,
    "setup_done": False,
    "admin": {"username": "admin", "password_hash": ""},
    "web": {"host": "0.0.0.0", "port": 80, "lan_only": True},
    "network": {
        "wan": {
            "interface": "",
            "mode": "none",          # none | dhcp | static | pppoe
            "ip": "",
            "netmask": "255.255.255.0",
            "gateway": "",
            "dns": [],
            "pppoe_user": "",
            "pppoe_password": "",
        },
        "lan": {"interface": "", "ip": "192.168.1.1", "netmask": "255.255.255.0"},
    },
    "dhcp": {
        "enabled": True,
        "start": "192.168.1.100",
        "end": "192.168.1.199",
        "lease_time": "12h",
        "auto_bind_first": False,    # 首次分配后自动固定 MAC↔IP
        "send_gateway": True,        # True=下发网关；False=不下发网关（客户端网关为空）
        "gateway": "",               # 下发的网关地址；留空 = 使用本机 LAN 地址
        "dns_servers": [],           # 空 = 使用 LAN 地址作为 DNS
        "static_leases": [],         # [{"mac": "...", "ip": "...", "name": "...", "pool": ""}]
        "extra_options": "",         # 追加的 dnsmasq 高级选项（每行一条）
        # 附加地址池：
        # tagged = 同网段按设备标签分配（静态绑定到池），vlan = 独立 VLAN/网段
        "pools": [],
    },
    "dns": {
        "use_system": False,
        "upstreams": ["223.5.5.5", "119.29.29.29"],
        "cache_size": 512,
    },
    "monitor": {
        "interval": 2.0,             # 采样间隔（秒）
        "netbios": True,             # 尝试通过 NetBIOS 获取设备名称
        "offline_keep_days": 7,      # 离线设备保留天数
        "history_points": 600,       # 内存中保留的历史采样点数
        "db_flush_sec": 15,          # 累计流量落库周期（秒）
        "gateway_interval": 30,      # 出口网关探针周期（秒）
    },
    "gateways": [],                  # 上游出口网关探针配置
    "firewall": {"enabled": True},
    "sys": {
        "reboot_cmd": "systemctl reboot",
        "poweroff_cmd": "systemctl poweroff",
    },
}


def deep_merge(base, over):
    """递归合并两个字典，over 覆盖 base。"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def new_default():
    return copy.deepcopy(DEFAULTS)


def mac_norm(mac):
    """规范化 MAC 地址为大写 AA:BB:CC:DD:EE:FF，非法返回 None。"""
    if not mac:
        return None
    m = re.sub(r"[^0-9a-fA-F]", "", str(mac))
    if len(m) != 12:
        return None
    return ":".join(m[i:i + 2].upper() for i in range(0, 12, 2))


def is_ipv4(s):
    try:
        ipaddress.IPv4Address(str(s))
        return True
    except Exception:
        return False


def is_netmask(s):
    """是否为合法的连续 IPv4 子网掩码。"""
    try:
        ip = ipaddress.IPv4Address(str(s))
        bits = bin(int(ip))[2:].zfill(32)
        return "01" not in bits
    except Exception:
        return False


def mask_to_prefix(mask):
    return ipaddress.IPv4Network("0.0.0.0/" + str(mask)).prefixlen


def lease_seconds(value):
    """把租约字符串换算成秒；infinite 返回 0，无法解析返回默认 12 小时。"""
    s = str(value or "").strip()
    if s == "infinite":
        return 0
    m = re.fullmatch(r"(\d+)([smhdw])", s)
    if not m:
        return 12 * 3600
    n = int(m.group(1))
    unit = m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def lan_network(cfg):
    """返回 LAN 网段 ipaddress.IPv4Network。"""
    lan = cfg["network"]["lan"]
    return ipaddress.IPv4Network("%s/%s" % (lan["ip"], lan["netmask"]), strict=False)


def in_lan(cfg, ipstr):
    try:
        return ipaddress.IPv4Address(str(ipstr)) in lan_network(cfg)
    except Exception:
        return False


def pool_iface(cfg, pool):
    """返回 VLAN 地址池对应的网卡名。"""
    if pool.get("interface"):
        return str(pool["interface"])
    if pool.get("vlan_id"):
        parent = pool.get("parent") or cfg["network"]["lan"].get("interface") or ""
        if parent:
            return "%s.%s" % (parent, pool["vlan_id"])
    return ""


def lan_networks(cfg):
    """返回所有 LAN 网段（默认池 + 启用的 VLAN 池）。"""
    nets = []
    try:
        nets.append(lan_network(cfg))
    except Exception:
        pass
    for p in (cfg.get("dhcp", {}).get("pools") or []):
        if not p.get("enabled", True) or p.get("type") != "vlan":
            continue
        try:
            nets.append(ipaddress.IPv4Network(
                "%s/%s" % (p["ip"], p.get("netmask") or "255.255.255.0"), strict=False))
        except Exception:
            pass
    return nets


def lan_interfaces(cfg):
    """返回所有需要 DHCP/转发/监控的 LAN 网卡（默认 + VLAN）。"""
    ifaces = []
    primary = cfg.get("network", {}).get("lan", {}).get("interface", "")
    if primary:
        ifaces.append(primary)
    for p in (cfg.get("dhcp", {}).get("pools") or []):
        if p.get("enabled", True) and p.get("type") == "vlan":
            name = pool_iface(cfg, p)
            if name and name not in ifaces:
                ifaces.append(name)
    return ifaces


def parse_excludes(text, net):
    """解析排除地址文本：单 IP 或 IP 范围（a-b），逗号/空格分隔。

    返回 [(start_int, end_int)]；格式错误抛 ValueError。
    """
    out = []
    for token in re.split(r"[,，;\s]+", str(text or "").strip()):
        if not token:
            continue
        parts = token.split("-", 1)
        try:
            a = ipaddress.IPv4Address(parts[0].strip())
            b = ipaddress.IPv4Address(parts[1].strip()) if len(parts) == 2 else a
        except Exception:
            raise ValueError("排除地址格式错误：%s" % token)
        if a not in net or b not in net:
            raise ValueError("排除地址 %s 不在地址池网段内" % token)
        if int(a) > int(b):
            raise ValueError("排除地址范围起止颠倒：%s" % token)
        out.append((int(a), int(b)))
    return out


def subtract_ip_ranges(start, end, excludes):
    """从 [start,end] 中扣除排除区间，返回剩余区间整数列表。"""
    segs = [(int(start), int(end))]
    for a, b in excludes:
        nxt = []
        for s, e in segs:
            if b < s or a > e:
                nxt.append((s, e))
                continue
            if s < a:
                nxt.append((s, a - 1))
            if e > b:
                nxt.append((b + 1, e))
        segs = nxt
    return segs


def validate(cfg):
    """校验配置，返回 (错误列表, 警告列表)，全部为中文。"""
    errors, warnings = [], []
    web = cfg.get("web", {})
    try:
        port = int(web.get("port", 80))
        if not 1 <= port <= 65535:
            errors.append("管理端口必须在 1-65535 之间")
    except (TypeError, ValueError):
        errors.append("管理端口必须是数字")

    wan = cfg.get("network", {}).get("wan", {})
    lan = cfg.get("network", {}).get("lan", {})
    wan_if = (wan.get("interface") or "").strip()
    lan_if = (lan.get("interface") or "").strip()
    if cfg.get("setup_done"):
        if not lan_if:
            errors.append("请选择 LAN 内网网卡")
        elif lan_if == wan_if:
            errors.append("WAN 网卡与 LAN 网卡不能是同一块网卡")
        if wan.get("mode") == "dhcp" and not wan_if:
            errors.append("WAN 使用 DHCP 自动获取时必须选择 WAN 网卡")
        if wan.get("mode") == "static" and not wan_if:
            errors.append("WAN 使用静态地址时必须选择 WAN 网卡")
        if wan.get("mode") == "pppoe" and not wan_if:
            errors.append("WAN 使用 PPPoE 拨号时必须选择 WAN 网卡")
    if not is_ipv4(lan.get("ip")):
        errors.append("LAN 地址不是合法的 IPv4 地址")
    if not is_netmask(lan.get("netmask")):
        errors.append("LAN 子网掩码不是合法的连续掩码")

    mode = wan.get("mode", "none")
    if mode not in ("none", "dhcp", "static", "pppoe"):
        errors.append("WAN 模式无效")
    if mode == "static":
        if not is_ipv4(wan.get("ip")):
            errors.append("WAN 静态 IP 不是合法的 IPv4 地址")
        if not is_netmask(wan.get("netmask")):
            errors.append("WAN 子网掩码不是合法的连续掩码")
        if not is_ipv4(wan.get("gateway")):
            errors.append("WAN 网关不是合法的 IPv4 地址")
    if mode == "pppoe" and cfg.get("setup_done") and not wan.get("pppoe_user"):
        errors.append("PPPoE 拨号需要填写宽带账号")
    if wan.get("dns"):
        for d in wan["dns"]:
            if not is_ipv4(d):
                errors.append("WAN DNS 地址无效：%s" % d)

    dhcp = cfg.get("dhcp", {})
    if dhcp.get("enabled"):
        if not is_ipv4(dhcp.get("start")) or not is_ipv4(dhcp.get("end")):
            errors.append("DHCP 地址池的起始/结束地址无效")
        else:
            net = lan_network(cfg)
            s = ipaddress.IPv4Address(dhcp["start"])
            e = ipaddress.IPv4Address(dhcp["end"])
            if s not in net or e not in net:
                errors.append("DHCP 地址池必须位于 LAN 网段 %s 内" % net)
            elif s > e:
                errors.append("DHCP 地址池起始地址不能大于结束地址")
        if not LEASE_PAT.match(str(dhcp.get("lease_time", ""))):
            errors.append("租约时间格式无效（如 1h / 12h / 1d / infinite）")
        if dhcp.get("send_gateway") and dhcp.get("gateway") and not is_ipv4(dhcp.get("gateway")):
            errors.append("DHCP 下发的网关地址无效：%s" % dhcp.get("gateway"))
        for d in dhcp.get("dns_servers", []):
            if not is_ipv4(d):
                errors.append("DHCP 下发的 DNS 地址无效：%s" % d)
        seen = set()
        pools = dhcp.get("pools") or []
        pool_map = {}
        if not isinstance(pools, list):
            errors.append("DHCP 附加地址池格式错误")
            pools = []
        for p in pools:
            if not isinstance(p, dict):
                errors.append("DHCP 附加地址池配置项格式错误")
                continue
            pid = str(p.get("id") or "").strip()
            name = str(p.get("name") or "").strip()
            ptype = str(p.get("type") or "tagged").lower()
            if not name:
                errors.append("附加地址池名称不能为空")
            if pid:
                if pid in pool_map:
                    errors.append("附加地址池 ID 重复：%s" % pid)
                pool_map[pid] = p
            if ptype not in ("tagged", "vlan"):
                errors.append("地址池“%s”的类型无效（tagged/vlan）" % (name or pid))
                continue
            net = None
            if ptype == "vlan":
                if not is_ipv4(p.get("ip")) or not is_netmask(p.get("netmask")):
                    errors.append("地址池“%s”的网关地址/掩码无效" % (name or pid))
                else:
                    net = ipaddress.IPv4Network(
                        "%s/%s" % (p["ip"], p["netmask"]), strict=False)
                vlan = p.get("vlan_id")
                if vlan not in (None, ""):
                    try:
                        v = int(vlan)
                        if not 1 <= v <= 4094:
                            errors.append("地址池“%s”的 VLAN ID 必须在 1-4094" % (name or pid))
                    except (TypeError, ValueError):
                        errors.append("地址池“%s”的 VLAN ID 无效" % (name or pid))
                elif not p.get("interface"):
                    errors.append("地址池“%s”需要 VLAN ID 或接口名" % (name or pid))
            else:
                net = lan_network(cfg)
            if not is_ipv4(p.get("start")) or not is_ipv4(p.get("end")):
                errors.append("地址池“%s”的起始/结束地址无效" % (name or pid))
            elif net is not None:
                s = ipaddress.IPv4Address(p["start"])
                e = ipaddress.IPv4Address(p["end"])
                if s not in net or e not in net:
                    errors.append("地址池“%s”的范围必须位于 %s 内" % (name or pid, net))
                elif s > e:
                    errors.append("地址池“%s”起始地址不能大于结束地址" % (name or pid))
            if p.get("gateway") and not is_ipv4(p.get("gateway")):
                errors.append("地址池“%s”的网关地址无效" % (name or pid))
            for d in p.get("dns_servers") or []:
                if not is_ipv4(d):
                    errors.append("地址池“%s”的 DNS 地址无效：%s" % (name or pid, d))
            if p.get("lease_time") and not LEASE_PAT.match(str(p.get("lease_time"))):
                errors.append("地址池“%s”的租约时间格式无效" % (name or pid))
            if net is not None:
                try:
                    parse_excludes(p.get("exclude"), net)
                except ValueError as e:
                    errors.append("地址池“%s”：%s" % (name or pid, e))
            for line in str(p.get("extra_options") or "").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "," not in line:
                    errors.append("地址池“%s”的自定义选项格式应为“代码,值”：%s" % (name or pid, line))

        for it in dhcp.get("static_leases", []):
            m = mac_norm(it.get("mac"))
            if not m:
                errors.append("静态分配中的 MAC 地址无效")
                continue
            if m in seen:
                errors.append("静态分配中存在重复的 MAC 地址 %s" % m)
            seen.add(m)
            pool_id = str(it.get("pool") or "").strip()
            target = lan_network(cfg)
            if pool_id:
                p = pool_map.get(pool_id)
                if not p:
                    errors.append("静态分配引用了不存在的地址池：%s" % pool_id)
                elif (p.get("type") or "tagged") == "vlan" and is_ipv4(p.get("ip")):
                    try:
                        target = ipaddress.IPv4Network(
                            "%s/%s" % (p["ip"], p.get("netmask") or "255.255.255.0"),
                            strict=False)
                    except Exception:
                        pass
            if not is_ipv4(it.get("ip")) or ipaddress.IPv4Address(it["ip"]) not in target:
                errors.append("静态分配 IP 不在对应地址池网段内：%s" % it.get("ip"))

    dns = cfg.get("dns", {})
    for u in dns.get("upstreams", []):
        if not is_ipv4(u):
            errors.append("上游 DNS 地址无效：%s" % u)

    m = cfg.get("monitor", {})
    try:
        if not 0.5 <= float(m.get("interval", 2.0)) <= 60:
            errors.append("采样间隔必须在 0.5-60 秒之间")
    except (TypeError, ValueError):
        errors.append("采样间隔必须是数字")

    gateways = cfg.get("gateways") or []
    if not isinstance(gateways, list):
        errors.append("出口网关配置必须是列表")
        gateways = []
    seen_ids = set()
    for gw in gateways:
        if not isinstance(gw, dict):
            errors.append("出口网关配置项格式错误")
            continue
        name = (gw.get("name") or "").strip()
        gid = (gw.get("id") or "").strip()
        if not name:
            errors.append("出口网关名称不能为空")
        if gid and gid in seen_ids:
            errors.append("出口网关 ID 重复：%s" % gid)
        seen_ids.add(gid)
        if not is_ipv4(gw.get("ip")):
            errors.append("出口网关 %s 的 IP 地址无效" % (name or gw.get("ip", "")))
        method = (gw.get("method") or "auto").lower()
        if method not in ("auto", "snmp", "ssh", "http", "demo"):
            errors.append("出口网关 %s 的采集方式无效" % name)
        if method == "snmp" and not (gw.get("sessions_oid") or gw.get("hosts_oid")):
            errors.append("出口网关 %s 使用 SNMP 时需填写至少一个 OID" % name)
        if method == "ssh" and not (gw.get("sessions_cmd") or gw.get("hosts_cmd")):
            errors.append("出口网关 %s 使用 SSH 时需填写至少一条命令" % name)
        if method == "http" and not (gw.get("http_url") or "").startswith(("http://", "https://")):
            errors.append("出口网关 %s 使用 HTTP 时需填写 http(s) 地址" % name)

    if wan_if and lan_if and wan_if == lan_if:
        errors.append("WAN 网卡与 LAN 网卡不能是同一块网卡")

    if cfg.get("firewall", {}).get("enabled") is False:
        warnings.append("防火墙已关闭：流量计数与 NAT 依赖 nftables 规则，关闭后内网将无法上网且无法统计流量")

    return errors, warnings


def load(path):
    """加载配置。返回 (cfg, 状态字符串)。"""
    if not os.path.exists(path):
        return new_default(), "new"
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        cfg = deep_merge(DEFAULTS, raw)
        return cfg, "ok"
    except Exception as e:
        return new_default(), "error: %s" % e


def save(path, cfg):
    """原子化写入配置。使用确定性临时文件名，避免依赖 tempfile。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
