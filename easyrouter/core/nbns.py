# -*- coding: utf-8 -*-
"""NetBIOS 名称服务（NBNS）查询：向设备询问其计算机名，用于识别设备名称。"""
import random
import socket
import struct
import time


def _encode_name(name):
    """NetBIOS 第一级编码：每个字符拆成两个大写字母。"""
    out = bytearray()
    name = (name or "").ljust(15, " ")[:15].upper()
    for ch in name:
        b = ord(ch)
        out.append(ord("A") + (b >> 4))
        out.append(ord("A") + (b & 0x0F))
    return bytes(out)


def _decode_name(raw):
    """NBSTAT 应答中的名称是纯 ASCII（15 字节，NUL/空格补齐）。"""
    try:
        return raw.split(b"\x00")[0].decode("ascii", "replace").strip()
    except Exception:
        return ""


def build_query():
    tid = random.randint(0, 0xFFFF)
    flags = 0x0110  # RD
    qdcount = 1
    qname = b"\x20" + _encode_name("*") + b"\x00"  # 通配符查询
    qtype = struct.pack(">H", 0x0020)  # NBSTAT
    qclass = struct.pack(">H", 0x0001)  # IN
    return struct.pack(">HHHHHH", tid, flags, qdcount, 0, 0, 0) + qname + qtype + qclass


def parse_response(data):
    """解析 NBNS 应答，返回设备名或 None。支持域名压缩指针。"""
    try:
        if len(data) < 12:
            return None
        qdcount = struct.unpack(">H", data[4:6])[0]
        ancount = struct.unpack(">H", data[6:8])[0]
        pos = 12

        def skip_name(p):
            if p >= len(data):
                return -1
            if data[p] & 0xC0 == 0xC0:          # 压缩指针：2 字节
                return p + 2
            end = data.find(b"\x00", p)          # 普通标签：扫描到 0x00
            return end + 1 if end >= 0 else -1

        # 跳过问题区
        for _ in range(qdcount):
            pos = skip_name(pos)
            if pos < 0 or pos + 4 > len(data):
                return None
            pos += 4  # qtype + qclass

        # 解析应答区
        for _ in range(ancount):
            pos = skip_name(pos)
            if pos < 0 or pos + 10 > len(data):
                return None
            pos += 2 + 2 + 4                  # type + class + ttl
            rdlen = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            rdata = data[pos:pos + rdlen]
            pos += rdlen
            if len(rdata) < 2:
                continue
            num = rdata[0]
            off = 1
            for _ in range(min(num, 16)):
                if off + 18 > len(rdata):
                    break
                raw_name = rdata[off:off + 15]
                ntype = rdata[off + 15]
                flags = struct.unpack(">H", rdata[off + 16:off + 18])[0]
                off += 18
                is_unique = (flags & 0x8000) == 0
                if ntype in (0x00, 0x03, 0x20) and is_unique:
                    name = _decode_name(raw_name)
                    if name and "*" not in name:
                        return name
    except Exception:
        return None
    return None


class NetbiosResolver:
    """带缓存的 NetBIOS 名称解析器。"""

    CACHE_TTL = 600

    def __init__(self, broadcast_addr=None, log=None):
        self.broadcast_addr = broadcast_addr or "255.255.255.255"
        self.log = log
        self.cache = {}  # ip -> (ts, name)

    def resolve(self, ip, timeout=0.45):
        hit = self.cache.get(ip)
        if hit and time.time() - hit[0] < self.CACHE_TTL:
            return hit[1]
        name = self._query(ip, timeout)
        self.cache[ip] = (time.time(), name)
        return name

    def _query(self, ip, timeout):
        q = build_query()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            try:
                sock.sendto(q, (ip, 137))  # 先定向查询
                data, _ = sock.recvfrom(1024)
                name = parse_response(data)
                if name:
                    return name
            except socket.timeout:
                pass
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(q, (self.broadcast_addr, 137))  # 再广播查询
                while True:
                    try:
                        data, _ = sock.recvfrom(1024)
                        name = parse_response(data)
                        if name:
                            return name
                    except socket.timeout:
                        break
            except socket.timeout:
                pass
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return None
