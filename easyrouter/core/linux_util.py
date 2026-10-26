# -*- coding: utf-8 -*-
"""Linux 命令与文件操作工具。"""
import os
import subprocess
import tempfile


def run(cmd, timeout=10, input=None):
    """执行命令，返回 (returncode, stdout, stderr)。不会抛出异常。"""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           text=True, input=input)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError as e:
        return 127, "", "命令不存在: %s" % (getattr(e, "filename", e))
    except subprocess.TimeoutExpired:
        return 124, "", "命令执行超时"
    except Exception as e:
        return 1, "", str(e)


def read_file(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def write_file_atomic(path, content, mode=0o644):
    """原子化写文件（确定性临时文件名，不依赖 tempfile）。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def sysctl_set(key, value):
    """写入 /proc/sys。返回 (ok, msg)。"""
    path = "/proc/sys/" + key.replace(".", "/")
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True, ""
    except OSError as e:
        rc, _, err = run(["sysctl", "-w", "%s=%s" % (key, value)], timeout=10)
        if rc == 0:
            return True, ""
        return False, "sysctl %s=%s 失败: %s" % (key, value, err or e)


def sysctl_get(key, default=None):
    try:
        with open("/proc/sys/" + key.replace(".", "/"), "r") as f:
            return f.read().strip()
    except OSError:
        return default
