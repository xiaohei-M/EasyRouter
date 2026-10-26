# -*- coding: utf-8 -*-
"""出口网关探针。

上游路由器/光猫的会话表和在线主机表不在本机 conntrack 中，
必须逐台访问设备采集。本模块支持：

  * SNMP v2c GET（纯标准库实现 BER 编解码，适合设备暴露计数 OID 的场景）
  * SSH 远程命令（适合 OpenWrt / 可登录的路由器，读取 conntrack 与 DHCP 租约）
  * HTTP JSON 接口（设备提供 API 时按字段路径取值）
  * 自动探测：扫描常见端口，识别 HTTP 标题、SSH 横幅、SNMP sysDescr，
    并给出推荐的采集方式
"""
import json
import re
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque

from . import config as config_mod

COMMON_PORTS = [22, 80, 443, 161, 8080, 8443, 23]
METHOD_LABELS = {
    "auto": "自动探测", "snmp": "SNMP", "ssh": "SSH 命令",
    "http": "HTTP 接口", "demo": "演示",
}


# ============================================================
#  SNMP v2c（最小实现：GET 单个 OID）
# ============================================================
def _ber_len(n):
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag, content):
    return bytes([tag]) + _ber_len(len(content)) + content


def _ber_int(value):
    if value == 0:
        raw = b"\x00"
    else:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if raw[0] & 0x80:
            raw = b"\x00" + raw
    return _tlv(0x02, raw)


def _ber_oid(oid):
    parts = [int(x) for x in str(oid).strip().strip(".").split(".") if x != ""]
    if len(parts) < 2 or parts[0] > 2 or (parts[0] < 2 and parts[1] > 39):
        raise ValueError("OID 格式无效")
    out = bytearray([40 * parts[0] + parts[1]])
    for sub in parts[2:]:
        if sub < 0:
            raise ValueError("OID 子项不能为负数")
        chunks = [sub & 0x7F]
        sub >>= 7
        while sub:
            chunks.append((sub & 0x7F) | 0x80)
            sub >>= 7
        out += bytes(reversed(chunks))
    return _tlv(0x06, bytes(out))


def _ber_octets(text):
    if isinstance(text, bytes):
        return _tlv(0x04, text)
    return _tlv(0x04, text.encode("utf-8"))


def _read_tlv(data, pos):
    if pos + 2 > len(data):
        raise ValueError("SNMP 数据不完整")
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        n = length & 0x7F
        if n == 0 or n > 4 or pos + n > len(data):
            raise ValueError("SNMP 长度字段无效")
        length = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    end = pos + length
    if end > len(data):
        raise ValueError("SNMP 数据被截断")
    return tag, data[pos:end], end


def _decode_value(tag, content):
    if tag == 0x02:
        return int.from_bytes(content, "big", signed=True)
    if tag == 0x04:
        return content.decode("utf-8", "replace")
    if tag == 0x05:
        return None
    if tag == 0x06:
        if not content:
            return ""
        first = content[0]
        parts = [str(first // 40), str(first % 40)]
        val = 0
        for b in content[1:]:
            val = (val << 7) | (b & 0x7F)
            if not b & 0x80:
                parts.append(str(val))
                val = 0
        return ".".join(parts)
    if tag in (0x41, 0x42, 0x43, 0x46):  # Counter32 / Gauge32 / TimeTicks / Counter64
        return int.from_bytes(content, "big")
    if tag == 0x40:  # IpAddress
        return ".".join(str(b) for b in content)
    return content.hex()


def _parse_snmp_message(data):
    tag, msg, _ = _read_tlv(data, 0)
    if tag != 0x30:
        raise ValueError("不是 SNMP 报文")
    pos = 0
    tag, content, pos = _read_tlv(msg, pos)
    version = int.from_bytes(content, "big", signed=True) if tag == 0x02 else None
    tag, community, pos = _read_tlv(msg, pos)
    community = community.decode("utf-8", "replace") if tag == 0x04 else ""
    tag, pdu, pos = _read_tlv(msg, pos)
    if tag not in (0xA2, 0xA0):  # Response / GetRequest
        raise ValueError("SNMP 响应类型异常")
    p = 0
    tag, rid_b, p = _read_tlv(pdu, p)
    tag, err_b, p = _read_tlv(pdu, p)
    tag, erridx_b, p = _read_tlv(pdu, p)
    error_status = int.from_bytes(err_b, "big", signed=True)
    error_index = int.from_bytes(erridx_b, "big", signed=True)
    tag, vblist, p = _read_tlv(pdu, p)
    if tag != 0x30:
        raise ValueError("SNMP varbind 列表异常")
    vp = 0
    tag, vb, vp = _read_tlv(vblist, vp)
    if tag != 0x30:
        raise ValueError("SNMP varbind 异常")
    vpos = 0
    tag, oid_b, vpos = _read_tlv(vb, vpos)
    oid = _decode_value(0x06, oid_b) if tag == 0x06 else ""
    tag, val_b, vpos = _read_tlv(vb, vpos)
    value = _decode_value(tag, val_b)
    return {"version": version, "community": community, "oid": oid,
            "value": value, "error_status": error_status,
            "error_index": error_index}


def snmp_get(ip, community, oid, timeout=2.0, retries=1):
    """SNMP v2c GET 单个 OID，返回解析后的报文；失败抛异常。"""
    req_id = int(time.time() * 1000) & 0x7FFFFFFF
    varbind = _tlv(0x30, _ber_oid(oid) + _tlv(0x05, b""))
    pdu = _tlv(0xA0, _ber_int(req_id) + _ber_int(0) + _ber_int(0) + _tlv(0x30, varbind))
    packet = _tlv(0x30, _ber_int(1) + _ber_octets(community) + pdu)
    last_err = None
    for _ in range(retries + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (ip, 161))
            data, _addr = sock.recvfrom(8192)
            return _parse_snmp_message(data)
        except (socket.timeout, OSError, ValueError) as e:
            last_err = e
        finally:
            sock.close()
    raise RuntimeError("SNMP 查询失败：%s" % (last_err or "无响应"))


def snmp_sysdescr(ip, community="public", timeout=1.5):
    return snmp_get(ip, community, "1.3.6.1.2.1.1.1.0", timeout=timeout)


# ============================================================
#  自动探测
# ============================================================
def tcp_open(ip, port, timeout=0.6):
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def http_info(ip, port=80, timeout=2.0, use_https=False):
    """读取 HTTP 状态行、Server 头与页面标题。"""
    result = {"status": None, "server": "", "title": "", "location": ""}
    try:
        if use_https:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = socket.create_connection((ip, port), timeout=timeout)
            sock = ctx.wrap_socket(sock, server_hostname=ip)
        else:
            sock = socket.create_connection((ip, port), timeout=timeout)
        req = ("GET / HTTP/1.0\r\nHost: %s\r\nUser-Agent: EasyRouter-Probe/1.0\r\n"
               "Accept: text/html,*/*\r\nConnection: close\r\n\r\n" % ip)
        sock.sendall(req.encode("ascii", "ignore"))
        chunks = []
        total = 0
        while total < 16384:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
            total += len(data)
        sock.close()
        raw = b"".join(chunks).decode("utf-8", "replace")
        head, _, body = raw.partition("\r\n\r\n")
        lines = head.splitlines()
        if lines:
            m = re.match(r"HTTP/\d\.\d\s+(\d+)", lines[0])
            if m:
                result["status"] = int(m.group(1))
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip().lower()
                if k == "server":
                    result["server"] = v.strip()
                elif k == "location":
                    result["location"] = v.strip()
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        if m:
            result["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
    except (OSError, ValueError):
        pass
    return result


def ssh_banner(ip, port=22, timeout=1.5):
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.settimeout(timeout)
        data = sock.recv(256)
        sock.close()
        return data.decode("utf-8", "replace").strip()
    except OSError:
        return ""


def detect_gateway(ip, log=None):
    """探测一台网关的可用管理通道，并给出推荐采集方式。"""
    ip = str(ip).strip()
    result = {
        "ip": ip,
        "ports": {},
        "http": {},
        "ssh_banner": "",
        "snmp": {"ok": False, "sysdescr": "", "error": ""},
        "suggest": "unknown",
        "suggest_text": "未能识别，需要手动确认采集方式",
    }
    ports = {}
    threads = []
    lock = threading.Lock()

    def check(port):
        ok = tcp_open(ip, port)
        with lock:
            ports[port] = ok

    for p in COMMON_PORTS:
        t = threading.Thread(target=check, args=(p,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=3)
    result["ports"] = ports

    # Web 管理页可能跑在 80 / 8080 / 443 / 8443 上
    for port, use_https in ((80, False), (8080, False), (443, True), (8443, True)):
        if ports.get(port):
            info = http_info(ip, port, use_https=use_https)
            if info.get("status"):
                info["port"] = port
                result["http"] = info
                break
            if not result["http"].get("status"):
                info["port"] = port
                result["http"] = info
    if ports.get(22):
        result["ssh_banner"] = ssh_banner(ip)

    if ports.get(161):
        for community in ("public", "private"):
            try:
                resp = snmp_sysdescr(ip, community, timeout=1.2)
                val = resp.get("value")
                if isinstance(val, str) and val:
                    result["snmp"] = {"ok": True, "sysdescr": val[:200],
                                      "community": community, "error": ""}
                    break
            except Exception as e:
                result["snmp"] = {"ok": False, "sysdescr": "", "error": str(e)}

    title = (result["http"].get("title") or "") + " " + (result["http"].get("server") or "")
    lowered = title.lower()
    if "openwrt" in lowered or "luci" in lowered or "immortalwrt" in lowered:
        result["suggest"] = "ssh"
        result["suggest_text"] = "疑似 OpenWrt/LuCI：推荐使用 SSH 方式（可精确读取 conntrack 与租约）"
    elif result["snmp"]["ok"]:
        result["suggest"] = "snmp"
        result["suggest_text"] = "SNMP 可访问：推荐 SNMP 方式（需填写会话/主机数对应的 OID）"
    elif result["ssh_banner"]:
        result["suggest"] = "ssh"
        result["suggest_text"] = "SSH 服务可访问：推荐 SSH 命令方式（需账号密码或密钥）"
    elif result["http"].get("status"):
        result["suggest"] = "http"
        result["suggest_text"] = "仅检测到 Web 管理页：如设备有 JSON 接口，可用 HTTP 方式；否则需手动查看"
    if log:
        log.info("[网关探测] %s 端口=%s 建议=%s", ip,
                 ",".join(str(p) for p, ok in ports.items() if ok), result["suggest"])
    return result


# ============================================================
#  采集实现
# ============================================================
def _first_int(text):
    m = re.search(r"-?\d+", text or "")
    return int(m.group(0)) if m else None


def _json_path(obj, path):
    cur = obj
    for part in [p for p in str(path or "").split(".") if p]:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _http_get_json(url, username="", password="", timeout=6.0):
    req = urllib.request.Request(url, headers={"User-Agent": "EasyRouter-Probe/1.0"})
    if username:
        import base64
        token = base64.b64encode(("%s:%s" % (username, password)).encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read(1024 * 1024).decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError:
        return {"_raw": body}


def _run_ssh(gw, command, timeout=12):
    ip = gw.get("ip")
    user = gw.get("username") or "root"
    password = gw.get("password") or ""
    opts = ["-o", "BatchMode=yes" if not password else "BatchMode=no",
            "-o", "ConnectTimeout=6",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR"]
    target = "%s@%s" % (user, ip)
    if password:
        rc, _, _ = _run_cmd(["which", "sshpass"], timeout=3)
        if rc != 0:
            raise RuntimeError("使用密码登录需要安装 sshpass：apt install sshpass；或改用密钥登录")
        cmd = ["sshpass", "-p", password, "ssh"] + opts + [target, command]
    else:
        cmd = ["ssh"] + opts + [target, command]
    rc, out, err = _run_cmd(cmd, timeout=timeout)
    if rc != 0:
        raise RuntimeError((err or out or "SSH 命令执行失败").strip()[:300])
    return out


def _run_cmd(cmd, timeout=12, input_text=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           input=input_text)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "命令不存在：%s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "命令执行超时"
    except Exception as e:
        return 1, "", str(e)


def _probe_demo(gw):
    seed = sum(ord(c) for c in (gw.get("id") or gw.get("ip") or "gw"))
    rng = __import__("random").Random(int(time.time() // 20) + seed)
    ok = rng.random() > 0.06
    if not ok:
        return {"ok": False, "sessions": None, "hosts": None,
                "error": "演示：设备暂时无响应（模拟故障）"}
    return {"ok": True, "sessions": rng.randint(80, 900), "hosts": rng.randint(4, 42),
            "error": ""}


def probe_gateway(gw, log=None):
    """采集单台网关。返回结果字典。"""
    method = (gw.get("method") or "auto").lower()
    started = time.time()
    result = {"id": gw.get("id", ""), "name": gw.get("name", ""), "ip": gw.get("ip", ""),
              "method": method, "ok": False, "sessions": None, "hosts": None,
              "error": "", "ts": int(time.time()), "elapsed_ms": 0}
    try:
        if method == "demo":
            result.update(_probe_demo(gw))
        elif method == "snmp":
            community = gw.get("snmp_community") or "public"
            sess_oid = (gw.get("sessions_oid") or "").strip()
            host_oid = (gw.get("hosts_oid") or "").strip()
            if not sess_oid and not host_oid:
                raise RuntimeError("请填写会话数/在线主机数对应的 SNMP OID")
            errs = []
            if sess_oid:
                try:
                    val = snmp_get(gw["ip"], community, sess_oid).get("value")
                    result["sessions"] = int(val) if isinstance(val, (int, float)) else _first_int(val)
                except Exception as e:
                    errs.append("会话 OID：%s" % e)
            if host_oid:
                try:
                    val = snmp_get(gw["ip"], community, host_oid).get("value")
                    result["hosts"] = int(val) if isinstance(val, (int, float)) else _first_int(val)
                except Exception as e:
                    errs.append("主机 OID：%s" % e)
            if errs:
                result["error"] = "；".join(errs)
            result["ok"] = result["sessions"] is not None or result["hosts"] is not None
        elif method == "ssh":
            sess_cmd = (gw.get("sessions_cmd") or "").strip()
            host_cmd = (gw.get("hosts_cmd") or "").strip()
            if not sess_cmd and not host_cmd:
                raise RuntimeError("请填写会话数/在线主机数的 SSH 命令")
            errs = []
            if sess_cmd:
                try:
                    result["sessions"] = _first_int(_run_ssh(gw, sess_cmd))
                    if result["sessions"] is None:
                        errs.append("会话命令输出中没有数字")
                except Exception as e:
                    errs.append("会话：%s" % e)
            if host_cmd:
                try:
                    result["hosts"] = _first_int(_run_ssh(gw, host_cmd))
                    if result["hosts"] is None:
                        errs.append("主机命令输出中没有数字")
                except Exception as e:
                    errs.append("主机：%s" % e)
            if errs:
                result["error"] = "；".join(errs)
            result["ok"] = result["sessions"] is not None or result["hosts"] is not None
        elif method == "http":
            url = (gw.get("http_url") or "").strip()
            if not url:
                raise RuntimeError("请填写 HTTP 接口地址")
            data = _http_get_json(url, gw.get("http_user") or "",
                                  gw.get("http_password") or "")
            if isinstance(data, dict) and "_raw" in data:
                result["sessions"] = _first_int(data["_raw"]) if gw.get("sessions_json") else None
                if gw.get("hosts_json"):
                    result["hosts"] = _first_int(data["_raw"])
            else:
                if gw.get("sessions_json"):
                    v = _json_path(data, gw["sessions_json"])
                    result["sessions"] = int(v) if isinstance(v, (int, float)) else _first_int(v)
                if gw.get("hosts_json"):
                    v = _json_path(data, gw["hosts_json"])
                    result["hosts"] = int(v) if isinstance(v, (int, float)) else _first_int(v)
            if result["sessions"] is None and result["hosts"] is None:
                raise RuntimeError("未能从接口响应中提取到数字，请检查字段路径")
            result["ok"] = True
        elif method == "auto":
            det = detect_gateway(gw["ip"], log)
            result["detect"] = det
            result["error"] = "尚未选择采集方式。推荐：%s" % det["suggest_text"]
        else:
            raise RuntimeError("未知采集方式：%s" % method)
    except Exception as e:
        result["error"] = str(e)[:300]
        if log:
            log.warning("[网关] %s (%s) 采集失败：%s", gw.get("name"), gw.get("ip"), result["error"])
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    return result


class GatewayManager(threading.Thread):
    """后台定时探测所有出口网关，缓存最新结果。"""

    def __init__(self, cfg, log, demo=False):
        super().__init__(daemon=True, name="easyrouter-gateways")
        self.cfg = cfg
        self.log = log
        self.demo = demo
        self.lock = threading.RLock()
        self.results = {}
        self._stop = threading.Event()
        self.running = False
        self.last_run = 0

    def gateway_list(self):
        with self.lock:
            return list(self.cfg.get("gateways") or [])

    def update_cfg(self, cfg):
        with self.lock:
            self.cfg = cfg

    def run(self):
        while not self._stop.is_set():
            try:
                self.probe_all()
            except Exception:
                self.log.exception("网关采集线程异常")
            interval = 30
            try:
                interval = max(10, int(self.cfg.get("monitor", {}).get("gateway_interval", 30)))
            except (TypeError, ValueError):
                pass
            self._stop.wait(interval)

    def stop(self):
        self._stop.set()

    def probe_all(self):
        gateways = self.gateway_list()
        self.running = True
        for gw in gateways:
            if self._stop.is_set():
                break
            res = probe_gateway(gw, self.log)
            with self.lock:
                self.results[gw.get("id") or gw.get("ip")] = res
        self.last_run = int(time.time())
        self.running = False

    def probe_one(self, gid):
        for gw in self.gateway_list():
            if (gw.get("id") or gw.get("ip")) == gid:
                res = probe_gateway(gw, self.log)
                with self.lock:
                    self.results[gid] = res
                return res
        return None

    def snapshot(self):
        with self.lock:
            gates = []
            for gw in self.cfg.get("gateways") or []:
                item = dict(gw)
                if item.get("password"):
                    item["password"] = ""
                    item["has_password"] = True
                if item.get("http_password"):
                    item["http_password"] = ""
                    item["has_http_password"] = True
                gid = item.get("id") or item.get("ip")
                item["result"] = self.results.get(gid) or {
                    "id": gid, "ok": False, "sessions": None, "hosts": None,
                    "error": "等待首次采集", "ts": 0, "method": item.get("method"),
                }
                gates.append(item)
            return {"gateways": gates, "running": self.running,
                    "last_run": self.last_run}
