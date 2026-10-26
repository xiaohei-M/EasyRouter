# -*- coding: utf-8 -*-
"""HTTP API 处理函数（全部返回 JSON，错误信息为中文）。"""
import base64
import binascii
import ipaddress
import threading
import time
import urllib.parse
import uuid

from . import VERSION, APP_NAME, APP_NAME_EN
from . import auth as auth_mod
from . import config as config_mod
from . import gateways as gateways_mod
from . import leases as leases_mod
from . import upgrade as upgrade_mod
from .httpd import set_session_cookie


def register(app):
    r = app.router
    r.add("GET", "/api/health", api_health, auth=False)
    r.add("GET", "/api/status", api_status, auth=False)
    r.add("GET", "/api/interfaces", api_interfaces, auth=False)
    r.add("POST", "/api/clientlog", api_clientlog, auth=False)
    r.add("POST", "/api/setup", api_setup, auth=False)
    r.add("POST", "/api/login", api_login, auth=False)
    r.add("POST", "/api/logout", api_logout)
    r.add("GET", "/api/overview", api_overview)
    r.add("GET", "/api/devices", api_devices)
    r.add("GET", "/api/traffic", api_traffic)
    r.add("GET", "/api/sessions", api_sessions)
    r.add("GET", "/api/apps", api_apps)
    r.add("GET", "/api/leases", api_leases)
    r.add("POST", "/api/leases/bind", api_leases_bind)
    r.add("POST", "/api/leases/unbind", api_leases_unbind)
    r.add("GET", "/api/settings", api_settings)
    r.add("POST", "/api/settings", api_settings_save)
    r.add("GET", "/api/backup", api_backup)
    r.add("POST", "/api/backup/restore", api_backup_restore)
    r.add("GET", "/api/gateways", api_gateways)
    r.add("POST", "/api/gateways/save", api_gateways_save)
    r.add("POST", "/api/gateways/probe", api_gateways_probe)
    r.add("POST", "/api/gateways/detect", api_gateways_detect)
    r.add("POST", "/api/devices/alias", api_alias)
    r.add("POST", "/api/devices/wake", api_wake)
    r.add("POST", "/api/system/action", api_system_action)
    r.add("GET", "/api/system/upgrade", api_upgrade_status)
    r.add("POST", "/api/system/upgrade", api_upgrade_install)
    r.add("POST", "/api/system/upgrade/restore", api_upgrade_restore)
    r.add("POST", "/api/password", api_password)
    r.add("GET", "/api/logs", api_logs)


# ---------------- 基础 ----------------
def api_health(app, params, body, qs):
    return {"ok": True, "name": APP_NAME_EN, "version": VERSION}


def api_clientlog(app, params, body, qs):
    """接收浏览器端脚本错误，写入服务端日志便于排查。"""
    b = body or {}
    item = {
        "ts": int(time.time()),
        "kind": str(b.get("kind") or "error")[:32],
        "message": str(b.get("message") or "")[:800],
        "stack": str(b.get("stack") or "")[:5000],
        "url": str(b.get("url") or "")[:500],
        "ua": str(b.get("ua") or "")[:300],
        "ip": app._client_ip(),
    }
    app.client_errors.append(item)
    app.log.warning("[前端] %s: %s | %s | UA=%s",
                    item["kind"], item["message"],
                    item["stack"].replace("\n", " | ")[:1200], item["ua"])
    return {"ok": True}


def api_status(app, params, body, qs):
    token = app._request_token()
    return {
        "ok": True,
        "name": APP_NAME,
        "name_en": APP_NAME_EN,
        "version": VERSION,
        "setup_done": bool(app.cfg.get("setup_done")),
        "logged_in": bool(token and app.auth.valid(token)),
        "backend": app.backend.name,
    }


def api_interfaces(app, params, body, qs):
    try:
        ifaces = app.backend.interface_list()
    except Exception:
        app.log.exception("读取网卡列表失败")
        ifaces = []
    ifaces = [i for i in ifaces if not i.get("is_loopback")]
    return {"ok": True, "interfaces": ifaces}


def _auto_dhcp_range(cfg):
    """当 LAN 网段变化时自动把 DHCP 地址池调整到新网段 .100-.199。"""
    net = config_mod.lan_network(cfg)
    base = str(net.network_address)
    octets = base.split(".")
    start = "%s.%s.%s.100" % (octets[0], octets[1], octets[2])
    end = "%s.%s.%s.199" % (octets[0], octets[1], octets[2])
    if net.prefixlen >= 30:
        start = str(net.network_address + 1)
        end = str(net.broadcast_address - 1)
    return start, end


def api_setup(app, params, body, qs):
    if app.cfg.get("setup_done"):
        return {"ok": False, "error": "系统已完成安装，如需修改请到“网络设置”页面", "_status": 400}
    b = body or {}
    password = str(b.get("admin_password") or "")
    if len(password) < 6:
        return {"ok": False, "error": "管理员密码至少需要 6 位", "_status": 400}
    lan_iface = str(b.get("lan_interface") or "").strip()
    wan_iface = str(b.get("wan_interface") or "").strip()
    if not lan_iface:
        return {"ok": False, "error": "请选择 LAN 内网网卡", "_status": 400}
    if wan_iface and wan_iface == lan_iface:
        return {"ok": False, "error": "WAN 网卡与 LAN 网卡不能是同一块网卡", "_status": 400}
    lan_ip = str(b.get("lan_ip") or "192.168.1.1").strip()
    lan_mask = str(b.get("lan_netmask") or "255.255.255.0").strip()
    wan_mode = str(b.get("wan_mode") or "none").strip()
    if wan_mode not in ("none", "dhcp", "static", "pppoe"):
        wan_mode = "none"
    if not config_mod.is_ipv4(lan_ip):
        return {"ok": False, "error": "LAN 地址不是合法的 IPv4 地址", "_status": 400}
    if not config_mod.is_netmask(lan_mask):
        return {"ok": False, "error": "LAN 子网掩码不是合法的连续掩码", "_status": 400}

    new = config_mod.deep_merge(app.cfg, {
        "setup_done": True,
        "admin": {"password_hash": auth_mod.hash_password(password), "username": "admin"},
        "network": {
            "wan": {"interface": wan_iface, "mode": wan_mode},
            "lan": {"interface": lan_iface, "ip": lan_ip, "netmask": lan_mask},
        },
        "dhcp": {"send_gateway": bool(b.get("send_gateway", True)),
                 "gateway": str(b.get("dhcp_gateway") or "").strip()},
    })
    # 自动调整 DHCP 地址池与 LAN 地址冲突
    net = config_mod.lan_network(new)
    if not (ipaddress.IPv4Address(new["dhcp"]["start"]) in net
            and ipaddress.IPv4Address(new["dhcp"]["end"]) in net):
        start, end = _auto_dhcp_range(new)
        new["dhcp"]["start"] = start
        new["dhcp"]["end"] = end

    errors, warnings = config_mod.validate(new)
    if errors:
        return {"ok": False, "errors": errors, "_status": 400}

    old = app.cfg
    config_mod.save(app.conf_path, new)
    app.cfg = new
    app.monitor.update_cfg(new)
    app.gateway_mgr.update_cfg(new)
    e, w, applied = app.backend.apply(old, new)

    token = app.auth.create()
    result = {
        "ok": True,
        "message": "安装完成！%s 已就绪" % APP_NAME,
        "applied": applied,
        "warnings": warnings + w,
        "errors": e,
        "lan_url": "http://%s" % (new["network"]["lan"]["ip"]),
    }
    set_session_cookie(result, token, app.auth.ttl)
    return result


def api_login(app, params, body, qs):
    ip = app._client_ip()
    ok_wait, wait = app.limiter.check(ip)
    if not ok_wait:
        return {"ok": False, "error": "登录失败次数过多，请 %d 秒后再试" % wait, "_status": 429}
    b = body or {}
    password = str(b.get("password") or "")
    if not auth_mod.verify_password(password, app.cfg.get("admin", {}).get("password_hash", "")):
        app.limiter.fail(ip)
        return {"ok": False, "error": "密码错误", "_status": 400}
    app.limiter.ok(ip)
    token = app.auth.create()
    result = {"ok": True, "username": app.cfg["admin"].get("username", "admin")}
    set_session_cookie(result, token, app.auth.ttl)
    return result


def api_logout(app, params, body, qs):
    token = app._request_token()
    app.auth.destroy(token)
    result = {"ok": True}
    set_session_cookie(result, "", {"Max-Age": "0", "Path": "/", "HttpOnly": "", "SameSite": "Lax"})
    return result


# ---------------- 监控数据 ----------------
def api_overview(app, params, body, qs):
    snap = app.monitor.snapshot(180)
    cfg = app.cfg
    devices = snap["devices"]
    online = [d for d in devices if d["online"]]
    top = sorted(devices, key=lambda d: -(d["rx_rate"] + d["tx_rate"]))[:8]
    ifaces = [{"name": k, **v} for k, v in snap["interfaces"].items() if k != "lo"]
    ifaces.sort(key=lambda x: x["name"])
    dhcp = cfg.get("dhcp", {})
    active_leases = sum(1 for d in devices if d.get("lease_expiry", 0) > time.time())
    return {
        "ok": True,
        "version": VERSION,
        "boot_time": snap["boot_time"],
        "wan": snap["wan"],
        "lan": snap["lan"],
        "system": snap["system"],
        "sessions": snap["sessions"],
        "dhcp": {
            "enabled": dhcp.get("enabled", True),
            "range": "%s ~ %s" % (dhcp.get("start", ""), dhcp.get("end", "")),
            "lease_time": dhcp.get("lease_time", "12h"),
            "send_gateway": dhcp.get("send_gateway", True),
            "active_leases": active_leases,
            "upstreams": cfg.get("dns", {}).get("upstreams", []),
        },
        "online_count": len(online),
        "device_count": len(devices),
        "interfaces": ifaces,
        "history": snap["history"],
        "top_devices": [
            {"ip": d["ip"], "name": d["name"], "mac": d["mac"], "kind": d["kind"],
             "rx_rate": d["rx_rate"], "tx_rate": d["tx_rate"], "online": d["online"]}
            for d in top
        ],
    }


def _apply_query_filters(app, qs):
    qs_map = urllib.parse.parse_qs(qs or "")
    sort = (qs_map.get("sort") or ["ip"])[0]
    if sort not in ("ip", "mac", "name", "traffic", "sessions"):
        sort = "ip"
    query = (qs_map.get("q") or [""])[0].strip().lower()
    devices = app.monitor.devices_sorted(sort)
    if query:
        devices = [d for d in devices if query in d["name"].lower()
                   or query in d["ip"].lower() or query in d["mac"].lower()]
    return devices


def api_devices(app, params, body, qs):
    devices = _apply_query_filters(app, qs)
    return {
        "ok": True,
        "devices": devices,
        "total": len(devices),
        "online": sum(1 for d in devices if d["online"]),
    }


def api_traffic(app, params, body, qs):
    snap = app.monitor.snapshot(300)
    ifaces = [{"name": k, **v} for k, v in snap["interfaces"].items() if k != "lo"]
    ifaces.sort(key=lambda x: x["name"])
    devices = app.monitor.devices_sorted("ip")
    totals = {"rx": sum(d["rx_total"] for d in devices),
              "tx": sum(d["tx_total"] for d in devices)}
    return {
        "ok": True,
        "interfaces": ifaces,
        "devices": devices,
        "history": snap["history"],
        "totals": totals,
        "wan": snap["wan"],
    }


def api_sessions(app, params, body, qs):
    snap = app.monitor.snapshot(180)
    sessions = snap["sessions"]
    devices = app.monitor.devices_sorted("sessions")
    with_sess = [d for d in devices if d["sessions"] > 0]
    remote = sessions.get("remote") or {}
    remote_top = sorted(remote.items(), key=lambda kv: -kv[1])[:15]
    return {
        "ok": True,
        "total": sessions["total"],
        "lan_total": sessions.get("lan_total", 0),
        "tcp": sessions["tcp"],
        "udp": sessions["udp"],
        "icmp": sessions["icmp"],
        "other": sessions["other"],
        "devices": [
            {"ip": d["ip"], "name": d["name"], "mac": d["mac"], "kind": d["kind"],
             "sessions": d["sessions"], "rx_rate": d["rx_rate"], "tx_rate": d["tx_rate"],
             "online": d["online"]}
            for d in with_sess
        ],
        "remote_top": [{"ip": ip, "count": n} for ip, n in remote_top],
        "history": snap["sess_history"],
    }


def api_apps(app, params, body, qs):
    snap = app.monitor.snapshot(1)
    apps = snap.get("apps", [])
    devices = set()
    for a in apps:
        devices.update(d["ip"] for d in a.get("devices", []))
    return {
        "ok": True,
        "apps": apps,
        "total_apps": len(apps),
        "active_devices": len(devices),
        "total_queries": sum(a.get("queries", 0) for a in apps),
    }


def api_leases(app, params, body, qs):
    qs_map = urllib.parse.parse_qs(qs or "")
    q = (qs_map.get("q") or [""])[0]
    status = (qs_map.get("status") or ["all"])[0]
    data = leases_mod.list_leases(app, q, status)
    data["ok"] = True
    data["auto_bind"] = bool(app.cfg["dhcp"].get("auto_bind_first"))
    return data


def api_leases_bind(app, params, body, qs):
    b = body or {}
    ok, msg = leases_mod.bind_lease(app, b.get("mac"), b.get("ip"), b.get("name") or "")
    return {"ok": ok, "message": msg, "error": "" if ok else msg,
            "_status": 200 if ok else 400}


def api_leases_unbind(app, params, body, qs):
    b = body or {}
    ok, msg = leases_mod.unbind_lease(app, b.get("mac"))
    return {"ok": ok, "message": msg, "error": "" if ok else msg,
            "_status": 200 if ok else 400}


# ---------------- 设置 ----------------
def _redacted_cfg(cfg):
    out = config_mod.deep_merge({}, cfg)
    out.get("admin", {}).pop("password_hash", None)
    if out.get("network", {}).get("wan", {}).get("pppoe_password"):
        out["network"]["wan"]["pppoe_password"] = ""
    for gw in out.get("gateways", []) or []:
        if gw.get("password"):
            gw["password"] = ""
            gw["has_password"] = True
        if gw.get("http_password"):
            gw["http_password"] = ""
            gw["has_http_password"] = True
    return out


def api_settings(app, params, body, qs):
    return {"ok": True, "config": _redacted_cfg(app.cfg),
            "services": app.monitor.snapshot(1)["services"],
            "backend": app.backend.name}


def api_backup(app, params, body, qs):
    return {"ok": True, "backup": app.export_backup()}


def api_backup_restore(app, params, body, qs):
    b = body or {}
    data = b.get("backup") if isinstance(b.get("backup"), dict) else b
    ok, errors = app.restore_backup(data)
    return {"ok": ok, "errors": errors,
            "message": "备份已恢复" if ok else "恢复失败",
            "_status": 200 if ok else 400}


def api_settings_save(app, params, body, qs):
    b = body or {}
    if not isinstance(b, dict):
        return {"ok": False, "error": "参数格式错误", "_status": 400}
    # PPPoE 密码留空表示保持原密码
    wan_part = b.get("network", {}).get("wan")
    if wan_part is not None and not (wan_part.get("pppoe_password") or "").strip():
        wan_part.pop("pppoe_password", None)
    # 防止安装标志被关闭
    b.pop("setup_done", None)
    b.pop("admin", None)

    new = config_mod.deep_merge(app.cfg, b)
    errors, warnings = config_mod.validate(new)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "_status": 400}

    old = app.cfg
    config_mod.save(app.conf_path, new)
    app.cfg = new
    app.monitor.update_cfg(new)
    app.gateway_mgr.update_cfg(new)
    e, w, applied = app.backend.apply(old, new)
    warnings += w
    if old.get("web", {}) != new.get("web", {}):
        warnings.append("管理端口/监听地址的修改将在服务重启后生效")
    return {"ok": True, "applied": applied, "warnings": warnings, "errors": e}


# ---------------- 出口网关探针 ----------------
def api_gateways(app, params, body, qs):
    snap = app.gateway_mgr.snapshot()
    return {"ok": True, "gateways": snap["gateways"], "running": snap["running"],
            "last_run": snap["last_run"], "methods": gateways_mod.METHOD_LABELS}


def api_gateways_save(app, params, body, qs):
    b = body or {}
    gws = b.get("gateways")
    if not isinstance(gws, list):
        return {"ok": False, "error": "网关列表格式错误", "_status": 400}
    old_map = {g.get("id"): g for g in app.cfg.get("gateways", [])}
    cleaned = []
    for raw in gws[:32]:
        if not isinstance(raw, dict):
            continue
        g = {}
        g["id"] = str(raw.get("id") or "").strip() or ("gw-" + uuid.uuid4().hex[:8])
        g["name"] = str(raw.get("name") or "").strip()[:40]
        g["ip"] = str(raw.get("ip") or "").strip()
        g["method"] = str(raw.get("method") or "auto").lower()
        for k in ("snmp_community", "sessions_oid", "hosts_oid",
                  "username", "sessions_cmd", "hosts_cmd",
                  "http_url", "http_user", "sessions_json", "hosts_json"):
            if raw.get(k) is not None:
                g[k] = str(raw.get(k)).strip()
        for k in ("password", "http_password"):
            val = str(raw.get(k) or "")
            old_val = (old_map.get(g["id"]) or {}).get(k) or ""
            g[k] = val if val else old_val
        cleaned.append(g)

    new_cfg = config_mod.deep_merge(app.cfg, {"gateways": cleaned})
    errors, warnings = config_mod.validate(new_cfg)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "_status": 400}
    config_mod.save(app.conf_path, new_cfg)
    app.cfg = new_cfg
    app.monitor.update_cfg(new_cfg)
    app.gateway_mgr.update_cfg(new_cfg)
    threading.Thread(target=app.gateway_mgr.probe_all, daemon=True).start()
    return {"ok": True, "message": "网关配置已保存，正在探测…", "count": len(cleaned)}


def api_gateways_probe(app, params, body, qs):
    b = body or {}
    gid = str(b.get("id") or "").strip()
    if gid:
        threading.Thread(target=app.gateway_mgr.probe_one, args=(gid,), daemon=True).start()
        return {"ok": True, "message": "正在探测该网关…"}
    threading.Thread(target=app.gateway_mgr.probe_all, daemon=True).start()
    return {"ok": True, "message": "正在探测全部网关…"}


def api_gateways_detect(app, params, body, qs):
    b = body or {}
    ip = str(b.get("ip") or "").strip()
    if not config_mod.is_ipv4(ip):
        return {"ok": False, "error": "请输入合法的网关 IP 地址", "_status": 400}
    det = gateways_mod.detect_gateway(ip, app.log)
    return {"ok": True, "detect": det}


# ---------------- 设备操作 ----------------
def api_alias(app, params, body, qs):
    b = body or {}
    mac = str(b.get("mac") or "")
    name = str(b.get("name") or "").strip()
    if len(name) > 32:
        return {"ok": False, "error": "设备名称最长 32 个字符", "_status": 400}
    ok, msg = app.monitor.set_alias(mac, name)
    if not ok:
        return {"ok": False, "error": msg, "_status": 400}
    return {"ok": True, "message": "设备名称已更新" if name else "已恢复自动命名"}


def api_wake(app, params, body, qs):
    b = body or {}
    mac = config_mod.mac_norm(b.get("mac"))
    if not mac:
        return {"ok": False, "error": "MAC 地址无效", "_status": 400}
    ok, msg = app.backend.wake(mac)
    return {"ok": ok, "message": msg}


# ---------------- 系统 ----------------
def api_system_action(app, params, body, qs):
    b = body or {}
    action = str(b.get("action") or "")
    confirm = str(b.get("confirm") or "")
    if action == "reboot" and confirm == "确认重启":
        cmd = app.cfg.get("sys", {}).get("reboot_cmd", "systemctl reboot")
        msg = "系统将在 3 秒后重启"
    elif action == "poweroff" and confirm == "确认关机":
        cmd = app.cfg.get("sys", {}).get("poweroff_cmd", "systemctl poweroff")
        msg = "系统将在 3 秒后关机"
    else:
        return {"ok": False, "error": "需要输入确认文字后才能执行", "_status": 400}
    if app.backend.name == "demo":
        return {"ok": True, "message": "演示模式：已跳过执行「%s」" % cmd}
    def _run():
        time.sleep(3)
        import os
        os.system(cmd)
    threading.Thread(target=_run, daemon=True).start()
    app.log.warning("收到指令：%s", cmd)
    return {"ok": True, "message": msg}


def api_upgrade_status(app, params, body, qs):
    data = upgrade_mod.status(app)
    data["ok"] = True
    return data


def api_upgrade_install(app, params, body, qs):
    b = body or {}
    raw = b.get("data") or b.get("file") or ""
    if not isinstance(raw, str) or len(raw) > 17 * 1024 * 1024:
        return {"ok": False, "error": "升级包为空或超过 12MB", "_status": 400}
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "升级包编码无效", "_status": 400}
    try:
        ok, msg, version = upgrade_mod.install(app, data)
    except upgrade_mod.UpgradeError as e:
        return {"ok": False, "error": str(e), "_status": 400}
    return {"ok": ok, "message": msg, "version": version,
            "restarting": bool(ok and not app.demo)}


def api_upgrade_restore(app, params, body, qs):
    b = body or {}
    ok, msg = upgrade_mod.restore_backup(app, b.get("name") or "")
    return {"ok": ok, "message": msg, "error": "" if ok else msg,
            "_status": 200 if ok else 400}


def api_password(app, params, body, qs):
    b = body or {}
    old_pw = str(b.get("old_password") or "")
    new_pw = str(b.get("new_password") or "")
    if len(new_pw) < 6:
        return {"ok": False, "error": "新密码至少需要 6 位", "_status": 400}
    if not auth_mod.verify_password(old_pw, app.cfg["admin"].get("password_hash", "")):
        return {"ok": False, "error": "原密码不正确", "_status": 400}
    app.cfg["admin"]["password_hash"] = auth_mod.hash_password(new_pw)
    config_mod.save(app.conf_path, app.cfg)
    return {"ok": True, "message": "管理密码已修改"}


def api_logs(app, params, body, qs):
    services = app.monitor.snapshot(1)["services"]
    dnsmasq = (services.get("dnsmasq") or {}).get("log_tail", [])
    return {"ok": True, "app": list(app.log_tail), "dnsmasq": dnsmasq[-120:],
            "client": list(app.client_errors)}
