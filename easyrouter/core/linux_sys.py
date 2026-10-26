# -*- coding: utf-8 -*-
"""系统信息读取：网卡流量、CPU、内存、负载、温度。"""
import glob
import os
import time

from . import linux_util


class SystemReader:
    def __init__(self):
        self._prev_cpu = None
        self._prev_cpu_ts = 0.0
        self._prev_iface = {}      # name -> (rx, tx, ts)
        self._prev_iface_raw = {}  # name -> (rx, tx) 上次原始值（用于速率计算）

    # ---------------- 网卡字节数 ----------------
    def iface_bytes(self):
        out = {}
        try:
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()[2:]
        except OSError:
            return out
        for line in lines:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            cols = rest.split()
            if len(cols) < 10:
                continue
            try:
                out[name] = (int(cols[0]), int(cols[8]))  # rx_bytes, tx_bytes
            except ValueError:
                continue
        return out

    # ---------------- CPU ----------------
    def _read_cpu(self):
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
            parts = line.split()[1:]
            vals = [int(x) for x in parts[:8]]
            return vals
        except (OSError, ValueError, IndexError):
            return None

    def cpu_percent(self):
        now = time.time()
        vals = self._read_cpu()
        if not vals:
            return 0.0
        if self._prev_cpu:
            dt = now - self._prev_cpu_ts
            if dt > 0:
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                pidle = self._prev_cpu[3] + (self._prev_cpu[4] if len(self._prev_cpu) > 4 else 0)
                total = sum(vals) - sum(self._prev_cpu)
                if total > 0:
                    pct = 100.0 * (1.0 - (idle - pidle) / total)
                    self._prev_cpu, self._prev_cpu_ts = vals, now
                    return round(max(0.0, min(pct, 100.0)), 1)
        self._prev_cpu, self._prev_cpu_ts = vals, now
        return 0.0

    # ---------------- 内存 / 负载 / 运行时间 / 温度 ----------------
    def meminfo(self):
        total = used = 0
        try:
            with open("/proc/meminfo", "r") as f:
                info = {}
                for line in f:
                    k, _, v = line.partition(":")
                    info[k.strip()] = int(v.strip().split()[0]) * 1024
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", 0)
            used = total - avail if total else 0
        except (OSError, ValueError):
            pass
        return total, used

    def loadavg(self):
        try:
            with open("/proc/loadavg", "r") as f:
                parts = f.read().split()
            return [round(float(parts[i]), 2) for i in range(3)]
        except (OSError, ValueError, IndexError):
            return [0.0, 0.0, 0.0]

    def uptime(self):
        try:
            with open("/proc/uptime", "r") as f:
                return float(f.read().split()[0])
        except (OSError, ValueError):
            return 0.0

    def temperature(self):
        best = None
        for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
            try:
                with open(zone + "/type", "r") as f:
                    ztype = f.read().strip()
                with open(zone + "/temp", "r") as f:
                    val = float(f.read().strip()) / 1000.0
                if ztype in ("x86_pkg_temp", "cpu-thermal", "acpitz"):
                    return round(val, 1)
                if best is None:
                    best = round(val, 1)
            except (OSError, ValueError):
                continue
        return best
