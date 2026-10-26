# -*- coding: utf-8 -*-
"""连接跟踪（conntrack）读取：出口会话总数、每设备会话数、协议分布。"""
import re

from . import linux_util

COUNT_PATH = "/proc/sys/net/netfilter/nf_conntrack_count"
TABLE_PATH = "/proc/net/nf_conntrack"

PROTO_NAMES = {"6": "tcp", "17": "udp", "1": "icmp", "58": "icmp6"}
LINE_RE = re.compile(r"^ipv4\s+\d+\s+(\w+)\s+(\d+)\s+\d+\s+\S+\s+src=(\S+)\s+dst=(\S+)")


def read_count():
    """出口连接跟踪会话总数。"""
    v = linux_util.read_file(COUNT_PATH, "").strip()
    if v.isdigit():
        return int(v)
    return 0


def read_all(max_lines=200000):
    """解析完整 conntrack 表。

    返回 {"total", "by_src": {ip:n}, "by_dst": {ip:n}, "tcp", "udp", "icmp", "other"}
    """
    result = {"total": 0, "by_src": {}, "by_dst": {},
              "tcp": 0, "udp": 0, "icmp": 0, "other": 0}
    try:
        f = open(TABLE_PATH, "r", errors="replace")
    except OSError:
        result["total"] = read_count()
        return result
    try:
        n = 0
        for line in f:
            n += 1
            if n > max_lines:
                break
            m = LINE_RE.match(line)
            if not m:
                continue
            proto, pnum, src, dst = m.group(1), m.group(2), m.group(3), m.group(4)
            proto = PROTO_NAMES.get(pnum, proto or "other")
            if proto == "tcp":
                result["tcp"] += 1
            elif proto == "udp":
                result["udp"] += 1
            elif proto in ("icmp", "icmp6"):
                result["icmp"] += 1
            else:
                result["other"] += 1
            result["by_src"][src] = result["by_src"].get(src, 0) + 1
            result["by_dst"][dst] = result["by_dst"].get(dst, 0) + 1
            result["total"] += 1
    finally:
        f.close()
    return result
